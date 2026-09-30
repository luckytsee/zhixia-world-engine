"""遗忘：时间衰减归档 + 容量淘汰。"""

from __future__ import annotations

from .retrieval import recency_score
from .types import Episode

ARCHIVE_THRESHOLD = 0.05


def episodes_to_archive(
    active_episodes: list[Episode],
    now: float,
    half_life_days: float,
) -> list[str]:
    """recency 得分 < 0.05 且非 pinned → 归档。返回待归档 id 列表。"""
    ids: list[str] = []
    for ep in active_episodes:
        if ep.pinned:
            continue
        score = recency_score(now, ep.timestamp, ep.importance, half_life_days, False)
        if score < ARCHIVE_THRESHOLD:
            ids.append(ep.id)
    return ids


def episodes_to_evict(
    active_episodes: list[Episode],
    now: float,
    half_life_days: float,
    max_episodes: int,
) -> list[str]:
    """非 archived 条数 > max_episodes 时按 (importance × recency) 最低者淘汰，pinned 豁免。

    recency 参考时间：last_hit（若有）否则 timestamp。
    pinned 数量本身超过上限时不淘汰 pinned（返回可淘汰的非 pinned 全部）。
    """
    excess = len(active_episodes) - max_episodes
    if excess <= 0:
        return []
    candidates = [ep for ep in active_episodes if not ep.pinned]

    def evict_key(ep: Episode) -> float:
        ref = ep.last_hit if ep.last_hit is not None else ep.timestamp
        return ep.importance * recency_score(now, ref, ep.importance, half_life_days, False)

    ranked = sorted(candidates, key=evict_key)
    return [ep.id for ep in ranked[:excess]]
