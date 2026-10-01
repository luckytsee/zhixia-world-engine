/**
 * 共享节流器（任务书 §8.5）：两条主动通道必须同走一个闸门，否则一天能说八遍。
 *
 * 状态文件 filesDir/proactivity.json，**只进不出**（绝不回传 PC）——
 * "她的兴致"本体就是这份文件。
 *
 * ⚠️ 两端进程都会写它（App 同步后预约 / WorkScheduler 唤醒开口），
 * 没做跨进程锁——两个来源几乎不会同时写，v1 接受这个竞态。
 */

import { fileIo } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const ZX_LOG_DOMAIN: number = 0x0926;
const ZX_LOG_TAG: string = 'WeProactive';

/**
 * 每日上限。任务书 §8.2 原写"每天目标 2–4 次"，后来调高到 8
 * （先调高试跑，真实由头密度本来就低，节流器主要是防异常刷屏）。
 */
export const ZX_PROACTIVE_MAX_PER_DAY: number = 8;
/** 最小间隔 2.5 小时（任务书 §8.2） */
export const ZX_PROACTIVE_MIN_GAP_MS: number = 2.5 * 3600 * 1000;
/** 同一由头 48h 内不复用（任务书 §8.2） */
export const ZX_PROACTIVE_REASON_COOLDOWN_MS: number = 48 * 3600 * 1000;

/** 状态文件形状（全部为持久化字段，改形状要考虑老文件兼容） */
interface WeProactivityState {
  /** 'YYYY-MM-DD'，与 sentToday 配对做自然日重置 */
  date: string;
  sentToday: number;
  /** 上次真正开口的时刻（毫秒）；0 = 还没开口过 */
  lastFireMs: number;
  /** 由头 → 上次使用时刻（毫秒）；48h 内同由头不再用（由头固定少数几个，不清理也不会胀） */
  reasons: Record<string, number>;
  /**
   * 通道 A 预约额度：预约是为哪个自然日、占了几句。
   * （A 只有早安/晚安两个槽位，各至多 1 句/日，单日字段够用，不需要字典。）
   */
  reservedDate: string;
  reservedCount: number;
  /** 上次 B 唤醒时刻（§8.4 延迟分布用：两次唤醒的间隔 = 实际周期） */
  lastWakeMs: number;
  /** 已预约槽位键（'goodnight-2026-09-29T22:30'）：早安/晚安各记一个，避免重复预约同一顿 */
  plannedMorning: string;
  plannedNight: string;
  /** 测试提醒的 reminderId（#remind-test 发的，#remind-clear 按它取消） */
  testReminderIds: number[];
}

/** canFire 的结论（ok=false 时 why 给出人话原因，进 hilog） */
export interface WeProactiveGate {
  ok: boolean;
  why: string;
}

export class WeProactivity {
  private state: WeProactivityState = WeProactivity.fresh();
  private filePath: string = '';

  private static fresh(): WeProactivityState {
    const reasons: Record<string, number> = {};
    const s: WeProactivityState = {
      date: '', sentToday: 0, lastFireMs: 0,
      reasons: reasons, reservedDate: '', reservedCount: 0, lastWakeMs: 0,
      plannedMorning: '', plannedNight: '', testReminderIds: []
    };
    return s;
  }

  init(ctx: common.Context): void {
    this.filePath = ctx.filesDir + '/proactivity.json';
    this.state = this.load();
  }

  private load(): WeProactivityState {
    const fresh: WeProactivityState = WeProactivity.fresh();
    if (this.filePath === '' || !fileIo.accessSync(this.filePath)) {
      return fresh;
    }
    let file: fileIo.File | null = null;
    try {
      file = fileIo.openSync(this.filePath, fileIo.OpenMode.READ_ONLY);
      const stat = fileIo.statSync(this.filePath);
      const buf = new ArrayBuffer(stat.size);
      fileIo.readSync(file.fd, buf);
      const text = util.TextDecoder.create('utf-8').decodeWithStream(new Uint8Array(buf));
      const raw = JSON.parse(text) as WeProactivityState;
      // 老文件缺字段就当没有（v1 起步阶段没有老文件）
      fresh.date = typeof raw.date === 'string' ? raw.date : '';
      fresh.sentToday = typeof raw.sentToday === 'number' ? raw.sentToday : 0;
      fresh.lastFireMs = typeof raw.lastFireMs === 'number' ? raw.lastFireMs : 0;
      fresh.lastWakeMs = typeof raw.lastWakeMs === 'number' ? raw.lastWakeMs : 0;
      fresh.plannedMorning = typeof raw.plannedMorning === 'string' ? raw.plannedMorning : '';
      fresh.plannedNight = typeof raw.plannedNight === 'string' ? raw.plannedNight : '';
      if (Array.isArray(raw.testReminderIds)) {
        const ids: number[] = raw.testReminderIds;
        for (let i = 0; i < ids.length; i++) {
          if (typeof ids[i] === 'number') {
            fresh.testReminderIds.push(ids[i]);
          }
        }
      }
      fresh.reservedDate = typeof raw.reservedDate === 'string' ? raw.reservedDate : '';
      fresh.reservedCount = typeof raw.reservedCount === 'number' ? raw.reservedCount : 0;
      if (raw.reasons !== undefined && raw.reasons !== null) {
        fresh.reasons = raw.reasons;
      }
      return fresh;
    } catch (err) {
      return fresh;
    } finally {
      if (file !== null) {
        try {
          fileIo.closeSync(file);
        } catch (err) {
        }
      }
    }
  }

  private save(): void {
    if (this.filePath === '') {
      return;
    }
    let file: fileIo.File | null = null;
    try {
      file = fileIo.openSync(this.filePath,
        fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
      fileIo.writeSync(file.fd, JSON.stringify(this.state));
    } catch (err) {
      // 写不进去就算了：额度松一格的代价远小于打断流程
    } finally {
      if (file !== null) {
        try {
          fileIo.closeSync(file);
        } catch (err) {
        }
      }
    }
  }

  /** 'YYYY-MM-DD'（本地时区） */
  private static dayOf(ms: number): string {
    const d = new Date(ms);
    return d.getFullYear().toString().padStart(4, '0') + '-'
      + (d.getMonth() + 1).toString().padStart(2, '0') + '-'
      + d.getDate().toString().padStart(2, '0');
  }

  /** 今日已占用 = 已发 + 通道 A 为今天预约的（预约在先、开口在后，同一本账） */
  private usedToday(nowMs: number): number {
    const today: string = WeProactivity.dayOf(nowMs);
    if (this.state.date !== today) {
      // 自然日翻了：计数清零；过期的预约额度一并作废（预约没兑现 = 系统没弹，不算她说过了）
      this.state.date = today;
      this.state.sentToday = 0;
      if (this.state.reservedDate !== '' && this.state.reservedDate < today) {
        this.state.reservedDate = '';
        this.state.reservedCount = 0;
      }
      this.save();
    }
    const reservedToday: number = this.state.reservedDate === today ? this.state.reservedCount : 0;
    return this.state.sentToday + reservedToday;
  }

  /**
   * 开口前的总闸门（通道 B 唤醒时调；通道 A 在预约时调同样的检查）。
   * 顺序：今日上限 → 最小间隔 → 由头 48h 去重。任何一条不过都不开口。
   */
  canFire(reason: string, nowMs: number): WeProactiveGate {
    if (this.usedToday(nowMs) >= ZX_PROACTIVE_MAX_PER_DAY) {
      const g: WeProactiveGate = { ok: false, why: '今日额度已满(' + ZX_PROACTIVE_MAX_PER_DAY + ')' };
      return g;
    }
    if (this.state.lastFireMs > 0 && nowMs - this.state.lastFireMs < ZX_PROACTIVE_MIN_GAP_MS) {
      const gapH: number = Math.round((nowMs - this.state.lastFireMs) / 360000) / 10;
      const g: WeProactiveGate = { ok: false, why: '距上次开口仅' + gapH + '小时(<2.5)' };
      return g;
    }
    const last = this.state.reasons;
    const lastMs: number = typeof last[reason] === 'number' ? last[reason] : 0;
    // ⚠️ 锚点（早安/晚安，含带日期的键 morning@2026-09-29）与测试豁免 48h 去重：
    // 锚点防重靠"日期键"（同日同键在 48h 内被拦、次日换键自然放行），不靠 48h。
    const isAnchor: boolean = reason === 'test' || reason === 'morning' || reason === 'goodnight'
      || reason.startsWith('morning@') || reason.startsWith('night@');
    if (!isAnchor && lastMs > 0 && nowMs - lastMs < ZX_PROACTIVE_REASON_COOLDOWN_MS) {
      const g: WeProactiveGate = { ok: false, why: '由头' + reason + '在48h内用过' };
      return g;
    }
    const g: WeProactiveGate = { ok: true, why: '' };
    return g;
  }

  /** 某个由头键今天是否已经用过（锚点日期键 morning@YYYY-MM-DD 查这个） */
  hasFired(key: string): boolean {
    const last = this.state.reasons;
    return typeof last[key] === 'number' && last[key] > 0;
  }

  /** 调试命令的状态汇报（#remind-clear 现在是状态卡） */
  status(nowMs: number): string {
    this.usedToday(nowMs);
    const parts: string[] = [];
    parts.push('今日 ' + this.state.sentToday.toString() + '/' + ZX_PROACTIVE_MAX_PER_DAY.toString());
    if (this.state.lastFireMs > 0) {
      const d = new Date(this.state.lastFireMs);
      parts.push('上次开口 ' + d.getHours().toString().padStart(2, '0') + ':'
        + d.getMinutes().toString().padStart(2, '0'));
    } else {
      parts.push('还没开过口');
    }
    if (this.state.lastWakeMs > 0) {
      const d = new Date(this.state.lastWakeMs);
      parts.push('上次唤醒 ' + d.getHours().toString().padStart(2, '0') + ':'
        + d.getMinutes().toString().padStart(2, '0'));
    }
    return parts.join('，');
  }

  /** 真正发出去之后记账（额度、间隔、由头时间戳） */
  markFired(reason: string, nowMs: number): void {
    this.usedToday(nowMs); // 先触发日翻检查，再计数
    this.state.sentToday += 1;
    this.state.lastFireMs = nowMs;
    this.state.reasons[reason] = nowMs;
    this.save();
    hilog.info(ZX_LOG_DOMAIN, ZX_LOG_TAG, '开口记账: 由头=%{public}s 今日第%{public}d句',
      reason, this.state.sentToday);
  }

  /** 通道 A 预约占额度（槽位在哪个自然日就记到哪天头上） */
  reserve(slotDay: string, reason: string, nowMs: number): void {
    if (this.state.reservedDate !== slotDay) {
      this.state.reservedDate = slotDay;
      this.state.reservedCount = 0;
    }
    this.state.reservedCount += 1;
    this.state.reasons[reason] = nowMs;
    this.save();
  }

  /** 同一槽位别重复预约（同一顿早安/晚安只排一次；slotName: 'morning' | 'night'） */
  isSlotPlanned(slotName: string, slotKey: string): boolean {
    if (slotName === 'morning') {
      return this.state.plannedMorning === slotKey;
    }
    return this.state.plannedNight === slotKey;
  }

  markSlotPlanned(slotName: string, slotKey: string): void {
    if (slotName === 'morning') {
      this.state.plannedMorning = slotKey;
    } else {
      this.state.plannedNight = slotKey;
    }
    this.save();
  }

  /** 通道 B 唤醒记账（§8.4 延迟分布的原始数据：两次 lastWakeMs 的间隔 = 实际周期） */
  markWake(nowMs: number): number {
    const prev: number = this.state.lastWakeMs;
    this.state.lastWakeMs = nowMs;
    this.save();
    return prev;
  }

  /**
   * 通道 A 到点真正说了话（用户点了通知 / 系统弹了）——只更新"上次开口时刻"，
   * **不加今日计数**：额度在预约时已经用 reserve() 占掉了，这里再记就双倍扣。
   */
  markAnchorFired(nowMs: number): void {
    this.state.lastFireMs = nowMs;
    this.save();
  }

  /** 测试提醒 id 记账（#remind-clear 按它取消；只留最近 20 个） */
  addTestReminderId(id: number): void {
    this.state.testReminderIds.push(id);
    if (this.state.testReminderIds.length > 20) {
      this.state.testReminderIds.splice(0, this.state.testReminderIds.length - 20);
    }
    this.save();
  }

  /** 取出并清空测试提醒 id（返回取消前的清单） */
  takeTestReminderIds(): number[] {
    const ids: number[] = this.state.testReminderIds;
    this.state.testReminderIds = [];
    this.save();
    return ids;
  }
}
