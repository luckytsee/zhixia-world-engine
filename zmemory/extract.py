# -*- coding: utf-8 -*-
"""对话提取管道：一段对话 → 四层记忆的落库动作。

这是"随手开口就被记住"的实现处：

    turns（对话原文）
      + 已有记忆（facts 键值 / world_notes 全文，供比对）
      → LLM 提取（EXTRACT_PROMPT，严格 JSON）
      → episode 必写；facts 走认知比对（conflict 由 store 强制并置）；
        world_notes 只收她主动记下的；LLM 失败 → 一个字都不写（宁缺勿错）

红线已蒸馏进提示词（源自真机事故）：
- 气话/攻击/玩笑/一次性状态不进 facts；
- summary 禁止钟点与相对时间词（提取发生在对话之后，模型不知道当时几点）；
- 一件事一条回忆，不同事不许拼成连续故事；
- 她重说自己的旧认知 → 比对为 confirm（换说法 ≠ 新认知）。
"""
from __future__ import annotations

import json
import re

from .store import CompanionMemory, ORIGIN_ZIA_SAID

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")

EXTRACT_PROMPT = """你的任务：从一段"用户与 AI 伴侣的对话记录"中提取应长期记住的内容，输出严格 JSON（不要 markdown 代码块），格式：
{{"episode": {{"summary": "一句话概括这次对话", "importance": 0.3}},
  "facts": [{{"key": "简短键名", "value": "具体内容", "relation": "confirm|conflict|new"}}],
  "world_notes": [{{"text": "她主动说'要记住'的内容原话"}}]}}

已知记忆（用于 facts 的 relation 判断，键名+值都要对照）：
{existing}

字段规则：
- episode.summary 必写；对话很短就短写。
  ⚠️ 禁止出现钟点和相对时间词（"今天/昨天/刚才/三点"）——你在对话结束后才读它，
  不知道它发生在几点，写了就是猜。
  ⚠️ 一件事一条：有几件大事就概括最主要的一件，不要把不同话题拼成连续故事。
- facts 只收关于用户的稳定信息（喜好/习惯/计划/人际关系）。relation 判断：
  · confirm = 一致或同一件事的补充（换个说法讲同一件事）
  · conflict = 与已有认知不一致 → 系统会**并置**（旧认知保留，新认知另存），不会覆盖，
    所以拿不准就判 conflict
  · new = 全新的信息
- ⚠️⚠️ 这些**绝不进 facts**：
  气话与攻击（"你该去死"）；玩笑与假设（"我要是辞职了"）；一次性状态
  （"他今天很困"）。这些留在对话里就够了。
- world_notes 只收**她主动要求记住的自我认知**（"记住：我怕雾"）。
  她没说要记的不要放这里；没有就输出空数组。
- 全部用中文"""


def _parse_json(raw: str) -> dict | None:
    try:
        data = json.loads(_FENCE_RE.sub("", (raw or "").strip()))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _llm_chat(llm, messages) -> str:
    chat = getattr(llm, "chat", None)
    return chat(messages) if callable(chat) else llm(messages)


def extract(memory: CompanionMemory, turns: list[dict], llm, *,
            log=print, note_writer=None) -> dict | None:
    """处理一段对话并落库。turns: [{"role": "user"|"assistant", "content": ...}]。

    note_writer：可选回调 (text) -> None——调用方可在此把 world_notes 同步到
    自己的系统（例如礼物候选池）；本模块只写 memory。
    返回提取结果 dict（供上层记录/展示）；提取失败返回 None（记忆零写入）。
    """
    user_turns = [t for t in turns if t.get("role") == "user"]
    if not user_turns:
        return None
    transcript = "\n".join(
        f"{'用户' if t['role'] == 'user' else '她'}：{t['content']}" for t in turns)
    existing = "\n".join(
        [f"  · {f['key']}：{f['value']}" for f in memory.all_facts()]
        + [f"  · (她自己记的){n['text']}" for n in memory.all_world_notes()]
    ) or "  （还没有任何已知记忆）"

    try:
        raw = _llm_chat(llm, [
            {"role": "system", "content": EXTRACT_PROMPT.format(existing=existing)},
            {"role": "user", "content": transcript},
        ])
        data = _parse_json(raw)
    except Exception as exc:
        log(f"[提取] LLM 调用失败，本次不写入: {exc}")
        return None
    if not data or not isinstance(data.get("episode"), dict) \
            or not str(data["episode"].get("summary", "")).strip():
        log("[提取] 提取结果不可用（缺 episode.summary），本次不写入")
        return None

    ep_data = data["episode"]
    episode = memory.add_episode(
        summary=str(ep_data["summary"]).strip(),
        importance=float(ep_data.get("importance", 0.2) or 0.2))

    fact_count = conflict_count = 0
    for f in data.get("facts") or []:
        if not isinstance(f, dict):
            continue
        key, value = str(f.get("key", "")).strip(), str(f.get("value", "")).strip()
        relation = str(f.get("relation", "new")).strip()
        if not key or not value or relation not in ("confirm", "conflict", "new"):
            continue
        r = memory.record_claim(key, value, relation)
        fact_count += 1
        if r["action"] == "kept_both":
            conflict_count += 1

    note_count = 0
    for n in data.get("world_notes") or []:
        if isinstance(n, dict) and str(n.get("text", "")).strip():
            memory.add_world_note(str(n["text"]).strip(), ORIGIN_ZIA_SAID)
            note_count += 1
            if note_writer:
                try:
                    note_writer(str(n["text"]).strip())
                except Exception as exc:
                    log(f"[提取] note_writer 回调失败（不影响记忆）: {exc}")

    log(f"[提取] 1 条回忆 + {fact_count} 条事实"
        + (f"（{conflict_count} 条冲突并置）" if conflict_count else "")
        + f" + {note_count} 条她的认知")
    return {"episode": episode, "facts": fact_count,
            "conflicts": conflict_count, "world_notes": note_count}
