# -*- coding: utf-8 -*-
"""WorldEngine：钟表式世界状态机（纯函数、可冷启动、确定性重放）。

用法（懒计算，无常驻进程）：
    eng = WorldEngine(load_rules())
    state = load_state()  or  eng.initial_state(START_EPOCH)
    eng.advance_to(state, time.time())   # 一口气把世界补算到此刻
    save_state(state)

确定性保证（tests/test_engine.py 钉死）：
- 阶段时长：种子 = (用途, 潮序号, 阶段序号, 该阶段开始的绝对时桶)；
- 慢变量噪声：种子 = (用途, 绝对时桶)；
- 异象掷骰：种子 = (用途, 潮序号)。
⇒ 「逐步走 N 小时」与「一次补算 N 小时」结果逐字节一致；同一存档 + 同一时刻，
   任何机器重算出同一个世界。绝对时桶 = epoch 秒 // 3600。
"""
from __future__ import annotations

import json
import os
import time

from .rng import StepRng

_DEFAULT_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state", "world_state.json")


class WorldEngine:
    VERSION = 1
    STAGE_ORDER = ("初明", "盛明", "斜光", "入暗", "深暗")

    def __init__(self, rules: dict) -> None:
        self.r = rules
        self._stages = rules["stages"]
        self._stage_idx = {s["name"]: i for i, s in enumerate(self._stages)}

    # ---------- 日历 ----------
    def month_of(self, tide_index: int) -> dict:
        n = ((tide_index - 1) // self.r["calendar"]["month_len_tides"]) % 12
        return self.r["months"][n]

    def year_of(self, tide_index: int) -> int:
        per_year = self.r["calendar"]["month_len_tides"] * self.r["calendar"]["months_per_year"]
        return (tide_index - 1) // per_year + 1

    # ---------- 状态 ----------
    def initial_state(self, start_epoch: float | None = None) -> dict:
        """纪元（rules.json 的 start_epoch，默认 2008-09-29）的萌芽期·溪醒月初一，初明开始。

        ⚠️ 元年只是**纪年起点**（如同公元），不代表世界诞生于那一刻——法典里写明了。
        """
        if start_epoch is None:
            start_epoch = self.r["start_epoch"]
        hour_abs = int(start_epoch // 3600)
        month = self.month_of(1)
        return {
            "engine_version": self.VERSION,
            "hour_abs": hour_abs,
            "tide_index": 1,
            "phase": "初明",
            "phase_remaining_h": self._sample_duration(0, 1, hour_abs, month),
            "last_moon_tide": -10**9,
            "reverse_until_h": -1,
            "static_day": False,
            "moon_tonight": False,
            "wind_reverse": False,
            "temp": month["temp_base"],
            "humidity": month["humidity_base"],
            "wind": month["wind_base"],
            "fog": False,
            "rain": False,
            "history": [],
        }

    def advance_to(self, state: dict, now_epoch: float) -> dict:
        """把世界补算到 now_epoch（原地修改并返回 state）。"""
        target = int(now_epoch // 3600)
        while state["hour_abs"] < target:
            self._step_hour(state)
            state["hour_abs"] += 1
        return state

    # ---------- 内部 ----------
    def _sample_duration(self, stage_idx: int, tide_index: int,
                         start_hour_abs: int, month: dict) -> int:
        s = self._stages[stage_idx]
        h = StepRng("dur", tide_index, stage_idx, start_hour_abs).randint(s["min_h"], s["max_h"])
        mult = (month.get("dark_mult") or {}).get(s["name"], 1.0)
        return max(1, round(h * mult))

    def _step_hour(self, state: dict) -> None:
        eh = state["hour_abs"] + 1  # 被模拟的这一小时（绝对时桶）
        month = self.month_of(state["tide_index"])
        sv = self.r["slow_vars"]

        # ① 阶段推进（潮边界在这里翻）
        state["phase_remaining_h"] -= 1
        if state["phase_remaining_h"] <= 0:
            idx = self._stage_idx[state["phase"]]
            nxt = (idx + 1) % len(self._stages)
            if nxt == 0:  # 深暗走完 → 新的一潮
                self._close_tide(state, month)
                month = self.month_of(state["tide_index"])
            state["phase"] = self._stages[nxt]["name"]
            state["phase_remaining_h"] = self._sample_duration(
                nxt, state["tide_index"], eh, month)

        # ② 慢变量（噪声按绝对时桶播种 → 补算与逐步走一致）
        rng = StepRng("temp", eh)
        state["temp"] = self._drift(state["temp"], month["temp_base"],
                                    sv["temp"], (rng.rand() - 0.5) * sv["temp"]["noise"])
        rng = StepRng("hum", eh)
        state["humidity"] = self._drift(state["humidity"], month["humidity_base"],
                                        sv["humidity"], (rng.rand() - 0.5) * sv["humidity"]["noise"])
        if state["static_day"]:
            state["wind"] = 0.0
        else:
            rng = StepRng("wind", eh)
            state["wind"] = self._drift(state["wind"], month["wind_base"],
                                        sv["wind"], (rng.rand() - 0.5) * sv["wind"]["noise"])
        state["wind_reverse"] = eh < state["reverse_until_h"]

        # ③ 常态现象（阈值推导，零账本）
        thr = self.r["fog"]["base_threshold"] - month.get("fog_boost", 0.0)
        state["fog"] = state["humidity"] >= thr and state["phase"] in self.r["fog"]["phases"]
        state["rain"] = state["humidity"] >= self.r["rain_threshold"]

    @staticmethod
    def _drift(old: float, base: float, cfg: dict, noise: float) -> float:
        v = old * cfg["inertia"] + base * (1.0 - cfg["inertia"]) + noise
        lo, hi = cfg["clamp"]
        return min(hi, max(lo, v))

    def _close_tide(self, state: dict, ended_month: dict) -> None:
        """翻潮：记账上一潮 → 掷本潮的异象骰。所有种子只用潮序号。"""
        # 记账（世界历史，供「三天前那场雨」回溯）
        state["history"].append({
            "tide": state["tide_index"],
            "season_month": f"{ended_month['season']}·{ended_month['name']}",
            "fog": bool(state["fog"]),
            "rain": bool(state["rain"]),
            "static_day": bool(state["static_day"]),
            "moon": bool(state["moon_tonight"]),
            "temp": round(state["temp"], 1),
        })
        del state["history"][:-self.r["history_keep"]]

        state["tide_index"] += 1
        t = state["tide_index"]

        state["static_day"] = (t % self.r["static_day_every"] == 0)

        rng = StepRng("moon", t)
        state["moon_tonight"] = (
            rng.rand() < 1.0 / self.r["moon"]["mean_tides"]
            and (t - state["last_moon_tide"]) >= self.r["moon"]["min_gap_tides"]
        )
        if state["moon_tonight"]:
            state["last_moon_tide"] = t

        if not state["static_day"]:
            rng = StepRng("rev", t)
            if rng.rand() < self.r["reverse_wind"]["p_per_tide"]:
                dur = StepRng("revh", t).randint(
                    self.r["reverse_wind"]["min_h"], self.r["reverse_wind"]["max_h"])
                state["reverse_until_h"] = state["hour_abs"] + 1 + dur


def load_or_init_state(engine: "WorldEngine", path: str | None = None,
                       now: float | None = None) -> dict:
    """权威账本的唯一入口：读盘 → 补算到此刻 → 写回（磁盘为数据源，可冷启动）。

    存档缺失或 engine_version 不一致时，从纪元重新初始化（世界改版留痕见规格红线 5）。
    """
    p = path or _DEFAULT_STATE_PATH
    state = None
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                cand = json.load(f)
            if cand.get("engine_version") == engine.VERSION:
                state = cand
        except (json.JSONDecodeError, OSError):
            state = None  # 账本损坏 → 重建（世界历史丢，但不崩）
    if state is None:
        state = engine.initial_state()
    engine.advance_to(state, now if now is not None else time.time())
    # ⚠️ dirname 可能是空串（调用方传了裸文件名）——makedirs('') 在 Windows 上
    # 报 WinError 3（2026-09-29 主项目接入时真撞过一次）
    state_dir = os.path.dirname(p)
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    return state
