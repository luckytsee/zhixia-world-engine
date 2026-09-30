/**
 * 主动发起主循环（任务书 §8，2026-09-29 改版）。
 *
 * ⚠️ 改版原因：reminderAgentManager 被 1700002 管控卡死（本 API 版本普通权限
 * 提醒配额=0，见开发日志），通道 A 的"预约式"没了承载 → 早安/晚安锚点改由
 * **B 唤醒在时间窗内补说**（早 7:30–10:00 / 晚 21:00–23:30，当天没说过才算），
 * 自由由头照旧。预约式通道（reminderAgentManager）在本机 API 版本上配额为 0，故不采用，改用唤醒式。
 *
 * 三条开口纪律不变：
 * - 唤醒 ≠ 开口：有由头（或锚点窗）且过节流器才调 LLM；
 * - LLM 失败 → 降级发一句纯世界状态（§8.6）；
 * - 原话落 msgList（synced=0）推回 PC 进记忆管道（§8.6）。
 *
 * WeWorkSchedulerAbility（真唤醒）和 #remind-test（调试，立即跑一轮、
 * 无由头时强行开口且不占额度）都走这里。
 */

import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { WeTextKit } from '../ports/WeTextKit';
import { WeProactivePrompt } from '../ports/WeProactivePrompt';
import type { ChatSink, LlmClient, SnapshotSource, WeSnapshotDto } from '../ports/WePorts';
import { WeProactivity } from './WeProactivity';
import { WeProactiveReasons } from './WeProactiveReasons';
import { WeProactiveCommon } from './WeProactiveCommon';
import { WeWorldEngine } from '../world/WeWorldEngine';
import { WeWorldParse } from '../world/WeWorldRules';
import type { WeWorldRules, WeWorldState, WeWorldStateRaw, WeWorldRulesRaw, WeWorldRuleStage } from '../world/WeWorldRules';
import { ZX_RULES_JSON } from '../world/WeWorldDefaultRules';

const ZX_LOG_DOMAIN: number = 0x0926;
const ZX_LOG_TAG: string = 'WeProactive';

/** 调试运行参数：无由头时强行开口、不占额度、不计唤醒账 */
export class WeProactiveRunOpts {
  source: string = 'B';
  debug: boolean = false;
}

/**
 * 依赖注入包（宿主实现 WePorts 里的三个端口后传进来）。
 * ⚠️ 开源版刻意不 new 任何宿主对象——宿主自己决定快照从哪来、话往哪写。
 */
export class WeProactiveDeps {
  snapshotSource: SnapshotSource;
  chatSink: ChatSink;
  llm: LlmClient;

  constructor(snapshotSource: SnapshotSource, chatSink: ChatSink, llm: LlmClient) {
    this.snapshotSource = snapshotSource;
    this.chatSink = chatSink;
    this.llm = llm;
  }
}

export class WeProactiveCycle {
  /**
   * 跑一轮主动检查。返回给人看的结论（toast/日志两用）。
   * 纪律：世界只补算不写回；绝不 POST 回 PC。
   */
  static async run(ctx: common.Context, opts: WeProactiveRunOpts,
    deps: WeProactiveDeps): Promise<string> {
    const nowMs: number = Date.now();
    const pro = new WeProactivity();
    pro.init(ctx);

    const snapshot: WeSnapshotDto | null = deps.snapshotSource.load();
    if (snapshot === null) {
      WeProactiveCycle.log(opts, '无(原因:快照为空)');
      return '快照为空（先连电脑同步一次）';
    }

    // ---- 由头判断 ----
    // ① 锚点：唤醒落在早安/晚安窗里，且今天这一顿还没说过（日期键防重）
    const today: string = WeTextKit.ymd(nowMs);
    let reasonKey: string = '';
    let hint: string = '';
    const window: string = WeProactiveReasons.anchorWindow(nowMs);
    if (window !== '' && !pro.hasFired(window + '@' + today)) {
      reasonKey = window + '@' + today;
      hint = window === 'morning'
        ? '由头：早上到了你想跟他说早安的时候'
        : '由头：夜里到了你跟他说晚安、催他去睡的时候';
    }
    // ② 世界/事务由头（锚点不在场时才看）
    let state: WeWorldState | null = null;
    if (reasonKey === '') {
      const parsed = WeProactiveCycle.advanceWorld(snapshot, nowMs);
      state = parsed.state;
      const r = WeProactiveReasons.pick(state, parsed.staticDayEvery,
        WeProactiveCycle.giftCount(snapshot, 'unopened_packages'),
        WeProactiveCycle.giftCount(snapshot, 'wishes_waiting'), nowMs);
      if (r !== null) {
        reasonKey = r.reason;
        hint = r.hint;
      }
    }
    // ③ 调试兜底：#remind-test 没赶上任何由头时，强行开口验证链路
    if (reasonKey === '') {
      if (!opts.debug) {
        WeProactiveCycle.log(opts, '无由头，本次不开口（未调 LLM）');
        return '无由头，本次不开口';
      }
      reasonKey = 'test';
      hint = '由头：这是一次主动发起机制的测试，就当平时那样主动找他说句话';
    }

    // ---- 节流闸门（测试由头不占额度）----
    if (reasonKey !== 'test') {
      const gate = pro.canFire(reasonKey, nowMs);
      if (!gate.ok) {
        WeProactiveCycle.log(opts, '节流拦截(由头=' + reasonKey + ', ' + gate.why + ')');
        return '被节流拦下：' + gate.why;
      }
    }

    // ---- 生成 + 通知 + 落库 ----
    const messages = WeProactivePrompt.build(snapshot, hint, nowMs / 1000);
    const reply: string | null = await deps.llm.chatComplete(messages);
    let text: string = '';
    let rawText: string = '';
    if (reply !== null && reply.trim() !== '') {
      // 与聊天路径同一套清洗：先剥 [图:标签] 再洗话；入库存原文（[记住:] 要寄回电脑）
      const stripped = WeTextKit.stripStickerTags(reply);
      const cleaned = WeTextKit.cleanSpeech(stripped);
      if (cleaned !== '') {
        text = cleaned;
        rawText = stripped.trim();
      }
    }
    if (text === '') {
      text = WeProactiveCommon.worldShortLine(state);
      rawText = text;
      WeProactiveCycle.log(opts, 'LLM 失败，降级为纯世界状态');
    }
    await WeProactiveCommon.publishMsg(ctx, text);
    await WeProactiveCommon.insertAssistantMsg(deps.chatSink, rawText, nowMs);
    if (reasonKey !== 'test') {
      pro.markFired(reasonKey, nowMs);
    }
    WeProactiveCycle.log(opts, '已开口(由头=' + reasonKey + ', ' + text.length.toString() + '字)');
    return '已开口（' + text.length.toString() + '字）：' + text;
  }

  /** 快照世界克隆补算到 now（读模型补算：不写回快照、不回传） */
  private static advanceWorld(snapshot: WeSnapshotDto, nowMs: number): WeWorldAdvanced {
    const out: WeWorldAdvanced = { state: null, staticDayEvery: 0 };
    const seg = snapshot.world;
    if (seg === undefined || seg === null || seg.state === undefined || seg.state === null) {
      return out;
    }
    let rules: WeWorldRules | null = null;
    if (seg.rules !== undefined && seg.rules !== null) {
      rules = WeWorldParse.rules(seg.rules as WeWorldRulesRaw);
    }
    if (rules === null) {
      try {
        rules = WeWorldParse.rules(JSON.parse(ZX_RULES_JSON) as WeWorldRulesRaw);
      } catch (err) {
        rules = null;
      }
    }
    if (rules === null || seg.engine_version !== WeWorldEngine.VERSION) {
      return out;
    }
    const st: WeWorldState | null = WeWorldParse.state(
      JSON.parse(JSON.stringify(seg.state)) as WeWorldStateRaw);
    if (st === null) {
      return out;
    }
    const engine = new WeWorldEngine(rules);
    engine.advanceTo(st, nowMs / 1000);
    out.state = st;
    out.staticDayEvery = rules.staticDayEvery;
    return out;
  }

  private static giftCount(snapshot: WeSnapshotDto, field: string): number {
    const g = snapshot.gifts;
    if (g === undefined || g === null) {
      return 0;
    }
    const v: number | undefined = field === 'unopened_packages'
      ? g.unopened_packages : g.wishes_waiting;
    return typeof v === 'number' ? v : 0;
  }

  private static log(opts: WeProactiveRunOpts, msg: string): void {
    hilog.info(ZX_LOG_DOMAIN, ZX_LOG_TAG, '[%{public}s] %{public}s', opts.source, msg);
  }
}

/** 世界补算结果 */
interface WeWorldAdvanced {
  state: WeWorldState | null;
  staticDayEvery: number;
}
