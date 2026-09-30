# -*- coding: utf-8 -*-
"""确定性随机源（世界引擎的地基之一）。

⚠️ 这是「确定性重放」承诺的实现点，改任何一行都会让历史世界改变走向：
- 种子由任意键派生（绝对时间桶 / 潮序号），**绝不**用「调用次数」或平台 random；
- mulberry32，全部 32 位整数运算 + 无符号移位，Python 与 ArkTS（Math.imul 等价实现）
  可以逐位对出同一个答案 —— tests/test_vectors.json 就是两端共同的对答案卷。

规则：进引擎的噪声一律走 StepRng("用途名", ...键)，键里必须有绝对时间桶或潮序号。
"""
from __future__ import annotations

_MASK = 0xFFFFFFFF
_GOLDEN = 0x9E3779B9


def _mix32(x: int) -> int:
    x &= _MASK
    x ^= x >> 16
    x = (x * 0x7FEB352D) & _MASK
    x ^= x >> 15
    x = (x * 0x846CA68B) & _MASK
    x ^= x >> 16
    return x


def _key_int(k) -> int:
    """键统一成 32 位整数：字符串按 UTF-8 字节小端折叠（ArkTS 端同规则实现）。"""
    if isinstance(k, str):
        k = int.from_bytes(k.encode("utf-8"), "little")
    return int(k) & _MASK


class StepRng:
    """按 (用途, 键…) 派生种子的确定性随机流。"""

    def __init__(self, *keys) -> None:
        h = _GOLDEN
        for k in keys:
            h = _mix32((h ^ _key_int(k)) & _MASK)
        self._s = h

    def next_u32(self) -> int:
        # mulberry32（参考实现的标准步骤；ArkTS 移植必须逐行对应）
        self._s = (self._s + 0x6D2B79F5) & _MASK
        t = self._s
        t = ((t ^ (t >> 15)) * (t | 1)) & _MASK
        t = (t ^ ((t * (t ^ (t >> 7)) | 61)) & _MASK) & _MASK
        return (t ^ (t >> 14)) & _MASK

    def rand(self) -> float:
        """[0,1) 浮点。"""
        return self.next_u32() / 4294967296.0

    def randint(self, lo: int, hi: int) -> int:
        """闭区间 [lo, hi] 整数。"""
        if hi <= lo:
            return lo
        return lo + self.next_u32() % (hi - lo + 1)
