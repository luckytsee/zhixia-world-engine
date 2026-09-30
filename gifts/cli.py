# -*- coding: utf-8 -*-
"""礼物小屋演示命令行。

用法：
  python -m gifts.cli --mock        # mock LLM（体验流程，不花钱）
  python -m gifts.cli               # 真实 LLM：需环境变量 DEEPSEEK_API_KEY

菜单：寄出包裹 → 退出；下次打开时自动拆积压包裹；处理心意；看账本。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gifts import GiftStore, open_packages, summarize_ledger  # noqa: E402

PERSONA_DEFAULT = "你是一个 AI 伴侣。性格与世界观由上层注入；这里只处理礼物。"


def make_llm(mock: bool):
    if mock:
        class MockLLM:
            def chat(self, messages):
                return ('{"decision": "keep", "location": "屋里", '
                        '"note": "挺喜欢", "reply": "收下啦，谢谢你。"}')

            def vision_chat(self, system, prompt, image):
                return self.chat(messages=[])

        return MockLLM()
    from openai import OpenAI

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise SystemExit("未设置 DEEPSEEK_API_KEY，或改用 --mock")
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com/v1")

    class RealLLM:
        def chat(self, messages):
            return client.chat.completions.create(
                model="deepseek-chat", messages=messages,
                temperature=0.7).choices[0].message.content or ""

        def vision_chat(self, system, prompt, image_bytes):
            import base64
            b64 = base64.b64encode(image_bytes).decode()
            return client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": [
                              {"type": "text", "text": prompt},
                              {"type": "image_url",
                               "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
                temperature=0.7).choices[0].message.content or ""

    return RealLLM()


def main() -> None:
    ap = argparse.ArgumentParser(description="礼物小屋（demo）")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--dir", default=str(ROOT / "state"),
                    help="账本与图片的存放目录")
    args = ap.parse_args()

    base = Path(args.dir)
    store = GiftStore(base / "gifts.json", base / "gifts_pending.json",
                      images_dir=base / "gifts")

    print("=" * 52)
    print("  礼物小屋（寄快递式：寄出即走，下次打开才拆）")
    print("=" * 52)
    llm = make_llm(args.mock)
    open_packages(store, llm, PERSONA_DEFAULT,
                  locations=["屋里", "院子里", "书架上"])

    while True:
        ans = input("\n[1]寄出包裹 [2]处理心意 [3]看账本 [q]退出: ").strip().lower()
        if ans == "q":
            return
        if ans == "1":
            name = input("礼物是什么（一句名字）: ").strip()
            if not name:
                continue
            desc = input("想说的话（可空）: ").strip()
            img = input("图片路径（可空）: ").strip().strip('"')
            media, path = "text", ""
            if img:
                copied = store.import_image(img)
                if copied:
                    media, path = "image", copied
                else:
                    print("  ⚠️ 图片没取到，按文字寄出")
            store.add_package(name, desc, media=media, image_path=path)
            print("  📦 已寄出！下次打开小屋时她才会拆。")
        elif ans == "2":
            wishes = [e for e in store.pending() if e.get("kind") == "wish"]
            if not wishes:
                print("（架上没有等处理的心意）")
                continue
            for w in wishes:
                print(f"\n  「{w['name']}」附言：{w.get('note', '')}")
                a = input("  [y=收下 / n=婉拒 / s=先放着] ").strip().lower()
                if a == "s":
                    continue
                store.pop_pending(w["id"])
                store.record("her_to_user", str(w["name"]),
                             "sent" if a == "y" else "declined",
                             note=str(w.get("note", "")))
        elif ans == "3":
            print()
            print(summarize_ledger(store))


if __name__ == "__main__":
    main()
