from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import Episode, Fact, RetrievedEpisode


@runtime_checkable
class MemoryStore(Protocol):
    """记忆模块对外契约。实现方只需满足本协议，不得扩大接口面。"""

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
    ) -> Episode: ...

    def upsert_fact(
        self,
        *,
        key: str,
        value: str,
        confidence: float,
        evidence: list[str],
        now: float | None = None,
    ) -> Fact: ...

    def refute_fact(self, key: str) -> None: ...

    def pin_fact(self, key: str, pinned: bool = True) -> None: ...

    def search_episodes(
        self,
        *,
        query_text: str,
        context_topics: list[str] | None = None,
        top_k: int = 5,
        now: float | None = None,
    ) -> list[RetrievedEpisode]: ...

    def relevant_facts(
        self,
        *,
        query_text: str | None = None,
        limit: int = 10,
        include_tentative: bool = False,
    ) -> list[Fact]: ...

    def apply_decay(self, now: float | None = None) -> int: ...

    def record_hit(self, episode_id: str, now: float | None = None) -> None: ...

    def list_facts(self) -> list[Fact]: ...

    def forget_fact(self, key: str) -> None: ...

    def fact_evidence(self, key: str) -> list[Episode]: ...

    def export_all(self) -> str: ...
