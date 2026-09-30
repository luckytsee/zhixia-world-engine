# -*- coding: utf-8 -*-
"""礼物账本与候选池（异步双向）。

寄快递式语义：
- 一方把礼物"寄出"（进待处理池）即结束操作，**不需要对方在线**；
- 对方在下次处理时统一裁决（拆包裹/回应心意），回应文本由调用方提供的
  LLM 生成（见 opening.py），本模块只管账。
- 双向记账：寄出方/接收方/收下或拒绝，全部留痕——"谁送过什么、拒过什么"
  是关系历史的一部分。

文件形态：账本 ledger JSON + 候选池 pending JSON + 图片归档目录。
图片只保存副本路径（import_image 拷贝进归档目录，原文件不动）。
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

# 话题注入的泛触发词：提到任何一个就注入礼物块（不依赖具体礼物名命中）
GENERIC_TRIGGERS = ("礼物", "包裹", "寄", "收", "送")
_MIN_NAME_LEN = 2

STATUS_KEPT = "kept"          # 接收方收下
STATUS_SENT = "sent"          # （她的心意被）接收方收下
STATUS_DECLINED = "declined"  # 认真拒绝（落账）
# 注意：'discard'（整活打趣）不落账——由调用方在裁决后直接丢弃候选


def _new_id() -> str:
    return f"g{int(time.time() * 1000):x}-{uuid.uuid4().hex[:6]}"


class GiftStore:
    def __init__(self, ledger_path, pending_path,
                 images_dir=None, log: Callable | None = print) -> None:
        self.ledger_path = Path(ledger_path)
        self.pending_path = Path(pending_path)
        self.images_dir = Path(images_dir) if images_dir else self.ledger_path.parent / "gifts"
        self.log = log or (lambda *_: None)

    # ---------- 底层 ----------
    def _read(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            self.log(f"[礼物] {path.name} 读取失败（按空处理）: {exc}")
            return []

    def _write(self, path: Path, items: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    def ledger(self) -> list[dict]:
        return self._read(self.ledger_path)

    def pending(self) -> list[dict]:
        return self._read(self.pending_path)

    # ---------- 候选池 ----------
    def add_package(self, name: str, desc: str = "", media: str = "text",
                    image_path: str = "") -> dict:
        """寄给接收方的一件包裹，等待拆。media: text|image"""
        entry = {"id": _new_id(), "kind": "package", "name": name, "desc": desc,
                 "media": media, "image_path": image_path, "source": "user",
                 "proposed_at": time.time()}
        pool = self.pending()
        pool.append(entry)
        self._write(self.pending_path, pool)
        return entry

    def add_wish(self, name: str, note: str, source: str = "chat") -> dict:
        """一方想送出的一样心意，等待对方收/婉拒。source 自定义（如 chat/live）。"""
        entry = {"id": _new_id(), "kind": "wish", "name": name, "note": note,
                 "media": "text", "image_path": "", "source": source,
                 "proposed_at": time.time()}
        pool = self.pending()
        pool.append(entry)
        self._write(self.pending_path, pool)
        return entry

    def pop_pending(self, entry_id: str) -> dict | None:
        pool = self.pending()
        found = next((e for e in pool if e.get("id") == entry_id), None)
        if found:
            self._write(self.pending_path,
                        [e for e in pool if e.get("id") != entry_id])
        return found

    def import_image(self, src_path) -> str | None:
        """把礼物图片拷进归档目录（原文件不动）。失败返回 None。"""
        try:
            src = Path(src_path)
            if not src.is_file():
                return None
            self.images_dir.mkdir(parents=True, exist_ok=True)
            dst = self.images_dir / f"{int(time.time())}-{src.name}"
            shutil.copy2(src, dst)
            return str(dst)
        except Exception as exc:
            self.log(f"[礼物] 图片导入失败: {exc}")
            return None

    # ---------- 落账 ----------
    def record(self, direction: str, name: str, status: str, *,
               note: str = "", location: str = "", media: str = "text",
               image_path: str = "") -> dict:
        """direction: user_to_her | her_to_user；status: kept | sent | declined"""
        item = {"id": _new_id(), "direction": direction, "name": name,
                "status": status, "note": note, "location": location,
                "media": media, "image_path": image_path, "date": time.time()}
        ledger = self.ledger()
        ledger.append(item)
        self._write(self.ledger_path, ledger)
        return item

    # ---------- 注入 / 快照 ----------
    @staticmethod
    def _name_hits(name: str, text: str) -> bool:
        """话题命中：按 2-gram（中文按字切片），避免"全名不出现=全盲"。"""
        name = (name or "").strip()
        text = text or ""
        if not name or len(name) < _MIN_NAME_LEN:
            return False
        if name in text:
            return True
        return any(name[i:i + 2] in text for i in range(len(name) - 1))

    def render_context(self, user_text: str) -> str:
        """按话题命中注入礼物块（聊到才提，不背家当）+ 未拆包裹提示。空串=没得提。"""
        text = user_text or ""
        generic = any(t in text for t in GENERIC_TRIGGERS)
        lines: list[str] = []
        for item in self.ledger():
            name = str(item.get("name", ""))
            if not generic and not self._name_hits(name, text):
                continue
            d, s = item.get("direction"), item.get("status")
            if d == "user_to_her" and s == STATUS_KEPT:
                lines.append(f"- 对方送过你「{name}」"
                             + (f"，现在放在{item['location']}" if item.get("location") else "")
                             + (f"；{item['note']}" if item.get("note") else ""))
            elif d == "user_to_her" and s == STATUS_DECLINED:
                lines.append(f"- 对方寄过「{name}」，你没有收"
                             + (f"（{item['note']}）" if item.get("note") else ""))
            elif d == "her_to_user" and s == STATUS_SENT:
                lines.append(f"- 你送过对方「{name}」"
                             + (f"；{item['note']}" if item.get("note") else ""))
            elif d == "her_to_user" and s == STATUS_DECLINED:
                lines.append(f"- 你想送对方「{name}」，对方没要"
                             + (f"（{item['note']}）" if item.get("note") else ""))
        unopened = sum(1 for e in self.pending() if e.get("kind") == "package")
        if unopened:
            lines.append(f"- 对方寄来的包裹还有 {unopened} 件没拆")
        if not lines:
            return ""
        return ('=== 你们之间的礼物（自然地使用，禁止说"根据记录"） ===\n'
                + "\n".join(lines))

    def snapshot_payload(self) -> dict:
        """随快照下发给远端的摘要（不含图片路径——图片留在本机）。"""
        return {
            "items": [{"name": it.get("name", ""), "direction": it.get("direction"),
                       "status": it.get("status"), "location": it.get("location", ""),
                       "date": it.get("date")} for it in self.ledger()],
            "unopened_packages": sum(1 for e in self.pending() if e.get("kind") == "package"),
            "wishes_waiting": sum(1 for e in self.pending() if e.get("kind") == "wish"),
        }


def summarize_ledger(store: GiftStore, limit: int = 30) -> str:
    import time as _t
    lines = []
    for it in store.ledger()[-limit:]:
        d = _t.strftime("%m-%d", _t.localtime(float(it.get("date", 0))))
        arrow = "对方→你" if it.get("direction") == "user_to_her" else "你→对方"
        status = {"kept": "收下", "sent": "对方收下", "declined": "被拒"}.get(
            it.get("status", ""), it.get("status", ""))
        media = "🖼" if it.get("media") == "image" else ""
        lines.append(f"- ({d}) {arrow} {media}{it.get('name')} · {status}"
                     + (f" · 放在{it['location']}" if it.get("location") else "")
                     + (f" · {it['note']}" if it.get("note") else ""))
    return "\n".join(lines) if lines else "（账本还空着）"
