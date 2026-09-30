# -*- coding: utf-8 -*-
"""PillButton：圆角胶囊按钮（自绘，支持悬停变色与点击回调）。"""
from __future__ import annotations

import tkinter as tk


def rounded(canvas: tk.Canvas, x0, y0, x1, y1, r, **kw) -> int:
    """在画布上画圆角矩形（多边形平滑近似）。返回 item id。"""
    pts = [x0+r, y0, x1-r, y0, x1, y0, x1, y0+r, x1, y1-r, x1, y1,
           x1-r, y1, x0+r, y1, x0, y1, x0, y1-r, x0, y0+r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, **kw)


class PillButton(tk.Canvas):
    def __init__(self, master, text: str, command=None, width: int = 96,
                 height: int = 34, scale: float = 1.0,
                 bg: str = "#2D4A3E", fg: str = "white",
                 hover: str = "#3B5F50", font=("Microsoft YaHei UI", 10), **kw):
        self.w, self.h = int(width * scale), int(height * scale)
        super().__init__(master, width=self.w, height=self.h,
                         highlightthickness=0, bg=kw.pop("bg", master["bg"]))
        self.command = command
        self.colors = {"bg": bg, "hover": hover}
        self._body = rounded(self, 2, 2, self.w-2, self.h-2, self.h//2,
                             fill=bg, outline="")
        self._label = self.create_text(self.w/2, self.h/2, text=text,
                                       fill=fg, font=font)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self.itemconfigure(self._body, fill=hover))
        self.bind("<Leave>", lambda e: self.itemconfigure(self._body, fill=bg))

    def _click(self, _):
        if self.command:
            self.command()

    def set_text(self, text: str) -> None:
        self.itemconfigure(self._label, text=text)
