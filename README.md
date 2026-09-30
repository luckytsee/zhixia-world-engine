# Zhixia World Engine

一个面向 AI 伴侣的**确定性世界状态机**和一个**不覆盖旧值的记忆库**。纯 Python 标准库，零第三方依赖，Python 3.10+。

这个仓库包含两个独立模块：

1. **engine** —— 世界状态机。为 AI 伴侣维护一个持续运转的虚构世界：有自己的历法、昼夜循环、天气和稀有事件。伴侣程序不在线时世界照常推进；程序重新启动时，把世界一次性推算到当前时刻。
2. **zmemory** —— 记忆库。四层结构（事实 / 世界笔记 / 经历 / 会话缓冲），特点是**冲突不会覆盖旧值**：新认知和旧认知并存，由调用方决定怎么呈现。

两个模块都只需要伴侣程序在每轮对话前拼接一段定性描述，例如：

```
时节：萌芽期·抽芽月（第 13 年）
当前：入暗（这一段还剩约 3 小时）
光线：正在变暗，太阳高度已落
林中状态：声音传得反常地远，方向感开始发飘
天气：潮气偏重；微风
```

## 验证

本仓库的验证分四层，`python verify.py` 一条命令可跑前两层，`--full` 加第三层，`--privacy` 单独跑第四层：

| 层 | 工具 | 验证什么 |
|---|---|---|
| 单元测试 | `tests/test_engine.py`、`tests/test_memory.py` | 历法换算、状态机行为、冲突并置、pinned 不可覆盖等具体行为 |
| 向量卷对答案 | `tests/make_vectors.py` + `tests/test_vectors.json` | 确定性：固定起点 + 6/30/400/2000 小时的完整世界状态。**任何机器重新生成必须与仓库内版本逐字节一致**——这是跨语言/跨设备移植（如 ArkTS）的验收标准 |
| 长周期 soak | `tests/test_longrun.py`（`--full`） | 连续推算 10 个现实年（87,600 小时）后状态不变量完好，且与一次跳算逐字节一致（任意时距无漂移）；zmemory 侧 5,000 条混合写入零丢失、零覆盖 |
| 隐私终检 | `verify.py --privacy` | 全仓扫描作者信息/本机路径/疑似密钥，保证发布内容可公开 |

CI（GitHub Actions）在 Python 3.10/3.11/3.12 上自动跑前两层和向量卷比对；soak 约 30 秒，发布前本地跑 `python verify.py --all`。

## zmemory.extract：对话 → 记忆的管道（"随手开口就被记住"）

上面是账本，这里才是记账员：一段对话原文进来，提取器判定哪些内容该进哪一层，然后落库。

```python
from zmemory import CompanionMemory, make_llm_judge
from zmemory.extract import extract

mem = CompanionMemory("companion.db")

turns = [
    {"role": "user", "content": "在忙啥？对了，我怕雾这事你记住啊。我最近都一点才睡。"},
    {"role": "assistant", "content": "记下了。"},
]
result = extract(mem, turns, llm=your_llm)
# → episode 落经历层；"作息"走认知比对进事实层；
#   "我怕雾"是她主动要求记的 → 落她的认知层（只追加）
```

内置的行为红线（源自长期实际使用的教训，全部写死在提取提示词里）：
- 气话、攻击、玩笑、一次性状态（"他今天很困"）**绝不进事实层**——那些留在对话里就够了；
- 经历摘要禁止钟点与相对时间词（提取发生在对话之后，模型不知道当时几点，写了就是猜）；
- 不同话题不拼成连续故事；
- 她重说自己的旧认知 → 按比对处理（换个说法 ≠ 新认知）；
- **LLM 失败或输出不可用 → 一个字都不写**（宁缺勿错，绝不把坏数据写进她的历史）。

改口的语义：她对某事的认知若住在认知层，改口后**两种认知并存**（只追加，不删除）；
事实层的冲突则由 `record_claim` 并置为 `key（后来）`。两层各管各的。

## gifts：异步双向礼物系统（寄快递式）

礼物的交换不要求双方同时在线，像寄快递：寄出即结束操作，接收方在下次处理时统一裁决。

- **账本**（`gifts/store.py`）：双向记账——谁寄了、谁收了、谁认真拒绝了，全部留痕；
  图片礼物以副本归档（原文件不动，账本只存本机路径，快照不下发图片）；
- **裁决**（`gifts/opening.py`）：接收方对包裹三选一——`keep` 收下（含安放位置，候选
  通常取自世界参数的 `locations`）/ `decline` 认真拒绝（落账，会被记得）/ `discard`
  整活打趣（不落账）。裁决文本由你提供的 LLM 生成（支持 vision 读图片礼物），
  合理性约束内置在提示词里：角色只能收下其世界观内存在的东西。LLM 失败时包裹
  留在候选池，绝不丢件；`on_settled` 回调可把结论写进你自己的记忆系统；
- **命令行**：`python -m gifts.cli --mock` 可直接体验完整流程（mock 模式不花钱）。

## 快速开始

```bash
git clone https://github.com/luckytsee/zhixia-world-engine.git
cd zhixia-world-engine
python demo.py                # 把世界推算到现在，打印当前世界状态
python tests/test_engine.py   # 引擎测试 12 项
python tests/test_memory.py   # 记忆库测试 10 项
```

首次运行会在 `state/world_state.json` 生成世界存档，之后每次运行都从上次停下的位置继续。

## engine 的工作方式

```
rules.json（参数） → WorldEngine（状态机） → world_state.json（存档） → render()（定性描述）
```

- **推进**：以 1 现实小时为一步。状态机内部维护光潮阶段、温度/潮气/风三个慢变量，以及季节与稀有事件（静日、反向风、月出）。
- **确定性**：所有随机量按绝对时间或潮序号播种（自实现 mulberry32，见 `engine/rng.py`）。逐步推算 N 小时和一次性推算 N 小时结果完全相同，因此多端同步不需要对账——各端用同一份参数独立推算即可。`tests/test_vectors.json` 保存了 6/30/400/2000 小时的标准答案，用于跨平台验收。
- **懒计算**：没有常驻进程。伴侣启动时调用 `load_or_init_state()` 读档、推算到当前时间、写回。
- **世界参数**：全部在 `rules.json`（起算日期 `start_epoch`、各阶段时长、季节权重、事件概率等），`world_rules.md` 是对应的可读文档。

## zmemory 的工作方式

```python
from zmemory import CompanionMemory, make_llm_judge

mem = CompanionMemory("companion.db")
mem.record_claim("作息", "通常12点睡", "new")
mem.record_claim("作息", "昨天3点才睡", "conflict")
# 结果：两条并存——"作息"=通常12点睡；"作息（后来）"=昨天3点才睡
print(mem.to_prompt())
```

- **四层**：facts（事实，键值）、world_notes（追加式文本，没有修改/删除接口）、episodes（经历摘要）、session（进程内会话缓冲，不落盘）。
- **冲突处理**：`record_claim(key, value, relation)` 是写入事实的唯一入口，`relation` 有三个值：
  - `new`：插入新条目（已存在则按 `confirm` 处理）；
  - `confirm`：更新值（`first_learned` 保留首次记录时间）；
  - `conflict`：旧条目不动，新值存为 `key（后来）`（再次冲突则 `key（后来2）`，以此类推）。
- **pinned 事实**：`pin_fact()` 标记后任何关系都不改写其值。
- **relation 的来源**：由 Judge 决定。`make_llm_judge(llm)` 把任意 `chat(messages)->str` 的客户端包成 Judge（内置判词提示词，输出 JSON）；LLM 不可用时 `exact_judge` 做纯文本匹配兜底（只有"新值是旧值子串"才判 confirm，其余判 conflict——包含新限定词的表述可能反转语义，无 LLM 时不冒险）。

## 设计上的取舍

- **定性输出**：`render()` 和 `to_prompt()` 输出"潮气偏重"而非"湿度 0.87"。数值只存在于存档和参数里，调用方拿到的是可以直接拼进提示词的句子。
- **覆盖在存储层被禁止**：冲突处理逻辑写在 `record_claim` 内部，Judge 判错最多多存一条记录，不会丢失旧值。
- **世界参数与代码分离**：调数值只改 `rules.json`。但改动会影响推算结果，改后需要重跑 `tests/make_vectors.py` 更新 `test_vectors.json`（这个文件是多端一致性的验收标准）。

## 目录结构

```
world_rules.md          世界设定文档（人读）
rules.json              世界参数（引擎计算依据）
engine/
  rng.py                确定性随机源（mulberry32）
  engine.py             WorldEngine：initial_state / advance_to / load_or_init_state
  render.py             状态 → 定性描述
zmemory/
  store.py              CompanionMemory：四层记忆库
  reconcile.py          Judge：认知比对（LLM 可插拔 / 文本匹配兜底）
tests/
  test_engine.py        引擎测试 12 项
  test_memory.py        记忆库测试 10 项
  test_gifts.py         礼物系统测试 8 项
  test_longrun.py       长周期 soak（10 年重放 + 5000 条写入，约 30 秒）
verify.py              一键验证入口（快速/完整/隐私三档）
  make_vectors.py       重新生成 test_vectors.json
  test_vectors.json     固定时刻的标准答案（跨端验收用）
docs/01_世界引擎规格.md   架构与多端接入说明
demo.py                 演示脚本
.github/workflows/      CI：3.10 / 3.11 / 3.12 自动跑测试
```

## assets/example：示例立绘

一套可直接使用的桌面伴侣立绘（知夏形象，作者授权随仓库分发）：

| 文件 | 用途 |
|---|---|
| `happy.png` / `angry.png` / `neutral.png` | 情绪立绘（2048×2048 RGBA），按情绪标签映射显示 |
| `character.png` | 512×512 占位头像 |
| `zhixia.ico` | 应用图标 |

接入约定：上层程序解析 AI 回复中的情绪标签（happy/angry/neutral/…），按标签切换立绘；
未识别的情绪回退 `neutral.png`。把 `assets/example/` 里的文件配进你的桌面程序即可开箱使用。

## License

MIT
