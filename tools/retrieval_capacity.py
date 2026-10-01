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


def main() -> None:
    ap = argparse.ArgumentParser(description="检索容量测试")
    ap.add_argument("--scales", default="200,2000,8000",
                    help="逗号分隔的规模档（默认 200,2000,8000）")
    ap.add_argument("--quick", action="store_true", help="只跑 200,1000")
    ap.add_argument("--hash-embed", action="store_true",
                    help="用假向量（秒级，仅供机制排查）")
    args = ap.parse_args()

    scales = [200, 1000] if args.quick else [int(x) for x in args.scales.split(",")]
    embedder = HashEmbedder() if args.hash_embed else None
    mode = "假向量（机制排查用）" if args.hash_embed else "真实语义模型"
    print(f"检索容量测试 · 规模 {scales} · {mode}\n")

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
