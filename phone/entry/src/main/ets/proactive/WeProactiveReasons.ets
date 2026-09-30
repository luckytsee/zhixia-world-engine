/**
 * 由头判断（任务书 §8.3）：通道 B 唤醒时**全本地**判断有没有由头——
 * 唤醒 ≠ 开口，十次唤醒可能只有一次有由头；有由头才调 LLM（省钱闸门）。
 *
 * 归属照抄任务书 §8.3 的表：世界事件 = 本地阈值；未了的事 = 本地查账；
 * 无由头想念 = 本地低概率随机。这里只有状态和阈值，没有一句替她写好的台词
 * （台词由 LLM 看着世界块自己长）。
 */

import type { WeWorldState } from '../world/WeWorldRules';

/** 一个候选由头：reason 是去重键，hint 是给 LLM 的由头说明（不是台词） */
export interface WeProactiveReason {
  reason: string;
  hint: string;
}

/** 无由头想念的概率（每次唤醒独立掷骰；值来自任务书"低概率"的 v1 定值） */
const ZX_MISS_PROB: number = 0.06;
/** 深暗期仍允许惦记包裹的概率（"深暗很少主动开口"≠绝口不提惦记的事） */
const ZX_DARK_PACKAGE_PROB: number = 0.5;

/**
 * 锚点时间窗（2026-09-29 改版：通道 A 的 reminderAgentManager 被 1700002 管控
 * 配额卡死（普通权限配额=0，见开发日志），早安/晚安改由 B 唤醒在窗内补说——
 * 唤醒落在窗里且当天没说过才算。窗比槽位宽（系统唤醒稀疏）。
 */
const ZX_MORNING_WINDOW_H: number = 7.5;   // 7:30
const ZX_MORNING_WINDOW_END_H: number = 10.0;
const ZX_NIGHT_WINDOW_H: number = 21.0;    // 21:00
const ZX_NIGHT_WINDOW_END_H: number = 23.5;

export class WeProactiveReasons {
  /** 唤醒时刻落在哪个锚点窗里；不在任何窗 → '' */
  static anchorWindow(nowMs: number): string {
    const d = new Date(nowMs);
    const h: number = d.getHours() + d.getMinutes() / 60.0;
    if (h >= ZX_MORNING_WINDOW_H && h < ZX_MORNING_WINDOW_END_H) {
      return 'morning';
    }
    if (h >= ZX_NIGHT_WINDOW_H && h < ZX_NIGHT_WINDOW_END_H) {
      return 'night';
    }
    return '';
  }

  /**
   * 返回本次唤醒的由头；null = 没有由头，本次不开口（也不用调 LLM）。
   * 优先级：未了的事 > 世界事件 > 想念（惦记的事最像她会在意的事）。
   * ⚠️ 48h 去重不在这里做（那是节流器的账），这里只做状态判断与档位门控。
   * ⚠️ state=null（快照没带世界段）时只认"未了的事"——世界事件和想念都要真状态。
   */
  static pick(state: WeWorldState | null, staticDayEvery: number,
    unopenedPackages: number, wishesWaiting: number, nowMs: number): WeProactiveReason | null {

    // —— 锚点（原通道 A 的定时问候，改版后由唤醒在窗内补说；调用方已查过"今天没说过"）——
    // ⚠️ 锚点不看世界状态、不看深暗（晚安本来就在夜里）。
    const window: string = WeProactiveReasons.anchorWindow(nowMs);
    if (window === 'morning') {
      const r: WeProactiveReason = {
        reason: 'morning',
        hint: '由头：早上到了你想跟他说早安的时候'
      };
      return r;
    }
    if (window === 'night') {
      const r: WeProactiveReason = {
        reason: 'night',
        hint: '由头：夜里到了你跟他说晚安、催他去睡的时候'
      };
      return r;
    }

    // —— 未了的事（唤醒时本地查账；不依赖世界状态）——
    if (unopenedPackages > 0) {
      const isDark: boolean = state !== null && state.phase === '深暗';
      if (!isDark || Math.random() < ZX_DARK_PACKAGE_PROB) {
        const r: WeProactiveReason = {
          reason: 'package',
          hint: '由头：他寄来的包裹还有 ' + unopenedPackages.toString() + ' 件没拆，'
            + '你可以惦记这件事、好奇里面是什么'
        };
        return r;
      }
    }
    if (state === null) {
      return null;
    }

    const hour: number = new Date(nowMs).getHours();
    const isDark: boolean = state.phase === '深暗';
    if (isDark) {
      // 深暗很少主动开口：世界事件与想念都不触发（上面包裹已按概率放过一半）
      return null;
    }

    // —— 世界事件（唤醒时本地阈值判断，状态是真·此刻）——
    if (state.fog) {
      const r: WeProactiveReason = {
        reason: 'fog',
        hint: '由头：这会儿起了雾（潮气重、能见度低），你看见了想跟他说一声'
      };
      return r;
    }
    if (state.moon_tonight && hour >= 18) {
      const r: WeProactiveReason = {
        reason: 'moon',
        hint: '由头：今夜有月，你抬头看见了，想跟他说一声'
      };
      return r;
    }
    if (staticDayEvery > 0 && (state.tide_index + 1) % staticDayEvery === 0) {
      const r: WeProactiveReason = {
        reason: 'static_day_near',
        hint: '由头：快到静日了（下一潮就是），你想提前跟他说起这件事'
      };
      return r;
    }

    // —— 未了的事第二档：候选池里的心意（她想送他东西）——
    if (wishesWaiting > 0) {
      const r: WeProactiveReason = {
        reason: 'wish',
        hint: '由头：你心里存着一份想送他的心意还没送出去，想跟他提一句'
      };
      return r;
    }

    // —— 无由头想念（本地低概率；只在她的明期，深暗/入暗不想）——
    const bright: boolean = state.phase === '初明' || state.phase === '盛明'
      || state.phase === '斜光';
    if (bright && Math.random() < ZX_MISS_PROB) {
      const r: WeProactiveReason = {
        reason: 'miss',
        hint: '由头：没什么特别的事，就是想他了'
      };
      return r;
    }
    return null;
  }
}
