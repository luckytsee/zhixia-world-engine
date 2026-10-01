# memory 模块实现规格（SPEC）

> 本文件是实现契约。`types.py` 与 `base.py` 已定死，**不得修改**；你实现 `store.py`（SQLite 存储）、`retrieval.py`（混合检索）、`decay.py`（遗忘）、`embedding.py`（本地向量化）以及 `tests/`。
> 设计依据：`../docs/02_记忆系统设计.md`（可读，不可改）。

## 1. 硬约束

1. **只改 `desktop-ai-companion/memory/` 目录**，不碰其他目录。
2. **零网络**：除首次下载 embedding 模型外不得有任何网络请求；**禁止云 embedding API**。
3. **同步 API**：所有方法为普通同步函数（调用方自行放线程），不用 async。
4. **不引入需要编译的工具链**：向量检索用 **numpy 暴力余弦**（几百条数据毫秒级），不用 faiss / sqlite-vec。
5. embedding 模型：`sentence-transformers` 的 `paraphrase-multilingual-MiniLM-L12-v2`（本机已装 sentence-transformers 5.5.1，走全局 site-packages）。**embedder 必须可注入**：构造函数接受可选 `embedder` 参数（协议：`def embed(texts: list[str]) -> list[list[float]]`），测试时用 MockEmbedder，**测试不得下载模型、不得联网**。
6. HF 缓存：首次加载模型前设置 `HUGGINGFACE_HUB_CACHE=本地 HF 缓存目录（用 HUGGINGFACE_HUB_CACHE 指定）`（存在则用，不存在则创建）。
7. Python 3.12，类型注解齐全，通过 `mypy --strict` 不做硬性要求，但 `pyright basic` 应无错。

## 2. SQLite schema（`data/memory.db`，WAL 模式，路径可由构造参数覆盖）

```sql
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,             -- uuid4 hex
    timestamp REAL NOT NULL,
    summary TEXT NOT NULL,
    participants TEXT NOT NULL,      -- JSON array
    emotion TEXT,
    topics TEXT NOT NULL,            -- JSON array
    importance REAL NOT NULL,        -- 0.0-1.0
    pinned INTEGER NOT NULL DEFAULT 0,
    source_turns TEXT NOT NULL,      -- JSON array
    embedding BLOB,                  -- float32 序列化，可空
    last_hit REAL,
    archived INTEGER NOT NULL DEFAULT 0   -- 衰减后置 1，不再参与检索
);
CREATE INDEX IF NOT EXISTS idx_episodes_archived ON episodes(archived);

CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    first_learned REAL NOT NULL,
    last_confirmed REAL NOT NULL,
    evidence TEXT NOT NULL,          -- JSON array of episode ids
    status TEXT NOT NULL,            -- confirmed | tentative | refuted
    pinned INTEGER NOT NULL DEFAULT 0
);
```

## 3. 语义规则

### 3.1 写入

- `add_episode`：生成 id、若 embedder 存在则算 embedding 存 BLOB。`importance` 钳制到 [0,1]。
- `upsert_fact`：同 key 已存在 → 覆盖 value、confidence 取 max(旧, 新)、evidence 并集去重、last_confirmed 更新、status 恢复 confirmed。新事实 confidence ≥ 0.8 → confirmed；< 0.8 → **tentative**。
- `refute_fact`：status 置 refuted，**不物理删除**（可追溯）。
- `pin_fact`：置 pinned 标志。

### 3.2 检索 `search_episodes`

对每条非 archived 的 episode 计算混合得分：

```
score = w_vector × cosine(query_emb, ep_emb)
      + w_recency × exp(-Δdays / effective_half_life(importance))
      + w_importance × importance
      + w_keyword  × keyword_hit_ratio(query, episode)
```

- `effective_half_life = half_life_days × (1 + importance × 3)`（pinned 的 recency 项恒为 1.0，不衰减）
- `keyword_hit_ratio`：query 与 (summary + topics + participants) 的**子串命中**——中文按 2-gram 切 query（"小明" → ["小明"]，长度 <3 的 query 整段作为一个 token；英文/数字按空白切词），命中任一 token 记 1.0，否则 0.0
- 无 embedding 的条目：w_vector 项计 0，其余照常（不得崩溃）
- `context_topics` 额外命中时总分 ×1.1（情境加成）
- 返回按 score 降序的 top_k，同时更新命中条目的 `last_hit`（供容量淘汰用）
- **query_text 为空串时返回空列表**

### 3.3 事实检索 `relevant_facts`

- 默认只返回 confirmed；`include_tentative=True` 时含 tentative；**refuted 永不返回**
- `query_text` 提供时：key/value 与 query 有子串命中的排前，其余按 confidence 降序
- 截断到 limit

### 3.4 衰减 `apply_decay`（返回归档条数）

- 逐条计算 `exp(-Δdays / effective_half_life)`，得分 < 0.05 且非 pinned → archived=1
- 同时做**容量淘汰**：非 archived 条数 > max_episodes 时，按 (importance × recency) 最低者淘汰，pinned 豁免

### 3.5 可见性

- `fact_evidence(key)`：返回 evidence 里的 episode（按时间升序）
- `export_all()`：生成人可读文本——`=== FACTS ===`（每条：key、value、status、confidence、日期）+ `=== EPISODES ===`（每条：日期、summary、topics、importance），archived 的也列出但标注 `[archived]`

## 4. 构造参数

```python
class SQLiteMemoryStore:  # 实现 MemoryStore 协议
    def __init__(
        self,
        db_path: str | Path = "data/memory.db",
        *,
        embedder: Callable[[list[str]], list[list[float]]] | None = None,  # None=懒加载 sentence-transformers
        half_life_days: float = 30.0,
        max_episodes: int = 2000,
        weights: tuple[float, float, float, float] = (0.45, 0.25, 0.15, 0.15),  # vector, recency, importance, keyword
    ): ...
```

`memory/__init__.py` 导出 `SQLiteMemoryStore`。模块内部按需拆 `store.py / retrieval.py / decay.py / embedding.py`。

## 5. 测试（pytest，全离线，MockEmbedder 用确定性哈希向量）

至少覆盖（每条对应 06 文档验收标准）：

1. 写入/读取 round-trip：episode 字段无丢失
2. 混合检索排序：高相关 > 低相关；关键词精确命中把正确条目顶上来（人名/专名场景）
3. **衰减**：造 90 天前的低 importance 条目 → apply_decay 后 archived；高 importance（0.9）90 天前的**仍在**；pinned 永不 archived
4. 容量淘汰：塞 max_episodes+50 条 → 淘汰后 ≤ max_episodes，pinned 保留
5. 事实状态机：低 confidence → tentative 且 relevant_facts 默认不返回；upsert 同 key 覆盖合并 evidence；refute 后永不返回但 fact_evidence 仍可追溯
6. 时间旅行：所有方法的 `now` 参数可注入（不用 sleep）
7. export_all 可读、含 archived 标注

## 6. 验收命令

```powershell
cd <仓库根>
python -m pytest memory/tests/ -v          # 全绿
python -c "from memory import SQLiteMemoryStore; print('import ok')"
```

**完成定义**：测试全绿 + 验收命令通过 + 不修改 types.py/base.py/其他目录。完成后在 `memory/IMPLEMENTATION_NOTES.md` 里写：实现要点、与 SPEC 的偏差（如有）、已知限制。
