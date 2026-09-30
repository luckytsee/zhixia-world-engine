"""混合检索评分：向量 + 新近度 + 重要性 + 关键词命中。"""

from __future__ import annotations

import math
import re

import numpy as np

from .types import Episode

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

CONTEXT_BONUS = 1.1


def contains_cjk(text: str) -> bool:
    return _CJK_RE.search(text) is not None


def tokenize_query(query: str) -> list[str]:
    """查询切词：长度 <3 整段一个 token；中文段 2-gram；英文/数字按空白切。"""
    query = query.strip()
    if not query:
        return []
    if len(query) < 3:
        return [query]
    tokens: list[str] = []
    for word in query.split():
        if contains_cjk(word) and len(word) >= 3:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
        else:
            tokens.append(word)
    return tokens


def effective_half_life(importance: float, half_life_days: float) -> float:
    """重要性缩放半衰期：重要的事忘得慢。"""
    return half_life_days * (1.0 + importance * 3.0)


def recency_score(
    now: float,
    timestamp: float,
    importance: float,
    half_life_days: float,
    pinned: bool,
) -> float:
    """exp(-Δdays / effective_half_life)；pinned 恒为 1.0 不衰减。"""
    if pinned:
        return 1.0
    delta_days = max(0.0, (now - timestamp) / 86400.0)
    return math.exp(-delta_days / effective_half_life(importance, half_life_days))


def cosine(blob_a: bytes | None, vec_b: list[float] | None) -> float:
    """float32 BLOB 与向量的余弦相似度；任一缺失或维度不匹配计 0。"""
    if blob_a is None or not vec_b:
        return 0.0
    va = np.frombuffer(blob_a, dtype=np.float32)
    vb = np.asarray(vec_b, dtype=np.float32)
    if va.shape != vb.shape:
        return 0.0
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def keyword_hit(
    query_tokens: list[str],
    summary: str,
    topics: list[str],
    participants: list[str],
) -> float:
    """子串命中：query 任一 token 出现在 (summary + topics + participants) 记 1.0。"""
    if not query_tokens:
        return 0.0
    haystack = summary + " " + " ".join(topics) + " " + " ".join(participants)
    for token in query_tokens:
        if token in haystack:
            return 1.0
    return 0.0


def score_episode(
    query_embedding: list[float] | None,
    episode: Episode,
    query_tokens: list[str],
    weights: tuple[float, float, float, float],
    now: float,
    half_life_days: float,
    context_topics: list[str],
) -> float:
    """混合得分：w_vector×cos + w_recency×recency + w_importance×importance + w_keyword×hit。"""
    w_vector, w_recency, w_importance, w_keyword = weights
    score = (
        w_vector * cosine(episode.embedding, query_embedding)
        + w_recency
        * recency_score(now, episode.timestamp, episode.importance, half_life_days, episode.pinned)
        + w_importance * episode.importance
        + w_keyword * keyword_hit(query_tokens, episode.summary, episode.topics, episode.participants)
    )
    if context_topics:
        for topic in context_topics:
            if topic in episode.topics:
                score *= CONTEXT_BONUS
                break
    return score
