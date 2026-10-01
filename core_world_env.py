# -*- coding: utf-8 -*-
"""世界引擎的薄包装：把 engine 接到 Agent 上（对应主项目的 core/world_env.py）。

为什么单独一层：Agent 只认 `block()` / `snapshot_payload()` 这两个方法，
不直接 import 引擎——引擎项目缺失或损坏时只跳过注入，**她照常说话**。

与主项目版的差别：这里账本路径由调用方传入（示例用它写进 state/）；
主项目版从 config 读，并额外做了「[world] enabled=false 一键回滚」。
"""
from __future__ import annotations

import time


class WorldEnv:
    def __init__(self, engine, state_path: str | None = None, log=print) -> None:
        self.engine = engine
        self.state_path = state_path or None
        self.log = log

    def current(self, now: float | None = None) -> dict:
        """读盘 → 补算到此刻 → 写回（权威账本唯一入口，幂等）。"""
        from engine import load_or_init_state

        return load_or_init_state(self.engine, path=self.state_path,
                                  now=now if now is not None else time.time())

    def block(self, now: float | None = None) -> str:
        from engine import render

        return render(self.current(now), self.engine)["block"]

    def snapshot_payload(self, now: float | None = None) -> dict:
        """下发远端用的快照段（含 rules，供对端本地补算）。"""
        st = self.current(now)
        return {"engine_version": st.get("engine_version"), "state": st,
                "rules": self.engine.r, "saved_at": time.time()}
