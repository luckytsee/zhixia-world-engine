# -*- coding: utf-8 -*-
"""EmotionPanel 的图像加载路径测试（GUI，会开真窗口）。

⚠️ 存在的理由：此前只测纯函数（next_scale_step / anchored_position），
GUI 图像路径零覆盖 ⇒ `self._PIL.Image.open` 这种必然崩的写法没被拦住
（2026-10-01 外部审查抓到）。此文件专门走真实加载路径：
建一张临时 PNG → set_emotion → 断言立绘真的贴上了。

运行：python -m pytest tests/test_panel_gui.py -q
（无图形环境 / Tcl 运行库缺失时整类跳过，不误报）
"""


from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _gui_available() -> bool:
    """探测图形环境。Tk/Tcl 缺失、无显示器等任何异常都返回 False。

    ⚠️ 用**子进程**探测：某些残缺的 Tcl 安装会在创建 Tk 实例时让解释器状态
    变得不可用（本机 Python 3.12 即如此），进程内探测会把后续测试一起带崩。
    """
    import subprocess
    try:
        r = subprocess.run(
            [sys.executable, "-c",
             "import tkinter as tk; root = tk.Tk(); root.withdraw(); root.destroy()"],
            capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


_HAVE_GUI = _gui_available()
if not _HAVE_GUI:
    print("[跳过] 图形环境不可用（Tk/Tcl 缺失或无显示器）")
tk = None
Image = None
if _HAVE_GUI:
    import tkinter as tk          # noqa: F811
    from PIL import Image         # noqa: F811


@unittest.skipUnless(_HAVE_GUI, "无图形环境，跳过 GUI 测试")
class TestPanelImagePath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        from companion_ui.panel import EmotionPanel
        self.tmp = tempfile.mkdtemp()
        self.img_path = os.path.join(self.tmp, "happy.png")
        Image.new("RGBA", (64, 64), (80, 160, 90, 255)).save(self.img_path)
        self.panel = EmotionPanel(
            self.root, images={"happy": self.img_path},
            default_size=(120, 80),
            position_file=os.path.join(self.tmp, "pos.json"))

    def tearDown(self):
        try:
            self.panel.canvas.destroy()
        except Exception:
            pass

    def test_set_emotion_loads_real_image(self):
        """有图时必须真的贴上图（这是此前崩掉的那条路径）。"""
        self.panel.set_emotion("happy")
        self.assertIsNotNone(self.panel._photo)
        items = self.panel.canvas.find_all()
        self.assertTrue(any(self.panel.canvas.type(i) == "image" for i in items))

    def test_unknown_emotion_falls_back(self):
        """未知情绪无图 → 自绘兜底不报错；再切回有图的仍能工作。"""
        self.panel.set_emotion("不存在的情绪")
        self.assertIsNone(self.panel._photo)
        self.panel.set_emotion("happy")
        self.assertIsNotNone(self.panel._photo)

    def test_scale_reloads_image(self):
        """缩放后立绘重新贴图。"""
        self.panel.set_emotion("happy")
        self.panel.set_scale(125)
        self.assertIsNotNone(self.panel._photo)
        self.assertEqual(self.panel.w, 150)


if __name__ == "__main__":
    unittest.main(verbosity=2)
