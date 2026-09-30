/**
 * 验收向量自检——由 PC 侧 tests/test_vectors.json 原样生成（2026-09-29）。
 * 四组（6/30/400/2000 小时）：同一 start_epoch -> initialState -> advanceTo 后，
 * state 必须与卷中逐字段相等（数值精确相等，浮点不动）、renderBlock 逐字符相等。
 * App 启动时 selfTest() 打 hilog `世界向量=4/4`，装机验证过滤 WeWorld 看这行。
 * 再生成：python tools/gen_world_data.py（PC 侧向量变更后重跑）。
 */

import { hilog } from '@kit.PerformanceAnalysisKit';
import { WeWorldEngine } from './WeWorldEngine';
import { renderBlock } from './WeWorldRender';
import { WeWorldParse } from './WeWorldRules';
import type { WeWorldStateRaw, WeWorldState, WeWorldHistoryEntry, WeWorldRulesRaw } from './WeWorldRules';
import { ZX_RULES_JSON } from './WeWorldDefaultRules';

const ZX_LOG_DOMAIN: number = 0x0926;
const ZX_LOG_TAG: string = 'WeWorld';

const ZX_VECTORS_JSON: string = '{"start_epoch":1759130400,"note":"StepRng(mulberry32) + advance_to 的验收向量；Python 与 ArkTS 必须同答案。","cases":[{"after_hours":6,"state":{"engine_version":1,"hour_abs":488653,"tide_index":1,"phase":"盛明","phase_remaining_h":14,"last_moon_tide":-1000000000,"reverse_until_h":-1,"static_day":false,"moon_tonight":false,"wind_reverse":false,"temp":9.637232940000843,"humidity":0.6870029154633213,"wind":0.282871611024855,"fog":false,"rain":false,"history":[]},"render_block":"【她那边此刻】\\n时节：萌芽期·溪醒月（第 1 年）\\n当前：盛明（这一段还剩约 14 小时）\\n光线：正亮，稳定，太阳高度高\\n林中状态：林子最热闹的一段\\n天气：潮气偏重；微风"},{"after_hours":30,"state":{"engine_version":1,"hour_abs":488677,"tide_index":1,"phase":"深暗","phase_remaining_h":8,"last_moon_tide":-1000000000,"reverse_until_h":-1,"static_day":false,"moon_tonight":false,"wind_reverse":false,"temp":9.285837172476427,"humidity":0.6477860061687926,"wind":0.15311839106011965,"fog":false,"rain":false,"history":[]},"render_block":"【她那边此刻】\\n时节：萌芽期·溪醒月（第 1 年）\\n当前：深暗（这一段还剩约 8 小时）\\n光线：黑透，稳定，太阳高度无\\n林中状态：林子换成另一种声音\\n天气：潮气偏重；微风"},{"after_hours":400,"state":{"engine_version":1,"hour_abs":489047,"tide_index":11,"phase":"斜光","phase_remaining_h":1,"last_moon_tide":-1000000000,"reverse_until_h":-1,"static_day":false,"moon_tonight":false,"wind_reverse":false,"temp":9.757584209675876,"humidity":0.6431887496743891,"wind":0.4145601662251387,"fog":false,"rain":false,"history":[{"tide":1,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":8.7},{"tide":2,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":8.5},{"tide":3,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":7.5},{"tide":4,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":7.7},{"tide":5,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":9.8},{"tide":6,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":9.4},{"tide":7,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":9.6},{"tide":8,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":8.0},{"tide":9,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":4.6},{"tide":10,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":10.7}]},"render_block":"【她那边此刻】\\n时节：萌芽期·溪醒月（第 1 年）\\n当前：斜光（这一段还剩约 1 小时）\\n光线：正在明显变暗，太阳高度低\\n林中状态：金色斜光，影子拉得很长\\n天气：潮气偏重；风不小"},{"after_hours":2000,"state":{"engine_version":1,"hour_abs":490647,"tide_index":55,"phase":"盛明","phase_remaining_h":9,"last_moon_tide":53,"reverse_until_h":490061,"static_day":false,"moon_tonight":false,"wind_reverse":false,"temp":12.025888923411296,"humidity":0.6449990151832677,"wind":0.18424723413536087,"fog":false,"rain":false,"history":[{"tide":25,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":7.5},{"tide":26,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":9.4},{"tide":27,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":9.1},{"tide":28,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":8.0},{"tide":29,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":11.9},{"tide":30,"season_month":"萌芽期·溪醒月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":9.9},{"tide":31,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":13.5},{"tide":32,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":15.4},{"tide":33,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":14.2},{"tide":34,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":12.0},{"tide":35,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":17.2},{"tide":36,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":12.7},{"tide":37,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":true,"moon":false,"temp":10.4},{"tide":38,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":11.7},{"tide":39,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":10.5},{"tide":40,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":15.0},{"tide":41,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":15.1},{"tide":42,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":10.4},{"tide":43,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":14.8},{"tide":44,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":12.8},{"tide":45,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":13.6},{"tide":46,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":11.2},{"tide":47,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":13.7},{"tide":48,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":11.3},{"tide":49,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":7.9},{"tide":50,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":11.3},{"tide":51,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":12.2},{"tide":52,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":15.3},{"tide":53,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":true,"temp":15.0},{"tide":54,"season_month":"萌芽期·抽芽月","fog":false,"rain":false,"static_day":false,"moon":false,"temp":11.2}]},"render_block":"【她那边此刻】\\n时节：萌芽期·抽芽月（第 1 年）\\n当前：盛明（这一段还剩约 9 小时）\\n光线：正亮，稳定，太阳高度高\\n林中状态：林子最热闹的一段\\n天气：潮气偏重；微风"}]}';

interface WeVectorCaseRaw {
  after_hours?: number;
  state?: WeWorldStateRaw;
  render_block?: string;
}

interface WeVectorsRaw {
  start_epoch?: number;
  cases?: WeVectorCaseRaw[];
}

export class WeWorldVectors {
  /**
   * 跑全部向量，返回 '4/4' 或 'N/4: 首个失败详情'。
   * ⚠️ state 比较是**逐字段**：数值要求精确相等（浮点不动），漏比也算失败。
   */
  static run(): string {
    let raw: WeVectorsRaw;
    try {
      raw = JSON.parse(ZX_VECTORS_JSON) as WeVectorsRaw;
    } catch (err) {
      return '0/4: 向量 JSON 损坏';
    }
    if (typeof raw.start_epoch !== 'number' || !Array.isArray(raw.cases) || raw.cases.length === 0) {
      return '0/4: 向量形状不对';
    }
    let rulesRaw: object;
    try {
      rulesRaw = JSON.parse(ZX_RULES_JSON) as object;
    } catch (err) {
      return '0/4: 内置 rules JSON 损坏';
    }
    const rules = WeWorldParse.rules(rulesRaw as WeWorldRulesRaw);
    if (rules === null) {
      return '0/4: 内置 rules 解析失败';
    }
    const engine = new WeWorldEngine(rules);
    const start: number = raw.start_epoch;
    let pass = 0;
    for (let i = 0; i < raw.cases.length; i++) {
      const c = raw.cases[i];
      const expectState = WeWorldParse.state(c.state === undefined ? null : c.state);
      if (typeof c.after_hours !== 'number' || expectState === null
        || typeof c.render_block !== 'string') {
        return pass.toString() + '/' + raw.cases.length.toString() + ': 向量第'
          + (i + 1).toString() + '组形状不对';
      }
      const got: WeWorldState = engine.advanceTo(engine.initialState(start),
        start + c.after_hours * 3600);
      const diff = WeWorldVectors.stateDiff(got, expectState);
      if (diff !== '') {
        return pass.toString() + '/' + raw.cases.length.toString() + ': ' + c.after_hours.toString()
          + 'h ' + diff;
      }
      const gotBlock = renderBlock(got, engine);
      if (gotBlock !== c.render_block) {
        return pass.toString() + '/' + raw.cases.length.toString() + ': ' + c.after_hours.toString()
          + 'h render 不一致';
      }
      pass += 1;
    }
    return pass.toString() + '/' + raw.cases.length.toString();
  }

  /** App 启动自检：结果打 hilog（domain 0x0926, tag WeWorld），不阻塞启动 */
  static selfTest(): void {
    const t0 = Date.now();
    const r = WeWorldVectors.run();
    hilog.info(ZX_LOG_DOMAIN, ZX_LOG_TAG, '世界向量=%{public}s (耗时%{public}dms)',
      r, Date.now() - t0);
  }

  private static stateDiff(got: WeWorldState, want: WeWorldState): string {
    if (got.hour_abs !== want.hour_abs) {
      return 'hour_abs ' + got.hour_abs.toString() + '≠' + want.hour_abs.toString();
    }
    if (got.tide_index !== want.tide_index) {
      return 'tide_index ' + got.tide_index.toString() + '≠' + want.tide_index.toString();
    }
    if (got.phase !== want.phase) {
      return 'phase ' + got.phase + '≠' + want.phase;
    }
    if (got.phase_remaining_h !== want.phase_remaining_h) {
      return 'phase_remaining_h ' + got.phase_remaining_h.toString() + '≠'
        + want.phase_remaining_h.toString();
    }
    if (got.last_moon_tide !== want.last_moon_tide) {
      return 'last_moon_tide 不等';
    }
    if (got.reverse_until_h !== want.reverse_until_h) {
      return 'reverse_until_h ' + got.reverse_until_h.toString() + '≠'
        + want.reverse_until_h.toString();
    }
    if (got.static_day !== want.static_day || got.moon_tonight !== want.moon_tonight
      || got.wind_reverse !== want.wind_reverse || got.fog !== want.fog
      || got.rain !== want.rain) {
      return '布尔字段不等';
    }
    if (got.temp !== want.temp) {
      return 'temp ' + got.temp.toString() + '≠' + want.temp.toString();
    }
    if (got.humidity !== want.humidity) {
      return 'humidity ' + got.humidity.toString() + '≠' + want.humidity.toString();
    }
    if (got.wind !== want.wind) {
      return 'wind ' + got.wind.toString() + '≠' + want.wind.toString();
    }
    if (got.history.length !== want.history.length) {
      return 'history 条数 ' + got.history.length.toString() + '≠'
        + want.history.length.toString();
    }
    for (let i = 0; i < want.history.length; i++) {
      const a: WeWorldHistoryEntry = got.history[i];
      const b: WeWorldHistoryEntry = want.history[i];
      if (a.tide !== b.tide || a.season_month !== b.season_month || a.temp !== b.temp
        || a.fog !== b.fog || a.rain !== b.rain || a.static_day !== b.static_day
        || a.moon !== b.moon) {
        return 'history[' + i.toString() + '] 不等';
      }
    }
    return '';
  }
}
