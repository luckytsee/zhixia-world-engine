# -*- coding: utf-8 -*-
"""zmemory 测试：不可覆盖强制 / 冲突并置 / pinned 豁免 / 世界笔记只追加 / session 易失。

运行（仓库根目录）：python tests/test_memory.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zmemory import (CompanionMemory, exact_judge, make_llm_judge,  # noqa: E402
                     ORIGIN_ZIA_SAID)


def fresh(tmp: str) -> CompanionMemory:
    return CompanionMemory(os.path.join(tmp, "companion.db"), log=lambda *_: None)


class TestImmutability(unittest.TestCase):
    """⭐ 本模块的灵魂：她对你的认识是一部历史。"""

    def test_conflict_never_overwrites(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.record_claim("作息", "通常12点睡", "new")
        r = m.record_claim("作息", "昨天3点才睡", "conflict")
        self.assertEqual(r["action"], "kept_both")
        values = {f["key"]: f["value"] for f in m.all_facts()}
        self.assertEqual(values["作息"], "通常12点睡")            # 旧值原样
        self.assertEqual(values["作息（后来）"], "昨天3点才睡")    # 新认知并置

    def test_conflict_storm_appends_numbered(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.record_claim("口味", "爱吃面", "new")
        m.record_claim("口味", "不太爱吃面", "conflict")
        m.record_claim("口味", "又爱吃面了", "conflict")
        keys = {f["key"] for f in m.all_facts()}
        self.assertEqual(keys, {"口味", "口味（后来）", "口味（后来2）"})

    def test_pinned_untouched_even_on_confirm(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.record_claim("生日", "4月5日", "new")
        m.pin_fact("生日")
        r = m.record_claim("生日", "4月6日", "confirm")
        self.assertEqual(r["action"], "pinned_untouched")
        self.assertEqual(m.get_fact("生日")["value"], "4月5日")

    def test_judge_saying_new_but_exists_is_safe(self):
        """Judge 判错（new 但已存在）→ 按 confirm 处理，不至于误覆盖语义。"""
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.record_claim("学校", "UESTC", "new")
        r = m.record_claim("学校", "电子科技大学", "new")
        self.assertEqual(r["action"], "updated")
        self.assertEqual(m.get_fact("学校")["value"], "电子科技大学")


class TestJudges(unittest.TestCase):
    def test_exact_judge_paths(self):
        self.assertEqual(exact_judge("k", "v", None).relation, "new")
        self.assertEqual(exact_judge("k", "喜欢吃面", {"key": "k", "value": "喜欢吃面"}).relation,
                         "confirm")
        self.assertEqual(exact_judge("k", "不太喜欢吃面", {"key": "k", "value": "喜欢吃面"}).relation,
                         "conflict")

    def test_llm_judge_parses_and_falls_back(self):
        class GoodLLM:
            def chat(self, messages):
                return '```json\n{"relation": "conflict", "note": "测试"}\n```'

        class BadLLM:
            def chat(self, messages):
                return "我不会输出JSON"

        j = make_llm_judge(GoodLLM())("k", "v2", {"key": "k", "value": "v1"})
        self.assertEqual(j.relation, "conflict")
        j2 = make_llm_judge(BadLLM())("k", "v2", {"key": "k", "value": "v1"})
        self.assertEqual(j2.relation, "conflict")   # 兜底：精确不匹配 → conflict

    def test_full_pipeline_with_llm_judge(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)

        class LLM:
            def chat(self, messages):
                return '{"relation": "confirm", "note": "同一件事的补充"}'

        m.claim = None  # 防呆：确认下面用的是 record_claim 通道
        j = make_llm_judge(LLM())
        m.record_claim("住处", "树根底下的洞", "new")
        jd = j("住处", "没有窗，只有洞口透光", m.get_fact("住处"))
        m.record_claim(jd.key, jd.value, jd.relation)
        self.assertEqual(m.get_fact("住处")["value"], "没有窗，只有洞口透光")


class TestWorldNotesAndSession(unittest.TestCase):
    def test_world_notes_append_only(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.add_world_note("我答应过他——捡到顺眼的东西给他攒着", ORIGIN_ZIA_SAID)
        m.add_world_note("我这儿的雾石会发冷光")
        self.assertEqual(len(m.all_world_notes()), 2)
        # 接口层面就不存在删除/修改——append-only 是 API 形状，不是纪律
        self.assertFalse(hasattr(m, "delete_world_note"))
        self.assertFalse(hasattr(m, "update_world_note"))

    def test_session_is_volatile(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.session.append("user", "在吗")
        m.session.append("her", "在")
        self.assertEqual(len(m.session.turns), 2)
        m.session.clear()
        self.assertEqual(m.session.turns, [])
        # session 不落盘：库文件里没有它的表
        tables = {r[0] for r in m._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("session", tables)


class TestPrompt(unittest.TestCase):
    def test_to_prompt_sections(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.record_claim("作息", "晚睡晚起", "new")
        m.add_world_note("我怕雾")
        m.add_episode("他寄了件衣服给我")
        block = m.to_prompt()
        self.assertIn("晚睡晚起", block)
        self.assertIn("我怕雾", block)
        self.assertIn("他寄了件衣服给我", block)
        self.assertIn("不许不认", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
