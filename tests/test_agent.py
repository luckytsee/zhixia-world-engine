# -*- coding: utf-8 -*-
"""主循环测试：标签剥离 / 情绪解析 / [记住:] 的归属判定。

运行：python -m pytest tests/test_agent.py -q
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import Agent, is_her_own, parse_reply  # noqa: E402


class TestParseReply(unittest.TestCase):
    def test_strips_tags_and_marker(self):
        speech, emo, rem = parse_reply("嗯，知道了。[happy] [记住:我怕雾]")
        self.assertEqual(speech, "嗯，知道了。")     # 标签与标记都剥掉
        self.assertEqual(emo, "happy")               # 情绪从原文读（洗完就读不到了）
        self.assertEqual(rem, ["我怕雾"])

    def test_unknown_trailing_tag_stripped(self):
        speech, emo, _ = parse_reply("行吧。[图:好奇]")
        self.assertNotIn("[", speech)
        self.assertEqual(emo, "neutral")             # 认不出的标签不改情绪


class TestAttribution(unittest.TestCase):
    """归属判定：她的认知层不许被对方的话污染。"""

    def test_repeating_user_is_not_hers(self):
        """对方说"我怕雾这事你记一下"、她复述 → 不算她的认知（实测踩到过）。"""
        self.assertFalse(is_her_own("我怕雾", "我怕雾这事你记一下"))

    def test_her_own_statement_passes(self):
        self.assertTrue(is_her_own("我喜欢下雨天", "今天天气不错"))
        self.assertTrue(is_her_own("我怕雾", "你好呀在干嘛"))

    def test_agent_does_not_store_user_words_as_hers(self):
        """走完整主循环：复述对方的话不会进认知层。"""
        class WN:
            def __init__(self):
                self.notes = []

            def add(self, text):
                self.notes.append(text)

            def all(self):
                return []

        class LLM:
            def chat(self, messages):
                return "行，记下了。[neutral] [记住:我怕雾]"

        wn = WN()
        agent = Agent(llm=LLM(), persona_text="你是测试角色。", world_notes=wn,
                      log=lambda *_: None)
        agent.chat("我怕雾这事你记一下")
        self.assertEqual(wn.notes, [])          # 对方的恐惧没变成她的认知

    def test_agent_stores_her_own_words(self):
        class WN:
            def __init__(self):
                self.notes = []

            def add(self, text):
                self.notes.append(text)

            def all(self):
                return []

        class LLM:
            def chat(self, messages):
                return "嗯。[neutral] [记住:我喜欢下雨天]"

        wn = WN()
        agent = Agent(llm=LLM(), persona_text="你是测试角色。", world_notes=wn,
                      log=lambda *_: None)
        agent.chat("今天天气怎么样")
        self.assertEqual(wn.notes, ["我喜欢下雨天"])   # 她自己的话正常落


if __name__ == "__main__":
    unittest.main(verbosity=2)
