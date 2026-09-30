# -*- coding: utf-8 -*-
"""一键验证入口：把本仓库的全部验证手段收进一条命令。

用法：
  python verify.py              # 快速档：单元测试 + 向量卷一致性（约 5 秒）
  python verify.py --full      # 完整档：再加 10 年 soak（约 30 秒，发布前跑）
  python verify.py --privacy   # 隐私终检：全仓 grep 生活数据关键词（推远端前必跑）
  python verify.py --all       # 以上全部

各项含义见 README 的"验证"一节。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PRIVACY_PATTERNS = [
    r"luckytsee",
    r"D:\\\\",
    r"桌面",
    r"sk-[A-Za-z0-9]{10,}",          # 任何疑似 API key
    r"ghp_[A-Za-z0-9]+",             # GitHub token
]

PRIVACY_ALLOW = ("LICENSE",)        # 署名文件豁免


def run(desc: str, cmd: list[str]) -> bool:
    print(f"\n—— {desc}")
    print("   $", " ".join(cmd))
    code = subprocess.call([sys.executable] + cmd, cwd=ROOT)
    ok = code == 0
    print(f"   {'✓ 通过' if ok else '✗ 失败'}（exit={code}）")
    return ok


def privacy_check() -> bool:
    print("\n—— 隐私终检：全仓扫描生活数据关键词")
    bad: list[str] = []
    pat = re.compile("|".join(PRIVACY_PATTERNS))
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(ROOT).as_posix()
            if any(rel.startswith(a) for a in PRIVACY_ALLOW):
                continue
            if not re.search(r"\.(py|md|json|yml|txt|gitignore)$|^\.gitignore$", name):
                continue
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8"), 1):
                    if pat.search(line):
                        bad.append(f"{rel}:{i}: {line.strip()[:80]}")
            except (UnicodeDecodeError, OSError):
                continue
    if bad:
        print("   ✗ 命中疑似隐私内容：")
        for b in bad[:20]:
            print("     ", b)
        return False
    print("   ✓ 零命中")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="zhixia-world-engine 一键验证")
    ap.add_argument("--full", action="store_true", help="含 10 年 soak")
    ap.add_argument("--privacy", action="store_true", help="隐私终检")
    ap.add_argument("--all", action="store_true", help="全部档位")
    args = ap.parse_args()
    full = args.full or args.all
    privacy = args.privacy or args.all

    results: list[tuple[str, bool]] = []
    results.append(("单元测试：engine", run("引擎单元测试", ["tests/test_engine.py"])))
    results.append(("单元测试：zmemory", run("记忆库单元测试", ["tests/test_memory.py"])))

    # 向量卷一致性：重新生成后与仓库内版本逐字节比对
    vec = ROOT / "tests" / "test_vectors.json"
    backup = vec.read_bytes()
    ok = run("重新生成向量卷", ["tests/make_vectors.py"]) and vec.read_bytes() == backup
    if not ok:
        vec.write_bytes(backup)  # 失败时恢复原卷，避免留下被覆盖的工作区
    results.append(("向量卷一致性（确定性对答案）", ok))

    if full:
        results.append(("10 年 soak（不变量 + 重放一致）",
                        run("长周期 soak", ["tests/test_longrun.py"])))
    if privacy:
        results.append(("隐私终检", privacy_check()))

    print("\n" + "=" * 52)
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    print("=" * 52)
    if failed:
        print(f"未通过：{'、'.join(failed)}")
        sys.exit(1)
    print("全部通过。")


if __name__ == "__main__":
    main()
