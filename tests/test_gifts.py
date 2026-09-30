# -*- coding: utf-8 -*-
"""gifts 模块测试：账本流转 / 三分流裁决 / 图片归档 / 话题注入。

运行（仓库根目录）：python tests/test_gifts.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gifts import GiftStore, open_packages  # noqa: E402

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg==")


def make_store(tmp: str) -> GiftStore:
    return GiftStore(os.path.join(tmp, "gifts.json"),
                     os.path.join(tmp, "pending.json"),
                     images_dir=os.path.join(tmp, "imgs"))


def decision(decision: str, location: str = "书架上", note: str = "喜欢",
             reply: str = "收下啦。") -> str:
    return json.dumps({"decision": decision, "location": location, "note": note,
                       "reply": reply}, ensure_ascii=False)


class FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[str] = []

    def chat(self, messages):
        self.calls.append("chat")
        return self.reply

    def vision_chat(self, system, prompt, image):
        self.calls.append("vision")
        return self.reply


class TestLedger(unittest.TestCase):
    def test_full_flow_keep(self):
        tmp = tempfile.mkdtemp()
        st = make_store(tmp)
        st.add_package("围巾", "冬天用的", media="text")
        self.assertEqual(len(st.pending()), 1)
        st.record("user_to_her", "围巾", "kept", location="屋里")
        st.pop_pending(st.pending()[0]["id"])
        self.assertEqual(st.ledger()[0]["status"], "kept")
        self.assertEqual(len(st.pending()), 0)

    def test_import_image_copies_not_moves(self):
        tmp = tempfile.mkdtemp()
        st = make_store(tmp)
        src = os.path.join(tmp, "a.png")
        with open(src, "wb") as f:
            f.write(_PNG)
        dst = st.import_image(src)
        self.assertTrue(dst and os.path.exists(dst) and os.path.exists(src))
        self.assertIn(os.path.join(tmp, "imgs"), dst)

    def test_render_topic_gate_and_generic_trigger(self):
        tmp = tempfile.mkdtemp()
        st = make_store(tmp)
        st.record("user_to_her", "围巾", "kept", location="屋里")
        self.assertEqual(st.render_context("今天天气怎么样"), "")
        self.assertIn("围巾", st.render_context("那条围巾还在吗"))
        # 泛触发词：提到"礼物"就整块注入，不依赖具体名字
        st.record("her_to_user", "野花", "sent")
        block = st.render_context("收到我的礼物了吗")
        self.assertIn("围巾", block)
        self.assertIn("野花", block)

    def test_snapshot_payload_excludes_image_path(self):
        tmp = tempfile.mkdtemp()
        st = make_store(tmp)
        st.record("user_to_her", "画", "kept", image_path="X:/a.png")
        p = st.snapshot_payload()
        self.assertNotIn("image_path", p["items"][0])


class TestOpening(unittest.TestCase):
    def _run(self, verdict: str, media: str = "text"):
        tmp = tempfile.mkdtemp()
        st = make_store(tmp)
        if media == "image":
            src = os.path.join(tmp, "a.png")
            with open(src, "wb") as f:
                f.write(_PNG)
            st.add_package("围巾", media="image",
                           image_path=st.import_image(src))
        else:
            st.add_package("围巾")
        settled = []
        open_packages(st, FakeLLM(decision(verdict)), "你是测试角色。",
                      locations=["屋里", "书架上"],
                      on_settled=lambda *a: settled.append(a))
        return st, settled

    def test_keep_records_with_location(self):
        st, settled = self._run("keep", media="image")
        self.assertEqual(settled[0][1], "keep")
        item = st.ledger()[0]
        self.assertEqual(item["status"], "kept")
        self.assertEqual(item["media"], "image")
        self.assertEqual(len(st.pending()), 0)

    def test_decline_recorded(self):
        st, _ = self._run("decline")
        self.assertEqual(st.ledger()[0]["status"], "declined")

    def test_discard_not_recorded(self):
        st, _ = self._run("discard")
        self.assertEqual(len(st.pending()), 0)
        self.assertEqual(len(st.ledger()), 0)

    def test_llm_failure_keeps_package(self):
        tmp = tempfile.mkdtemp()
        st = make_store(tmp)
        st.add_package("茶叶")
        open_packages(st, FakeLLM("不是JSON"), "x")
        self.assertEqual(len(st.pending()), 1)   # 不丢件


if __name__ == "__main__":
    unittest.main(verbosity=2)
