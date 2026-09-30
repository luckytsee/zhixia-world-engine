# 实现说明（IMPLEMENTATION_NOTES）

> 对应 SPEC.md（2026-09-23）。契约文件 `types.py` / `base.py` 未做任何修改。
> 验收：`python -m pytest memory/tests/ -v` → 26 passed；`from memory import SQLiteMemoryStore` → ok。
> **Protocol 方法数以 base.py 为准：12 个**，全部实现并通过 `isinstance(store, MemoryStore)` 运行时检查（见 test_store.py::test_protocol_conformance）。

## 1. 文件结构

| 文件 | 职责 |
|---|---|
| `store.py` | `SQLiteMemoryStore`：12 个协议方法的 SQLite 实现，内部 RLock 保证线程安全 |
| `retrieval.py` | 混合评分：tokenize（中文 2-gram / 英文白空切词）、余弦、新近度、关键词命中、情境加成 |
| `decay.py` | 时间衰减归档（recency < 0.05）+ 容量淘汰（importance × recency 最低者，pinned 豁免） |
| `embedding.py` | 本地 sentence-transformers 懒加载，HF 缓存指向 `D:\models\hf`，禁止云 API |
| `tests/` | 26 个用例，MockEmbedder（确定性字符袋向量）全离线，覆盖 SPEC 第 5 节全部 7 项 |

## 2. 实现要点

- **embedding 序列化**：float32 numpy → BLOB；维度不匹配或任一侧缺失时向量项计 0，不崩溃。
- **查询向量惰性计算**：`search_episodes` 仅当存在带向量的候选条目时才对 query 做向量化，省掉无谓的模型调用。
- **last_hit 语义**：`search_episodes` 命中即更新（含返回对象），`record_hit` 可单独注入；容量淘汰的 recency 参考时间取 `last_hit ?? timestamp`。
- **fact 合并**：同 key upsert 时 value 覆盖、confidence 取 max、evidence 并集去重保序、`first_learned` 保留首次。
- **线程安全**：所有公开方法持 `RLock`，`check_same_thread=False`，调用方可放心放线程池。

## 3. 与 SPEC 的偏差（取舍记录）

1. **upsert 已存在 fact 的 status**：SPEC 3.1 的"status 恢复 confirmed"与"confidence ≥ 0.8 → confirmed / < 0.8 → tentative"存在歧义。取舍：统一按**合并后 confidence ≥ 0.8 → confirmed，否则 tentative**。理由：无条件恢复 confirmed 会让 0.5 置信度的事实进入 prompt，违反 06 文档"待验证不注入"的纪律。refuted 的 fact 被 upsert 后按此规则复活（不再是 refuted）。
2. **embedder=None 的懒加载时机**：在首次 `add_episode` 尝试加载本地模型；**加载失败（无网/无模型）则本进程内降级为无向量模式，不重试、不崩溃**，后续按关键词+新近度+重要性检索。SPEC 未明确失败策略，此为最保守选择。测试用 monkeypatch 验证了该降级路径（两个方向：写入端无 embedder、查询端有向量但 embedder 不可用）。
3. **衰减测试用 `half_life_days=10`**：SPEC 第 5 节的"90 天前低 importance 归档"场景在默认半衰期 30 天下数学上不成立——`exp(-90/(30×(1+3i)))` 仅在 i=0.0 时为 0.0498 勉强过阈，i≥0.1 时均 >0.05。改用 10 天半衰期使低重要性（0.1→0.001）与高重要性（0.9→0.088）两侧都有充分裕度，构造函数参数本身即为此覆盖。
4. **embedder 协议双形态**：SPEC 构造注解是 `Callable`，协议描述是 `def embed(texts)`。实现两者都支持（先查 `.embed` 方法，否则按 callable 调用）。
5. **静默 no-op**：`refute_fact` / `pin_fact` / `forget_fact` 对不存在的 key 不抛错；`fact_evidence` 对不存在的 key 返回 `[]`。记忆管道可能对幻觉 key 调用这些方法，抛错反而脆。
6. **list_facts 排序**：按 `first_learned` 升序（时间线视角），SPEC 未规定。

## 4. 已知限制

- **单进程**：SQLite 文件级锁，未处理多进程并发写。桌面伴侣单实例场景够用。
- **pinned 超限**：pinned 条目数本身超过 `max_episodes` 时无法淘汰到上限以内（pinned 豁免是硬规则）。
- **embedder 失败不重试**：本进程内缓存失败标记，重启进程才会再次尝试加载模型。
- **关键词命中是朴素子串匹配**：无分词、无 FTS 索引；每次检索全表加载候选（几千条量级毫秒级，符合设计规模，未做性能优化）。
- **export_all 格式为最小实现**：满足"人可读 + archived 标注"，未做分页/过滤。
