# -*- coding: utf-8 -*-
"""面板骨架纯逻辑测试（不开窗口）。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from companion_ui.panel import anchored_position, next_scale_step  # noqa: E402
from companion_ui.balance import api_root, parse_balance, is_low  # noqa: E402
from companion_ui import balance  # noqa: E402


class TestPanelLogic(unittest.TestCase):
    def test_scale_steps(self):
        steps = [80, 90, 100, 110, 125, 150]
        self.assertEqual(next_scale_step(steps, 100, True), 110)
        self.assertEqual(next_scale_step(steps, 100, False), 90)
        self.assertIsNone(next_scale_step(steps, 150, True))    # 顶格
        self.assertIsNone(next_scale_step(steps, 80, False))    # 底格
        self.assertEqual(next_scale_step(steps, 105, True), 110)  # 不在表内就近取档

    def test_anchor_keeps_bottom_right(self):
        """缩放修正：右下角锚点不动（变大 10% → 左上角左/上让出尺寸）。"""
        old_x = old_y = 100
        old_w, old_h = 760, 300
        nx, ny = anchored_position(old_x, old_y, 100, 110, old_w, old_h, 100)
        new_w, new_h = int(old_w * 1.1), int(old_h * 1.1)
        self.assertEqual(nx + new_w, old_x + old_w)   # 右边缘不动
        self.assertEqual(ny + new_h, old_y + old_h)   # 下边缘不动
        self.assertEqual((nx, ny), (24, 70))


class TestBalance(unittest.TestCase):
    def test_api_root(self):
        self.assertEqual(api_root("https://api.deepseek.com/v1"),
                         "https://api.deepseek.com")
        self.assertEqual(api_root("https://api.deepseek.com/"), "https://api.deepseek.com")

    def test_parse_balance(self):
        payload = {"is_available": True, "balance_infos": [
            {"currency": "CNY", "total_balance": "1.00"},
            {"currency": "USD", "total_balance": "16.40"}]}
        b = parse_balance(payload)
        self.assertTrue(b.ok)
        self.assertEqual(b.amount, 16.4)              # 优先 USD
        self.assertEqual(b.currency, "USD")
        self.assertFalse(parse_balance({}).ok)

    def test_parse_garbage(self):
        self.assertFalse(parse_balance({"balance_infos": []}).ok)
        self.assertFalse(parse_balance({"balance_infos": [
            {"currency": "USD", "total_balance": "abc"}]}).ok)

    def test_is_low(self):
        from companion_ui.balance import Balance
        self.assertTrue(is_low(Balance(ok=True, amount=2.9), 3.0))
        self.assertFalse(is_low(Balance(ok=False, error="x"), 3.0))   # 查询失败不误报


if __name__ == "__main__":
    unittest.main(verbosity=2)
