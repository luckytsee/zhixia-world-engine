"""存储层测试：round-trip、事实状态机、时间旅行、协议符合性。"""

from __future__ import annotations

from memory.base import MemoryStore
from memory.store import SQLiteMemoryStore
from memory.tests.mock_embedder import MockEmbedder
from memory.types import FACT_CONFIRMED, FACT_REFUTED, FACT_TENTATIVE

T0 = 1_700_000_000.0


def _add_episode(store: SQLiteMemoryStore, **overrides):
    params = {
        "summary": "用户聊了今天的进度",
        "participants": ["user", "ai"],
        "emotion": "happy",
        "topics": ["项目"],
        "importance": 0.7,
        "source_turns": ["u1", "a1"],
        "pinned": False,
        "now": T0,
    }
    params.update(overrides)
    return store.add_episode(**params)


# ---------- 1. 写入/读取 round-trip ----------

def test_protocol_conformance(store: SQLiteMemoryStore):
    assert isinstance(store, MemoryStore)


def test_episode_roundtrip_across_reopen(store, db_path):
    ep = _add_episode(
        store,
        summary="用户提到他朋友叫小明",
        participants=["user", "小明"],
        emotion="happy",
        topics=["感情", "生活"],
        importance=0.95,
        source_turns=["u1", "a1", "a2"],
        pinned=True,
    )
    assert len(ep.id) == 32
    store.upsert_fact(
        key="user.friend_name", value="小明", confidence=0.95, evidence=[ep.id], now=T0
    )

    reopened = SQLiteMemoryStore(str(db_path), embedder=MockEmbedder())
    episodes = reopened.fact_evidence("user.friend_name")
    assert len(episodes) == 1
    restored = episodes[0]
    assert restored.id == ep.id
    assert restored.timestamp == T0
    assert restored.summary == "用户提到他朋友叫小明"
    assert restored.participants == ["user", "小明"]
    assert restored.emotion == "happy"
    assert restored.topics == ["感情", "生活"]
    assert restored.importance == 0.95
    assert restored.pinned is True
    assert restored.source_turns == ["u1", "a1", "a2"]
    assert restored.embedding is not None
    assert restored.last_hit is None

    results = reopened.search_episodes(query_text="小明", now=T0)
    assert any(r.episode.id == ep.id for r in results)


def test_importance_clamped(store):
    ep_low = _add_episode(store, importance=5.0, summary="超过上限")
    ep_high = _add_episode(store, importance=-3.0, summary="低于下限")
    assert ep_low.importance == 1.0
    assert ep_high.importance == 0.0


# ---------- 5. 事实状态机 ----------

def test_low_confidence_fact_is_tentative(store):
    ep = _add_episode(store)
    fact = store.upsert_fact(
        key="user.likes_coffee", value="喜欢美式", confidence=0.5, evidence=[ep.id], now=T0
    )
    assert fact.status == FACT_TENTATIVE
    assert store.relevant_facts() == []
    assert store.relevant_facts(include_tentative=True)[0].key == "user.likes_coffee"


def test_upsert_same_key_merges(store):
    ep1 = _add_episode(store, summary="第一次提到")
    ep2 = _add_episode(store, summary="第二次确认")
    store.upsert_fact(
        key="user.job", value="做桌面AI项目", confidence=0.6, evidence=[ep1.id], now=T0
    )
    fact = store.upsert_fact(
        key="user.job",
        value="在做示例项目",
        confidence=0.9,
        evidence=[ep2.id],
        now=T0 + 100,
    )
    assert fact.value == "在做示例项目"
    assert fact.confidence == 0.9
    assert set(fact.evidence) == {ep1.id, ep2.id}
    assert fact.status == FACT_CONFIRMED
    assert fact.first_learned == T0
    assert fact.last_confirmed == T0 + 100


def test_upsert_confidence_keeps_max(store):
    store.upsert_fact(key="user.city", value="深圳", confidence=0.95, now=T0, evidence=[])
    fact = store.upsert_fact(key="user.city", value="深圳", confidence=0.4, now=T0 + 50, evidence=[])
    assert fact.confidence == 0.95
    assert fact.status == FACT_CONFIRMED


def test_refuted_fact_never_returned_but_traceable(store):
    ep = _add_episode(store, summary="用户否认了某个猜测")
    store.upsert_fact(
        key="user.hobby", value="喜欢爬山", confidence=0.9, evidence=[ep.id], now=T0
    )
    store.refute_fact("user.hobby")

    assert store.relevant_facts() == []
    assert store.relevant_facts(include_tentative=True) == []

    listed = {f.key: f for f in store.list_facts()}
    assert listed["user.hobby"].status == FACT_REFUTED

    evidence = store.fact_evidence("user.hobby")
    assert [e.id for e in evidence] == [ep.id]


def test_forget_fact(store):
    store.upsert_fact(key="user.tmp", value="临时", confidence=0.9, now=T0, evidence=[])
    store.forget_fact("user.tmp")
    assert store.list_facts() == []
    assert store.fact_evidence("user.tmp") == []


def test_relevant_facts_query_puts_hits_first(store):
    store.upsert_fact(
        key="user.name", value="叫小明", confidence=0.95, now=T0, evidence=[]
    )
    store.upsert_fact(
        key="user.project", value="在做桌面AI项目", confidence=0.9, now=T0, evidence=[]
    )
    store.upsert_fact(
        key="user.coffee", value="喜欢喝美式咖啡", confidence=0.5, now=T0, evidence=[]
    )

    default = store.relevant_facts()
    assert [f.key for f in default] == ["user.name", "user.project"]

    hits = store.relevant_facts(query_text="美式咖啡", include_tentative=True)
    assert hits[0].key == "user.coffee"

    limited = store.relevant_facts(limit=1)
    assert [f.key for f in limited] == ["user.name"]


# ---------- 6. 时间旅行（now 参数注入，不用 sleep） ----------

def test_time_travel_all_now_params(store):
    ep = _add_episode(store, summary="时间旅行的条目", importance=0.5)
    assert ep.timestamp == T0

    fact = store.upsert_fact(
        key="user.travel", value="ok", confidence=0.9, evidence=[ep.id], now=T0 + 10
    )
    assert fact.first_learned == T0 + 10
    assert fact.last_confirmed == T0 + 10

    store.record_hit(ep.id, now=T0 + 123)
    assert store.fact_evidence("user.travel")[0].last_hit == T0 + 123

    fresh = store.search_episodes(query_text="时间旅行", now=T0 + 200)
    assert fresh[0].episode.last_hit == T0 + 200


def test_search_score_changes_with_now(store):
    _add_episode(store, summary="衰减评分", importance=0.0, now=T0)
    s_recent = store.search_episodes(query_text="衰减评分", now=T0)[0].score
    s_later = store.search_episodes(query_text="衰减评分", now=T0 + 30 * 86400)[0].score
    assert s_later < s_recent
