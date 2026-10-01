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
from memory_writer import _fact_has_time_hint, _is_self_statement  # noqa: E402


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


class TestConflictTrigger(unittest.TestCase):
    """2026-10-01 修复：并置不再依赖 action 字段（外部实测暴露的漏口）。"""

    def _run(self, reconciliation: dict):
        tmp = tempfile.mkdtemp()
        store = SQLiteMemoryStore(os.path.join(tmp, "m.db"))
        wn = WorldNotesStore(os.path.join(tmp, "w.db"))
        writer = MemoryWriter(llm=None, store=store, log=lambda *_: None, world_notes=wn)
        store.upsert_fact(key="喜欢的主食", value="不太喜欢吃面",
                          confidence=0.9, evidence=[])
        writer.llm = type("L", (), {"chat": lambda s, m: json.dumps({
            "episode": {"summary": "聊到吃饭", "importance": 0.2},
            "facts": [{"key": "喜欢的主食", "value": "挺喜欢吃面", "confidence": 0.9}],
            "reconciliations": [reconciliation]}, ensure_ascii=False)})()
        writer.write_session([{"role": "user", "content": "我挺喜欢吃面的。"}])
        return {f.key: f.value for f in store.list_facts()}

    def test_conflict_without_action_still_coexists(self):
        """判了 conflict 但没填 action → 仍必须并置（原来会漏、旧值被覆盖）。"""
        got = self._run({"relation": "conflict", "target": "user_fact"})
        self.assertEqual(got["喜欢的主食"], "不太喜欢吃面")
        self.assertEqual(got["喜欢的主食（后来）"], "挺喜欢吃面")

    def test_conflict_with_rewritten_information_still_coexists(self):
        """new_information 是改写而非原文 → 仍必须并置。"""
        got = self._run({"relation": "conflict", "target": "user_fact",
                         "new_information": "喜欢吃面食"})
        self.assertIn("喜欢的主食（后来）", got)

    def test_confirm_still_updates_normally(self):
        """非冲突仍走正常更新（别把并置用过头）。"""
        got = self._run({"relation": "confirm", "target": "user_fact"})
        self.assertEqual(got["喜欢的主食"], "挺喜欢吃面")
        self.assertNotIn("喜欢的主食（后来）", got)


class TestFactTimeHint(unittest.TestCase):
    """事实层时间词：只标注不改写。"""

    def test_detects_time_words(self):
        self.assertTrue(_fact_has_time_hint("下午的会开了两个半小时（两点到四点半）"))
        self.assertTrue(_fact_has_time_hint("昨天买了个键盘"))
        self.assertTrue(_fact_has_time_hint("他平时晚上十点打游戏"))   # 提示，但不改写
        self.assertFalse(_fact_has_time_hint("他喜欢喝咖啡"))
        self.assertFalse(_fact_has_time_hint("开了两个半小时的会"))     # 时长不是时间点


class TestFactAttribution(unittest.TestCase):
    """归属守卫：她自己的事不许进"关于对方的事实"。

    实测背景（2026-10-01）：用户说"我怕雾这事你记一下"、她回"嗯？好"，
    提取器把她的话记成 `怕雾 = 用户怕雾`——**她的恐惧进了他的档案**，
    5 次复现 4 次。提示词改了不够，加了确定性拦阻。
    """

    def test_self_statements_blocked(self):
        self.assertTrue(_is_self_statement("怕雾", "用户怕雾"))
        self.assertTrue(_is_self_statement("怕雾", "怕雾"))
        self.assertTrue(_is_self_statement("住处", "我住树根底下"))

    def test_facts_about_him_pass(self):
        self.assertFalse(_is_self_statement("作息", "他晚上十点打游戏"))
        self.assertFalse(_is_self_statement("饮食", "他不太爱吃面"))
        self.assertFalse(_is_self_statement("妹妹", "他有个九岁的妹妹"))

    def test_blocked_in_pipeline(self):
        """走完整管道：她的自述不会落进事实层。"""
        tmp = tempfile.mkdtemp()
        store = SQLiteMemoryStore(os.path.join(tmp, "m.db"))
        wn = WorldNotesStore(os.path.join(tmp, "w.db"))
        writer = MemoryWriter(llm=None, store=store, log=lambda *_: None, world_notes=wn)
        writer.llm = type("L", (), {"chat": lambda s, m: json.dumps({
            "episode": {"summary": "聊到害怕的事", "importance": 0.3},
            "facts": [{"key": "怕雾", "value": "用户怕雾", "confidence": 0.9},
                      {"key": "作息", "value": "他晚上十点打游戏", "confidence": 0.9}],
            "reconciliations": []}, ensure_ascii=False)})()
        writer.write_session([{"role": "user", "content": "我怕雾这事你记一下"},
                              {"role": "assistant", "content": "嗯？好。"}])
        keys = {f.key for f in store.list_facts()}
        self.assertNotIn("怕雾", keys)        # 拦下
        self.assertIn("作息", keys)           # 关于他的照常写


if __name__ == "__main__":
    unittest.main(verbosity=2)
