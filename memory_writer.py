from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from typing import Protocol


class LLMProtocol(Protocol):
    """任何提供 chat(messages) -> str 的客户端都算。"""

    def chat(self, messages: list[dict[str, str]]) -> str: ...

if TYPE_CHECKING:
    from memory.base import MemoryStore
    from memory.types import Fact

_EXTRACTION_PROMPT = """你的任务：从一段"用户与桌面AI伴侣的对话记录"中提取长期记忆，输出严格的 JSON（不要 markdown 代码块，不要任何解释文字），格式：
{{"episode": {{"summary": "一句话概括这次对话", "participants": ["用户"], "emotion": "整体情绪词或null", "topics": ["话题1", "话题2"], "importance": 0.3}}, "facts": [{{"key": "简短键名", "value": "具体内容", "confidence": 0.9}}], "affect": {{"comfort": 0, "closeness": 0, "note": ""}}, "gifts": [{{"name": "东西名", "note": "她的原话附言"}}], "reconciliations": [{{"relation": "conflict|confirm|new", "target": "user_fact|world_note", "existing": "她原来知道的", "new_information": "他刚说的", "action": "keep_both|ignore", "note": "一句话说明"}}]}}

规则：
- episode.summary 必须有；对话很短就短写
- ⚠️⚠️ summary 里**禁止出现钟点和相对时间词**（"凌晨/早上/中午/下午/傍晚/晚上/今天/昨天/
  刚才/两点"这类）——这段对话是**半小时后**才被提取的，你**根本不知道它发生在几点几分**，
  写了就是猜。**真机事故**：把当天的"下午两点"写成了"凌晨两点多"，她照着复述给用户听，
  用户直接质疑"记忆错乱了"。时间由系统的时间戳记录，**不需要你写**。
- ⚠️ **一件事一条回忆**：这段对话里若有几件事，summary 只概括**最主要的那一件**；
  不要把不同时间/不同话题的事**混成一件**（真机事故：把"下午被吐槽余额"和"下午对着壁纸
  发呆"拼成了"凌晨盯着屏幕死磕"，凭空造出一个不存在的场景）。
- 涉及未完成/计划中的事，必须写进 summary，但**别写"明天/后天/今晚"**——用
  "原本计划""后来""接下来"这类不含绝对时间的说法（同上：提取时已经过了半小时）
- importance：日常闲聊 0.1-0.3；涉及用户生活、习惯、人际关系、情绪 0.4-0.7；重大事件 0.8-1.0
- facts 只记关于用户的稳定信息（喜好、习惯、计划、人际关系），一次性闲聊不记；没有就输出空数组
- confidence：用户亲口直说的 0.9；推测的 0.5-0.7
- 与已存在事实含义相同时，必须复用已存在的键名（更新它），不要造近义新键
- ⚠️⚠️ **下面这些是"你已经知道的"（键名 + 值都要用上）**：
  **不是只看键名**——要拿**值**去跟"他刚说的"对照：
{existing_facts}
  · 一致 → 正常更新（`relation: confirm`）
  · **不一致 → 不要直接覆盖！** 见下面的 `reconciliations` 说明。

⚠️⚠️ **下面是"她自己记下的事"（关于她自己 / 她的世界）**：
{existing_world_notes}
⚠️ **这一块必须一起用于 `reconciliations` 的比对**（2026-09-28 补的缺口）：
  · 她**重说/补充**自己的事（换个说法讲住处、讲喜好）→ 判 `confirm`，**不是 `new`**。
    （真机例子：库里已有"我住在林子边上一棵大树根底下凹进去的地方"，
     她后来说"我住处没有窗，只有树根洞口透光"——那是**同一件事的补充**，
     当时被判成了 `new`（"此前不知道伴侣住在哪里"），**因为没拿这一块去比**。）
  · 她**改口**（"以前怕雾，现在没那么怕了"）→ 判 `conflict`（旧的不许覆盖，另存一条）。
  · 确实**全新**的事（从没提过的地方/喜好）→ 才是 `new`。
  · ⚠️ 没有可比的旧记录时，输出空字符串即可（别硬凑）。

⚠️⚠️ **绝对不要记进 facts 的东西**（这是硬红线，违反即失败）：
- **他情绪上来的话／气话**："你该去死""我就是个废物""这破项目我不做了"——
  那是**情绪**，不是他的设定。**气话不是事实。**
- **攻击性表达**：辱骂、威胁、"滚""烦死你了"这类——**一句都不许进 facts**。
- **玩笑、假设、反问**："我要是辞职了怎么办"不是"他辞职了"；
  "你看我像有钱人吗"不是"他有钱"。
- **关于伴侣的负面评价**：不要记成"用户认为伴侣XX"。
- **一次性的状态**："他今天很困""他好像不太高兴"——那是**当下**，不是长期事实。
⇒ 这些**留在对话里就够了**，不要变成他以后的"人设"。

- ``affect``：**这段对话对"他和伴侣的关系"的影响**（不是他的情绪）。
  · ``comfort``：舒适度增减，整数，范围 -30~+30。被攻击/被贬低/被冷落 → 负；
    被关心/被道歉/聊得开心 → 正；**普通闲聊就是 0**。
  · ``closeness``：亲近度增减，整数，范围 -15~+15。**只有真正拉近或拉远的事才算**：
    他主动分享私人的事、道歉、说心里话 → 正；反复攻击、敷衍、冷暴力 → 负；
    **普通闲聊是 0**（别日常就加）。
  · ``note``：一句话说明为什么（会作为"最近发生的事"影响到她的语气）。
    ⚠️ **写法要用她的视角**，如"他刚才说了句挺重的话""他跟我道歉了""他愿意说自己的事了"。
    没有明显影响就给空字符串和 0。
  · ⚠️ 判断要**看语境**：他开玩笑式地损你（"你咋这么笨哈哈"）**不扣 comfort**；
    但认真地说重话（连续负面、没有玩笑信号）**要扣**。

- ``reconciliations``：**他刚说的话，跟你已经知道的，是什么关系**（认知比对）。
  这一项**最重要**——它决定"他的话能不能改变你已经形成的东西"。
  · ``relation``：
    - ``confirm`` 一致或补充（"他明天八点有课" vs 已有"他不喜欢早起"）→ 正常记
    - ``conflict`` **不一致**（"他喜欢吃面" vs 已有"他不太喜欢面食"）→ **必须列出来**
    - ``new`` 全新的信息，没有可比的旧认知
  · ``existing``：她原来知道的（原文照抄上面的值）；``new_information``：他刚说的
  · ``action``（**只有两个值，别自己发明**）：
    - ``keep_both`` —— **新旧并存，不许覆盖旧的**。绝大多数 conflict 都用这个
      （"通常十二点睡"和"昨天三点才睡"逻辑上可以同时成立；口味变了也是历史的一部分）
    - ``ignore`` —— 这个例子不重要，不用管
  · ⚠️⚠️ **`conflict` 不等于谁错了**。"我通常12点睡"和"我昨天3点睡"**可以同时成立**。
    ⇒ **遇到 conflict，一律先用 `keep_both`**，不要把旧值改掉、更不要删掉。
    她以前怎么认识你，本身也是你们相处历史的一部分。
  · ⚠️ 没有明显比对对象时（纯闲聊、无新信息）→ **输出空数组**。
- ``gifts``：**她在这段对话里主动提出要送他东西**（"我想给你带一束花""等你生日我
  做点什么给你"）→ 每件一条 {{"name": 东西名, "note": 她的原话}}。⚠️ 只记**她要送出**
  的；她"想要什么"不记（那是聊天内容）；她收下/拒绝他寄的也不在这记（礼物小屋管）。
  没有就输出空数组。
- 全部用中文"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


class MemoryWriter:
    def __init__(self, llm: LLMProtocol, store: MemoryStore,
                 log: Callable[[str], None] = print,
                 affect: object | None = None,
                 chat_log_path: str | Path | None = None,
                 world_notes: object | None = None,
                 gift_store: object | None = None) -> None:
        self.llm = llm
        self.store = store
        self.log = log
        # ⭐ 关系状态（2026-09-28）：会话结束时按提取出的 `affect` 字段更新。
        # **不加调用**（复用同一次提取），代价是"延迟到会话结束才更新"——
        # 当场生效的那部分交给 agent 的本地快速判断（高危词，零成本）。
        self.affect = affect
        # ⭐ 认知冲突留痕（2026-09-28）：写到 chat.log，**这是你能发现"她记错了"的
        # 唯一途径**。时点跟 agent 的每轮日志不同（这个是会话结束时），所以直写。
        self.chat_log_path = Path(chat_log_path) if chat_log_path else None
        # ⭐⭐ 世界笔记（2026-09-28 晚补）：**"她已经知道什么"的第二半**。
        # 提取器的 `reconciliations`（认知比对）原来只拿 `facts` 去比，
        # **没拿 `world_notes`** ⇒ 她重说自己的事永远被判成 `new`
        # （真机：库里已有"我住在…大树根底下"，她后来说"我住处没有窗…"，
        #  被判成"此前不知道伴侣住在哪里"）。⇒ 近义重复堆积 + 看不到"认知变化"。
        # `None` = 没接（照旧只比 facts，不崩）。
        self.world_notes = world_notes
        # ⭐ 赠礼候选（2026-09-29）：提取器给出的"她主动要送他的东西"落进候选池，
        # 由礼物小屋（tools/gift_house.py）处理。None = 没接（静默跳过）。
        # 手机端会话走同一条提取管道（单写点），她答应过的会自动带回来。
        self.gift_store = gift_store

    def _known_world_notes(self) -> str:
        """她已经记下的世界笔记 → 给提取器做比对用的一段文本。

        ⚠️ **全量列出**（不是只给键名）：跟 `facts` 那段同一个道理——
        要比"值"，只给键名比不了。
        ⚠️ 没接 `world_notes` 或读取失败 → 返回一句说明，**不崩**。
        """
        if self.world_notes is None:
            return "  （本次拿不到她自己记的事——只按上面的事实比对）"
        try:
            notes = self.world_notes.all()
        except Exception as exc:
            self.log(f"[记忆] 世界笔记读取失败（本次不用于比对）: {exc}")
            return "  （本次拿不到她自己记的事——只按上面的事实比对）"
        if not notes:
            return "  （她自己还没记过什么）"
        return "\n".join(f"  · {n.text}" for n in notes)

    def write_session(self, turns: list[dict[str, str]]) -> bool:
        user_messages = [m for m in turns if m["role"] == "user"]
        if not user_messages:
            return False
        transcript = "\n".join(
            f"{'用户' if m['role'] == 'user' else '她'}：{m['content']}" for m in turns
        )
        try:
            existing_facts: dict[str, Fact] = {f.key: f for f in self.store.list_facts()}
            # ⚠️⚠️ 必须传**键名 + 值**，不能只传键名（2026-09-28 修的缺陷）。
            # 只给键名时，提取器**看不见"她已知什么"**，于是它能防"造新键"、
            # **防不了"值矛盾"**——这正是"我喜欢吃面"撞上"不太喜欢面食"时
            # 会被直接覆盖的根因。用户要的"认知比对层"就建立在这个之上。
            existing_block = "\n".join(
                f"  · {f.key}：{f.value}" for f in existing_facts.values()
            ) or "  （她现在还不了解你什么）"
            world_block = self._known_world_notes()
            raw = self.llm.chat(
                [
                    {"role": "system", "content": _EXTRACTION_PROMPT.format(
                        existing_facts=existing_block,
                        existing_world_notes=world_block)},
                    {"role": "user", "content": transcript},
                ]
            )
            data = self._parse_json(raw)
        except Exception as exc:
            self.log(f"[记忆] 会话提取失败，本次不写入: {exc}")
            return False
        if not isinstance(data, dict):
            self.log("[记忆] 提取结果不是 JSON 对象，本次不写入")
            return False

        episode_data = data.get("episode")
        if not isinstance(episode_data, dict) or not str(episode_data.get("summary", "")).strip():
            self.log("[记忆] 提取结果缺 episode.summary，本次不写入")
            return False
        importance = _clamp(_to_float(episode_data.get("importance"), 0.2), 0.0, 1.0)
        emotion = episode_data.get("emotion")
        episode = self.store.add_episode(
            summary=str(episode_data["summary"]).strip(),
            participants=_to_str_list(episode_data.get("participants"), ["用户"]),
            emotion=str(emotion).strip() if isinstance(emotion, str) and emotion.strip() else None,
            topics=_to_str_list(episode_data.get("topics"), []),
            importance=importance,
            source_turns=[m["content"][:200] for m in user_messages[:3]],
        )

        fact_count = 0
        conflict_count = 0
        # ⭐ 认知比对（2026-09-28）：提取器给出的"他刚说的 vs 她已经知道的"。
        # 只有 `conflict` + `keep_both` 会改变写入行为（**不覆盖旧值**）；
        # 其余情况照旧走正常 upsert。
        reconciliations = [rc for rc in (data.get("reconciliations") or [])
                           if isinstance(rc, dict)]
        facts_data = data.get("facts")
        if isinstance(facts_data, list):
            for fact in facts_data:
                if not isinstance(fact, dict):
                    continue
                key = str(fact.get("key", "")).strip()
                value = str(fact.get("value", "")).strip()
                if not key or not value:
                    continue
                confidence = _clamp(_to_float(fact.get("confidence"), 0.9), 0.0, 1.0)
                old = existing_facts.get(key)
                if (old is not None and old.status == "confirmed"
                        and confidence < old.confidence):
                    self.log(f"[记忆] 低置信提取未覆盖已有事实：{key}")
                    continue
                # ⭐⭐ 认知比对（2026-09-28，用户定的"比对层"）：
                # 提取器说这条跟已有认知**冲突**时，**不许覆盖旧值**——
                # 用户口径："conflict 不等于谁错了"（"通常12点睡"和"昨天3点睡"可以同时成立），
                # "她以前怎么认识你，本身也是你们相处历史的一部分"。
                # ⚠️ 现在只做 `keep_both`：**旧的照旧、新的另存一条**（键名加后缀区分）。
                is_conflict = any(
                    str(rc.get("target", "")).startswith("user_fact")
                    and str(rc.get("action", "")) == "keep_both"
                    and str(rc.get("new_information", "")).strip()
                    and str(rc.get("new_information", "")).strip() in value
                    for rc in reconciliations
                )
                if is_conflict and old is not None:
                    new_key = f"{key}（后来）"
                    self.log(f"[记忆] 认知冲突 → 不覆盖旧值：{key}「{old.value}」"
                             f" vs 新「{value}」→ 存为 {new_key}")
                    self.store.upsert_fact(
                        key=new_key, value=value, confidence=confidence,
                        evidence=[episode.id])
                    conflict_count += 1
                    continue
                self.store.upsert_fact(
                    key=key, value=value, confidence=confidence, evidence=[episode.id]
                )
                fact_count += 1
        # ⭐ 关系状态更新（2026-09-28）：复用同一次提取产出的 `affect` 字段，
        # **不额外调用 API**。判断"这段对话对关系的影响"由提取器一起做。
        affect_note = self._apply_affect(data.get("affect"))
        gift_note = self._apply_gifts(data.get("gifts"))
        reconcile_note = ""
        if reconciliations:
            # ⚠️ 冲突**留痕**（用户 2026-09-28 要的"能看见"）：
            # 不写进日志你就不知道"她发现了矛盾"，也没法判断她记对没有。
            shown = "；".join(
                f"{rc.get('relation')}: {rc.get('existing')} → {rc.get('new_information')}"
                for rc in reconciliations[:3])
            reconcile_note = f"；认知比对 {len(reconciliations)} 条（{shown}）"
            self._write_chat_note(reconciliations, conflict_count)
        self.log(f"[记忆] 已写入：1 条回忆（importance {importance:.1f}）"
                 f"+ {fact_count} 条事实"
                 + (f"，{conflict_count} 条冲突另存（未覆盖旧值）" if conflict_count else "")
                 + affect_note + gift_note + reconcile_note)
        return True

    def _apply_gifts(self, payload: object) -> str:
        """提取出的"她主动要送他的东西"→ 礼物候选池。返回日志后缀（空串=没有）。

        ⚠️ 只进**候选池**，不直接落账——账本动作只发生在礼物小屋（他裁决收不收）。
        手机端会话走同一条提取管道（单写点），所以手机上她答应的也自动带回来。
        """
        if self.gift_store is None or not isinstance(payload, list):
            return ""
        added = 0
        for g in payload:
            if not isinstance(g, dict):
                continue
            name = str(g.get("name", "")).strip()
            if not name:
                continue
            self.gift_store.add_wish(name, str(g.get("note", "")).strip(),
                                     source="chat")
            added += 1
        return f"，{added} 条礼物心意进候选池" if added else ""

    def _apply_affect(self, payload: object) -> str:
        """把提取器给的 `affect` 字段应用到关系状态。返回日志后缀（空串=没影响）。

        ⚠️ **看语境，不看词面**（用户 2026-09-28 定的关键）：
        他开玩笑式地损（"你咋这么笨哈哈"）**不扣**；认真说重话才扣。
        这个判断交给 LLM（提示词里已写明），本地那套只兜极端情况。

        ⚠️ 数字**钳在 ±30 / ±15**（提示词已限，这里再兜一次）——
        防某次提取抽风，一句闲聊把关系打到谷底。
        """
        if self.affect is None or not isinstance(payload, dict):
            return ""
        try:
            comfort = float(payload.get("comfort", 0) or 0)
            closeness = float(payload.get("closeness", 0) or 0)
        except (TypeError, ValueError):
            return ""
        comfort = max(-30.0, min(30.0, comfort))
        closeness = max(-15.0, min(15.0, closeness))
        note = str(payload.get("note", "") or "").strip()
        if not (comfort or closeness):
            return ""
        state = self.affect.apply_delta(closeness=closeness, comfort=comfort, event=note)
        return (f"；关系变化（亲近 {closeness:+.0f} / 舒适 {comfort:+.0f}"
                f" → {state.closeness:.0f}/{state.comfort:.0f}）"
                + (f"：{note}" if note else ""))

    def _write_chat_note(self, reconciliations: list[dict], conflicts: int) -> None:
        """把"她发现了什么认知矛盾"追加进 `data/chat.log`。

        ⚠️ 为什么由提取器直接写、而不是走 `DebugInfo`：
        **时点不同**——`chat.log` 每轮写，而 `reconciliations` 是**会话结束时**才产生的。
        硬塞进 DebugInfo 会导致"这轮的日志里没有它"。

        ⚠️ 这是**你能发现她记错了**的唯一途径（用户 2026-09-28 要的）：
        ```
        你 > 我其实挺喜欢吃面的
              📝 认知比对：饮食偏好「不太喜欢面食」→ 新「挺喜欢吃面的」
                 （冲突，旧值保留，新的存为「饮食偏好（后来）」）
        ```
        失败只吞——日志永远不该拖累记忆写入。
        """
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            lines = [f"      📝 认知比对（会话结束提取时发现）{stamp}"]
            for rc in reconciliations:
                rel = str(rc.get("relation", "?"))
                mark = "⚠️ 冲突" if rel == "conflict" else rel
                lines.append(f"         {mark}：{rc.get('existing', '')}"
                             f" → {rc.get('new_information', '')}")
                if rc.get("note"):
                    lines.append(f"           说明：{rc['note']}")
                if rel == "conflict" and str(rc.get("action")) == "keep_both":
                    lines.append("           ⇒ 旧值**保留**，新的另存一条（未覆盖）")
            if conflicts:
                lines.append(f"         （本轮 {conflicts} 条冲突未覆盖旧值）")
            path = self.chat_log_path
            if path is None:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception:
            pass

    def _parse_json(self, raw: str) -> dict | list | None:
        return parse_llm_json(raw)


def parse_llm_json(raw: str) -> dict | list | None:
    text = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _to_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_str_list(value: object, default: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return default
