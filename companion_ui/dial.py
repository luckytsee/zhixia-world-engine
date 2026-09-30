# -*- coding: utf-8 -*-
"""StatusDial：桌面伴侣的状态圆盘组件（tkinter Canvas 自绘）。

源自知夏桌面端的余额圆盘：圆环 + 大数字 + 下方小字，数值低于阈值整组变红，
按固定间隔刷新。提炼为通用组件——标签、单位、阈值、颜色都可配。

用法：
    from companion_ui import StatusDial
    dial = StatusDial(root, label="余额", unit="¥", low=3.0)
    dial.set_value(16.4)          # 正常显示
    dial.set_value(None)          # 未取到 → 显示 "—"（不编数字）
    dial.poll(fetch, seconds=60)  # 定时刷新（fetch 返回数值或 None）
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# 缺省配色（主项目同源：墨色数字、低于阈值转深红）
INK_NORMAL = "#37352F"
INK_LOW = "#C0392B"
RING_BG = "#E9E9E8"
RING_FG = "#2D4A3E"


def decide_ink(value, low: float) -> str:
    """纯函数：数值低于阈值 → 警示色。None/非数值 → 正常色。"""
    if isinstance(value, (int, float)) and value < low:
        return INK_LOW
    return INK_NORMAL


def format_value(value) -> str:
    """纯函数：None → "—"（不知道就显示不知道，不编数字）；整数不带小数点。"""
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class StatusDial(tk.Canvas):
    """圆环状态盘。size 为画布边长（正方形）；ring 占外圈 70%，中间大数字，下方小字。"""

    def __init__(self, master, size: int = 90, label: str = "", unit: str = "",
                 low: float = 0.0, scale: float = 1.0,
                 font_family: str | None = None, **kwargs) -> None:
        self.S_size = int(size * scale)
        super().__init__(master, width=self.S_size, height=self.S_size,
                         highlightthickness=0, bg=kwargs.pop("bg", "white"))
        self.scale = scale
        self.low = float(low)
        self.label = label
        self.unit = unit
        self.font_family = font_family or ("Microsoft YaHei UI" if sys_platform() == "win32" else "TkDefaultFont")
        num_pt = max(10, int(16 * scale))
        lab_pt = max(7, int(8 * scale))
        self._num_id = self.create_text(
            self.S_size / 2, self.S_size * 0.44, text="—", anchor="center",
            fill=INK_NORMAL, font=(self.font_family, num_pt))
        self._lab_id = self.create_text(
            self.S_size / 2, self.S_size * 0.72, text=label, anchor="center",
            fill=INK_NORMAL, font=(self.font_family, lab_pt))
        self._draw_ring(fraction=None)
        self._after_id = None

    def S(self, v: float) -> float:
        return v * self.scale

    def _draw_ring(self, fraction: float | None) -> None:
        """外圈：底环全圆；fraction 给定时叠加进度弧（0~1）。"""
        m = max(4, int(self.S_size * 0.06))
        w = max(3, int(self.S_size * 0.055))
        self.delete("ring")
        self.create_oval(m, m, self.S_size - m, self.S_size - m,
                         outline=RING_BG, width=w, tags="ring")
        if fraction is not None:
            f = min(1.0, max(0.0, fraction))
            self.create_arc(m, m, self.S_size - m, self.S_size - m,
                            start=90, extent=-360 * f, outline=RING_FG,
                            width=w, style="arc", tags="ring")
        self.tag_raise(self._num_id)
        self.tag_raise(self._lab_id)

    def set_value(self, value, fraction: float | None = None) -> None:
        """更新数值（None 显示 —）；fraction 可选，驱动外圈进度弧。"""
        ink = decide_ink(value, self.low)
        text = format_value(value)
        if self.unit and value is not None:
            text = f"{text}{self.unit}"
        self.itemconfigure(self._num_id, text=text, fill=ink)
        self.itemconfigure(self._lab_id, fill=ink)
        self._draw_ring(fraction)

    def poll(self, fetch, seconds: float = 60.0) -> None:
        """定时刷新：fetch() 返回数值或 None（在后台线程取数时，
        由调用方经队列投递到主线程再调 set_value）。"""
        def tick() -> None:
            try:
                self.set_value(fetch())
            finally:
                self._after_id = self.after(int(seconds * 1000), tick)
        tick()


def sys_platform() -> str:
    import platform
    return platform.system()
