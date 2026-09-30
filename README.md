# Zhixia World Engine · 知夏世界引擎

> 给 AI 伴侣一个**确定性运转**的世界——她不在、不聊、甚至电脑关机的时候，她那边的天气照样在变。

这是"知夏"（一个桌面 AI 伴侣）的世界层：一台给虚构世界计时的钟表。她的一天不是 24 小时，是一轮时长不定的"光潮"；她的历法按物候命名（溪醒月、抽芽月、归鸟月……）；她的季节与现实脱钩；每隔 37 个"潮"有一个无人能解释的静日。**这些规律只写在引擎里，她永远只看得到现象**——不告诉她"湿度 0.87"，只告诉她"潮气很重"。

```
【她那边此刻】
时节：萌芽期·抽芽月（第 13 年）
当前：入暗（这一段还剩约 3 小时）
光线：正在变暗，光快没了，太阳高度已落
林中状态：声音传得反常地远，方向感开始发飘
天气：潮气偏重；微风
```

## 为什么是确定性状态机，而不是让 LLM 模拟世界

[Stanford Generative Agents](https://github.com/joonspk-research/generative_agents) 用 LLM 反思流驱动一整个小镇——那是"一群 NPC 的社会实验"。这个仓库回答的是另一个问题：**怎么让"一个"AI 伴侣的世界便宜、稳定、随身携带**：

- **纯函数**：`状态(现在) = advance(存档, 经过的时长)`。没有常驻进程——伴侣程序启动时把世界一口气补算到此刻，关机一晚上的世界照样"走过了一夜"。
- **确定性重放**：所有随机量按绝对时间桶/潮序号播种（自实现 mulberry32），逐步走 200 小时与一次补算 200 小时**逐字节相同**；同一组验收向量（`tests/test_vectors.json`）在 Python 和 ArkTS 上跑出同一个世界——手机和电脑上，她的世界是同一个。
- **只给状态，不给台词**：引擎输出维度化字段（当前/光线/太阳高度/林中状态/天气/时节），**一个字的口语都不写**。她怎么形容斜光，是她自己长出来的——我们是在给她一个世界，不是给她写天气预报。
- **零依赖**：纯 Python 标准库（3.10+），无任何第三方包。

## 快速开始

```bash
git clone <本仓库>
cd zhixia-engine
python demo.py                # 看"她那边此刻"——首次运行会把世界从纪元推算到现在
python tests/test_engine.py   # 11 项测试，应全绿
```

仅此而已：**零第三方依赖**，任意 Python 3.10+。CI 会在 3.10/3.11/3.12 上自动跑同一组测试。

第一次运行会从纪元（`rules.json` 的 `start_epoch`）把世界推算到当前时刻并落盘到 `state/world_state.json`。之后每次运行，世界都会从上次停下的地方继续走。

---

**English TL;DR**: A deterministic world-state machine for AI companions — her world has its own calendar (a "day" averages ~36 real hours), seasons decoupled from ours, weather driven by slowly-varying state variables, and rare unexplained phenomena. Pure function + saved ledger: no daemon, cold-startable, bit-identical replay across devices (Python & ArkTS verified against the same test vectors). Zero dependencies; the companion only ever sees qualitative phenomena — never the rules, never numbers.

## 定制你自己的世界

世界的全部规律都在两份文件里，改它们就是改世界：

- **`world_rules.md`**：法典（人读版）——三条根本规律、光潮五阶、十二月、异象、地点；
- **`rules.json`**：机器参数（计算唯一依据）——时长范围、慢变量惯性、雾阈值、异象概率、**纪元**（把 `start_epoch` 改成你想让她"出生"的那天）。

⚠️ 两条铁律（也是这个设计的全部趣味所在）：
1. 改了影响世界走向的代码，必须重跑 `tests/make_vectors.py` 并人工过目新旧差异——世界改版要留痕；
2. 渲染层永远不出现数字、不出现替她写好的口语。

## 结构

```
world_rules.md        法典（人读，含注入纪律）
rules.json            参数（计算唯一依据）
engine/
  rng.py              StepRng：确定性随机源（mulberry32，字符串键 UTF-8 小端折叠）
  engine.py           WorldEngine：initial_state / advance_to / load_or_init_state
  render.py           render(state) → 维度化字段 + 注入文本
tests/
  test_engine.py      11 项测试（确定性重放 / 历法 / 静日 / 渲染 / 向量卷）
  make_vectors.py     生成验收向量卷
  test_vectors.json   固定起点 + 6/30/400/2000 小时的完整状态（跨端对答案用）
docs/01_世界引擎规格.md  四层架构 / 手机端移植三原则 / 红线
```

## 接到你的 AI 伴侣上

- 伴侣每轮对话前调用 `render(state, engine)["block"]`，把这几行拼进上下文——几十字，零 token 压力；
- 伴侣启动时 `load_or_init_state()` 补算并落盘——世界随她醒来；
- 多端同步：把 `{engine_version, state, rules}` 随快照下发，另一端按同一套 `advance()` 本地补算（对 `test_vectors.json` 验收），权威账本永远只在一端。

## License

MIT
