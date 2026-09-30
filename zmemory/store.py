# -*- coding: utf-8 -*-
"""认知史存储（四层：facts / world_notes / episodes / session）。

⭐ 本模块的全部灵魂是一条**被代码强制的铁律**：
  她对你的认识是一部历史，不是一张随时被 UPDATE 的表。
  - 冲突**永不覆盖**旧值——新认知以 `key（后来）` 并置（`record_claim` 层面强制）；
  - pinned 事实任何关系下都不改写；
  - 世界笔记**只追加**，连删除接口都不存在（"不许不认"是机制不是提示词）；
  - session 是易失的——"进入对话 ≠ 进入记忆"。

零依赖：纯标准库 sqlite3。多线程安全（RLock）。
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid

# 世界笔记的来源值域（和知夏主项目同口径；开源版预留扩展）
ORIGIN_ZIA_SAID = "zia_said"      # 她自己说"要记住"的
ORIGIN_OWNER_TOLD = "owner_told"  # 他亲口告知的（她自己的话优先级更高）

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key            TEXT PRIMARY KEY,
    value          TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 0.9,
    first_learned  REAL NOT NULL,
    last_confirmed REAL NOT NULL,
    pinned         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS world_notes (
    id    TEXT PRIMARY KEY,
    ts    REAL NOT NULL,
    text  TEXT NOT NULL,
    origin TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id         TEXT PRIMARY KEY,
    ts         REAL NOT NULL,
    summary    TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.2
);
"""


def _new_id() -> str:
    return f"{int(time.time() * 1000):x}-{uuid.uuid4().hex[:6]}"


class CompanionMemory:
    """四层记忆。所有"改写"都要过 `record_claim`，并置/拒绝由这里强制。"""

    def __init__(self, path, log=print) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        self.log = log or (lambda *_: None)
        self.session: SessionBuffer = SessionBuffer()  # 易失，不落盘

    # ---------- facts ----------
    def get_fact(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT key, value, confidence, first_learned, last_confirmed, pinned "
                "FROM facts WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return {"key": row[0], "value": row[1], "confidence": row[2],
                "first_learned": row[3], "last_confirmed": row[4], "pinned": bool(row[5])}

    def all_facts(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value, confidence, first_learned, last_confirmed, pinned "
                "FROM facts ORDER BY first_learned").fetchall()
        return [{"key": r[0], "value": r[1], "confidence": r[2],
                 "first_learned": r[3], "last_confirmed": r[4], "pinned": bool(r[5])}
                for r in rows]

    def pin_fact(self, key: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE facts SET pinned = 1 WHERE key = ?", (key,))
            self._conn.commit()

    def record_claim(self, key: str, value: str, relation: str, *,
                     confidence: float = 0.9, note: str = "") -> dict:
        """认知进入事实层的**唯一入口**。relation 来自 Judge（confirm/conflict/new）。

        ⭐ 不可覆盖规则在这里强制：
        - confirm      → 更新值（保留 first_learned，confidence 取 max）
        - conflict     → 旧值原样不动，新认知存为 `key（后来）`（再撞就 `（后来2）`…）
        - new          → 插入（若已存在则按 confirm 处理——Judge 判错也不至于覆盖历史）
        - 任何情况下 pinned 事实的值都不改写（conflict 照常并置）
        """
        key, value = key.strip(), value.strip()
        now = time.time()
        old = self.get_fact(key)
        with self._lock:
            if relation == "conflict":
                base = f"{key}（后来"
                n = 1
                new_key = f"{base}）"
                while self.get_fact(new_key) is not None:
                    n += 1
                    new_key = f"{base}{n}）"
                self._conn.execute(
                    "INSERT INTO facts (key, value, confidence, first_learned, last_confirmed)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (new_key, value, confidence, now, now))
                self._conn.commit()
                self.log(f"[记忆] 冲突并置：{key} 不动，新认知存为 {new_key}"
                         + (f"（{note}）" if note else ""))
                return {"action": "kept_both", "key": new_key, "old": old}
            if old is None:
                self._conn.execute(
                    "INSERT INTO facts (key, value, confidence, first_learned, last_confirmed)"
                    " VALUES (?, ?, ?, ?, ?)", (key, value, confidence, now, now))
                self._conn.commit()
                return {"action": "created", "key": key, "old": None}
            if old["pinned"]:
                self.log(f"[记忆] {key} 是钉死的事实，任何关系都不改写")
                return {"action": "pinned_untouched", "key": key, "old": old}
            if relation == "confirm":
                self._conn.execute(
                    "UPDATE facts SET value = ?, confidence = ?, last_confirmed = ? "
                    "WHERE key = ?",
                    (value, max(old["confidence"], confidence), now, key))
                self._conn.commit()
                return {"action": "updated", "key": key, "old": old}
            # relation == "new" 但已存在 → Judge 判错了，按确认处理并留痕
            self.log(f"[记忆] Judge 判 new 但 {key} 已存在——按 confirm 处理")
            return self.record_claim(key, value, "confirm", confidence=confidence, note=note)

    # ---------- world_notes（append-only，没有删除/修改接口——故意的） ----------
    def add_world_note(self, text: str, origin: str = ORIGIN_ZIA_SAID,
                       source_turn: str | None = None) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("空的认知不值得记")
        note = {"id": _new_id(), "ts": time.time(), "text": text, "origin": origin}
        if source_turn:
            note["text"] = f"{text}（{source_turn}）"
        with self._lock:
            self._conn.execute(
                "INSERT INTO world_notes (id, ts, text, origin) VALUES (?, ?, ?, ?)",
                (note["id"], note["ts"], note["text"], note["origin"]))
            self._conn.commit()
        return note

    def all_world_notes(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, text, origin FROM world_notes ORDER BY ts").fetchall()
        return [{"id": r[0], "ts": r[1], "text": r[2], "origin": r[3]} for r in rows]

    # ---------- episodes ----------
    def add_episode(self, summary: str, importance: float = 0.2) -> dict:
        ep = {"id": _new_id(), "ts": time.time(),
              "summary": (summary or "").strip(), "importance": float(importance)}
        if not ep["summary"]:
            raise ValueError("空的经历不值得记")
        with self._lock:
            self._conn.execute(
                "INSERT INTO episodes (id, ts, summary, importance) VALUES (?, ?, ?, ?)",
                (ep["id"], ep["ts"], ep["summary"], ep["importance"]))
            self._conn.commit()
        return ep

    def recent_episodes(self, limit: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, summary, importance FROM episodes "
                "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "ts": r[1], "summary": r[2], "importance": r[3]}
                for r in rows]

    # ---------- 注入（只给背景，定性措辞；和世界引擎同一纪律） ----------
    def to_prompt(self, fact_limit: int = 15, episode_limit: int = 5) -> str:
        lines = ['=== 关于他的记忆（背景资料，自然地用，禁止说"根据记录"） ===']
        facts = self.all_facts()[-fact_limit:]
        if facts:
            lines.append("[你已经知道的]".replace("[", "「").replace("]", "」"))
            lines += [f"- {f['key']}：{f['value']}" for f in facts]
        notes = self.all_world_notes()
        if notes:
            lines.append("「你自己记下的事（必须记得，不许不认）」")
            lines += [f"- {n['text']}" for n in notes]
        eps = self.recent_episodes(episode_limit)
        if eps:
            lines.append("「最近的经历（各自独立，别拼成连续故事）」")
            lines += [f"- {e['summary']}" for e in eps]
        return "\n".join(lines)


class SessionBuffer:
    """易失的当下。`进入对话 ≠ 进入记忆`——这里的东西进程结束即消失。"""

    def __init__(self, max_turns: int = 20) -> None:
        self._turns: list[dict] = []
        self._max = max_turns

    def append(self, role: str, content: str) -> None:
        self._turns.append({"role": role, "content": content})
        del self._turns[:-self._max]

    @property
    def turns(self) -> list[dict]:
        return list(self._turns)

    def clear(self) -> None:
        self._turns.clear()
