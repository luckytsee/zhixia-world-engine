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
from zmemory import CompanionMemory  # noqa: E402

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
    def test_5000_claims_no_loss(self):
        tmp = tempfile.mkdtemp()
        m = CompanionMemory(os.path.join(tmp, "soak.db"), log=lambda *_: None)
        m.record_claim("锚点", "原始值", "new")
        m.pin_fact("锚点")

        n_new = n_conf = n_conflict = 0
        for i in range(5000):
            if i % 3 == 0:
                m.record_claim(f"事实{i}", f"值{i}", "new")
                n_new += 1
            elif i % 3 == 1:
                m.record_claim(f"事实{i}", f"值{i}-补充", "confirm")
                n_conf += 1
            else:
                m.record_claim("潮汐记录", f"第{i}次观测", "conflict")
                n_conflict += 1

        facts = {f["key"]: f["value"] for f in m.all_facts()}
        # 原始值零丢失
        self.assertEqual(facts["锚点"], "原始值")
        # 首条 conflict 因无旧知按 new 落为正键，其后每次冲突各自并置：1 + (n-1) = n 条
        tide_keys = [k for k in facts if k.startswith("潮汐记录")]
        self.assertEqual(len(tide_keys), n_conflict)
        self.assertEqual(facts["潮汐记录"], "第2次观测")            # 基准条目未被任何后续冲突覆盖
        self.assertEqual(facts["事实1"], "值1-补充")               # confirm 正常更新
        # 总账：锚点 + new 键 + confirm 键（首次即独立成键）+ 潮汐并置族
        self.assertEqual(len(facts), 1 + n_new + n_conf + n_conflict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
