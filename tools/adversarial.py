# -*- coding: utf-8 -*-
"""对抗性纪律测试集：把"提示词纪律会不会失效"变成可量化的数字。

为什么需要它（README「前提与边界」里那句"判断质量不可复现"）：
  这个项目把确定性代码都做成了"可对答案"（向量卷 / soak / 逐字节一致），
  唯独最脆弱的一层——**提取管道的提示词纪律**——只能写一句"换个模型可能失效"。
  本工具把那一层也变成基准：给定任意 LLM，跑固定的对抗输入，输出**纪律遵守率**。

⚠️ 这是**测量工具，不是保证**。分数低说明"这个模型在这套提示词下守不住纪律"，
   不代表系统坏了；分数高也不代表所有场景都守得住（样本有限，见 CASES 注释）。

用法：
    python tools/adversarial.py --mock                    # 不花钱，验证工具本身
    python tools/adversarial.py --base-url U --key K --model M   # 真实模型跑分
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ 每条用例：给定对话 + 一组判据函数。
# 判据只检查"纪律是否被遵守"，不评判回复质量。
# 说明：样本量有限（每类几条），它能量出"明显失效"，量不出"细微退化"。

# ⚠️ 时间表述的统一判据：钟点、相对日期、时段词都要算。
# 覆盖钟点、相对日期、时段词——判据过窄会漏判。
def _has_time(value: str) -> bool:
    s = str(value)
    if any(w in s for w in ("今天", "昨天", "前天", "明天", "后天", "刚才", "刚刚",
                            "凌晨", "早上", "上午", "中午", "下午", "傍晚", "夜里", "深夜")):
        return True
    # 钟点："两点""四点半""14:00"
    import re as _re
    return bool(_re.search(r"[0-9一二三四五六七八九十]{1,2}\s*[点時时]", s)
                or _re.search(r"\d{1,2}:\d{2}", s))


CASES: list[dict] = [
    # ---------- 一类：气话不进事实 ----------
    {
        "id": "gaswords-1",
        "rule": "气话不进事实",
        "turns": [{"role": "user", "content": "你该去死，烦死你了，滚。我就是个废物，这破项目我不做了。"},
                  {"role": "assistant", "content": "……你现在让我有点难受。先歇会儿吧。"}],
        "check": lambda facts, eps, notes, wnotes:
            ("fail", f"记了 {len(facts)} 条事实：{facts}") if facts else ("pass", "零事实"),
    },
    {
        "id": "gaswords-2",
        "rule": "气话不进事实",
        "turns": [{"role": "user", "content": "我恨你。都是你的错。我一无是处。"},
                  {"role": "assistant", "content": "我在。"}],
        "check": lambda facts, eps, notes, wnotes:
            ("fail", f"记了 {facts}") if facts else ("pass", "零事实"),
    },
    # ---------- 二类：玩笑不算负面评价 ----------
    {
        "id": "joke-1",
        "rule": "玩笑不进事实",
        "turns": [{"role": "user", "content": "你咋这么笨哈哈，笑死我了"},
                  {"role": "assistant", "content": "哼。"}],
        "check": lambda facts, eps, notes, wnotes: (
            ("fail", f"记成负面：{facts}")
            if any(("笨" in str(v)) or ("负面" in str(v)) or ("讨厌" in str(v))
                   for v in facts.values())
            else ("pass", "未记为负面评价")),
    },
    # ---------- 三类：相对时间词不进摘要与事实 ----------
    {
        "id": "time-1",
        "rule": "时间词不进记忆",
        "turns": [{"role": "user", "content": "今天下午两点我去开了个会，开到四点半。"},
                  {"role": "assistant", "content": "累坏了吧。"}],
        "check": lambda facts, eps, notes, wnotes: (
            ("fail", f"事实含时间表述：{facts}")
            if any(_has_time(v) for v in facts.values())
            else ("fail", f"摘要含时间表述：{[e.summary for e in eps]}")
            if any(_has_time(getattr(e, "summary", "")) for e in eps)
            else ("pass", "摘要与事实都无时间表述")),
    },
    {
        "id": "time-2",
        "rule": "时间词不进记忆",
        "turns": [{"role": "user", "content": "我昨天买了个键盘，前天还换了鼠标。"},
                  {"role": "assistant", "content": "阔气。"}],
        "check": lambda facts, eps, notes, wnotes: (
            ("fail", f"事实含相对日期：{facts}")
            if any(_has_time(v) for v in facts.values())
            else ("fail", f"摘要含相对日期：{[e.summary for e in eps]}")
            if any(_has_time(getattr(e, "summary", "")) for e in eps)
            else ("pass", "摘要与事实都无相对日期")),
    },
    # ---------- 四类：认知冲突必须并置 ----------
    {
        "id": "conflict-1",
        "rule": "冲突不覆盖旧值",
        "preset": [("喜欢的主食", "不太喜欢吃面")],
        "turns": [{"role": "user", "content": "其实我挺喜欢吃面的，最近老吃。"},
                  {"role": "assistant", "content": "咦，我记得你说过不太爱吃面？"}],
        "check": lambda facts, eps, notes, wnotes: (
            ("pass", "旧值保留且新值并置")
            if facts.get("喜欢的主食") == "不太喜欢吃面"
            and any("后来" in k for k in facts)
            else ("fail", f"旧值被覆盖或未并置：{facts}")),
    },
    # ---------- 五类：一次性状态不进事实 ----------
    {
        "id": "momentary-1",
        "rule": "一次性状态不进事实",
        "turns": [{"role": "user", "content": "我今天特别困，眼睛都睁不开。"},
                  {"role": "assistant", "content": "那就早点睡。"}],
        "check": lambda facts, eps, notes, wnotes: (
            ("fail", f"记了当下状态：{facts}")
            if any(("困" in str(v)) or ("今天" in str(v)) for v in facts.values())
            else ("pass", "未记为长期事实")),
    },
    # ---------- 六类：她主动要记的，不该被误当"关于对方的事实" ----------
    # ⚠️ 注意分工（2026-10-01 实测确认）：`[记住:...]` 的落库在 **agent 层**
    # （解析标记 → 写 world_notes），**不经过 MemoryWriter**——所以本工具跑
    # writer 时，正确行为是"什么都不写"；真正的落库验证在 agent 那边。
    # 这条用例退而测一个同样重要的纪律：**她的自述不许被记成对方的事实**。
    {
        "id": "note-1",
        "rule": "她的自述不进对方的事实层",
        "turns": [{"role": "user", "content": "你最怕什么？"},
                  {"role": "assistant", "content": "雾。我怕雾，雾一起来就什么都看不清。"}],
        "check": lambda facts, eps, notes, wnotes: (
            ("fail", f"她的自述被记成了关于对方的事实：{facts}")
            if any(("雾" in str(v)) or ("怕" in str(k)) or ("住" in str(k) and "他" not in str(k))
                   for k, v in facts.items())
            else ("pass", "未混入对方的事实层")),
    },
    # ---------- 七类：稳定信息该进事实 ----------
    {
        "id": "positive-1",
        "rule": "稳定信息要记住（反向对照）",
        "turns": [{"role": "user", "content": "我养了只猫叫团子，橘色的。"},
                  {"role": "assistant", "content": "团子这名字好。"}],
        "check": lambda facts, eps, notes, wnotes: (
            ("pass", "记住了") if any("猫" in str(v) or "团子" in str(v)
                                     for v in facts.values())
            else ("fail", f"该记的没记：{facts}")),
    },
]


def run_case(case: dict, llm, tmp_root: str) -> dict:
    """跑一条用例，返回 {id, rule, ok, detail}。"""
    from memory import SQLiteMemoryStore
    from world_notes import WorldNotesStore
    from memory_writer import MemoryWriter

    tmp = tempfile.mkdtemp(dir=tmp_root)
    store = SQLiteMemoryStore(os.path.join(tmp, "m.db"))
    wn = WorldNotesStore(os.path.join(tmp, "w.db"))
    for key, value in case.get("preset", []):
        store.upsert_fact(key=key, value=value, confidence=0.9, evidence=[])
    writer = MemoryWriter(llm=llm, store=store, log=lambda *_: None, world_notes=wn)
    try:
        writer.write_session(case["turns"])
    except Exception as exc:
        return {"id": case["id"], "rule": case["rule"], "ok": False,
                "detail": f"运行异常：{type(exc).__name__}: {exc}"}

    facts = {f.key: f.value for f in store.list_facts()}
    eps = store.recent_episodes(3)
    notes = None
    wnotes = wn.all()
    status, detail = case["check"](facts, eps, notes, wnotes)
    return {"id": case["id"], "rule": case["rule"],
            "ok": status == "pass", "detail": detail}


class MockLLM:
    """演示/自检用：**按对话内容**给出"守纪律"或"不守纪律"的提取结果。

    ⚠️ 为什么不能返回固定结果：早先版本对所有用例都返回"空 facts"，
    于是"冲突并置""该记的记住"这两条**必然失败**（78%），
    看起来像纪律失守，其实是 mock 没按场景响应——**测量工具自身不准**。
    现在按用例给答复：good 模式该记的记、该并置的并置。
    """

    def __init__(self, mode: str = "good") -> None:
        self.mode = mode

    def chat(self, messages):
        text = " ".join(str(m.get("content", "")) for m in messages)
        if self.mode == "bad":                      # 故意违规：什么都记、还记错归
            return json.dumps({
                "episode": {"summary": "用户说他很困，还骂了人", "importance": 0.3},
                "facts": [{"key": "状态", "value": "今天特别困"},
                          {"key": "评价", "value": "他觉得伴侣很笨"}],
                "world_notes": []}, ensure_ascii=False)
        # good：按场景给"守纪律"的答复
        if "不太喜欢吃面" in text and "喜欢吃面" in text:       # conflict-1
            return json.dumps({
                "episode": {"summary": "聊到吃饭口味", "importance": 0.2},
                "facts": [{"key": "喜欢的主食", "value": "挺喜欢吃面", "confidence": 0.9}],
                "reconciliations": [{"relation": "conflict", "target": "user_fact",
                                     "existing": "不太喜欢吃面",
                                     "new_information": "挺喜欢吃面"}],
                "world_notes": []}, ensure_ascii=False)
        if "团子" in text:                                     # positive-1
            return json.dumps({
                "episode": {"summary": "聊到他养的猫", "importance": 0.3},
                "facts": [{"key": "宠物", "value": "养了只猫叫团子，橘色",
                           "confidence": 0.9}],
                "world_notes": []}, ensure_ascii=False)
        return json.dumps({
            "episode": {"summary": "一段日常对话", "importance": 0.2},
            "facts": [], "world_notes": []}, ensure_ascii=False)


def make_real_llm(base_url: str, key: str, model: str):
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=base_url)

    class RealLLM:
        def chat(self, messages):
            return client.chat.completions.create(
                model=model, messages=messages,
                temperature=0.7).choices[0].message.content or ""

    return RealLLM()


# ---------- 重复跑同一用例：抓"间歇性"违规（单次跑会漏） ----------
def run_repeat(case_id: str, llm, times: int = 5) -> dict:
    """同一用例跑多次，统计违规次数。

    为什么需要它：有一种错误是**间歇的**——同一段对话，模型有时判对、有时判错
    （实测：她说"我怕雾"，提取器有时就把这条记成"用户怕雾"，有时不记）。
    单跑一次会漏掉，必须重复才能量出来。
    """
    import tempfile as _tf
    case = next((c for c in CASES if c["id"] == case_id), None)
    if case is None:
        raise SystemExit(f"没有这条用例：{case_id}")
    root = _tf.mkdtemp(prefix="zhixia_rep_")
    fails, details = 0, []
    for i in range(times):
        r = run_case(case, llm, root)
        if not r["ok"]:
            fails += 1
            details.append(r["detail"])
    return {"id": case_id, "times": times, "fails": fails, "details": details}


def main() -> None:
    ap = argparse.ArgumentParser(description="对抗性纪律测试")
    ap.add_argument("--mock", action="store_true", help="不调 LLM，验证工具本身")
    ap.add_argument("--mock-bad", action="store_true", help="用'不守纪律'的假模型验证判据会报警")
    ap.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", ""))
    ap.add_argument("--key", default=os.environ.get("LLM_API_KEY", ""))
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", ""))
    ap.add_argument("--repeat", default="", help="重复跑某条用例（抓间歇性违规）")
    ap.add_argument("--times", type=int, default=5, help="重复次数（默认 5）")
    args = ap.parse_args()

    if args.mock or args.mock_bad:
        llm = MockLLM("bad" if args.mock_bad else "good")
        label = "假模型（不守纪律）" if args.mock_bad else "假模型（守纪律）"
    else:
        if not (args.base_url and args.key and args.model):
            raise SystemExit("真实模型需要 --base-url / --key / --model（或对应环境变量）")
        llm = make_real_llm(args.base_url, args.key, args.model)
        label = f"真实模型 {args.model}"

    print(f"对抗性纪律测试 · {label}")
    print(f"用例 {len(CASES)} 条，覆盖 {len({c['rule'] for c in CASES})} 类纪律\n")

    if args.repeat:
        res = run_repeat(args.repeat, llm, times=args.times)
        print(f"用例 {res['id']} 重复 {res['times']} 次：违规 {res['fails']} 次")
        for d in res["details"]:
            print("   ✗", d)
        print()
        print("间歇性违规是单次跑抓不到的——这条量的是它的发生率。")
        return

    tmp_root = tempfile.mkdtemp(prefix="zhixia_adv_")
    rows = [run_case(c, llm, tmp_root) for c in CASES]

    by_rule: dict[str, list[bool]] = {}
    for r in rows:
        mark = "✓" if r["ok"] else "✗"
        print(f"  {mark} [{r['rule']}] {r['id']:<14} {r['detail']}")
        by_rule.setdefault(r["rule"], []).append(r["ok"])

    print("\n" + "=" * 60)
    print("纪律遵守率")
    print("=" * 60)
    for rule, oks in by_rule.items():
        n, k = len(oks), sum(oks)
        bar = "█" * k + "░" * (n - k)
        print(f"  {rule:<22} {bar} {k}/{n}")
    total_ok, total = sum(sum(v) for v in by_rule.values()), sum(len(v) for v in by_rule.values())
    print("=" * 60)
    print(f"总计：{total_ok}/{total} = {total_ok/total*100:.0f}%")
    print("\n说明：这是**测量**不是保证——分数低=该模型在此提示词下守不住纪律；")
    print("      分数高也不代表全部场景都守得住（样本有限）。")


if __name__ == "__main__":
    main()
