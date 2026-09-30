"""SQLiteMemoryStore：记忆模块的 SQLite 实现（满足 base.py 的 MemoryStore 协议）。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from .decay import episodes_to_archive, episodes_to_evict
from .retrieval import score_episode, tokenize_query
from .types import (
    Episode,
    Fact,
    RetrievedEpisode,
    FACT_CONFIRMED,
    FACT_TENTATIVE,
)

EmbedFn = Callable[[list[str]], list[list[float]]]

FACT_CONFIRM_THRESHOLD = 0.8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    summary TEXT NOT NULL,
    participants TEXT NOT NULL,
    emotion TEXT,
    topics TEXT NOT NULL,
    importance REAL NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    source_turns TEXT NOT NULL,
    embedding BLOB,
    last_hit REAL,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_episodes_archived ON episodes(archived);

CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    first_learned REAL NOT NULL,
    last_confirmed REAL NOT NULL,
    evidence TEXT NOT NULL,
    status TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0
);
"""


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _now_or(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _vec_to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        timestamp=float(row["timestamp"]),
        summary=row["summary"],
        participants=json.loads(row["participants"]),
        emotion=row["emotion"],
        topics=json.loads(row["topics"]),
        importance=float(row["importance"]),
        pinned=bool(row["pinned"]),
        source_turns=json.loads(row["source_turns"]),
        embedding=row["embedding"],
        last_hit=row["last_hit"],
    )


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        key=row["key"],
        value=row["value"],
        confidence=float(row["confidence"]),
        first_learned=float(row["first_learned"]),
        last_confirmed=float(row["last_confirmed"]),
        evidence=json.loads(row["evidence"]),
        status=row["status"],
        pinned=bool(row["pinned"]),
    )


class SQLiteMemoryStore:
    """SQLite 实现的长期记忆。同步 API，线程安全（内部锁），单文件存储。"""

    def __init__(
        self,
        db_path: str | Path = "data/memory.db",
        *,
        embedder: EmbedFn | None = None,
        half_life_days: float = 30.0,
        max_episodes: int = 2000,
        weights: tuple[float, float, float, float] = (0.45, 0.25, 0.15, 0.15),
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder: EmbedFn | None = embedder
        self._embedder_load_failed = False
        self._half_life_days = float(half_life_days)
        self._max_episodes = int(max_episodes)
        self._weights = tuple(float(w) for w in weights)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------- embedder ----------

    def _ensure_embedder(self) -> bool:
        """embedder=None 时懒加载本地模型；失败则本进程降级为无向量模式，不崩溃。"""
        if self._embedder is not None:
            return True
        if self._embedder_load_failed:
            return False
        try:
            from .embedding import get_default_embedder

            self._embedder = get_default_embedder()
            return True
        except Exception:
            self._embedder_load_failed = True
            return False

    def _call_embedder(self, texts: list[str]) -> list[list[float]] | None:
        embedder = self._embedder
        if embedder is None:
            return None
        if hasattr(embedder, "embed"):
            result = embedder.embed(texts)
        else:
            result = embedder(texts)
        return result if result else None

    # ---------- 写入：episode ----------

    def add_episode(
        self,
        *,
        summary: str,
        participants: list[str],
        emotion: str | None,
        topics: list[str],
        importance: float,
        source_turns: list[str] | None = None,
        pinned: bool = False,
        now: float | None = None,
    ) -> Episode:
        ts = _now_or(now)
        importance = _clamp01(importance)
        episode_id = uuid.uuid4().hex
        turns = list(source_turns) if source_turns is not None else []

        embedding_blob: bytes | None = None
        with self._lock:
            if self._ensure_embedder():
                vectors = self._call_embedder([summary])
                if vectors is not None and vectors[0]:
                    embedding_blob = _vec_to_blob(vectors[0])
            self._conn.execute(
                "INSERT INTO episodes (id, timestamp, summary, participants, emotion, topics,"
                " importance, pinned, source_turns, embedding, last_hit, archived)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)",
                (
                    episode_id,
                    ts,
                    summary,
                    json.dumps(list(participants), ensure_ascii=False),
                    emotion,
                    json.dumps(list(topics), ensure_ascii=False),
                    importance,
                    int(pinned),
                    json.dumps(turns, ensure_ascii=False),
                    embedding_blob,
                ),
            )
            self._conn.commit()

        return Episode(
            id=episode_id,
            timestamp=ts,
            summary=summary,
            participants=list(participants),
            emotion=emotion,
            topics=list(topics),
            importance=importance,
            pinned=pinned,
            source_turns=turns,
            embedding=embedding_blob,
            last_hit=None,
        )

    # ---------- 写入：fact ----------

    def upsert_fact(
        self,
        *,
        key: str,
        value: str,
        confidence: float,
        evidence: list[str],
        now: float | None = None,
    ) -> Fact:
        ts = _now_or(now)
        confidence = _clamp01(confidence)
        new_evidence = list(dict.fromkeys(evidence))

        with self._lock:
            row = self._conn.execute("SELECT * FROM facts WHERE key = ?", (key,)).fetchone()
            if row is None:
                status = FACT_CONFIRMED if confidence >= FACT_CONFIRM_THRESHOLD else FACT_TENTATIVE
                fact = Fact(
                    key=key,
                    value=value,
                    confidence=confidence,
                    first_learned=ts,
                    last_confirmed=ts,
                    evidence=new_evidence,
                    status=status,
                    pinned=False,
                )
                self._conn.execute(
                    "INSERT INTO facts (key, value, confidence, first_learned, last_confirmed,"
                    " evidence, status, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        fact.key,
                        fact.value,
                        fact.confidence,
                        fact.first_learned,
                        fact.last_confirmed,
                        json.dumps(fact.evidence, ensure_ascii=False),
                        fact.status,
                        int(fact.pinned),
                    ),
                )
            else:
                old = _row_to_fact(row)
                merged_evidence = list(dict.fromkeys(old.evidence + new_evidence))
                merged_confidence = max(old.confidence, confidence)
                status = (
                    FACT_CONFIRMED if merged_confidence >= FACT_CONFIRM_THRESHOLD else FACT_TENTATIVE
                )
                fact = Fact(
                    key=key,
                    value=value,
                    confidence=merged_confidence,
                    first_learned=old.first_learned,
                    last_confirmed=ts,
                    evidence=merged_evidence,
                    status=status,
                    pinned=old.pinned,
                )
                self._conn.execute(
                    "UPDATE facts SET value = ?, confidence = ?, last_confirmed = ?,"
                    " evidence = ?, status = ? WHERE key = ?",
                    (
                        fact.value,
                        fact.confidence,
                        fact.last_confirmed,
                        json.dumps(fact.evidence, ensure_ascii=False),
                        fact.status,
                        key,
                    ),
                )
            self._conn.commit()

        return fact

    def refute_fact(self, key: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE facts SET status = 'refuted' WHERE key = ?", (key,)
            )
            self._conn.commit()

    def pin_fact(self, key: str, pinned: bool = True) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE facts SET pinned = ? WHERE key = ?", (int(pinned), key)
            )
            self._conn.commit()

    # ---------- 检索 ----------

    def search_episodes(
        self,
        *,
        query_text: str,
        context_topics: list[str] | None = None,
        top_k: int = 5,
        now: float | None = None,
    ) -> list[RetrievedEpisode]:
        if not query_text:
            return []
        ts_now = _now_or(now)
        tokens = tokenize_query(query_text)
        topics = list(context_topics) if context_topics is not None else []

        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM episodes WHERE archived = 0 ORDER BY timestamp ASC"
            ).fetchall()
            episodes = [_row_to_episode(r) for r in rows]

            query_embedding: list[float] | None = None
            if any(ep.embedding is not None for ep in episodes) and self._ensure_embedder():
                vectors = self._call_embedder([query_text])
                if vectors is not None and vectors[0]:
                    query_embedding = vectors[0]

            scored: list[tuple[float, Episode]] = [
                (
                    score_episode(
                        query_embedding,
                        ep,
                        tokens,
                        self._weights,
                        ts_now,
                        self._half_life_days,
                        topics,
                    ),
                    ep,
                )
                for ep in episodes
            ]
            scored.sort(key=lambda pair: pair[0], reverse=True)

            results: list[RetrievedEpisode] = []
            for score, ep in scored[: max(0, int(top_k))]:
                self._conn.execute(
                    "UPDATE episodes SET last_hit = ? WHERE id = ?", (ts_now, ep.id)
                )
                ep.last_hit = ts_now
                results.append(RetrievedEpisode(episode=ep, score=score))
            if results:
                self._conn.commit()

        return results

    def relevant_facts(
        self,
        *,
        query_text: str | None = None,
        limit: int = 10,
        include_tentative: bool = False,
    ) -> list[Fact]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM facts").fetchall()
        facts = [_row_to_fact(r) for r in rows]

        allowed = {FACT_CONFIRMED}
        if include_tentative:
            allowed.add(FACT_TENTATIVE)
        facts = [f for f in facts if f.status in allowed]

        if query_text:
            tokens = tokenize_query(query_text)

            def is_hit(fact: Fact) -> bool:
                haystack = fact.key + " " + fact.value
                if query_text in haystack:
                    return True
                return any(token in haystack for token in tokens)

            facts.sort(key=lambda f: (not is_hit(f), -f.confidence))
        else:
            facts.sort(key=lambda f: -f.confidence)

        return facts[: max(0, int(limit))]

    def recent_episodes(self, limit: int = 50) -> list[Episode]:
        """最近的 N 条未归档回忆（新→旧）。手机同步快照导出用（2026-09-26）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM episodes WHERE archived = 0"
                " ORDER BY timestamp DESC LIMIT ?",
                (max(0, int(limit)),),
            ).fetchall()
        return [_row_to_episode(r) for r in rows]

    # ---------- 遗忘 ----------

    def apply_decay(self, now: float | None = None) -> int:
        ts_now = _now_or(now)
        with self._lock:
            archived_rows = self._conn.execute(
                "SELECT id FROM episodes WHERE archived = 1"
            ).fetchall()
            archived_ids = {row["id"] for row in archived_rows}
            all_rows = self._conn.execute("SELECT * FROM episodes").fetchall()
            all_episodes = [_row_to_episode(r) for r in all_rows]
            active = [ep for ep in all_episodes if ep.id not in archived_ids]

            to_archive = set(episodes_to_archive(active, ts_now, self._half_life_days))
            survivors = [ep for ep in active if ep.id not in to_archive]
            to_archive.update(
                episodes_to_evict(survivors, ts_now, self._half_life_days, self._max_episodes)
            )

            for episode_id in to_archive:
                self._conn.execute(
                    "UPDATE episodes SET archived = 1 WHERE id = ?", (episode_id,)
                )
            if to_archive:
                self._conn.commit()

        return len(to_archive)

    def record_hit(self, episode_id: str, now: float | None = None) -> None:
        ts = _now_or(now)
        with self._lock:
            self._conn.execute(
                "UPDATE episodes SET last_hit = ? WHERE id = ?", (ts, episode_id)
            )
            self._conn.commit()

    # ---------- 可见性 ----------

    def list_facts(self) -> list[Fact]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM facts ORDER BY first_learned ASC, key ASC"
            ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def forget_fact(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM facts WHERE key = ?", (key,))
            self._conn.commit()

    def fact_evidence(self, key: str) -> list[Episode]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM facts WHERE key = ?", (key,)).fetchone()
            if row is None:
                return []
            evidence_ids = json.loads(row["evidence"])
            if not evidence_ids:
                return []
            placeholders = ",".join("?" for _ in evidence_ids)
            episode_rows = self._conn.execute(
                f"SELECT * FROM episodes WHERE id IN ({placeholders}) ORDER BY timestamp ASC",
                tuple(evidence_ids),
            ).fetchall()
        return [_row_to_episode(r) for r in episode_rows]

    def export_all(self) -> str:
        with self._lock:
            fact_rows = self._conn.execute(
                "SELECT * FROM facts ORDER BY first_learned ASC, key ASC"
            ).fetchall()
            episode_rows = self._conn.execute(
                "SELECT * FROM episodes ORDER BY timestamp ASC"
            ).fetchall()

        lines: list[str] = ["=== FACTS ==="]
        if not fact_rows:
            lines.append("(none)")
        for row in fact_rows:
            fact = _row_to_fact(row)
            pinned_mark = " | pinned" if fact.pinned else ""
            lines.append(f"[{fact.key}] {fact.value}")
            lines.append(
                f"  status: {fact.status} | confidence: {fact.confidence:.2f}"
                f" | learned: {_fmt_date(fact.first_learned)}"
                f" | confirmed: {_fmt_date(fact.last_confirmed)}{pinned_mark}"
            )

        lines.append("=== EPISODES ===")
        if not episode_rows:
            lines.append("(none)")
        for row in episode_rows:
            ep = _row_to_episode(row)
            archived_mark = " [archived]" if bool(row["archived"]) else ""
            pinned_mark = " | pinned" if ep.pinned else ""
            lines.append(f"[{_fmt_date(ep.timestamp)}] {ep.summary}{archived_mark}")
            lines.append(
                f"  topics: {', '.join(ep.topics)} | importance: {ep.importance:.2f}{pinned_mark}"
            )

        return "\n".join(lines)
