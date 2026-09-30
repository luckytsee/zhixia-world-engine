/**
 * 世界引擎的类型与解析：rules（世界参数）+ state（世界状态）。
 *
 * ⚠️ 命名刻意保持**蛇形**（与 PC `rules.json` / 快照 world 段逐字一致）：
 * 这份数据从网线到磁盘到引擎**不改键名**——历史上 WeSnapshotStore 的
 * "写盘驼峰/读盘蛇形"往返 bug 恰恰出在改名上，这里整体不动名就没有往返。
 * Raw 后缀 = JSON.parse 第一跳（字段可缺），经 parse 校验后拷进严格类型。
 */

// ---- rules（世界参数，形状 = 上游 Python 世界引擎的 rules.json） ----

export interface WeWorldRuleStageRaw {
  name?: string;
  mean_h?: number;
  min_h?: number;
  max_h?: number;
  light?: string;
  sun?: string;
  forest?: string;
}

export interface WeWorldRuleMonthRaw {
  n?: number;
  name?: string;
  season?: string;
  phen?: string;
  temp_base?: number;
  humidity_base?: number;
  wind_base?: number;
  fog_boost?: number;
  dark_mult?: Record<string, number>;
}

export interface WeWorldRulesRaw {
  engine_version?: number;
  start_epoch?: number;
  calendar?: WeWorldCalendarRaw;
  stages?: WeWorldRuleStageRaw[];
  months?: WeWorldRuleMonthRaw[];
  slow_vars?: WeWorldSlowVarsRaw;
  fog?: WeWorldFogRaw;
  rain_threshold?: number;
  static_day_every?: number;
  moon?: WeWorldMoonRaw;
  reverse_wind?: WeWorldReverseWindRaw;
  history_keep?: number;
}

export interface WeWorldCalendarRaw {
  month_len_tides?: number;
  months_per_year?: number;
}

export interface WeWorldSlowVarRaw {
  inertia?: number;
  noise?: number;
  clamp?: number[];
}

export interface WeWorldSlowVarsRaw {
  temp?: WeWorldSlowVarRaw;
  humidity?: WeWorldSlowVarRaw;
  wind?: WeWorldSlowVarRaw;
}

export interface WeWorldFogRaw {
  base_threshold?: number;
  phases?: string[];
}

export interface WeWorldMoonRaw {
  mean_tides?: number;
  min_gap_tides?: number;
}

export interface WeWorldReverseWindRaw {
  p_per_tide?: number;
  min_h?: number;
  max_h?: number;
}

/** 严格 rules（引擎只用这些字段；与 Raw 同名，只是必填化） */
export interface WeWorldRuleStage {
  name: string;
  min_h: number;
  max_h: number;
  light: string;
  sun: string;
  forest: string;
}

export interface WeWorldRuleMonth {
  name: string;
  season: string;
  temp_base: number;
  humidity_base: number;
  wind_base: number;
  fog_boost: number;
  dark_mult: Record<string, number> | null;
}

export interface WeWorldSlowVar {
  inertia: number;
  noise: number;
  clampLo: number;
  clampHi: number;
}

export interface WeWorldRules {
  stages: WeWorldRuleStage[];
  months: WeWorldRuleMonth[];
  monthLenTides: number;
  monthsPerYear: number;
  temp: WeWorldSlowVar;
  humidity: WeWorldSlowVar;
  wind: WeWorldSlowVar;
  fogBaseThreshold: number;
  fogPhases: string[];
  rainThreshold: number;
  staticDayEvery: number;
  moonMeanTides: number;
  moonMinGapTides: number;
  revPPerTide: number;
  revMinH: number;
  revMaxH: number;
  historyKeep: number;
}

// ---- state（世界状态，形状 = 快照 world.state，蛇形照抄 PC） ----

export interface WeWorldHistoryEntry {
  tide: number;
  season_month: string;
  fog: boolean;
  rain: boolean;
  static_day: boolean;
  moon: boolean;
  temp: number;
}

export interface WeWorldStateRaw {
  engine_version?: number;
  hour_abs?: number;
  tide_index?: number;
  phase?: string;
  phase_remaining_h?: number;
  last_moon_tide?: number;
  reverse_until_h?: number;
  static_day?: boolean;
  moon_tonight?: boolean;
  wind_reverse?: boolean;
  temp?: number;
  humidity?: number;
  wind?: number;
  fog?: boolean;
  rain?: boolean;
  history?: WeWorldHistoryEntry[];
}

/** 严格 state（advanceTo 原地改它；蛇形键与 PC 逐字一致，别改名） */
export interface WeWorldState {
  engine_version: number;
  hour_abs: number;
  tide_index: number;
  phase: string;
  phase_remaining_h: number;
  last_moon_tide: number;
  reverse_until_h: number;
  static_day: boolean;
  moon_tonight: boolean;
  wind_reverse: boolean;
  temp: number;
  humidity: number;
  wind: number;
  fog: boolean;
  rain: boolean;
  history: WeWorldHistoryEntry[];
}

// ---- 解析 ----

export class WeWorldParse {
  /** rules JSON → 严格 rules；形状不对/缺关键字段 → null（宁可不用，不喂半份数据） */
  static rules(raw: WeWorldRulesRaw | null): WeWorldRules | null {
    if (raw === null || raw === undefined) {
      return null;
    }
    const cal = raw.calendar;
    const sv = raw.slow_vars;
    const fog = raw.fog;
    const moon = raw.moon;
    const rev = raw.reverse_wind;
    if (cal === undefined || cal.month_len_tides === undefined || cal.months_per_year === undefined
      || sv === undefined || fog === undefined || moon === undefined || rev === undefined
      || raw.rain_threshold === undefined || raw.static_day_every === undefined
      || raw.history_keep === undefined) {
      return null;
    }
    const stages: WeWorldRuleStage[] = [];
    if (Array.isArray(raw.stages)) {
      const rs: WeWorldRuleStageRaw[] = raw.stages;
      for (let i = 0; i < rs.length; i++) {
        const s = rs[i];
        if (typeof s.name !== 'string' || typeof s.min_h !== 'number'
          || typeof s.max_h !== 'number' || typeof s.light !== 'string'
          || typeof s.sun !== 'string' || typeof s.forest !== 'string') {
          return null;
        }
        const st: WeWorldRuleStage = {
          name: s.name, min_h: s.min_h, max_h: s.max_h,
          light: s.light, sun: s.sun, forest: s.forest
        };
        stages.push(st);
      }
    }
    if (stages.length === 0) {
      return null;
    }
    const months: WeWorldRuleMonth[] = [];
    if (Array.isArray(raw.months)) {
      const rm: WeWorldRuleMonthRaw[] = raw.months;
      for (let i = 0; i < rm.length; i++) {
        const m = rm[i];
        if (typeof m.name !== 'string' || typeof m.season !== 'string'
          || typeof m.temp_base !== 'number' || typeof m.humidity_base !== 'number'
          || typeof m.wind_base !== 'number') {
          return null;
        }
        const mm: WeWorldRuleMonth = {
          name: m.name, season: m.season, temp_base: m.temp_base,
          humidity_base: m.humidity_base, wind_base: m.wind_base,
          fog_boost: typeof m.fog_boost === 'number' ? m.fog_boost : 0.0,
          dark_mult: m.dark_mult !== undefined ? m.dark_mult : null
        };
        months.push(mm);
      }
    }
    if (months.length === 0) {
      return null;
    }
    const temp = WeWorldParse.slowVar(sv.temp);
    const hum = WeWorldParse.slowVar(sv.humidity);
    const wind = WeWorldParse.slowVar(sv.wind);
    if (temp === null || hum === null || wind === null) {
      return null;
    }
    const phases: string[] = [];
    if (Array.isArray(fog.phases)) {
      const fp: string[] = fog.phases;
      for (let i = 0; i < fp.length; i++) {
        if (typeof fp[i] === 'string') {
          phases.push(fp[i]);
        }
      }
    }
    if (phases.length === 0) {
      return null;
    }
    if (typeof moon.mean_tides !== 'number' || typeof moon.min_gap_tides !== 'number'
      || typeof rev.p_per_tide !== 'number' || typeof rev.min_h !== 'number'
      || typeof rev.max_h !== 'number') {
      return null;
    }
    const rules: WeWorldRules = {
      stages: stages,
      months: months,
      monthLenTides: cal.month_len_tides,
      monthsPerYear: cal.months_per_year,
      temp: temp,
      humidity: hum,
      wind: wind,
      fogBaseThreshold: typeof fog.base_threshold === 'number' ? fog.base_threshold : 0.0,
      fogPhases: phases,
      rainThreshold: raw.rain_threshold,
      staticDayEvery: raw.static_day_every,
      moonMeanTides: moon.mean_tides,
      moonMinGapTides: moon.min_gap_tides,
      revPPerTide: rev.p_per_tide,
      revMinH: rev.min_h,
      revMaxH: rev.max_h,
      historyKeep: raw.history_keep
    };
    return rules;
  }

  private static slowVar(raw: WeWorldSlowVarRaw | undefined): WeWorldSlowVar | null {
    if (raw === undefined || typeof raw.inertia !== 'number' || typeof raw.noise !== 'number'
      || !Array.isArray(raw.clamp) || raw.clamp.length < 2) {
      return null;
    }
    const cl: number[] = raw.clamp;
    if (typeof cl[0] !== 'number' || typeof cl[1] !== 'number') {
      return null;
    }
    const v: WeWorldSlowVar = { inertia: raw.inertia, noise: raw.noise, clampLo: cl[0], clampHi: cl[1] };
    return v;
  }

  /** state → 严格 state；形状不对 → null（世界宁可缺席，不崩聊天） */
  static state(raw: WeWorldStateRaw | null): WeWorldState | null {
    if (raw === null || raw === undefined) {
      return null;
    }
    if (typeof raw.engine_version !== 'number' || typeof raw.hour_abs !== 'number'
      || typeof raw.tide_index !== 'number' || typeof raw.phase !== 'string'
      || typeof raw.phase_remaining_h !== 'number' || typeof raw.last_moon_tide !== 'number'
      || typeof raw.reverse_until_h !== 'number' || typeof raw.temp !== 'number'
      || typeof raw.humidity !== 'number' || typeof raw.wind !== 'number'
      || typeof raw.static_day !== 'boolean' || typeof raw.moon_tonight !== 'boolean'
      || typeof raw.wind_reverse !== 'boolean' || typeof raw.fog !== 'boolean'
      || typeof raw.rain !== 'boolean') {
      return null;
    }
    const history: WeWorldHistoryEntry[] = [];
    if (Array.isArray(raw.history)) {
      const rh: WeWorldHistoryEntry[] = raw.history;
      for (let i = 0; i < rh.length; i++) {
        const h = rh[i];
        if (typeof h !== 'object' || h === null) {
          continue;
        }
        if (typeof h.tide !== 'number' || typeof h.season_month !== 'string'
          || typeof h.temp !== 'number' || typeof h.fog !== 'boolean'
          || typeof h.rain !== 'boolean' || typeof h.static_day !== 'boolean'
          || typeof h.moon !== 'boolean') {
          continue;
        }
        const e: WeWorldHistoryEntry = {
          tide: h.tide, season_month: h.season_month, fog: h.fog, rain: h.rain,
          static_day: h.static_day, moon: h.moon, temp: h.temp
        };
        history.push(e);
      }
    }
    const st: WeWorldState = {
      engine_version: raw.engine_version,
      hour_abs: raw.hour_abs,
      tide_index: raw.tide_index,
      phase: raw.phase,
      phase_remaining_h: raw.phase_remaining_h,
      last_moon_tide: raw.last_moon_tide,
      reverse_until_h: raw.reverse_until_h,
      static_day: raw.static_day,
      moon_tonight: raw.moon_tonight,
      wind_reverse: raw.wind_reverse,
      temp: raw.temp,
      humidity: raw.humidity,
      wind: raw.wind,
      fog: raw.fog,
      rain: raw.rain,
      history: history
    };
    return st;
  }
}
