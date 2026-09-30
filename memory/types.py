from __future__ import annotations

from dataclasses import dataclass, field

FACT_CONFIRMED = "confirmed"
FACT_TENTATIVE = "tentative"
FACT_REFUTED = "refuted"


@dataclass
class Episode:
    """情景记忆：一次会话/事件的摘要条目。存摘要，不存对话原文。"""

    id: str
    timestamp: float
    summary: str
    participants: list[str]
    emotion: str | None
    topics: list[str]
    importance: float
    pinned: bool = False
    source_turns: list[str] = field(default_factory=list)
    embedding: bytes | None = None
    last_hit: float | None = None


@dataclass
class Fact:
    """语义记忆：关于用户的抽象事实，可被推翻。"""

    key: str
    value: str
    confidence: float
    first_learned: float
    last_confirmed: float
    evidence: list[str]
    status: str = FACT_CONFIRMED
    pinned: bool = False


@dataclass
class RetrievedEpisode:
    episode: Episode
    score: float
