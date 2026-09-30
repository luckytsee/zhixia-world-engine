# phone/ —— 鸿蒙（HarmonyOS / ArkTS）移植件

本目录是把仓库核心的**世界引擎**搬到**鸿蒙手机**上的 ArkTS 实现，外加一套**唤醒式主动发起**。
它不是 Python 代码的封装，是**同一套算法的重写**——因此两边必须逐字节对答案（见下）。

> ⚠️ **环境要求：HarmonyOS + ArkTS + DevEco Studio**。
> 这是鸿蒙原生工程（`.ets` / `oh-package.json5` / `hvigorfile.ts`），
> **不是** Node/TypeScript 项目，也不能用普通 TS 工具链构建。
> 仓库其余部分是 Python（PC 侧），两边共享同一份世界参数与验收向量。

## 它做什么

1. **`entry/src/main/ets/world/` —— 确定性重放的 ArkTS 移植**
   光潮五阶 / 季节 / 天气 / 异象的状态机，与 Python 版**逐字段对答案**：
   同一份存档 + 同一时刻，任何设备算出同一个世界。
2. **`entry/src/main/ets/proactive/` —— 唤醒式主动发起**
   系统择机唤醒 App → 本地把世界补算到此刻 → **本地判断有没有由头**
   （全本地、零成本）→ 有才调 LLM → 本地通知。全程不需要服务器，
   App 被杀也能弹（提醒走系统级）。

## 快速开始

```bash
# 用 DevEco Studio 打开 phone/ 目录，或命令行：
hvigorw --mode module -p module=entry@default -p product=default assembleHap
```

装到设备后，首页两个按钮：

- **跑一次自检** → 显示 `4/4` 才算移植成功（比对下面的验收向量）
- **现在开口一次** → 跑一轮真实链路（世界补算 → 由头 → 节流 → LLM → 通知 → 落库）

## 与 PC 侧的一致性（这是移植的验收标准）

| 数据 | 位置 | 来源 |
|---|---|---|
| 世界参数 | `world/WeWorldDefaultRules.ets` 的 `ZX_RULES_JSON` | 由 PC 侧 `rules.json` 生成 |
| 验收向量 | `world/WeWorldVectors.ets` 的 `ZX_VECTORS_JSON` | 由 PC 侧 `tests/test_vectors.json` 生成（4 组：6/30/400/2000 小时） |

⚠️ **两份内嵌数据必须与 PC 侧保持同步**——参数一旦不一致，手机端算出的世界就和电脑端
对不上（快照里的 `world.rules` 缺失时，会回退到本地这份兜底规则）。
PC 侧改动后必须重新生成这两个文件。

**自检判据**：`initialState()` → `advanceTo()` 后的 state 与向量卷**逐字段相等**
（数值精确相等，浮点不动）、渲染文本**逐字符相等**。App 启动时打 hilog
`世界向量=4/4`，装机验证过滤 `WeWorld` 看这行。

## 与世界引擎的三条约定

1. **读模型补算**：本地 advance 只用于渲染和注入，**绝不写回快照、绝不回传**；
2. **版本门**：快照 `world.engine_version` 与本端不一致 → 不补算，直接用快照原状态
   （世界宁可停在出门那一刻，也不能和电脑端矛盾）；
3. **只给状态不给台词**：世界块是维度化字段（此刻/光线/天气/时节），不是写好的句子。

## 目录

```
entry/src/main/ets/
├── world/                       确定性世界状态机（纯逻辑，无副作用）
│   ├── WeWorldRng.ets            确定性随机源（mulberry32，与 Python 端逐位一致）
│   ├── WeWorldRules.ets          规则/状态类型与解析
│   ├── WeWorldEngine.ets         状态推进 advanceTo
│   ├── WeWorldRender.ets         状态 → 注入文本
│   ├── WeWorldDefaultRules.ets   内置兜底规则（生成物，勿手改）
│   └── WeWorldVectors.ets        验收向量自检（生成物）
├── proactive/                   唤醒式主动发起
│   ├── WeProactivity.ets         节流器（每日上限 / 最小间隔 / 由头去重）
│   ├── WeProactiveReasons.ets    由头判断（全本地）
│   ├── WeProactiveCycle.ets      主循环：补算 → 由头 → 节流 → LLM → 通知 → 落库
│   ├── WeProactiveCommon.ets     通知发布 + 消息落库
│   └── WeWorkSchedulerAbility.ets  WorkScheduler 扩展入口
└── ports/                       宿主 App 的对接层（凭据由宿主注入，不写死）
```

## 不包含什么

- **不含任何凭据**：`apiKey` / `baseUrl` 由宿主 App 注入；
- **不含聊天界面**：本目录只做世界推进与主动发起，对话 UI 属于宿主 App；
- **不含人格文本**：注入给模型的是世界状态，人格由宿主提供。
