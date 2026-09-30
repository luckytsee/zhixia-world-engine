# -*- coding: utf-8 -*-
"""对话提取管道测试：随手开口→自动落库→改口并置→红线→失败不写。

运行（仓库根目录）：python tests/test_extract.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zmemory import CompanionMemory  # noqa: E402
from zmemory.extract import extract  # noqa: E402


def fresh(tmp: str) -> CompanionMemory:
    return CompanionMemory(os.path.join(tmp, "companion.db"), log=lambda *_: None)


class ScriptedLLM:
    """按预设返回提取 JSON 的假 LLM。"""

    def __init__(self, payload):
        self.payload = json.dumps(payload, ensure_ascii=False) \
            if isinstance(payload, dict) else payload
        self.prompts: list[str] = []

    def chat(self, messages):
        self.prompts.append(messages[0]["content"])
        return self.payload


class TestExtraction(unittest.TestCase):
    def test_casual_remember_lands_in_layers(self):
        """随手开口："记住：我怕雾" + 顺带说了作息 → 三层各落各位。"""
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        llm = ScriptedLLM({
            "episode": {"summary": "他问我在忙什么，我说在整理草药；聊到他晚睡", "importance": 0.3},
            "facts": [{"key": "作息", "value": "经常凌晨一点睡", "relation": "new"}],
            "world_notes": [{"text": "我怕雾"}],
        })
        r = extract(m, [
            {"role": "user", "content": "在忙啥？对了我怕雾这事你记住啊。我最近都是一点才睡。"},
            {"role": "assistant", "content": "记下了。一点睡？你胆子真大。"},
        ], llm)
        self.assertIsNotNone(r)
        self.assertEqual(m.get_fact("作息")["value"], "经常凌晨一点睡")
        self.assertTrue(any("我怕雾" in n["text"] for n in m.all_world_notes()))
        self.assertEqual(len(m.recent_episodes(1)), 1)

    def test_change_of_mind_creates_coexistence(self):
        """改口："以前怕雾，现在不怕了" → 冲突并置，两种认知都活着。"""
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.add_world_note("我怕雾")
        llm = ScriptedLLM({
            "episode": {"summary": "她主动说起自己不再怕雾了", "importance": 0.4},
            "facts": [{"key": "怕雾", "value": "现在不怕了", "relation": "conflict"}],
            "world_notes": [{"text": "我现在好像不怕雾了"}],
        })
        extract(m, [
            {"role": "user", "content": "你现在还怕雾吗？"},
            {"role": "assistant", "content": "说来奇怪，最近好像不怕了。"},
        ], llm)
        # 旧认知原样活着，新认知并置
        self.assertTrue(any(n["text"] == "我怕雾" for n in m.all_world_notes()))
        self.assertTrue(any("好像不怕" in n["text"] for n in m.all_world_notes()))
        # 语义边界：她对"怕雾"的认知住在 world_notes（认知层），
        # 所以改口的并置发生在认知层（上面两条断言）；
        # facts 里从没有过"怕雾"，"（后来）"机制自然不触发——两层各管各的
        self.assertEqual(r_conflicts(m), 0)

    def test_gaswords_not_in_facts(self):
        """红线：气话/一次性状态不进 facts——由提示词约束，管道只认 LLM 的输出，
        因此本测试验证的是"LLM 遵守红线时管道不画蛇添足"。"""
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        llm = ScriptedLLM({
            "episode": {"summary": "他情绪上来骂了人，后来道了歉", "importance": 0.4},
            "facts": [],
            "world_notes": [],
        })
        extract(m, [
            {"role": "user", "content": "你该去死。我今天特别困。"},
            {"role": "assistant", "content": "你现在让我有点难受。"},
        ], llm)
        self.assertEqual(m.all_facts(), [])   # 提取器没给 facts → 一个都不写

    def test_llm_failure_writes_nothing(self):
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        llm = ScriptedLLM("不是JSON")
        r = extract(m, [{"role": "user", "content": "随便聊聊"}], llm)
        self.assertIsNone(r)
        self.assertEqual(m.all_facts(), [])
        self.assertEqual(m.all_world_notes(), [])
        self.assertEqual(m.recent_episodes(1), [])

    def test_existing_memory_is_passed_for_comparison(self):
        """已有记忆（含她的世界笔记）必须喂给提取器做比对。"""
        tmp = tempfile.mkdtemp()
        m = fresh(tmp)
        m.record_claim("饮食", "不太爱吃面", "new")
        m.add_world_note("我住在树根底下")
        llm = ScriptedLLM({"episode": {"summary": "闲聊"}, "facts": [], "world_notes": []})
        extract(m, [{"role": "user", "content": "吃饭没"}], llm)
        self.assertIn("不太爱吃面", llm.prompts[0])
        self.assertIn("我住在树根底下", llm.prompts[0])


def r_conflicts(m: CompanionMemory) -> int:
    return sum(1 for f in m.all_facts() if "（后来）" in f["key"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
