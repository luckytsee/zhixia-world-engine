# -*- coding: utf-8 -*-
"""InputBox：带占位符的输入框（回车回调，发送后自动清空）。"""
from __future__ import annotations

import tkinter as tk

PLACEHOLDER = "说点什么…"


class InputBox(tk.Frame):
    def __init__(self, master, on_return=None, width: int = 280,
                 font=("Microsoft YaHei UI", 11), bg: str = "white", **kw):
        super().__init__(master, bg=kw.pop("bg", bg))
        self.on_return = on_return
        self.entry = tk.Entry(self, font=font, relief="flat", bg=bg,
                              fg="#8C8A84", width=width)
        self.entry.pack(fill="x", ipady=5, padx=4)
        self._placeholder_on = True
        self.entry.insert(0, PLACEHOLDER)
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<Return>", self._submit)

    def _focus_in(self, _):
        if self._placeholder_on:
            self.entry.delete(0, "end")
            self.entry.configure(fg="#37352F")
            self._placeholder_on = False

    def _focus_out(self, _):
        if not self.entry.get():
            self._placeholder_on = True
            self.entry.insert(0, PLACEHOLDER)
            self.entry.configure(fg="#8C8A84")

    def _submit(self, _):
        if self._placeholder_on:
            return
        text = self.get().strip()
        if text and self.on_return:
            self.clear()
            self.on_return(text)

    def get(self) -> str:
        return "" if self._placeholder_on else self.entry.get()

    def clear(self) -> None:
        self.entry.delete(0, "end")
        self._focus_out(None)
