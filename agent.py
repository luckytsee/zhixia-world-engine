# -*- coding: utf-8 -*-
"""Agent 主循环：把零件拼成一个能跑的伴侣。

一轮对话做什么（顺序就是设计）：

    人格（persona）
      + 世界状态（world engine 的 render，若接了）
      + 长期记忆（facts / world_notes / episodes，若接了）
      + 关系档位（affect 的隐性约束，若接了）
      + 最近几轮对话（session，易失）
    → LLM
    → 从回复里剥掉情绪标签与 [记住:...] 标记 → 得到可发出的正文
    → [记住:...] 落进她的认知层（world_notes）
    → 会话结束时调 MemoryWriter 提取长期记忆

⚠️ 三个关键纪律（都在下面代码里，改之前先读注释）：
  1. **标签与标记必须剥掉再发**——她写的 `[happy]`、`[记住:...]` 是内部约定，对方不该看见；
  2. **记忆只在会话结束时写一次**，不在每轮写（省调用、也更像人"事后回忆"）；
  3. **任何一层挂了都不能让她失声**——世界/记忆/关系任意一个抛异常，
     其余部分照常组装，最差也要能回一句话。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---- 情绪标签：只认这 7 个英文词（与人格里写死的约定一致）----
KNOWN_EMOTIONS = frozenset(
    {"neutral", "happy", "sad", "angry", "curious", "tired", "surprised"})
_EN_TAG_RE = re.compile(r"\[([a-zA-Z_]+)\]")
# 末尾那个短标签（她换新词时兜底剥掉）
_TRAILING_TAG_RE = re.compile(r"[\[［][^\[\]［］\n]{1,12}[\]］]\s*$")
# `[记住:...]`（全角括号也认）
_REMEMBER_RE = re.compile(r"[\[［]\s*记住\s*[:：]\s*([^\]］\[]+?)\s*[\]］]")


def parse_reply(raw: str) -> tuple[str, str, list[str]]:
    """把她的原始回复拆成（正文, 情绪, 要记住的条目）。

    ⚠️ 情绪要从**原文**读——洗完再读就读不到了（先剥再读是踩过的坑）。
    """
    raw = raw or ""
    tags = [t.lower() for t in _EN_TAG_RE.findall(raw)]
    emotion = next((t for t in tags if t in KNOWN_EMOTIONS), "neutral")
    remember = [m.strip() for m in _REMEMBER_RE.findall(raw)]
    speech = _REMEMBER_RE.sub("", raw)
    speech = _strip_tags(speech).strip()
    return speech, emotion, remember


def _strip_tags(text: str) -> str:
    """剥掉已知情绪标签；末尾未知短标签也兜底剥掉。"""
    def keep(m: re.Match) -> str:
        return "" if m.group(1).strip().lower() in KNOWN_EMOTIONS else m.group(0)
    text = _EN_TAG_RE.sub(keep, text)
    return _TRAILING_TAG_RE.sub("", text).strip()


def is_her_own(text: str, recent_user_text: str) -> bool:
    """这条"要记住"的内容，是**她自己的**，还是在复述对方刚说的话？

    ⚠️ 为什么需要（2026-10-01 实测）：
      对方说"我怕雾这事你记一下"，她答"行，记下了 [记住:我怕雾]"——
      于是"我怕雾"被当成**她的自我认知**存了。可那是**对方**的恐惧。
      认知层是她的人格地基，被对方的话污染后，她会真以为自己怕雾
      （而设计上她的喜好恐惧"应该长出来，不是写死的"）。

    判据（保守：拿不准就当"不是她的"，宁可不记也不污染）：
      · 内容里的实词在对方最近说的话里出现过 → 判为复述，不落；
      · 内容以"我"开头、且对方的话里**没有**对应内容 → 是她自己的，落。
    """
    item = (text or "").strip()
    if not item:
        return False
    if not recent_user_text:
        return True                       # 没有对方的话可比 → 视为她自己说的
    # 取内容里的实词（2 字以上），看是否大量出现在对方的话里
    grams = {item[i:i + 2] for i in range(len(item) - 1)}
    if not grams:
        return True
    hit = sum(1 for g in grams if g in recent_user_text)
    if hit / len(grams) >= 0.5:           # 一半以上重合 → 判为复述
        return False
    return True


@dataclass
class DebugInfo:
    """这一轮实际注入了什么（排查用，不注入给模型）。"""
    facts: list[str] = field(default_factory=list)
    world_notes: list[str] = field(default_factory=list)
    episodes: list[str] = field(default_factory=list)
    world_block: str = ""
    affect_block: str = ""
    search: tuple[bool, str] | None = None


class Agent:
    """最小可跑的伴侣主循环。

    llm：任何提供 chat(messages) -> str 的客户端（OpenAI 兼容皆可）。
    其余参数都可以为 None —— 缺哪一层就少哪一层，不影响她说话。
    """

    def __init__(self, llm, persona_text: str, *,
                 memory=None, world_notes=None, affect=None, world=None,
                 writer=None, search=None, session_turns: int = 20, log=print) -> None:
        self.llm = llm
        self.persona_text = persona_text
        self.memory = memory
        self.world_notes = world_notes
        self.affect = affect
        self.world = world
        self.writer = writer          # 会话结束时用（MemoryWriter）
        # 联网（可选，tools/web_search.py）。人格里承诺了"能自己查"，
        # 没接时她会照人格说"我可以查"——所以接上才算兑现。
        self.search = search
        self.session_turns = int(session_turns)
        self.log = log
        self.session: list[dict[str, str]] = []
        self.debug = DebugInfo()

    # ---------- 组装 ----------
    def build_messages(self, user_text: str) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = [{"role": "system", "content": self.persona_text}]
        self.debug = DebugInfo()

        # 长期记忆（可选）：事实 + 她自己的认知 + 相关经历
        if self.memory is not None:
            try:
                facts = [f for f in self.memory.list_facts()][:15]
                self.debug.facts = [f"{f.key}：{f.value}" for f in facts]
            except Exception as exc:
                self.log(f"[记忆] 事实读取失败，跳过: {exc}")
            if self.debug.facts:
                msgs.append({"role": "system", "content":
                             "=== 关于他的记忆（背景资料，自然地用，禁止说"
                             "\"根据记录\"） ===\n"
                             + "\n".join(f"- {x}" for x in self.debug.facts)})
            try:
                eps = [r.episode for r in self.memory.search_episodes(
                    query_text=user_text, top_k=5)] if user_text else []
                self.debug.episodes = [e.summary for e in eps]
            except Exception as exc:
                self.log(f"[记忆] 经历检索失败，跳过: {exc}")
            if self.debug.episodes:
                msgs.append({"role": "system", "content":
                             "=== 相关回忆（括号里的日期准，正文里的钟点不可信） ===\n"
                             + "\n".join(f"- {s}" for s in self.debug.episodes)})

        # 她自己的认知（只追加，含"不许不认"的约束）
        if self.world_notes is not None:
            try:
                notes = self.world_notes.all()
                self.debug.world_notes = [n.text for n in notes]
            except Exception as exc:
                self.log(f"[认知] 读取失败，跳过: {exc}")
            if self.debug.world_notes:
                msgs.append({"role": "system", "content":
                             "=== 你自己记下的事（这是你的认知，不许不认；"
                             "可以改主意，但不能说自己没说过） ===\n"
                             + "\n".join(f"- {x}" for x in self.debug.world_notes)})

        # 关系档位（数字只产生隐性约束，绝不出现）
        if self.affect is not None:
            try:
                self.debug.affect_block = self.affect.render()
            except Exception as exc:
                self.log(f"[关系] 渲染失败，跳过: {exc}")
            if self.debug.affect_block:
                msgs.append({"role": "system", "content": self.debug.affect_block})

        # 联网（可选）：只在"像在问外面世界的事"时查一次，避免每轮都搜
        if self.search is not None and self._looks_like_fact_query(user_text):
            try:
                outcome = self.search.search(user_text)
                self.debug.search = (outcome.ok, getattr(outcome, "backend", ""))
                if outcome.ok:
                    from tools.web_search import render_for_prompt
                    msgs.append({"role": "system", "content": render_for_prompt(outcome)})
                else:
                    msgs.append({"role": "system", "content":
                                 "（联网没查到——如实说不知道，别编）"})
            except Exception as exc:
                self.log(f"[联网] 查询失败，跳过: {exc}")

        # 世界状态（只给状态，不给台词）
        if self.world is not None:
            try:
                self.debug.world_block = self.world.block()
            except Exception as exc:
                self.log(f"[世界] 渲染失败，跳过: {exc}")
            if self.debug.world_block:
                msgs.append({"role": "system", "content": self.debug.world_block})

        msgs.extend(self.session[-self.session_turns:])
        msgs.append({"role": "user", "content": user_text})
        return msgs

    @staticmethod
    def _looks_like_fact_query(text: str) -> bool:
        """粗判"这句话是不是在问外面世界的事"（要不要联网）。

        ⚠️ 刻意保守：只在**明显像在问事实**时才搜（问句 + 不含"你/我"这类私人指代）。
        宁可少搜，也不要每轮都去打搜索引擎——那是给聊天加延迟。
        真实项目里这一步可以用更聪明的方式（工具调用），这里给最小可用版。
        """
        t = (text or "").strip()
        if len(t) < 4 or not t.endswith(("？", "?", "吗", "呢")):
            return False
        if any(w in t for w in ("你", "我", "咱", "他", "她", "感觉", "今天心情")):
            return False
        return True

    # ---------- 一轮对话 ----------
    def chat(self, user_text: str) -> str:
        """回一句话（返回值是**可发出的正文**，标签已剥）。"""
        messages = self.build_messages(user_text)
        try:
            raw = self.llm.chat(messages)
        except Exception as exc:
            self.log(f"[LLM] 调用失败: {exc}")
            return "……等一下，我这边有点问题。"

        speech, emotion, remember = parse_reply(raw)
        self.session.append({"role": "user", "content": user_text})
        self.session.append({"role": "assistant", "content": speech})
        del self.session[:-self.session_turns * 2]

        # 她说"要记住"的 → 落进她自己的认知层
        # ⚠️ 落之前先判归属：如果这条其实是**对方说的**（她在复述），不能进她的认知层
        #    （否则对方的一句"我怕雾"，会变成她自己的恐惧——实测踩到过）
        for item in remember:
            if self.world_notes is None:
                continue
            if not is_her_own(item, user_text):
                self.log(f"[认知] 这条是对方说的，不记成她自己的认知：{item}")
                continue
            try:
                self.world_notes.add(item)
                self.log(f"[认知] 她记下了：{item}")
            except Exception as exc:
                self.log(f"[认知] 落库失败（标记仍会被剥掉）: {exc}")
        return speech

    # ---------- 会话结束 ----------
    def end_session(self) -> None:
        """把这一段对话交给提取管道写长期记忆。失败只记日志，不影响她。"""
        if self.writer is None or not self.session:
            return
        try:
            self.writer.write_session(list(self.session))
        except Exception as exc:
            self.log(f"[记忆] 会话提取失败，本次不写入: {exc}")
        finally:
            self.session.clear()
