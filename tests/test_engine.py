# -*- coding: utf-8 -*-
"""世界引擎测试：确定性重放 / 历法 / 静日 / 渲染 / 验收向量。

运行（项目根目录下）：python tests/test_engine.py
向量卷 tests/test_vectors.json 由 tests/make_vectors.py 生成——
它同时是将来 ArkTS 移植的验收标准（两端跑同一组输入必须同答案）。
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import WorldEngine, load_rules, load_or_init_state, render  # noqa: E402

START_EPOCH = 1759130400  # 固定起点，向量卷同款（与纪元无关）


def fresh_engine() -> WorldEngine:
    return WorldEngine(load_rules())


class TestCalendar(unittest.TestCase):
    def test_month_year_mapping(self):
        e = fresh_engine()
        self.assertEqual(e.month_of(1)["name"], "溪醒月")
        self.assertEqual(e.month_of(30)["name"], "溪醒月")
        self.assertEqual(e.month_of(31)["name"], "抽芽月")
        self.assertEqual(e.month_of(241)["name"], "长暗月")   # 第 9 月
        self.assertEqual(e.year_of(360), 1)
        self.assertEqual(e.year_of(361), 2)

    def test_year_rollover(self):
        e = fresh_engine()
        st = e.initial_state(START_EPOCH)
        e.advance_to(st, START_EPOCH + 361 * 36 * 3600)  # 361 潮 × 均值 36h
        self.assertEqual(st["tide_index"] >= 361, True)
        self.assertEqual(e.year_of(st["tide_index"]) >= 2, True)
        self.assertTrue(len(st["history"]) > 0)

    def test_epoch_from_rules(self):
        """纪元＝2008-09-29（他的 18 周岁）；18 现实年 ≈ 她的 12.15 年 → 第 13 年、萌芽期。"""
        e = fresh_engine()
        st = e.initial_state()  # 不传参 → 用 rules.json 的 start_epoch
        self.assertEqual(st["hour_abs"], 1222617600 // 3600)
        e.advance_to(st, 1222617600 + 18 * 365 * 24 * 3600)
        self.assertEqual(e.year_of(st["tide_index"]), 13)
        self.assertEqual(e.month_of(st["tide_index"])["season"], "萌芽期")

    def test_load_or_init_state(self):
        """账本入口：首次初始化→落盘；再读→补算衔接（不重置世界）。"""
        import tempfile
        e = fresh_engine()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "world_state.json")
            a = load_or_init_state(e, path=p, now=1222617600 + 100 * 3600)
            tide_a = a["tide_index"]
            b = load_or_init_state(e, path=p, now=1222617600 + 200 * 3600)
            self.assertGreater(b["tide_index"], tide_a)  # 世界继续走，没有重置
            self.assertTrue(os.path.exists(p))

    def test_dark_month_mult(self):
        e = fresh_engine()
        m9 = e.month_of(241)
        self.assertEqual(m9["dark_mult"]["深暗"], 1.25)
        # 深暗 6–16 × 1.25 → 8–20（与法典「暗期合计 8–20」吻合）
        for _ in range(50):
            d = e._sample_duration(4, 241, 999999, m9)
            self.assertTrue(8 <= d <= 20)


class TestDeterminism(unittest.TestCase):
    def test_stepwise_equals_jump(self):
        """逐步走 200 小时 ≡ 一次补算 200 小时（确定性重放的核心承诺）。"""
        e = fresh_engine()
        a = e.initial_state(START_EPOCH)
        b = copy.deepcopy(a)
        for i in range(1, 201):
            e.advance_to(a, START_EPOCH + i * 3600)
        e.advance_to(b, START_EPOCH + 200 * 3600)
        self.assertEqual(a, b)

    def test_replay_from_saved_json(self):
        """存档 JSON 往返后重算，结果一致（磁盘为数据源）。"""
        e = fresh_engine()
        a = e.initial_state(START_EPOCH)
        e.advance_to(a, START_EPOCH + 500 * 3600)
        roundtrip = json.loads(json.dumps(a))
        e.advance_to(roundtrip, START_EPOCH + 600 * 3600)
        c = e.initial_state(START_EPOCH)
        e.advance_to(c, START_EPOCH + 600 * 3600)
        self.assertEqual(roundtrip, c)


class TestAnomalies(unittest.TestCase):
    def test_static_day_forces_zero_wind(self):
        e = fresh_engine()
        st = e.initial_state(START_EPOCH)
        st["tide_index"] = 36          # 下一潮 = 37 → 静日
        st["phase"] = "深暗"
        st["phase_remaining_h"] = 1
        st["static_day"] = False
        e.advance_to(st, (st["hour_abs"] + 2) * 3600)
        self.assertTrue(st["static_day"])
        self.assertEqual(st["wind"], 0.0)

    def test_history_records(self):
        e = fresh_engine()
        st = e.initial_state(START_EPOCH)
        e.advance_to(st, START_EPOCH + 40 * 36 * 3600)  # 约 40 潮
        # history 只留最近 30 潮（设计行为）：第 1 潮应被滚掉，第 11 潮应在
        self.assertFalse(any(h["tide"] == 1 for h in st["history"]))
        self.assertTrue(any(h["tide"] == 11 for h in st["history"]))
        self.assertLessEqual(len(st["history"]), 30)


class TestRender(unittest.TestCase):
    def test_fields_and_block(self):
        e = fresh_engine()
        st = e.initial_state(START_EPOCH)
        e.advance_to(st, START_EPOCH + 100 * 3600)
        out = render(st, e)
        for key in ("时节", "当前", "光线", "林中状态", "天气"):
            self.assertIn(key, out["fields"])
        self.assertTrue(out["block"].startswith("【她那边此刻】"))
        # 只给状态不给台词：字段里不许出现引号包裹的固定口语
        for v in out["fields"].values():
            self.assertNotIn("「", v)


class TestVectors(unittest.TestCase):
    def test_against_saved_vectors(self):
        """与向量卷对答案（移植/重构后必须仍然全对）。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_vectors.json")
        with open(path, "r", encoding="utf-8") as f:
            vectors = json.load(f)
        e = fresh_engine()
        for case in vectors["cases"]:
            st = e.initial_state(vectors["start_epoch"])
            e.advance_to(st, vectors["start_epoch"] + case["after_hours"] * 3600)
            self.assertEqual(st, case["state"], f"向量不符: +{case['after_hours']}h")
            self.assertEqual(render(st, e)["block"], case["render_block"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
