# -*- coding: utf-8 -*-
"""ChatBubble：对话气泡面板（宽底高自适应 + 滚轮滚动）。"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

INK = "#37352F"


class ChatBubble(tk.Frame):
    """定宽文本气泡：高度随内容增长，超过 max_height 后滚轮滚动。

    set_text(text) 返回最终高度——调用方可据此调整窗口/布局。
    """

    def __init__(self, master, width: int = 280, max_height: int = 200,
                 scale: float = 1.0, bg: str = "#F7F7F5",
                 font_family: str | None = None, font_size: int = 11, **kw) -> None:
        self.w = int(width * scale)
        self.max_h = int(max_height * scale)
        self.font = (font_family or "Microsoft YaHei UI", max(9, int(font_size * scale)))
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, width=self.w, height=60, highlightthickness=0,
                                bg=bg)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar = tk.Scrollbar(self, command=self.canvas.yview, width=10)
        self.bar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self._text_id = self.canvas.create_text(
            8, 6, text="", anchor="nw", width=self.w - 16,
            fill=INK, font=self.font, justify="left")
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.set_text("")

    def _wheel(self, event):
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def set_text(self, text: str, emotion_hint: str | None = None) -> int:
        """写入文本，返回内容所需高度（像素）。"""
        f = tkfont.Font(font=self.font)
        lines = 0
        for raw in (text or "").split("\n"):
            lines += max(1, -(-f.measure(raw) // max(1, self.w - 16)))
        line_h = f.metrics("linespace")
        need = min(self.max_h, max(40, lines * line_h + 12))
        self.canvas.configure(height=need, scrollregion=(0, 0, self.w, lines * line_h + 12))
        self.canvas.itemconfigure(self._text_id, text=text or "")
        self.canvas.yview_moveto(0)
        return need
