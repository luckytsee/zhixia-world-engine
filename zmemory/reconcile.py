# -*- coding: utf-8 -*-
"""认知比对（Judge）：他刚说的话，和已知的，是什么关系。

三条输出（Judgement.relation，只有三个值）：
- confirm  一致或补充 → 正常更新
- conflict 不一致     → **不覆盖**，旧值原样、新认知并置（store 层强制）
- new      全新信息   → 插入

两个内置 Judge：
- `exact_judge`    无 LLM 的兜底：精确匹配 + 子串判断，其余一律判 conflict
- `make_llm_judge` 把任意 `llm(messages)->str` 包装成 Judge，LLM 调用失败时自动退回 exact_judge

说明：conflict 的处理是"并置"而不是丢弃——语义相反但可以同时成立的表述
（如"通常12点睡"和"昨天3点才睡"）两条都保留，由上层决定如何呈现。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass
class Judgement:
    relation: str            # confirm | conflict | new
    key: str
    value: str
    note: str = ""


def exact_judge(key: str, value: str, existing: dict | None) -> Judgement:
    """无 LLM 兜底：只有"新话是旧话的子串"才算补充。

    ⚠️ 方向反了不行："不太喜欢吃面"**包含**"喜欢吃面"——限定词会反转语义，
    旧话是新话的子串时一律 conflict（并置无害，覆盖不可逆）。"""
    if existing is None:
        return Judgement("new", key, value)
    old = existing["value"]
    if value == old:
        return Judgement("confirm", key, value, "完全一致")
    if value in old:
        return Judgement("confirm", key, value, "新话是旧话的一部分，视为补充")
    return Judgement("conflict", key, value, "字面不一致（无 LLM 时不冒险）")


JUDGE_PROMPT = """你的任务：判断"新认知"与"已有认知"的关系，输出严格 JSON（不要 markdown 代码块）：
{"relation": "confirm|conflict|new", "note": "一句话说明"}

规则：
- confirm：一致、同一件事的补充（换个说法讲住处/喜好 = 同一件事的补充）
- conflict：字面或语义不一致。⚠️ **conflict 不等于谁错了**——"通常12点睡"和"昨天3点睡"
  可以同时成立；口味变了也是历史的一部分。判 conflict 是**安全**的：系统不会覆盖旧认知，
  只会把新认知并置在旁边。拿不准时判 conflict。
- new：没有可比的旧认知，确实是全新的
- 你只判关系，不做任何动作；动作由存储层强制执行"""


def make_llm_judge(llm) -> object:
    """llm：`chat(messages) -> str` 的对象或函数（DeepSeek/OpenAI 客户端都行）。"""

    def _chat(messages) -> str:
        chat = getattr(llm, "chat", None)
        return chat(messages) if callable(chat) else llm(messages)

    def judge(key: str, value: str, existing: dict | None) -> Judgement:
        if existing is None:
            return Judgement("new", key, value)
        old_block = f"已有认知：{existing['key']} = {existing['value']}"
        try:
            raw = _chat([
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": f"{old_block}\n新认知：{key} = {value}"},
            ])
            data = json.loads(_FENCE_RE.sub("", (raw or "").strip()))
            relation = str(data.get("relation", ""))
            if relation not in ("confirm", "conflict", "new"):
                raise ValueError(f"非法 relation: {relation!r}")
            return Judgement(relation, key, value, str(data.get("note", "")))
        except Exception as exc:  # LLM 失败/乱说 → 落到无 LLM 兜底
            print(f"[记忆] Judge 失败（{exc}），退回精确匹配")
            return exact_judge(key, value, existing)

    return judge
