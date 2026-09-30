# -*- coding: utf-8 -*-
"""StatusDial 纯逻辑测试（不开窗口：颜色决策与格式化是纯函数）。

运行（仓库根目录）：python tests/test_ui.py
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from companion_ui import decide_ink, format_value  # noqa: E402


class TestDialLogic(unittest.TestCase):
    def test_ink_threshold(self):
        self.assertEqual(decide_ink(16.4, 3.0), "#37352F")   # 正常
        self.assertEqual(decide_ink(2.9, 3.0), "#C0392B")    # 低于阈值 → 红
        self.assertEqual(decide_ink(None, 3.0), "#37352F")   # 未取到不误报
        self.assertEqual(decide_ink("16", 3.0), "#37352F")   # 非数值不误报

    def test_format(self):
        self.assertEqual(format_value(None), "—")            # 不知道就显示不知道
        self.assertEqual(format_value(16.0), "16")           # 整数不带小数点
        self.assertEqual(format_value(16.4), "16.4")
        self.assertEqual(format_value(0), "0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
