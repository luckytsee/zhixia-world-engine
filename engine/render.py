# -*- coding: utf-8 -*-
"""渲染层：把世界状态转成可拼进提示词的定性描述。

输出维度化字段（时节/当前阶段/光线/林中状态/天气/异象），不输出数值，
也不预置任何固定台词——措辞由上层模型自行组织。
"""
from __future__ import annotations


def _humidity_word(h: float) -> str:
    if h < 0.40:
        return "干燥"
    if h < 0.62:
        return "正常"
    if h < 0.78:
        return "偏重"
    return "很重"


def _wind_word(state: dict) -> str:
    if state["wind_reverse"]:
        return "风整个反着吹"
    w = state["wind"]
    if w < 0.05:
        return "没有一丝风"
    if w < 0.30:
        return "微风"
    if w < 0.60:
        return "风不小"
    return "风很大"


def render(state: dict, engine) -> dict:
    """返回 {"fields": {维度: 值}, "block": 可直接注入的多行文本}。"""
    rules = engine.r
    stage = next(s for s in rules["stages"] if s["name"] == state["phase"])
    month = engine.month_of(state["tide_index"])
    year = engine.year_of(state["tide_index"])

    weather = (f"潮气{_humidity_word(state['humidity'])}"
               f"{'，起了雾' if state['fog'] else ''}"
               f"{'，在下雨' if state['rain'] else ''}；{_wind_word(state)}")

    fields: dict[str, str] = {
        "时节": f"{month['season']}·{month['name']}（第 {year} 年）",
        "当前": f"{state['phase']}（这一段还剩约 {max(0, state['phase_remaining_h'])} 小时）",
        "光线": f"{stage['light']}，太阳高度{stage['sun']}",
        "林中状态": stage["forest"],
        "天气": weather,
    }
    omens = []
    if state["static_day"]:
        omens.append("静日：全天没有一丝风")
    if state["moon_tonight"]:
        omens.append("今夜有月")
    if state["wind_reverse"]:
        omens.append("风向反了")
    if omens:
        fields["异象"] = "；".join(omens)

    lines = ["【她那边此刻】"] + [f"{k}：{v}" for k, v in fields.items()]
    return {"fields": fields, "block": "\n".join(lines)}
