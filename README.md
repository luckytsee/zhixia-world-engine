# Zhixia World Engine

一个长期运行的 AI 伴侣的**记忆与关系系统**（决策层），外加配套的确定性世界引擎、礼物交换和
桌面 UI 组件。纯 Python 标准库，零第三方依赖，Python 3.10+。

## 先说什么最值得看：决策层

**记忆与关系系统（`memory/` + `world_notes.py` + `affect.py` + `memory_writer.py`）是这个仓库的核心**，
它解决长期伴侣最难的一件事：**她对你的认识是一条连续的、不会被覆盖的历史**。

- **四层记忆**：事实（键值 + 置信度 + 钉死）/ 世界笔记（她自己的认知）/ 经历（可按语义检索，
  带时间衰减）/ 会话（易失——"进入对话 ≠ 进入记忆"）；
- **认知比对，冲突不覆盖**：你说的话和她已知的不一致时，旧认知原样保留、新认知并置
  （`饮食` 与 `饮食（后来）` 并存）——"通常十二点睡"和"昨天三点睡"可以同时成立。
  这是把"她的记忆"当历史，而不是当一张随时被 UPDATE 的表；
- **关系状态**（`affect.py`）：亲近/舒适两维，**数字只产生隐性行为约束，绝不出现在她的话里**；
- **提取管道**（`memory_writer.py`）：会话结束时一次提取，产出经历 + 事实（走认知比对）+
  关系增量 + 礼物候选；**气话、攻击、玩笑绝不进事实层**；摘要禁止钟点与相对时间词
  （提取发生在对话之后，模型并不知道当时几点，写了就是猜）；
- **她自己决定记什么**（`world_notes.py`）：她主动说"记住"的才进这层；含**事后修正删除通道**；
  注入侧有确定性的外观过滤。

## 配套的三块

1. **engine —— 世界引擎**。给伴侣一个持续运转的虚构世界：自己的历法、昼夜（"光潮"五阶）、天气、
   稀有事件。**你不在时世界照常推进**，下次启动一次性补算到此刻——不冻结、不重置。渲染给模型的
   是定性描述（"潮气偏重；微风"），数字只活在存档里。
2. **gifts —— 礼物交换**。异步双向、像寄快递：寄出即结束操作，对方下次处理时统一裁决。
3. **companion_ui —— 桌面 UI 组件**。自绘零素材（圆盘/气泡/胶囊按钮/输入框/面板骨架），
   外加余额查询、截屏与摄像头感知、本地人脸闸门。

世界引擎每轮注入给模型的是这样一段定性描述：

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
| 长周期 soak | `tests/test_longrun.py`（`--full`） | 连续推算 10 个现实年（87,600 小时）后状态不变量完好，且与一次跳算逐字节一致（任意时距无漂移）；记忆层 5,000 条混合写入零丢失、零覆盖 |
| 隐私终检 | `verify.py --privacy` | 全仓扫描作者信息/本机路径/疑似密钥，保证发布内容可公开 |

CI（GitHub Actions）在 Python 3.10/3.11/3.12 上自动跑前两层和向量卷比对；soak 约 30 秒，发布前本地跑 `python verify.py --all`。

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

## 决策层：记忆与关系（1:1 移植自实际运行的系统）

这部分不是"示例实现"，而是**正在跑的那套逻辑的原样移植**（个人化措辞已去除，行为零改动）：

| 模块 | 承担什么 | 三处关键设计 |
|---|---|---|
| `memory/` | 四层记忆：facts（键值+置信度+钉死）/ episodes（经历+向量检索+时间衰减）/ 检索打分 / 容量淘汰 | 检索是"分词+余弦+新近度+关键词+情境"的混合打分；钉死条目豁免淘汰 |
| `world_notes.py` | 她的自我认知（她主动说"记住"的） | **含事后修正删除通道**；注入侧有确定性外观过滤（判据踩过"误杀 25%"的坑后收紧）；全量注入，上限只是上限 |
| `affect.py` | 关系状态（亲近/舒适两维） | **数字只产生隐性行为约束，绝不出现在她的话里**；高危词触发候选，玩笑降级 |
| `memory_writer.py` | 对话 → 记忆的管道（会话结束时一次提取） | 认知比对：conflict **不覆盖**旧值（并置为 `key（后来）`）；气话/攻击/玩笑**绝不进事实**；摘要禁钟点与相对时间词 |

```python
from memory import SQLiteMemoryStore          # 四层记忆
from world_notes import WorldNotesStore       # 她的自我认知
from affect import AffectStore                # 关系状态
from memory_writer import MemoryWriter        # 对话 → 记忆的提取管道

mem = SQLiteMemoryStore("data/memory.db")
wn = WorldNotesStore("data/world.db")
writer = MemoryWriter(llm=your_llm, store=mem, world_notes=wn)
writer.write_session(turns)     # 一次提取：经历 + 事实（走比对）+ 关系 + 礼物候选
```

## 快速开始

```bash
git clone https://github.com/luckytsee/zhixia-world-engine.git
cd zhixia-world-engine
python demo.py                # 把世界推算到现在，打印当前世界状态
python tests/test_engine.py   # 引擎测试 12 项
python -m pytest tests/test_decision_layer.py -q   # 决策层 4 项
python -m pytest memory/tests/ -q                  # 记忆库自带 26 项
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

## 设计上的取舍

- **定性输出**：`render()` 和 `to_prompt()` 输出"潮气偏重"而非"湿度 0.87"。数值只存在于存档和参数里，调用方拿到的是可以直接拼进提示词的句子。
- **覆盖发生在哪一层要说清**：冲突并置的逻辑在**写入管道**（`memory_writer`）里——
  比对判定为冲突时，旧的照旧、新的另存为 `key（后来）`；即便判定出错，也最多多存一条。
  ⚠️ 存储层的 `upsert_fact` 本身照写不拒（它保证的是不丢数据）；"钉死"事实的保护同样在
  写入管道层。世界笔记那条链路才是**只追加**（删除接口只用于事后修正）。
- **世界参数与代码分离**：调数值只改 `rules.json`。但改动会影响推算结果，改后需要重跑 `tests/make_vectors.py` 更新 `test_vectors.json`（这个文件是多端一致性的验收标准）。

## 目录结构

```
world_rules.md          世界设定文档（人读）
rules.json              世界参数（引擎计算依据）
engine/
  rng.py                确定性随机源（mulberry32）
  engine.py             WorldEngine：initial_state / advance_to / load_or_init_state
  render.py             状态 → 定性描述
memory/                四层记忆库（store/retrieval/decay/embedding + 自带 26 项测试）
world_notes.py         她的自我认知（含修正删除通道 + 注入侧外观过滤）
affect.py              关系状态（数字只产生隐性行为约束）
memory_writer.py       对话提取管道（认知比对 / 红线 / 礼物候选）
tests/
  test_engine.py        引擎测试 12 项
  test_decision_layer.py 决策层测试（删除通道 / 外观过滤 / 冲突并置 / 气话红线）4 项
  test_panel_gui.py     面板图像路径测试（真实加载立绘 / 兜底 / 缩放重贴）3 项
  test_gifts.py         礼物系统测试 8 项
  test_longrun.py       长周期 soak（10 年重放 + 5000 条写入，约 30 秒）
verify.py              一键验证入口（快速/完整/隐私三档）
  make_vectors.py       重新生成 test_vectors.json
  test_vectors.json     固定时刻的标准答案（跨端验收用）
docs/01_世界引擎规格.md   架构与多端接入说明
demo.py                 演示脚本
.github/workflows/      CI：3.10 / 3.11 / 3.12 自动跑测试
```

## companion_ui：桌面伴侣 UI 组件（tkinter，自绘零素材）

从知夏桌面端提炼出的可复用组件——**不依赖任何图片素材**，clone 即可拼出一个能跑的桌面面板：

- `StatusDial` 状态圆盘：圆环 + 大数字 + 阈值变红 + 定时刷新（源自余额圆盘；
  数值未知显示 "—" 而不是编数字）；
- `ChatBubble` 对话气泡：定宽、高度随内容自适应、超长滚轮滚动；
- `PillButton` 胶囊按钮：自绘圆角、悬停变色、点击回调；
- `InputBox` 输入框：占位符提示、回车回调、发送后自动清空。

```bash
python -m companion_ui   # 一个会动的迷你面板：圆盘 + 气泡 + 按钮 + 输入框
```

## companion_ui 的三条功能管道

- **余额查询**（`balance.py`）：DeepSeek `/user/balance`（OpenAI 兼容系通用），纯标准库
  urllib、零依赖。解析是纯函数离线可测；**任何异常都不外抛**——余额只是界面上的数字，
  断网不该让伴侣崩掉。配 `StatusDial` 就是截图右下角那个"剩余金额"盘。
- **感知管道**（`perception.py`）：截屏（可涂黑伴侣窗口自身，避免它入镜）→ 缩放 →
  JPEG；摄像头一帧；以及**本地人脸闸门**——YuNet 检出 + SFace 特征 + 与基准照算余弦，
  过阈值才认（"宁可漏认不可错认"，分数可标定）。模型 onnx 与基准照全部由调用方传入，
  纯本地不联网；opencv 是可选依赖，没装只影响感知不影响其他组件。
- **面板骨架**（`panel.py`）：无边框置顶窗口 + 按情绪换立绘 + 任意处拖动 +
  Ctrl+滚轮档位缩放（右下角锚点不动）+ 位置记忆 + 点击热区（主项目的"拍照/看屏幕"
  按钮就是底图上的热区）。素材解耦：传什么图显示什么图，无图自绘兜底。

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
