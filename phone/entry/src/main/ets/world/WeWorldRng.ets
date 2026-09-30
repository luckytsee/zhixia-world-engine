/**
 * StepRng 移植（世界引擎的确定性地基）。
 *
 * ⚠️ 逐行对照 `上游 Python 世界引擎的 engine/rng.py`，改任何一行都会和电脑对出两个世界：
 * - 种子由 (用途名, 绝对时桶/潮序号…) 派生，绝不用调用次数、Date.now()、Math.random()；
 * - mulberry32 的**本项目变体**（rng.py 第 48 行不是网上标准版，少了 `+ t`），
 *   验收向量 tests/test_vectors.json 锚定的是这个变体；
 * - 全部 32 位整数运算：Math.imul + >>>0，每步都落在无符号 32 位里。
 *
 * 本文件不 import 任何 @kit（纯逻辑），便于脱离设备直接对答案。
 */

const ZX_MASK: number = 0xFFFFFFFF;
const ZX_GOLDEN: number = 0x9E3779B9;

/** 种子键：字符串按 UTF-8 字节小端折叠成 int，数字直接 & 0xFFFFFFFF（rng.py _key_int） */
export type WeWorldKey = string | number;

export class WeStepRng {
  private s: number;

  constructor(keys: Array<WeWorldKey>) {
    let h: number = ZX_GOLDEN;
    for (let i = 0; i < keys.length; i++) {
      h = WeStepRng.mix32((h ^ WeStepRng.keyInt(keys[i])) >>> 0);
    }
    this.s = h;
  }

  /** mulberry32（rng.py 第 43–49 行逐行翻译，⚠️ 不是网上标准 mulberry32） */
  nextU32(): number {
    this.s = (this.s + 0x6D2B79F5) >>> 0;
    let t: number = this.s;
    t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
    const p: number = Math.imul(t, t ^ (t >>> 7)) >>> 0;
    t = (t ^ ((p | 61) & ZX_MASK)) >>> 0;
    return (t ^ (t >>> 14)) >>> 0;
  }

  /** [0,1) 浮点（rng.py rand） */
  rand(): number {
    return this.nextU32() / 4294967296.0;
  }

  /** 闭区间 [lo, hi] 整数（rng.py randint） */
  randint(lo: number, hi: number): number {
    if (hi <= lo) {
      return lo;
    }
    return lo + this.nextU32() % (hi - lo + 1);
  }

  /** rng.py _mix32：乘两个奇常量 + 三轮移位异或 */
  private static mix32(x0: number): number {
    let x: number = x0 >>> 0;
    x = (x ^ (x >>> 16)) >>> 0;
    x = Math.imul(x, 0x7FEB352D) >>> 0;
    x = (x ^ (x >>> 15)) >>> 0;
    x = Math.imul(x, 0x846CA68B) >>> 0;
    x = (x ^ (x >>> 16)) >>> 0;
    return x;
  }

  /**
   * 字符串 → UTF-8 字节 → 小端整数，取低 4 字节（等价 Python
   * int.from_bytes(b, 'little') & 0xFFFFFFFF——整串折叠后只留低 32 位）。
   * 现有用途名全在 4 字节内（dur/temp/hum/wind/moon/rev/revh），这里仍按通用规则实现。
   */
  private static keyInt(k: WeWorldKey): number {
    if (typeof k === 'number') {
      return (k & ZX_MASK) >>> 0;
    }
    const bytes: number[] = [];
    for (let i = 0; i < k.length; i++) {
      const c: number = k.charCodeAt(i);
      if (c < 0x80) {
        bytes.push(c);
      } else if (c < 0x800) {
        bytes.push(0xC0 | (c >> 6), 0x80 | (c & 0x3F));
      } else if (c >= 0xD800 && c <= 0xDBFF && i + 1 < k.length
        && k.charCodeAt(i + 1) >= 0xDC00 && k.charCodeAt(i + 1) <= 0xDFFF) {
        // 代理对 → 4 字节
        const cp: number = 0x10000 + ((c - 0xD800) << 10) + (k.charCodeAt(i + 1) - 0xDC00);
        bytes.push(0xF0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3F),
          0x80 | ((cp >> 6) & 0x3F), 0x80 | (cp & 0x3F));
        i += 1;
      } else {
        bytes.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F));
      }
    }
    let v: number = 0;
    const n: number = bytes.length < 4 ? bytes.length : 4;
    for (let i = 0; i < n; i++) {
      v = (v | (bytes[i] << (8 * i))) >>> 0;
    }
    return v >>> 0;
  }
}
