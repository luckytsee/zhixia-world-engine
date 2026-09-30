/**
 * 渲染层移植：状态 → 注入用文本（只给状态，不给台词）。
 *
 * ⚠️ 逐行对照 `上游 Python 世界引擎的 engine/render.py`：定性词表与阈值一字不差，
 * render 产出的 block 在验收向量里逐字符比对——她怎么说由她自己长出来，
 * 这个文件里多一个形容词都是移植错误。
 */

import type { WeWorldEngine } from './WeWorldEngine';
import type { WeWorldState } from './WeWorldRules';

/** render.py _humidity_word */
function humidityWord(h: number): string {
  if (h < 0.40) {
    return '干燥';
  }
  if (h < 0.62) {
    return '正常';
  }
  if (h < 0.78) {
    return '偏重';
  }
  return '很重';
}

/** render.py _wind_word */
function windWord(state: WeWorldState): string {
  if (state.wind_reverse) {
    return '风整个反着吹';
  }
  const w: number = state.wind;
  if (w < 0.05) {
    return '没有一丝风';
  }
  if (w < 0.30) {
    return '微风';
  }
  if (w < 0.60) {
    return '风不小';
  }
  return '风很大';
}

/**
 * render.py render：返回可直接注入的多行文本（首行【她那边此刻】）。
 * 字段顺序 = Python dict 插入序：时节/当前/光线/林中状态/天气/[异象]——别重排。
 */
export function renderBlock(state: WeWorldState, engine: WeWorldEngine): string {
  const stage = engine.stageOf(state.phase);
  const month = engine.monthOf(state.tide_index);
  const year = engine.yearOf(state.tide_index);

  const remain: number = Math.max(0, state.phase_remaining_h);
  let weather: string = '潮气' + humidityWord(state.humidity);
  if (state.fog) {
    weather += '，起了雾';
  }
  if (state.rain) {
    weather += '，在下雨';
  }
  weather += '；' + windWord(state);

  const lines: string[] = [];
  lines.push('【她那边此刻】');
  lines.push('时节：' + month.season + '·' + month.name + '（第 ' + year.toString() + ' 年）');
  lines.push('当前：' + state.phase + '（这一段还剩约 ' + remain.toString() + ' 小时）');
  lines.push('光线：' + stage.light + '，太阳高度' + stage.sun);
  lines.push('林中状态：' + stage.forest);
  lines.push('天气：' + weather);
  const omens: string[] = [];
  if (state.static_day) {
    omens.push('静日：全天没有一丝风');
  }
  if (state.moon_tonight) {
    omens.push('今夜有月');
  }
  if (state.wind_reverse) {
    omens.push('风向反了');
  }
  if (omens.length > 0) {
    lines.push('异象：' + omens.join('；'));
  }
  return lines.join('\n');
}
