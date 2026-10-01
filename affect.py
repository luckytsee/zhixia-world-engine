"""关系状态（affect）：伴侣对"这个人"和"我们之间"的连续认识。

设计依据（设计定稿时）：

⭐⭐ 核心原则：**数字只产生隐性行为约束，绝不出现在她的话里。**
```
关系值（内部数字）
   ↓ 不给她看、也不让她说
   ↓ 只决定"她怎么说话"
行为倾向层 → LLM 自然表达
```
⚠️ **不要**写成 `comfort < 30 → 话变短` 这种规则——那是 RPG 好感度，
会让关系退化成游戏血条。设计口径：
> "应该让数字只产生几个**隐性的行为约束**"，再由 LLM 自然表达。

⭐⭐ **亲近 ≠ 舒适**（用户特别强调，别合成一维）

| 维度 | 初值 | 影响 |
|---|---|---|
| `closeness` 亲近度 | **20/100** | 主动透露 / 私人话题开放 / 亲密互动接受 |
| `comfort` 舒适度 | **50/100** | 回复长度倾向 / 配合意愿 / 距离感 |

**为什么初值不同**：脚本里写的是"刚认识、有一点熟悉感，但谈不上亲密"。
舒适中等（不别扭也不放松）、亲近低（还没积累）——**关系必须从零长出来**，
一上来写"关系很好"以后所有东西都是假的。

⭐⭐ **情感不是句子的属性，是"句子 × 关系 × 上下文"**（设计口径）

所以**不做情感词典**——同一句"你咋这么笨"：
- 陌生人说 → 冒犯
- 很熟的人说 → 亲昵式损人
- 吵架时说 → 真攻击

⇒ 本地检测**只产生"候选负面事件"，不直接扣分**（用户明确要求）：
```
命中高危表达 → potential_negative_affect（候选）
              ↓ 结合上下文
              ├─ 明显攻击 → 当场影响
              ├─ 疑似玩笑 → 轻微 / 暂不处理
              └─ 无法判断 → 等会话提取器（精细判断）
```
设计口径："**第一阶段就应该允许她误判**"——我们要观察的不是"她一次判对"，
而是"**她能不能通过连续互动逐渐学会：这个人说这种话到底什么意思**"。

⚠️ 后续（本次未做，见 SPEC）："他损我通常是在逗我"这类**关系认知**应当由
伴侣自己从长期互动中学出来（进 `world_notes`，`origin=zia_said`），
**不是系统硬编码**。那需要"事件计数与模式识别"，现在数据量不够。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# 维度初值（设计定稿时定）
INIT_CLOSENESS = 20.0
INIT_COMFORT = 50.0

# 行为倾向的**档位边界**（只用来挑措辞，不是"低于就惩罚"）
# ⚠️ 这些数字是**当前阶段的工程参数**，不是架构规则——等有真实互动再调。
_LOW = 30.0
_MID = 60.0

# ⚠️ 高危表达（本地、零成本）。**只产生候选，不直接扣分**——见模块头说明。
# 词表刻意短：宁漏不误杀（用户说"第一阶段就应该允许她误判"，
# 且他自己基本不会说这类话，冒烟靠造语料）。
_HIGH_RISK = (
    "去死", "死吧", "滚", "闭嘴", "傻逼", "傻B", "草泥马", "操你", "妈的",
    "有病", "废物", "垃圾", "烦死", "恨你", "讨厌你", "没用的东西",
)
# 疑似玩笑的信号（出现这些，候选降级为"暂不处理"——等会话提取器判）
_PLAYFUL_MARKERS = ("哈哈", "hhh", "233", "😂", "🤣", "笑死", "开玩笑", "逗你", "狗头")


@dataclass
class AffectState:
    """关系状态。数字内部用，**不给她看**。"""

    closeness: float = INIT_CLOSENESS
    comfort: float = INIT_COMFORT
    updated_at: float = 0.0
    # 最近发生的负面事件（给注入层用；只留最近几条，不长期存）
    recent_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "closeness": round(self.closeness, 1),
            "comfort": round(self.comfort, 1),
            "updated_at": self.updated_at,
            "recent_events": list(self.recent_events),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AffectState":
        return cls(
            closeness=float(data.get("closeness", INIT_CLOSENESS)),
            comfort=float(data.get("comfort", INIT_COMFORT)),
            updated_at=float(data.get("updated_at", 0.0)),
            recent_events=[str(x) for x in (data.get("recent_events") or [])][-5:],
        )


def detect_negative_candidate(text: str) -> str | None:
    """本地高危检测（零成本）。返回候选原因；没有则 None。

    ⚠️ **只产生候选，不在这里扣分**（设计定稿时要求）——
    因为"草泥马哈哈哈哈"和"草泥马，你他妈有病吧"不能一样处理。

    返回：
      · `"high_risk"`  → 疑似真攻击（没有玩笑信号）
      · `"playful?"`   → 命中高危词但带玩笑信号 → **暂不处理**，等会话提取器判
      · None           → 没命中
    """
    text = text or ""
    if not any(w in text for w in _HIGH_RISK):
        return None
    if any(m in text for m in _PLAYFUL_MARKERS):
        return "playful?"
    return "high_risk"


def _band(value: float) -> str:
    if value < _LOW:
        return "low"
    if value < _MID:
        return "mid"
    return "high"


def behavior_hints(state: AffectState) -> list[str]:
    """把两维数字翻成**行为倾向**（不是规则）。

    ⚠️ 这里产出的是"倾向"，注入层会把它包成自然语言给 LLM，
    **由它自己组织语气**——不是"低于 X 就执行 Y"。

    ⚠️⚠️ **2026-09-28 第二轮修（用户报"没感到她不开心"）**：
    原来低舒适度只说"不太舒服：话少一点，别那么配合，**也可以**拉开点距离"——
    三处太软：①"不太舒服"是状态不是情绪 ②"别那么配合"是行为指令
    ③"**也可以**"＝可选 ⇒ 模型默认不选。
    现在：**说清情绪 + 去掉"也可以" + 明确"别装没事"**，并且**指向情绪标签**
    （她的 `[sad]`/`[angry]` 原来跟关系层完全没连，所以 30 个场景几乎全打 `[neutral]`）。
    """
    hints: list[str] = []
    c, f = _band(state.closeness), _band(state.comfort)

    # 亲近度 → 愿意透露多少、接不接受亲密互动
    if c == "low":
        hints.append("你跟他还没那么熟：不太主动说自己的事，也不习惯太亲密的说法")
    elif c == "mid":
        hints.append("你跟他算熟了：愿意聊自己的事，但还不是什么都说得出口")
    else:
        hints.append("你跟他很熟了：愿意主动说自己的事，接得住亲密的话")

    # 舒适度 → **情绪 + 行为**（低档要"看得出来不开心"，不是"照常但话少"）
    if f == "low":
        hints.append("**你现在心里是不舒服的**——还记着他刚才那事，"
                     "有情绪，别装没事：话明显变少、语气淡、不想顺着他说")
        hints.append("这种时候你可以**只回一句短的**（\"……嗯。\"\"不想说。\"都行）——"
                     "⚠️ **但别一个字都不回**：什么都不说等于没反应，他只会以为你没听见")
        # ⚠️ 情绪标签必须点出来，否则她会一直打 [neutral]
        hints.append("⚠️ **这种时候你的情绪绝不是 [neutral]**——"
                     "多半是 [sad]（委屈、闷）或者 [angry]（不爽），按你自己的感觉挑")
    elif f == "mid":
        hints.append("你现在还算自在：正常说话就行")
    else:
        hints.append("你现在挺自在：愿意多聊几句，也可以主动接话")

    for ev in state.recent_events[-2:]:
        hints.append(f"（原因：{ev}）")
    return hints


class AffectStore:
    """关系状态的持久化（JSON 文件，单机单进程够用）。

    ⚠️ 为什么不用 SQLite：只有两个数字 + 几条最近事件，**没有查询需求**。
    用 JSON 是为了你**能直接打开看**（调试可观测性）。
    """

    MAX_EVENTS = 5

    def __init__(self, path: str | Path, *, log: object | None = None) -> None:
        self.path = Path(path)
        self._log = log
        self._lock = threading.RLock()
        self.state = self._load()

    # ---------- 读写 ----------

    def _load(self) -> AffectState:
        try:
            if self.path.exists():
                return AffectState.from_dict(
                    json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass                    # 读坏了就退回初值，不崩
        return AffectState()

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
            except OSError:
                pass                # 关系状态坏了也不该拦住她说话

    # ---------- 变更 ----------

    def apply_delta(self, *, closeness: float = 0.0, comfort: float = 0.0,
                    event: str = "", now: float | None = None) -> AffectState:
        """调整关系值（钳在 0~100）。`event` 非空则记一条最近事件。"""
        with self._lock:
            s = self.state
            s.closeness = max(0.0, min(100.0, s.closeness + closeness))
            s.comfort = max(0.0, min(100.0, s.comfort + comfort))
            s.updated_at = time.time() if now is None else float(now)
            if event:
                s.recent_events = (s.recent_events + [event])[-self.MAX_EVENTS:]
            self.save()
            return s

    # ---------- 注入 ----------

    def render(self) -> str:
        """关系状态的提示词块。**不提任何数字**（用户明确要求）。

        ⚠️ 结尾那句原来写"**让它们自然体现在你的语气里就够了**"——
        模型读成"知道了，照常答"（真机 30 例几乎全打 `[neutral]`）。
        现在改成**要求它表现出来**（设计定稿时："希望她看得出来不开心，
        也该有反应"）——但**仍然不许报数字/报状态**，只是不许"照常"。
        """
        hints = behavior_hints(self.state)
        if not hints:
            return ""
        lines = ["=== 你现在跟他的关系（**照这个状态说话**，但别解释、别报数字） ==="]
        lines.extend(f"· {h}" for h in hints)
        lines.append("（⚠️ **不许说出这些状态、不许提任何数字**——"
                     "但**也不许当成没这回事**：该淡就淡、该少话就少话、"
                     "该不高兴就让他看出来。）")
        return "\n".join(lines)
