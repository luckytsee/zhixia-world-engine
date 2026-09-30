# -*- coding: utf-8 -*-
"""知夏世界引擎：钟表式世界状态机（纯函数、可冷启动、确定性重放）。"""
from __future__ import annotations

import json
import os

from .engine import WorldEngine, load_or_init_state
from .render import render

_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "rules.json")


def load_rules(path: str | None = None) -> dict:
    with open(path or _RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


__all__ = ["WorldEngine", "render", "load_rules", "load_or_init_state"]
