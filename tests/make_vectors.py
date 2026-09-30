# -*- coding: utf-8 -*-
"""生成验收向量卷 tests/test_vectors.json。

这份卷子有两个用途：
1. 本项目回归：引擎代码任何改动后重跑，答案变了就说明世界的走向变了；
2. ArkTS 移植验收：手机端实现同一套 StepRng/advance 后，跑同一组输入必须同答案。

运行（项目根目录下）：python tests/make_vectors.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import WorldEngine, load_rules, render  # noqa: E402

START_EPOCH = 1759130400
AFTER_HOURS = [6, 30, 400, 2000]


def main() -> None:
    e = WorldEngine(load_rules())
    cases = []
    for h in AFTER_HOURS:
        st = e.initial_state(START_EPOCH)
        e.advance_to(st, START_EPOCH + h * 3600)
        cases.append({
            "after_hours": h,
            "state": st,
            "render_block": render(st, e)["block"],
        })
    out = {
        "start_epoch": START_EPOCH,
        "note": "StepRng(mulberry32) + advance_to 的验收向量；Python 与 ArkTS 必须同答案。",
        "cases": cases,
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_vectors.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("vectors written:", path)


if __name__ == "__main__":
    main()
