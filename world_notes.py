"""世界笔记：伴侣自己决定记住的事（`[记住:...]`）。

定位与设计依据见 `docs/03_世界笔记规格.md`。要点：

- **不是 `facts` 的扩展，是并列的新链路。** `facts` 的 `key` 是主键 ⇒ 只存当前快照、
  存不下时间线；而且它的提取提示词写死"只记关于用户的"⇒ 她的自述会被契约主动排除。
- **决定权在她**：她主动写 `[记住:...]` 才记，系统不做判断、不筛选、不自动捕获。
- **`[记住:...]` 是唯一入口**：她用自然语言说"我记一下"不算（否则又变成系统猜她意图）。
- **可以改主意，但不能假装自己没说过**（SPEC 3.9）。

⚠️ 本模块**独立库**（`data/zia_world.db`），与 `memory.db` 物理隔离——
世界链路坏掉时，伴侣程序照常跑。
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

# 来源值域（SPEC 3.7）。现在只产生前两个，后两个是**契约的一部分**——
# 将来加值时不用到处改判断。
ORIGIN_ZIA_SAID = "zia_said"        # 她自己说/决定的
ORIGIN_OWNER_TOLD = "owner_told"    # 你告诉她的（含纠正）
ORIGIN_FROM_CONTACT = "from_contact"  # ⏸ 联系人说的（暂不产生）
ORIGIN_WORLD_MADE = "world_made"      # ⏸ 她的世界动作（暂不产生）

_SCHEMA = """
CREATE TABLE IF NOT EXISTS world_notes (
    id             TEXT PRIMARY KEY,
    ts             REAL NOT NULL,
    text           TEXT NOT NULL,
    origin         TEXT NOT NULL,
    source_turn_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_world_notes_ts ON world_notes(ts);
"""

# ⚠️ 注入侧过滤（SPEC 3.6）：挡掉"明显是外观/能力"的条目。
# 加这道闸的理由：**LLM 不一定会听话，但过滤是确定性的**——
# 她的自我信息源目前只有 persona 里那几句话，很容易把 persona 抄回去，
# 记出「我有浅绿色长发」这种东西。人格里也写了"什么不要记"，两条是双保险。
# ⚠️⚠️ 这道过滤的**判据在 2026-09-28 改过**（原来会误杀，是个真 bug）：
#
# 原来的写法是**子串包含**（`any(h in text for h in HINTS)`），结果：
#   · "我喜欢靠在树上听风，风**穿**过叶子的声音" → 被 `穿` 误杀
#   · "林子里还有别的**精灵**"                → 被 `精灵` 误杀
# 8 条真实数据里误杀 2 条（25%）——**过滤器比它要防的问题更伤人**。
#
# 现在改成**"整条就是在讲外形/能力"才拦**：必须出现**外观专属词**
# （发色/眼眸/呆毛这类日常聊不到的词），**不能靠"穿""精灵"这种日常字眼**。
# 判据：一条笔记如果同时含"外观词"且不含任何"世界/生活词"，才拦。
_WARDROBE_WORDS = (
    "长发", "短发", "发色", "呆毛", "刘海", "眼眸", "立绘", "外貌", "长相",
    "高跟", "裙子", "束腰", "飘带", "精灵耳", "耳朵", "尖耳", "绿发", "浅绿",
)
# 这些词一出现，说明这条**在讲她的世界/生活**，不是单纯描述外形 → 放行
_LIFE_WORDS = (
    "我住", "林子", "树", "风", "雾", "石", "花", "吃", "喝", "出门", "平时",
    "别的", "其他", "我这儿", "我这里", "喜欢", "怕", "习惯", "出门", "世界",
    "时候", "地方", "东西", "里", "边",
)
_ABILITY_HINTS = ("我能认出", "我认得", "一眼认出", "我会认出")


def looks_like_appearance(text: str) -> bool:
    """像"单纯在描述自己外形/能力"吗（注入侧过滤用）。

    ⚠️ 判据（2026-09-28 收紧）：**必须出现外观专属词，且不含任何世界/生活词**。
    理由见 `_WARDROBE_WORDS` 上面的说明——旧的子串匹配会误杀
    "风穿过叶子""别的精灵"这类完全正常的笔记。
    """
    if any(h in text for h in _ABILITY_HINTS):
        return True
    if not any(w in text for w in _WARDROBE_WORDS):
        return False
    # 含外观词，但也在讲她的世界/生活 → 不是纯外形描述，放行
    return not any(w in text for w in _LIFE_WORDS)



@dataclass
class WorldNote:
    id: str
    ts: float
    text: str
    origin: str
    source_turn_id: str | None

    @property
    def when(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.ts))


def _row_to_note(row: sqlite3.Row) -> WorldNote:
    return WorldNote(
        id=row["id"],
        ts=float(row["ts"]),
        text=row["text"],
        origin=row["origin"],
        source_turn_id=row["source_turn_id"],
    )


class WorldNotesStore:
    """世界笔记的 SQLite 存储。同步 API，线程安全（内部锁）。

    只有四列（SPEC 3.3 的最小集）：
    `key/kind/valid_from/valid_to/superseded_by` **预留不建**——
    它们是"同一件事随时间变化"的解法，但她会不会记这种会变的东西现在完全不知道。
    `facts` 表就是"存储设计早于真实需求"的产物，不踩第二次。
    """

    def __init__(self, db_path: str | Path = "data/zia_world.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------- 写 ----------

    def add(
        self,
        text: str,
        *,
        origin: str = ORIGIN_ZIA_SAID,
        source_turn_id: str | None = None,
        now: float | None = None,
    ) -> WorldNote | None:
        """记一条。`text` 为空则返回 None（不写空条目）。"""
        text = (text or "").strip()
        if not text:
            return None
        ts = time.time() if now is None else float(now)
        note = WorldNote(
            id=uuid.uuid4().hex,
            ts=ts,
            text=text,
            origin=origin,
            source_turn_id=source_turn_id,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO world_notes (id, ts, text, origin, source_turn_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (note.id, note.ts, note.text, note.origin, note.source_turn_id),
            )
            self._conn.commit()
        return note

    def delete(self, note_id: str) -> bool:
        """删一条。返回是否真的删掉了。

        ⚠️ **删了笔记 ≠ 她忘了**（SPEC 5.4）：她的对话历史里还留着自己说过的话，
        下次可能又记一遍。这不是 bug，是设计的事实。
        """
        with self._lock:
            cur = self._conn.execute("DELETE FROM world_notes WHERE id = ?", (note_id,))
            self._conn.commit()
        return cur.rowcount > 0

    # ---------- 读 ----------

    def all(self) -> list[WorldNote]:
        """全部笔记（新→旧）。事后修正通道用。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM world_notes ORDER BY ts DESC"
            ).fetchall()
        return [_row_to_note(r) for r in rows]

    def get(self, note_id: str) -> WorldNote | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM world_notes WHERE id = ?", (note_id,)
            ).fetchone()
        return _row_to_note(row) if row is not None else None

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM world_notes").fetchone()[0])

    def search(self, query_text: str, *, limit: int = 8) -> list[WorldNote]:
        """要注入的几条世界笔记。

        ⚠️⚠️ **2026-09-28 晚改：不再按关键词筛，改为"全量注入（受 limit 上限）"**。
        原因（真机事故，有 hilog 证据）：
        ```
        手机问"你怕什么"→ 笔记"我怕雾——雾一起来，几棵树之外就什么都看不清"
        2-gram 命中靠的是"什么"这两个字（"什么都看不清"里那个）。
        换成"你怕啥""你怕不怕""你害怕吗""你家在哪里来着"⇒ **零命中 ⇒ 整块不注入**
        ⇒ 她只能现编（真机：连编三次不同的答案，"怕火""突然的动静"…）
        ```
        ⇒ **"按话题检索"这套机制本身是错的**：她"是谁、住哪、怕什么"这类认知
        **不该按话题筛**——那是她的自我，不是资料库条目。人会忘记自己怕什么吗？

        **现在**：全量给她（外观/能力类仍过滤，见 SPEC 3.6），受 `limit` 上限约束。
        ⚠️ **`limit` 仍是"上限"不是目标**，只是现在库小（8 条 ≈ 400 字）时
        上限不构成实际限制。等攒到几十条、需要区分"核心 vs 细节"时再谈分类
        （用户 2026-09-28 认可："现在先全量，数据量上来再说"）。

        ⚠️ `query_text` 参数**保留但不再用于筛选**——留给以后换检索策略
        （embedding / 语义相关 / 最近激活）时用，外面的 `agent.py` 不用改。
        """
        notes = [n for n in self.all() if not looks_like_appearance(n.text)]
        return notes[:limit]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
