# -*- coding: utf-8 -*-
"""跨端一致性校验：phone/ 内嵌的生成物必须与 PC 侧逐字段等价。

运行（仓库根目录）：python phone/check_parity.py
（这是移植的验收工具；CI 不便跑鸿蒙工程，改为本地/发布前手动执行）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHONE = ROOT / "phone"


def arkt_unescape(s: str) -> str:
    """还原 ArkTS 单引号字符串里的转义（\\n → 换行 等）。"""
    out, i = [], 0
    table = {"n": "\n", "t": "\t", "'": "'", '"': '"', "\\": "\\"}
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(table.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def grab(path: Path, const: str) -> dict:
    m = re.search(const + r": string = '(.+?)';",
                  path.read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit(f"找不到 {const}：{path}")
    return json.loads(arkt_unescape(m.group(1)))


def main() -> int:
    ok = True

    pc_rules = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    ph_rules = grab(PHONE / "entry/src/main/ets/world/WeWorldDefaultRules.ets",
                    "ZX_RULES_JSON")
    same = pc_rules == ph_rules
    print(f"{'✓' if same else '✗'} 世界参数 rules.json 与手机端兜底规则"
          + ("" if same else f"（epoch {pc_rules['start_epoch']} vs {ph_rules['start_epoch']}）"))
    ok &= same

    pc_vec = json.loads((ROOT / "tests/test_vectors.json").read_text(encoding="utf-8"))
    ph_vec = grab(PHONE / "entry/src/main/ets/world/WeWorldVectors.ets",
                  "ZX_VECTORS_JSON")
    same = pc_vec == ph_vec
    n = len(pc_vec.get("cases", []))
    print(f"{'✓' if same else '✗'} 验收向量（{n} 组）与手机端自检卷")
    ok &= same

    print("\n全部一致。" if ok else "\n有不一致——手机端生成物需按 PC 侧重新生成。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
