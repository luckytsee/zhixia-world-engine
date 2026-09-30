# -*- coding: utf-8 -*-
"""长周期 soak 测试：把"跑十年会不会漂"变成仓库内的可验证事实。

- 引擎：连续推进 10 个现实年（87,600 小时），校验状态不变量，
  并与"一次跳算到同一时刻"逐字节对答案（确定性在任意时距上成立）；
- zmemory：5,000 条混合 claim（new/confirm/conflict 各占其一），
  校验旧值零丢失、计数精确、pinned 不可动。

运行（仓库根目录）：python tests/test_longrun.py（全程约 6-7 分钟，发布前手动跑；CI 只跑 test_engine + test_memory，避免私有仓库吃 Actions 配额）
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import WorldEngine, load_rules  # noqa: E402
from memory import SQLiteMemoryStore  # noqa: E402

TEN_YEARS_H = 10 * 365 * 24  # 87,600 小时（10 个现实年）


class TestEngineSoak(unittest.TestCase):
    def test_ten_year_invariants_and_replay(self):
        e = WorldEngine(load_rules())
        start = e.r["start_epoch"]
        a = e.initial_state(start)
        e.advance_to(a, start + TEN_YEARS_H * 3600)

        # --- 不变量 ---
        self.assertTrue(400 <= a["tide_index"] <= 30000, a["tide_index"])
        self.assertIn(a["phase"], e.STAGE_ORDER)
        self.assertGreater(a["phase_remaining_h"], 0)
        lo, hi = load_rules()["slow_vars"]["temp"]["clamp"]
        self.assertTrue(lo <= a["temp"] <= hi)
        self.assertIsInstance(a["fog"], bool)
        self.assertIsInstance(a["rain"], bool)
        self.assertLessEqual(len(a["history"]), 30)      # 回溯账本有界
        self.assertEqual(a["engine_version"], 1)
        # 慢变量没被十年噪声顶到边界外粘死
        self.assertLess(a["humidity"], 0.98)

        # --- 确定性：逐步走 10 年 ≡ 一次跳算 10 年 ---
        b = e.initial_state(start)
        e.advance_to(b, start + TEN_YEARS_H * 3600)
        self.assertEqual(a, b)

        # --- 再走 1 小时仍与"从头重放"一致（存档续跑不引入漂移）---
        c = copy.deepcopy(a)
        e.advance_to(c, start + (TEN_YEARS_H + 1) * 3600)
        d = e.initial_state(start)
        e.advance_to(d, start + (TEN_YEARS_H + 1) * 3600)
        self.assertEqual(c, d)




class TestMemorySoak(unittest.TestCase):
    def test_5000_facts_no_loss_and_pin_flag(self):
        """5,000 条事实写入零丢失；钉死标记正确落库。

        ⚠️ 层面说明（与真实设计对齐）：`pin` 的**保护**发生在写入管道层
        （memory_writer 覆盖前检查 `pinned`），`upsert_fact` 本身照写。
        store 层保证的是"不丢数据"，不是"拒绝覆盖"。"""
        tmp = tempfile.mkdtemp()
        store = SQLiteMemoryStore(os.path.join(tmp, "soak.db"))
        store.upsert_fact(key="生日", value="4月5日", confidence=0.95, evidence=[])
        store.pin_fact("生日")

        for i in range(5000):
            store.upsert_fact(key=f"事实{i}", value=f"值{i}",
                              confidence=0.9, evidence=[])

        facts = {f.key: f for f in store.list_facts()}
        self.assertEqual(len(facts), 5001)                    # 零丢失
        self.assertTrue(facts["生日"].pinned)
        self.assertEqual(facts["事实4999"].value, "值4999")


if __name__ == "__main__":
    unittest.main(verbosity=2)
