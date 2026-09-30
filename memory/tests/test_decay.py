"""衰减与容量淘汰测试 + export_all 可读性。"""

from __future__ import annotations

from memory.store import SQLiteMemoryStore
from memory.tests.mock_embedder import MockEmbedder

T0 = 1_700_000_000.0
DAY = 86400.0


def _add(store, **overrides):
    params = {
        "summary": "一条记录",
        "participants": ["user"],
        "emotion": None,
        "topics": ["闲聊"],
        "importance": 0.3,
        "now": T0,
    }
    params.update(overrides)
    return store.add_episode(**params)


# ---------- 3. 时间衰减 ----------

def test_decay_archives_old_low_importance(store_factory):
    """半衰期 10 天：90 天前低重要性归档，高重要性仍在，pinned 永不归档。"""
    store = store_factory(half_life_days=10.0)
    ep_low = _add(
        store, summary="闲聊了一些琐事", importance=0.1, now=T0 - 90 * DAY
    )
    ep_high = _add(
        store, summary="用户聊了重要项目进展", topics=["项目"], importance=0.9, now=T0 - 90 * DAY
    )
    ep_pinned = _add(
        store, summary="用户叮嘱要记住这件事", importance=0.1, pinned=True, now=T0 - 90 * DAY
    )

    archived_count = store.apply_decay(now=T0)
    assert archived_count == 1

    results = store.search_episodes(query_text="用户", top_k=10, now=T0)
    returned_ids = {r.episode.id for r in results}
    assert ep_low.id not in returned_ids
    assert ep_high.id in returned_ids
    assert ep_pinned.id in returned_ids

    text = store.export_all()
    assert ep_low.summary in text
    assert "[archived]" in text

    # 归档条目仍可通过 fact_evidence 追溯
    store.upsert_fact(
        key="user.trivial", value="琐事", confidence=0.9, evidence=[ep_low.id], now=T0
    )
    assert [e.id for e in store.fact_evidence("user.trivial")] == [ep_low.id]


def test_pinned_never_archived(store_factory):
    store = store_factory(half_life_days=1.0)
    _add(store, summary="钉住的久远记忆", importance=0.0, pinned=True, now=T0 - 365 * DAY)
    assert store.apply_decay(now=T0) == 0


def test_recent_episodes_not_archived(store_factory):
    store = store_factory(half_life_days=10.0)
    _add(store, summary="昨天的事", importance=0.1, now=T0 - DAY)
    assert store.apply_decay(now=T0) == 0


# ---------- 4. 容量淘汰 ----------

def test_capacity_eviction(store_factory):
    store = store_factory(max_episodes=3)
    pinned_a = _add(store, summary="钉住A", importance=0.1, pinned=True)
    pinned_b = _add(store, summary="钉住B", importance=0.2, pinned=True)
    keep = _add(store, summary="高价值", importance=0.9)
    _add(store, summary="低价值丙", importance=0.3)
    _add(store, summary="低价值乙", importance=0.5)
    _add(store, summary="低价值甲", importance=0.7)

    evicted = store.apply_decay(now=T0)
    assert evicted == 3

    results = store.search_episodes(query_text="", top_k=10, now=T0)
    assert results == []  # 空查询返回空

    text = store.export_all()
    active_summaries = {"高价值", "钉住A", "钉住B"}
    for line in text.splitlines():
        if line.startswith("[") and "202" in line and "[archived]" not in line:
            summary = line.split("] ", 1)[1]
            assert summary in active_summaries

    results_all = store.search_episodes(query_text="价值 钉住", top_k=10, now=T0)
    returned_ids = {r.episode.id for r in results_all}
    assert returned_ids == {pinned_a.id, pinned_b.id, keep.id}


def test_capacity_not_triggered_under_limit(store_factory):
    store = store_factory(max_episodes=10)
    for i in range(5):
        _add(store, summary=f"条目{i}", importance=0.5)
    assert store.apply_decay(now=T0) == 0
    assert len(store.search_episodes(query_text="条目", top_k=10, now=T0)) == 5


# ---------- 7. export_all ----------

def test_export_all_sections(store, db_path):
    ep = _add(store, summary="用户聊了项目进度", topics=["项目"], importance=0.8, now=T0)
    store.upsert_fact(
        key="user.project", value="桌面AI伴侣", confidence=0.9, evidence=[ep.id], now=T0
    )
    store.forget_fact  # noqa: B018  (仅确认方法存在)

    text = store.export_all()
    assert "=== FACTS ===" in text
    assert "=== EPISODES ===" in text
    assert "[user.project] 桌面AI伴侣" in text
    assert "confirmed" in text
    assert "用户聊了项目进度" in text
    assert "topics: 项目" in text
    assert "[archived]" not in text  # 未归档的不带标注


def test_export_empty_store(store):
    text = store.export_all()
    assert "=== FACTS ===" in text
    assert "=== EPISODES ===" in text
    assert "(none)" in text
