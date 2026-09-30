/**
 * WorldEngine 移植：钟表式世界状态机（纯函数、确定性重放）。
 *
 * ⚠️ 逐行对照 `上游 Python 世界引擎的 engine/engine.py`，验收 = tests/test_vectors.json
 * 四组逐字段全对（WeWorldVectors.selfTest）。确定性三条（engine.py 文件头）：
 * - 阶段时长种子 = (用途, 潮序号, 阶段序号, 该阶段开始的绝对时桶)；
 * - 慢变量噪声种子 = (用途, 绝对时桶)；异象骰种子 = (用途, 潮序号)；
 * - 绝对时桶 = epoch 秒 // 3600。逐步走 N 小时 == 一次补算 N 小时。
 *
 * ⚠️ Python round() 是银行家舍入：长暗月 dark_mult=1.25 时 h*1.25 会出精确 .5
 * （h=6→7.5、10→12.5、14→17.5），JS Math.round 全进位 ⇒ 必须用 roundHalfEven。
 */

import { WeStepRng } from './WeWorldRng';
import type { WeWorldRuleMonth, WeWorldRuleStage, WeWorldRules, WeWorldState, WeWorldHistoryEntry, WeWorldSlowVar } from './WeWorldRules';

export class WeWorldEngine {
  static readonly VERSION: number = 1;
  static readonly STAGE_COUNT: number = 5;

  private readonly rules: WeWorldRules;

  constructor(rules: WeWorldRules) {
    this.rules = rules;
  }

  getRules(): WeWorldRules {
    return this.rules;
  }

  /** engine.py month_of */
  monthOf(tideIndex: number): WeWorldRuleMonth {
    const n: number = Math.floor((tideIndex - 1) / this.rules.monthLenTides) % 12;
    return this.rules.months[n];
  }

  /** engine.py year_of */
  yearOf(tideIndex: number): number {
    const perYear: number = this.rules.monthLenTides * this.rules.monthsPerYear;
    return Math.floor((tideIndex - 1) / perYear) + 1;
  }

  stageOf(name: string): WeWorldRuleStage {
    for (let i = 0; i < this.rules.stages.length; i++) {
      if (this.rules.stages[i].name === name) {
        return this.rules.stages[i];
      }
    }
    return this.rules.stages[0];
  }

  stageIndexOf(name: string): number {
    for (let i = 0; i < this.rules.stages.length; i++) {
      if (this.rules.stages[i].name === name) {
        return i;
      }
    }
    return 0;
  }

  /** engine.py initial_state：纪元时刻 = 萌芽期·溪醒月初一，初明开始 */
  initialState(startEpoch: number): WeWorldState {
    const hourAbs: number = Math.floor(startEpoch / 3600);
    const month: WeWorldRuleMonth = this.monthOf(1);
    const st: WeWorldState = {
      engine_version: WeWorldEngine.VERSION,
      hour_abs: hourAbs,
      tide_index: 1,
      phase: this.rules.stages[0].name,
      phase_remaining_h: this.sampleDuration(0, 1, hourAbs, month),
      last_moon_tide: -1000000000,
      reverse_until_h: -1,
      static_day: false,
      moon_tonight: false,
      wind_reverse: false,
      temp: month.temp_base,
      humidity: month.humidity_base,
      wind: month.wind_base,
      fog: false,
      rain: false,
      history: []
    };
    return st;
  }

  /** engine.py advance_to：一口气补算到 nowEpoch（原地改 state 并返回） */
  advanceTo(state: WeWorldState, nowEpoch: number): WeWorldState {
    const target: number = Math.floor(nowEpoch / 3600);
    let guard: number = 0;
    while (state.hour_abs < target) {
      this.stepHour(state);
      state.hour_abs += 1;
      guard += 1;
      if (guard > 1000000) {
        break; // 时钟被拨错时的保险丝，正常离线补算远到不了这个量级
      }
    }
    return state;
  }

  /** engine.py _sample_duration：种子 = ("dur", 潮序号, 阶段序号, 阶段开始的绝对时桶) */
  private sampleDuration(stageIdx: number, tideIndex: number,
    startHourAbs: number, month: WeWorldRuleMonth): number {
    const s: WeWorldRuleStage = this.rules.stages[stageIdx];
    const h: number = new WeStepRng(['dur', tideIndex, stageIdx, startHourAbs])
      .randint(s.min_h, s.max_h);
    let mult: number = 1.0;
    if (month.dark_mult !== null) {
      const v: number | undefined = month.dark_mult[s.name];
      if (v !== undefined) {
        mult = v;
      }
    }
    const raw: number = h * mult;
    const rounded: number = WeWorldEngine.roundHalfEven(raw);
    return Math.max(1, rounded);
  }

  /** engine.py _step_hour：被模拟的这一小时 eh = hour_abs + 1（推进前） */
  private stepHour(state: WeWorldState): void {
    const eh: number = state.hour_abs + 1;
    let month: WeWorldRuleMonth = this.monthOf(state.tide_index);

    // ① 阶段推进（潮边界在这里翻）
    state.phase_remaining_h -= 1;
    if (state.phase_remaining_h <= 0) {
      const idx: number = this.stageIndexOf(state.phase);
      const nxt: number = (idx + 1) % this.rules.stages.length;
      if (nxt === 0) {
        // 深暗走完 → 新的一潮
        this.closeTide(state, month);
        month = this.monthOf(state.tide_index);
      }
      state.phase = this.rules.stages[nxt].name;
      state.phase_remaining_h = this.sampleDuration(nxt, state.tide_index, eh, month);
    }

    // ② 慢变量（噪声按绝对时桶播种 → 补算与逐步走一致）
    const rt: WeStepRng = new WeStepRng(['temp', eh]);
    state.temp = WeWorldEngine.drift(state.temp, month.temp_base, this.rules.temp,
      (rt.rand() - 0.5) * this.rules.temp.noise);
    const rh: WeStepRng = new WeStepRng(['hum', eh]);
    state.humidity = WeWorldEngine.drift(state.humidity, month.humidity_base, this.rules.humidity,
      (rh.rand() - 0.5) * this.rules.humidity.noise);
    if (state.static_day) {
      state.wind = 0.0;
    } else {
      const rw: WeStepRng = new WeStepRng(['wind', eh]);
      state.wind = WeWorldEngine.drift(state.wind, month.wind_base, this.rules.wind,
        (rw.rand() - 0.5) * this.rules.wind.noise);
    }
    state.wind_reverse = eh < state.reverse_until_h;

    // ③ 常态现象（阈值推导，零账本）
    const thr: number = this.rules.fogBaseThreshold - month.fog_boost;
    state.fog = state.humidity >= thr && this.rules.fogPhases.indexOf(state.phase) >= 0;
    state.rain = state.humidity >= this.rules.rainThreshold;
  }

  /** engine.py _drift：惯性混合 + clamp */
  private static drift(oldV: number, base: number, cfg: WeWorldSlowVar, noise: number): number {
    const v: number = oldV * cfg.inertia + base * (1.0 - cfg.inertia) + noise;
    return Math.min(cfg.clampHi, Math.max(cfg.clampLo, v));
  }

  /** engine.py _close_tide：记账上一潮 → 掷本潮的异象骰（种子只用潮序号） */
  private closeTide(state: WeWorldState, endedMonth: WeWorldRuleMonth): void {
    const entry: WeWorldHistoryEntry = {
      tide: state.tide_index,
      season_month: endedMonth.season + '·' + endedMonth.name,
      fog: state.fog,
      rain: state.rain,
      static_day: state.static_day,
      moon: state.moon_tonight,
      temp: WeWorldEngine.roundTo1(state.temp)
    };
    state.history.push(entry);
    if (state.history.length > this.rules.historyKeep) {
      state.history.splice(0, state.history.length - this.rules.historyKeep);
    }

    state.tide_index += 1;
    const t: number = state.tide_index;

    state.static_day = (t % this.rules.staticDayEvery === 0);

    const rm: WeStepRng = new WeStepRng(['moon', t]);
    state.moon_tonight = rm.rand() < 1.0 / this.rules.moonMeanTides
      && (t - state.last_moon_tide) >= this.rules.moonMinGapTides;
    if (state.moon_tonight) {
      state.last_moon_tide = t;
    }

    if (!state.static_day) {
      const rr: WeStepRng = new WeStepRng(['rev', t]);
      if (rr.rand() < this.rules.revPPerTide) {
        const rh: WeStepRng = new WeStepRng(['revh', t]);
        const dur: number = rh.randint(this.rules.revMinH, this.rules.revMaxH);
        state.reverse_until_h = state.hour_abs + 1 + dur;
      }
    }
  }

  /** Python round() 的银行家舍入（.5 时取偶）；仅用于非负小数量级（阶段时长） */
  static roundHalfEven(x: number): number {
    const f: number = Math.floor(x);
    const diff: number = x - f;
    if (diff > 0.5) {
      return f + 1;
    }
    if (diff < 0.5) {
      return f;
    }
    return (f % 2 === 0) ? f : f + 1;
  }

  /** Python round(x, 1)：非精确平手时与 Math.round(x*10)/10 同结果（向量对答案兜底验证） */
  static roundTo1(x: number): number {
    return Math.round(x * 10) / 10;
  }
}
