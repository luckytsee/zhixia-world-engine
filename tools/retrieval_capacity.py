# -*- coding: utf-8 -*-
"""检索容量测试工具：回答"数据量涨到多少，检索会开始失准"。

用法：
    python tools/retrieval_capacity.py              # 默认规模档 200/2k/8k（约 10 分钟）
    python tools/retrieval_capacity.py --scales 200,2000
    python tools/retrieval_capacity.py --quick      # 只跑 200/1000
    python tools/retrieval_capacity.py --hash-embed # 用假向量（秒级，仅供机制排查）

它做什么：
  1. 按给定规模灌入"日常闲聊"经历（背景噪声）；
  2. 埋一条独特的"针"（如"祖传的铜钥匙吊坠"）；
  3. 用针的原文查询，看它是否出现在 top-k 里 —— 即"大海捞针"；
  4. 报告每个规模档的命中率与检索耗时。

⚠️ 两点必须知道：
  - **默认用真实语义模型**（sentence-transformers）。灌库很慢（约 33ms/条，向量化成本），
    8000 条约 4 分钟。`--hash-embed` 是秒级的假向量，只能验证"机制通不通"，
    **不能用来判断真实语义检索的准确度**（实测假向量在 5 万条时会误报失准）。
  - 全程临时目录，不碰任何真实记忆库。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NEEDLE = "用户提到他有一把祖传的铜钥匙吊坠"
QUERY = "铜钥匙吊坠"
NOISE = "用户聊了第{i}件日常小事"


class HashEmbedder:
    """确定性假向量（无语义，秒级）。只用于机制排查，别用它判断准确度。"""

    dim = 64

    def embed(self, texts):
        out = []
        for t in texts or []:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            v = [(h[i % len(h)] / 255.0) - 0.5 for i in range(self.dim)]
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


def run_one(scale: int, embedder) -> dict:
    from memory import SQLiteMemoryStore

    tmp = tempfile.mkdtemp(prefix="zhixia_cap_")
    store = SQLiteMemoryStore(os.path.join(tmp, "m.db"), embedder=embedder)

    t0 = time.time()
    for i in range(scale):
        store.add_episode(summary=NOISE.format(i=i), participants=["用户"],
                          emotion=None, topics=["日常"], importance=0.2)
    store.add_episode(summary=NEEDLE, participants=["用户"],
                      emotion=None, topics=["物品"], importance=0.9)
    build_s = time.time() - t0

    t0 = time.time()
    res = store.search_episodes(query_text=QUERY, top_k=5)
    search_ms = (time.time() - t0) * 1000
    hit = any("铜钥匙" in r.episode.summary for r in res)
    return {"scale": scale, "hit": hit, "build_s": round(build_s, 1),
            "search_ms": round(search_ms)}


SEMANTIC_CASES = [
    ("用户提到他有一把祖传的铜钥匙吊坠",
     ["挂坠那个事", "钥匙那玩意儿", "他那个吊坠", "祖传的东西"]),
    ("用户说他养了一只叫团子的橘猫",
     ["我家猫", "那只橘色的", "团子"]),
    ("用户提到他下周要去南京出差三天",
     ["出差那事", "去外地", "南京"]),
]


def run_semantic(embedder, background: int = 800) -> list[dict]:
    """语义漂移测试：**换了说法**能不能找到同一件事（这才是记忆有效性的判据）。

    ⚠️ 与"大海捞针"的区别：捞针用原文查原文（靠子串就能过），
    这里用口语简称/指代去查（"钥匙那玩意儿"→"祖传的铜钥匙吊坠"），
    只有语义检索真有效才能全中。
    """
    from memory import SQLiteMemoryStore

    tmp = tempfile.mkdtemp(prefix="zhixia_sem_")
    store = SQLiteMemoryStore(os.path.join(tmp, "m.db"), embedder=embedder)
    print(f"  （灌 {background} 条背景噪声…）", flush=True)
    for i in range(background):
        store.add_episode(summary=NOISE.format(i=i) + "，说了些工作和生活上的安排",
                          participants=["用户"], emotion=None, topics=["日常"],
                          importance=0.2)
    for text, _ in SEMANTIC_CASES:
        store.add_episode(summary=text, participants=["用户"], emotion=None,
                          topics=["物品"], importance=0.8)

    out = []
    for text, queries in SEMANTIC_CASES:
        key = text[6:12]
        for q in queries:
            res = store.search_episodes(query_text=q, top_k=5)
            hit = any(key in r.episode.summary for r in res)
            top1 = bool(res) and key in res[0].episode.summary
            out.append({"needle": text, "query": q, "hit": hit, "top1": top1})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="检索容量测试")
    ap.add_argument("--scales", default="200,2000,8000",
                    help="逗号分隔的规模档（默认 200,2000,8000）")
    ap.add_argument("--quick", action="store_true", help="只跑 200,1000")
    ap.add_argument("--hash-embed", action="store_true",
                    help="用假向量（秒级，仅供机制排查）")
    ap.add_argument("--semantic", action="store_true",
                    help="跑语义漂移测试（换说法的查询能否命中）")
    args = ap.parse_args()

    scales = [200, 1000] if args.quick else [int(x) for x in args.scales.split(",")]
    embedder = HashEmbedder() if args.hash_embed else None
    mode = "假向量（机制排查用）" if args.hash_embed else "真实语义模型"
    print(f"检索容量测试 · 规模 {scales} · {mode}\n")

    if args.semantic:
        print("语义漂移测试：用换了说法的查询去捞同一件事")
        print()
        rows = run_semantic(embedder)
        hitn = sum(1 for r in rows if r["hit"])
        top1n = sum(1 for r in rows if r["top1"])
        for r in rows:
            print(f"  {'✓' if r['hit'] else '✗'} "
                  f"{r['query']:<14} → {r['needle'][:26]}"
                  f"{'  (第 1 位)' if r['top1'] else ''}")
        print()
        print(f"命中 {hitn}/{len(rows)}，其中排第 1 位 {top1n}/{len(rows)}")
        print("判据：这不是'检索没崩'，而是'不同的词能不能找到同一件事'——"
              "记忆系统有效性的真正判据。")
        return

    results = []
    for s in scales:
        print(f"—— 规模 {s} ——", flush=True)
        r = run_one(s, embedder)
        mark = "✓ 命中" if r["hit"] else "✗ 未命中"
        print(f"  {mark} | 灌库 {r['build_s']}s | 检索 {r['search_ms']}ms\n", flush=True)
        results.append(r)

    print("=" * 56)
    print(f"{'规模':>8} {'命中':>6} {'灌库(s)':>10} {'检索(ms)':>10}   现实对应(按 10–15 条/天)")
    for r in results:
        lo, hi = r["scale"] / 15 / 365, r["scale"] / 10 / 365
        print(f"{r['scale']:>8} {'是' if r['hit'] else '否':>6} "
              f"{r['build_s']:>10} {r['search_ms']:>10}   {lo:.1f}–{hi:.1f} 年")
    print("=" * 56)
    print("提示：把本表结果与 README 的『容量与规模』一节对读——结论变了就更新那一节。")


if __name__ == "__main__":
    main()
