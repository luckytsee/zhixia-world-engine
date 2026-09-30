/**
 * 主动发起的消息组装（从宿主 App 的 Prompt 组装层抽出，开源版独立自带）。
 *
 * ⚠️ 设计要点（上游踩过的坑，照抄别改）：
 *   1. **只给状态不给台词**：世界块是维度化字段（【此刻】光线/天气/时节…），
 *      不是替模型写好的句子。怎么说由模型自己长。
 *   2. **世界块与"在线聊天"同源**：主动开口和用户聊天时看到的是同一个世界，
 *      否则她会在两种场合说出矛盾的天气/时辰。
 *   3. **版本门**：快照里的 world.engine_version 与本端实现不一致 → 不补算，
 *      直接渲染快照原状态（世界宁可停在出门那一刻，也不能和电脑端矛盾）。
 *   4. **读模型补算**：本地 advance 的结果只用于渲染，绝不写回快照、绝不回传。
 */

import { WeWorldEngine } from '../world/WeWorldEngine';
import { renderBlock } from '../world/WeWorldRender';
import { WeWorldParse } from '../world/WeWorldRules';
import type { WeWorldRules, WeWorldStateRaw, WeWorldRulesRaw } from '../world/WeWorldRules';
import { ZX_RULES_JSON } from '../world/WeWorldDefaultRules';
import { WeTextKit } from './WeTextKit';
import type { WeSnapshotDto } from './WePorts';

/** 一条 LLM 消息（role: system | user | assistant） */
export interface WeLlmMessage {
  role: string;
  content: string;
}

/** 组装结果（worldLog 给日志观测用） */
interface ProactiveBuild {
  messages: WeLlmMessage[];
  worldLog: string;
}

export class WeProactivePrompt {
  /**
   * 组一次"主动开口"的 prompt：persona → 记忆 → 世界块 → 时间行 → 指令。
   * 没有历史（她不是接话，是自己开口）。
   */
  static build(snapshot: WeSnapshotDto | null, hint: string, atSec: number): WeLlmMessage[] {
    return WeProactivePrompt.buildDetailed(snapshot, hint, atSec).messages;
  }

  static buildDetailed(snapshot: WeSnapshotDto | null, hint: string,
    atSec: number): ProactiveBuild {
    const out: WeLlmMessage[] = [];
    const persona: string = snapshot !== null && snapshot.persona !== undefined
      && snapshot.persona !== '' ? snapshot.persona : 'You are a friendly assistant.';
    const personaMsg: WeLlmMessage = { role: 'system', content: persona };
    out.push(personaMsg);
    if (snapshot !== null) {
      const env = WeProactivePrompt.renderEnv(snapshot, atSec);
      if (env.env !== '') {
        const envMsg: WeLlmMessage = { role: 'system', content: env.env };
        out.push(envMsg);
      }
      if (env.gift !== '') {
        const giftMsg: WeLlmMessage = { role: 'system', content: env.gift };
        out.push(giftMsg);
      }
      const nowMsg: WeLlmMessage = { role: 'system', content: WeProactivePrompt.nowLine(atSec) };
      out.push(nowMsg);
      const askMsg: WeLlmMessage = { role: 'user', content: WeTextKit.proactiveInstruction(hint) };
      out.push(askMsg);
      const r: ProactiveBuild = { messages: out, worldLog: env.worldLog };
      return r;
    }
    const nowMsg2: WeLlmMessage = { role: 'system', content: WeProactivePrompt.nowLine(atSec) };
    out.push(nowMsg2);
    const askMsg2: WeLlmMessage = { role: 'user', content: WeTextKit.proactiveInstruction(hint) };
    out.push(askMsg2);
    const r: ProactiveBuild = { messages: out, worldLog: '无(原因:快照为空)' };
    return r;
  }

  /** 时间行：**必须带日期**（上游事故：只给时刻，模型分不清记忆是过去还是未来） */
  private static nowLine(atSec: number): string {
    const d = new Date(atSec * 1000);
    const wd: string = '日一二三四五六'.charAt(d.getDay());
    return '现在是 ' + d.getFullYear().toString() + '年' + (d.getMonth() + 1).toString()
      + '月' + d.getDate().toString() + '日 周' + wd + ' '
      + d.getHours().toString().padStart(2, '0') + ':'
      + d.getMinutes().toString().padStart(2, '0') + '。'
      + '（此刻没人跟你说话——这条消息是你自己要主动发的。）';
  }

  /** 世界块 + 礼物块（在线聊天与主动开口共用同一份，保证双端同一个世界） */
  private static renderEnv(snapshot: WeSnapshotDto, atSec: number): EnvBlocks {
    const r: EnvBlocks = { env: '', gift: '', worldLog: '无(原因:未下发)' };
    if (snapshot.worldPresent === true && snapshot.world !== undefined && snapshot.world !== null) {
      const seg = snapshot.world;
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
      if (rules === null) {
        r.worldLog = '无(原因:规则解析失败)';
      } else if (seg.state === undefined || seg.state === null) {
        r.worldLog = '无(原因:状态缺失)';
      } else {
        const engine = new WeWorldEngine(rules);
        if (seg.engine_version === WeWorldEngine.VERSION) {
          // 克隆再补算到此刻（读模型补算：绝不写回快照）
          const live = WeWorldParse.state(
            JSON.parse(JSON.stringify(seg.state)) as WeWorldStateRaw);
          if (live !== null) {
            engine.advanceTo(live, atSec);
            r.env = renderBlock(live, engine);
            r.worldLog = '有(潮' + live.tide_index.toString() + '/' + live.phase + ')';
          } else {
            r.worldLog = '无(原因:状态解析失败)';
          }
        } else {
          // 版本门：不补算，渲染快照原状态
          const frozen = WeWorldParse.state(seg.state as WeWorldStateRaw);
          if (frozen !== null) {
            r.env = renderBlock(frozen, engine);
            r.worldLog = '有(版本不符,停在快照时刻)';
          } else {
            r.worldLog = '无(原因:状态解析失败)';
          }
        }
      }
    }
    // 礼物：只注入"有未拆包裹"一行（宿主可换成自己的账本摘要）
    if (snapshot.giftsPresent === true && snapshot.gifts !== undefined && snapshot.gifts !== null) {
      const unopened: number | undefined = snapshot.gifts.unopened_packages;
      if (typeof unopened === 'number' && unopened > 0) {
        r.gift = '=== 你们之间的礼物 ===\n- 他寄来的包裹还有 ' + unopened.toString()
          + ' 件没拆（你可以惦记着这事）';
      }
    }
    return r;
  }
}

interface EnvBlocks {
  env: string;
  gift: string;
  worldLog: string;
}
