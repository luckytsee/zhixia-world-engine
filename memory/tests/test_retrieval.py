"""检索测试：混合排序、关键词命中、情境加成、空查询、无向量降级。"""

from __future__ import annotations

import memory.embedding
from memory.store import SQLiteMemoryStore
from memory.tests.mock_embedder import MockEmbedder

T0 = 1_700_000_000.0
DAY = 86400.0


def _add(store, **overrides):
    params = {
        "summary": "一条普通记录",
        "participants": ["user"],
        "emotion": None,
        "topics": ["闲聊"],
        "importance": 0.3,
        "now": T0,
    }
    params.update(overrides)
    return store.add_episode(**params)


def test_high_relevance_beats_low(store):
    _add(store, summary="用户提到他朋友小明", topics=["感情"], importance=0.9)
    _add(store, summary="聊了会儿天气不错", topics=["闲聊"], importance=0.3)
    results = store.search_episodes(query_text="小明", now=T0)
    assert results[0].episode.summary == "用户提到他朋友小明"
    assert results[0].score > results[1].score


def test_keyword_exact_hit_beats_recency(store):
    """30 天前的"小明"条目要被关键词顶到最新的闲聊条目前面。"""
    _add(
        store,
        summary="用户说他朋友叫小明",
        topics=["感情"],
        importance=0.9,
        now=T0 - 30 * DAY,
    )
    _add(store, summary="今天天气不错心情挺好", topics=["闲聊"], importance=0.3, now=T0)
    results = store.search_episodes(query_text="小明", now=T0)
    assert results[0].episode.summary == "用户说他朋友叫小明"


def test_context_topics_bonus(store):
    _add(store, summary="用户提到他朋友小明", topics=["感情"], importance=0.9)
    with_bonus = store.search_episodes(
        query_text="小明", context_topics=["感情"], now=T0
    )[0].score
    without_bonus = store.search_episodes(query_text="小明", now=T0)[0].score
    assert with_bonus > without_bonus
    assert abs(without_bonus * 1.1 - with_bonus) < 1e-6


def test_empty_query_returns_empty_list(store):
    _add(store, summary="随便什么")
    assert store.search_episodes(query_text="", now=T0) == []


def test_top_k_limits_results(store):
    for i in range(6):
        _add(store, summary=f"关于项目的讨论第{i}轮", topics=["项目"], importance=0.5)
    results = store.search_episodes(query_text="项目", top_k=3, now=T0)
    assert len(results) == 3


def test_search_updates_last_hit(store):
    ep = _add(store, summary="被命中的条目")
    store.search_episodes(query_text="被命中", now=T0 + 999)
    store.upsert_fact(key="k", value="v", confidence=0.9, evidence=[ep.id], now=T0)
    assert store.fact_evidence("k")[0].last_hit == T0 + 999


def test_no_embedding_store_never_crashes(tmp_path, monkeypatch):
    """embedder 加载失败 → 降级为纯 关键词+新近度+重要性，不崩溃。"""
    def boom():
        raise RuntimeError("测试环境禁止加载模型")

    monkeypatch.setattr(memory.embedding, "get_default_embedder", boom)

    store = SQLiteMemoryStore(str(tmp_path / "m.db"), embedder=None)
    ep = store.add_episode(
        summary="没有向量也要能存取",
        participants=["user"],
        emotion=None,
        topics=["测试"],
        importance=0.5,
        now=T0,
    )
    assert ep.embedding is None

    results = store.search_episodes(query_text="向量", now=T0)
    assert len(results) == 1
    assert results[0].episode.id == ep.id
    assert results[0].score > 0.0  # 关键词 + 新近度 + 重要性仍有分


def test_missing_query_embedder_with_stored_embeddings(tmp_path, monkeypatch):
    """条目有向量但查询时 embedder 不可用 → 向量项全计 0，不崩溃。"""
    db = str(tmp_path / "m.db")
    writer = SQLiteMemoryStore(db, embedder=MockEmbedder())
    writer.add_episode(
        summary="已有向量的条目",
        participants=["user"],
        emotion=None,
        topics=["测试"],
        importance=0.8,
        now=T0,
    )

    def boom():
        raise RuntimeError("测试环境禁止加载模型")

    monkeypatch.setattr(memory.embedding, "get_default_embedder", boom)

    reader = SQLiteMemoryStore(db, embedder=None)
    results = reader.search_episodes(query_text="向量", now=T0)
    assert len(results) == 1
