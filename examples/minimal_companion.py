# -*- coding: utf-8 -*-
"""端到端示例：一个最小的、能跑起来的伴侣。

把仓库里的零件全部接上——人格 + 世界引擎 + 四层记忆 + 关系状态 + 提取管道——
然后在终端里跟她说话。

用法：
    export LLM_API_KEY=sk-...            # 或 --key
    python examples/minimal_companion.py --key sk-...
    python examples/minimal_companion.py --demo      # 不调 LLM，先看接线是否正常

退出时（或输入 /end）会把这段对话交给提取管道，写进长期记忆。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "phone"))   # 不需要，但保持路径一致

PERSONA = ROOT / "persona" / "system_prompt.md"
DATA = ROOT / "state" / "demo"


def build(api_key: str, base_url: str, model: str, data_dir: Path):
    """把五个零件接起来。任何一个零件缺失都不影响其余部分。"""
    from agent import Agent
    from memory import SQLiteMemoryStore
    from world_notes import WorldNotesStore
    from affect import AffectStore
    from memory_writer import MemoryWriter
    from engine import WorldEngine, load_rules

    data_dir.mkdir(parents=True, exist_ok=True)

    # 1) 世界引擎（可选：EngineError 时她就没有"那边此刻"）
    world = None
    try:
        from core_world_env import WorldEnv  # 见下方：本示例自带的薄包装
        engine = WorldEngine(load_rules())
        world = WorldEnv(engine, str(data_dir / "world_state.json"))
    except Exception as exc:
        print(f"[世界] 未接入（{exc}）——她不会有世界环境注入")

    # 2) 记忆（可选）
    memory = SQLiteMemoryStore(str(data_dir / "memory.db"))
    world_notes = WorldNotesStore(str(data_dir / "world.db"))
    affect = AffectStore(str(data_dir / "affect.json"))

    # 3) LLM
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)

    class LLM:
        def chat(self, messages):
            return client.chat.completions.create(
                model=model, messages=messages,
                temperature=0.7).choices[0].message.content or ""

        def vision_chat(self, system: str, prompt: str, image_jpeg: bytes) -> str:
            """看图说话（她"看一眼"时走这条）。用标准的多模态消息格式。"""
            import base64
            b64 = base64.b64encode(image_jpeg).decode()
            return client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": [
                              {"type": "text", "text": prompt},
                              {"type": "image_url",
                               "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
                temperature=0.7).choices[0].message.content or ""

    # 4) 提取管道（会话结束时用）
    client_llm = LLM()          # 复用同一个客户端（原来 writer 和 agent 各建了一个）
    writer = MemoryWriter(llm=client_llm, store=memory, log=print,
                          affect=affect, world_notes=world_notes)

    # 5) 联网（可选：人格里承诺了"能自己查"，接上才算兑现）
    search = None
    try:
        from tools.web_search import WebSearch
        search = WebSearch(log=print)
    except Exception as exc:
        print(f"[联网] 未接入（{exc}）")

    # 6) 看（可选：截屏 / 摄像头。人格里写了"她能看到你那边"，接上才算兑现）
    vision = None
    try:
        from companion_ui import perception
        vision = {"screen": perception.grab_screen,
                  "camera": perception.capture_camera}
    except Exception as exc:
        print(f"[看] 未接入（{exc}）——截屏要 Pillow、摄像头要 opencv")

    agent = Agent(llm=client_llm, persona_text=PERSONA.read_text(encoding="utf-8"),
                  memory=memory, world_notes=world_notes, affect=affect,
                  world=world, writer=writer, search=search, vision=vision,
                  log=print)
    return agent


def main() -> None:
    ap = argparse.ArgumentParser(description="最小可跑伴侣")
    ap.add_argument("--key", default=os.environ.get("LLM_API_KEY", ""))
    ap.add_argument("--base-url", default=os.environ.get(
        "LLM_BASE_URL", "https://api.deepseek.com/v1"))
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", "deepseek-chat"))
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--demo", action="store_true",
                    help="不调 LLM：只验证接线（世界/记忆/人格能否组装）")
    args = ap.parse_args()

    if args.demo:
        from agent import parse_reply
        print("接线自检（不调 LLM）\n" + "=" * 46)
        print(f"人格：{'✓ 已加载' if PERSONA.is_file() else '✗ 缺失'} "
              f"（{len(PERSONA.read_text(encoding='utf-8'))} 字符）")
        try:
            from engine import WorldEngine, load_rules
            from core_world_env import WorldEnv
            env = WorldEnv(WorldEngine(load_rules()), str(Path(args.data) / "ws.json"))
            print("世界：✓ 已接入")
            print("  " + env.block().replace("\n", "\n  "))
        except Exception as exc:
            print(f"世界：✗ 未接入（{exc}）")
        # 解析自检（剥标签、读情绪、取 [记住:]）
        speech, emo, rem = parse_reply("嗯，知道了。[happy] [记住:我怕雾]")
        print(f"解析自检：正文={speech!r} 情绪={emo} 待记忆={rem}")
        keep = (speech == "嗯，知道了。" and emo == "happy" and rem == ["我怕雾"])
        print(f"解析结果：{'✓ 正确' if keep else '✗ 异常'}")
        try:
            from tools.web_search import WebSearch
            o = WebSearch(log=lambda *_: None).search("庆余年")
            print(f"联网：{'✓ 已接入' if o.ok else '✗ 查询失败'}（{o.backend} {o.elapsed_ms}ms）")
        except Exception as exc:
            print(f"联网：✗ 未接入（{exc}）")
        # 看：截屏与摄像头各自独立（缺哪个只影响哪个）
        try:
            from companion_ui import perception
            shot = perception.grab_screen(max_side=200)
            print(f"截屏：✓ 可用（{len(shot)} 字节 JPEG）")
        except Exception as exc:
            print(f"截屏：✗ 不可用（{type(exc).__name__}: {exc}）")
        try:
            from companion_ui import perception
            cam = perception.capture_camera()
            print(f"摄像头：{'✓ 可用' if cam else '✗ 没取到画面（没插/被占用/无权限）'}")
        except Exception as exc:
            print(f"摄像头：✗ 不可用（{type(exc).__name__}: {exc}）")
        return

    if not args.key:
        raise SystemExit("需要 --key 或环境变量 LLM_API_KEY（或先跑 --demo 看接线）")

    agent = build(args.key, args.base_url, args.model, Path(args.data))
    print("=" * 46)
    print("跟她说话（/end 结束并写进长期记忆，/look 让她看一眼屏幕，/cam 看摄像头，/q 退出）")
    print("=" * 46)
    try:
        while True:
            try:
                text = input("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text in ("/q", "/quit"):
                break
            if text in ("/end", "/exit"):
                break
            if text in ("/look", "/看"):
                print(f"她 > {agent.look('screen')}")
                continue
            if text in ("/cam", "/摄像头"):
                print(f"她 > {agent.look('camera')}")
                continue
            reply = agent.chat(text)
            print(f"她 > {reply}")
    finally:
        print("\n（整理这段对话…）")
        agent.end_session()
        print("（已写入长期记忆）")


if __name__ == "__main__":
    main()
