# -*- coding: utf-8 -*-
"""一眼看懂这个仓库的 demo：把世界推算到"现在"，打印她那边此刻。

运行：python demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engine import WorldEngine, load_rules, load_or_init_state, render


def main() -> None:
    engine = WorldEngine(load_rules())
    state = load_or_init_state(engine)  # 首次：从纪元推算到此刻并落盘
    print(render(state, engine)["block"])
    print(f"\n（潮序号 {state['tide_index']} · 引擎版本 {state['engine_version']} · "
          f"账本 state/world_state.json）")


if __name__ == "__main__":
    main()
