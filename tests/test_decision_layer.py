# -*- coding: utf-8 -*-
"""决策层关键行为测试：世界笔记 delete 通道 / 外观过滤 / writer 冲突并置与红线。

运行（仓库根目录）：python -m pytest tests/test_decision_layer.py -q
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_notes import WorldNotesStore, looks_like_appearance  # noqa: E402
from memory import SQLiteMemoryStore  # noqa: E402
from memory_writer import MemoryWriter  # noqa: E402
from gifts import GiftStore  # noqa: E402


def make_world_notes(tmp: str) -> WorldNotesStore:
    return WorldNotesStore(os.path.join(tmp, "world.db"))


class TestWorldNotes(unittest.TestCase):
    def test_delete_channel_exists(self):
        """事后修正通道：删除接口存在且可用（真实决策层与 append-only 的区别）。"""
        tmp = tempfile.mkdtemp()
        wn = make_world_notes(tmp)
        note = wn.add("我怕雾", source_turn_id="sess-3")
        self.assertEqual(wn.count(), 1)
        self.assertTrue(wn.delete(note.id))
        self.assertEqual(wn.count(), 0)

    def test_search_returns_all_filtered(self):
        """全量注入（上限内）；外观/能力类被确定性过滤。"""
        tmp = tempfile.mkdtemp()
        wn = make_world_notes(tmp)
        wn.add("我怕雾——雾一起来几棵树外就什么都看不清")
        wn.add("我喜欢靠在树上听风，风穿过叶子的声音")       # 曾被子串匹配误杀
        wn.add("林子里还有别的精灵")                          # 同上
        wn.add("我有浅绿色长发")                              # 纯外形 → 拦
        got = [n.text for n in wn.search("你怕什么")]
        self.assertIn("我怕雾——雾一起来几棵树外就什么都看不清", got)
        self.assertIn("我喜欢靠在树上听风，风穿过叶子的声音", got)
        self.assertIn("林子里还有别的精灵", got)
        self.assertNotIn("我有浅绿色长发", got)
        self.assertTrue(looks_like_appearance("我能认出他"))  # 能力类


class TestWriter(unittest.TestCase):
    def _make(self, tmp: str):
        store = SQLiteMemoryStore(os.path.join(tmp, "memory.db"))
        wn = make_world_notes(tmp)
        gifts = GiftStore(os.path.join(tmp, "gifts.json"),
                          os.path.join(tmp, "pending.json"))
        writer = MemoryWriter(llm=None, store=store, log=lambda *_: None,
                              world_notes=wn, gift_store=gifts)
        return writer, store, wn, gifts

    def test_conflict_keeps_both(self):
        """认知比对：conflict → 旧值不动，新认知存为「（后来）」。"""
        tmp = tempfile.mkdtemp()
        writer, store, wn, gifts = self._make(tmp)
        store.upsert_fact(key="饮食", value="不太爱吃面", confidence=0.9, evidence=[])
        writer.llm = type("L", (), {"chat": lambda s, m: json.dumps({
            "episode": {"summary": "聊到吃饭", "importance": 0.2},
            "facts": [{"key": "饮食", "value": "爱吃面", "confidence": 0.9}],
            "affect": {"comfort": 0, "closeness": 0, "note": ""},
            "reconciliations": [{"relation": "conflict", "target": "user_fact",
                                 "existing": "不太爱吃面", "new_information": "爱吃面",
                                 "action": "keep_both", "note": "口味表述不同"}],
            "gifts": []}, ensure_ascii=False)})()
        writer.write_session([
            {"role": "user", "content": "我其实爱吃面。"},
            {"role": "assistant", "content": "咦，我记得你说过不太爱吃面？"},
        ])
        values = {f.key: f.value for f in store.list_facts()}
        self.assertEqual(values["饮食"], "不太爱吃面")          # 旧认知不动
        self.assertEqual(values["饮食（后来）"], "爱吃面")       # 新认知并置

    def test_gifts_to_pending_and_gaswords_red_line(self):
        """她的心意进候选池；气话/状态不给 facts 就一个都不写。"""
        tmp = tempfile.mkdtemp()
        writer, store, wn, gifts = self._make(tmp)
        writer.llm = type("L", (), {"chat": lambda s, m: json.dumps({
            "episode": {"summary": "他情绪上来骂了一句，后来道了歉", "importance": 0.4},
            "facts": [],
            "affect": {"comfort": -8, "closeness": 0, "note": "他刚才说了句重话"},
            "reconciliations": [],
            "gifts": [{"name": "溪边的石头", "note": "给你留着"}]}, ensure_ascii=False)})()
        writer.write_session([
            {"role": "user", "content": "你该去死。我今天特别困。对了，我捡了块石头给你留着。"},
            {"role": "assistant", "content": "……石头我收下。但刚才那句让我难受。"},
        ])
        self.assertEqual(store.list_facts(), [])               # 红线：一个事实都不写
        pool = gifts.pending()
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["name"], "溪边的石头")


if __name__ == "__main__":
    unittest.main(verbosity=2)
