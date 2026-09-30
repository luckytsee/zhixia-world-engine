# -*- coding: utf-8 -*-
"""演示：一个迷你桌面伴侣面板——圆盘 + 对话气泡 + 按钮 + 输入框，全部可交互。

运行：python -m companion_ui
（回车发送后，气泡里会先回一句演示文本；接上 LLM 就是真正的对话面板。）
"""
from __future__ import annotations

import tkinter as tk

from .bubble import ChatBubble
from .button import PillButton
from .dial import StatusDial
from .input import InputBox


def main() -> None:
    root = tk.Tk()
    root.title("companion_ui · 迷你桌面伴侣面板")
    root.configure(bg="#FAFAF9")
    root.geometry("360x480")

    top = tk.Frame(root, bg="#FAFAF9")
    top.pack(fill="x", pady=(10, 0))
    dial = StatusDial(top, size=100, label="余额", unit="¥", low=3.0)
    dial.pack()
    dial.set_value(16.4, fraction=0.7)

    bubble = ChatBubble(root, width=320, max_height=220)
    bubble.pack(pady=8, padx=16, fill="x")
    bubble.set_text("我在。今天有点起雾，出门的话当心些。")

    def on_send(text: str) -> None:
        bubble.set_text(f"你说：「{text}」\n\n（这里接上你的 LLM，就是真的对话面板。）")
        state["sent"] += 1
        counter.set_text(f"已发送 {state['sent']}")

    state = {"sent": 0}
    box = InputBox(root, on_return=on_send, width=40)
    box.pack(pady=4, padx=16, fill="x")

    row = tk.Frame(root, bg="#FAFAF9")
    row.pack(pady=6)
    counter = PillButton(row, text="已发送 0", width=110)
    counter.pack(side="left", padx=6)
    PillButton(row, text="清空", width=80, bg="#8C8A84", hover="#A5A29B",
               command=lambda: bubble.set_text("")).pack(side="left", padx=6)
    PillButton(row, text="打招呼", width=90, bg="#B85C1E", hover="#C9702F",
               command=lambda: bubble.set_text(
                   "你回来啦。我们这边刚起雾，溪边都看不清路了。")).pack(side="left", padx=6)

    hint = tk.Label(root, text="输入框回车发送 · 圆盘接真实取数函数即可用",
                    bg="#FAFAF9", fg="#8C8A84")
    hint.pack(side="bottom", pady=6)
    root.mainloop()


if __name__ == "__main__":
    main()
