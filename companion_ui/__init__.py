# -*- coding: utf-8 -*-
"""companion_ui：桌面伴侣的可复用 UI 组件（tkinter，自绘、零素材依赖）。"""
from __future__ import annotations

from .dial import StatusDial, decide_ink, format_value
from .bubble import ChatBubble
from .button import PillButton, rounded
from .input import InputBox

__all__ = ["StatusDial", "decide_ink", "format_value",
           "ChatBubble", "PillButton", "rounded", "InputBox"]
