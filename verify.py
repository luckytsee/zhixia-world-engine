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
    # 注：不再单列"桌面"——公开的桌面伴侣项目里"桌面"是正当技术词，
    # 本机路径由 D:\\ 模式负责抓取
    r"sk-[A-Za-z0-9]{10,}",          # 任何疑似 API key
    r"ghp_[A-Za-z0-9]+",             # GitHub token
]

PRIVACY_ALLOW_FILES = ("LICENSE", "verify.py")   # 署名文件 + 扫描器自身（含探测模式）
PRIVACY_ALLOW_LINE = re.compile(r"github\.com/luckytsee/")   # 公开仓库地址属公开身份


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


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
            if rel.startswith(PRIVACY_ALLOW_FILES):
                continue
            if not re.search(r"\.(py|md|json|yml|txt|gitignore)$|^\.gitignore$", name):
                continue
            try:
                # ⚠️ 必须 .splitlines()：enumerate 直接迭代字符串得到的是单个字符，
                # 单字符永远匹配不到多字符模式——第一版栽在这里，假绿了半天
                for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                    if PRIVACY_ALLOW_LINE.search(line):
                        continue
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

    # 向量卷一致性：重新生成后与仓库内版本比对。
    # 换行不敏感比较（\r\n 归一为 \n）——git 的 autocrlf 可能让工作区行尾与
    # 重新生成的不同，那是 checkout 行为差异，不是世界变了
    vec = ROOT / "tests" / "test_vectors.json"
    backup = vec.read_bytes()
    ok = run("重新生成向量卷", ["tests/make_vectors.py"]) and _norm(vec.read_bytes()) == _norm(backup)
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
