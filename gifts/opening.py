# -*- coding: utf-8 -*-
"""拆包裁决：接收方对寄来的包裹作出回应（收下 / 认真拒绝 / 整活打趣）。

裁决文本由调用方提供的 LLM 生成；本模块负责流程与账务：
- keep    → 落账（含安放位置，候选列表由调用方传入，通常来自世界参数的 locations）
- decline → 落账（认真拒绝也是关系历史）
- discard → 只丢弃候选，**不落账**（玩笑式包裹一笑而过即可）
LLM 失败时包裹留在候选池，下次再拆——绝不丢件。

合理性约束已写进裁决提示词：角色只能送出/收下其世界观内存在的东西。
"""
from __future__ import annotations

import json
from pathlib import Path

from .store import GiftStore, STATUS_KEPT, STATUS_DECLINED

# 三种裁决的含义（提示词与文档共用同一口径）
DECISIONS = {
    "keep": "收下：正常且愿意收的东西，给出安放位置",
    "decline": "认真拒绝：合理但不想要/不方便收，给出理由（落账，会被记得）",
    "discard": "整活打趣：荒谬到无法认真对待（如一艘航母），一句话打趣完即丢，不落账",
}

_OPEN_PROMPT = """{context}

【送礼合理性（硬约束）】
你扮演的角色只能送出/收下其世界观内存在的东西；凡是需要花钱购买的、
现实工业属性的、世界观内不存在的，都属于"整活"范畴。
{reasonable_extra}

现在对方寄来一件礼物：「{name}」（{media_desc}{desc}）
请你以该角色的身份处理这件包裹，三选一：
{decision_lines}

{vision_part}

严格输出 JSON（不要 markdown 代码块）：
{{"decision": "keep|decline|discard", "location": "收下时的安放处，其他情况为空串",
  "note": "一句话备注（账本用）", "reply": "对寄送者说的话，符合角色口吻，一到两句"}}"""

_VISION_PART = ("（这是一张图片礼物。先用一两句描述你看见了什么，再按上面的规则判断。）")


def open_packages(store: GiftStore, llm, persona: str, *,
                  context: str = "", locations: list[str] | None = None,
                  reasonable_extra: str = "", on_settled=None) -> None:
    """处理候选池里的全部包裹。

    llm：需提供 chat(messages)->str 与 vision_chat(system, prompt, jpeg_bytes)->str。
    persona：角色设定文本（作为 system 提示词），由调用方注入。
    locations：安放位置候选（通常来自世界参数 rules.json 的 locations）。
    on_settled(entry, decision, reply_json)：可选回调——调用方可在此把结论
    写进自己的记忆系统（例如生成一条经历摘要）。
    """
    packages = [e for e in store.pending() if e.get("kind") == "package"]
    if not packages:
        return
    loc_lines = "、".join(locations) if locations else "（由你自定）"
    for pkg in packages:
        name, media = str(pkg.get("name", "?")), str(pkg.get("media", "text"))
        desc = str(pkg.get("desc", "") or "")
        decision_lines = "\n".join(f"- {k}：{v}" for k, v in DECISIONS.items())
        prompt = _OPEN_PROMPT.format(
            context=context, reasonable_extra=reasonable_extra,
            name=name, desc=desc,
            media_desc="图片礼物）" if media == "image" else "文字描述）",
            decision_lines=decision_lines,
            vision_part=_VISION_PART if media == "image" else "")
        try:
            if media == "image":
                img = Path(pkg["image_path"]).read_bytes()
                raw = llm.vision_chat(persona, prompt, img)
            else:
                raw = llm.chat([{"role": "system", "content": persona},
                                {"role": "user", "content": prompt}])
            reply = json.loads(raw.strip().removeprefix("```json")
                               .removesuffix("```").strip())
        except Exception as exc:
            print(f"  ⚠️ 拆「{name}」失败，包裹留在架上下次再拆: {exc}")
            continue
        if not isinstance(reply, dict) or reply.get("decision") not in DECISIONS:
            print(f"  ⚠️ 「{name}」的回应解析失败，包裹留在架上下次再拆")
            continue

        decision = reply["decision"]
        text = str(reply.get("reply", "")).strip()
        print(f"\n  包裹：「{name}」\n  她 > {text}")
        if decision == "keep":
            item = store.record("user_to_her", name, STATUS_KEPT,
                                note=str(reply.get("note", "")),
                                location=str(reply.get("location", "")),
                                media=media, image_path=str(pkg.get("image_path", "")))
            store.pop_pending(pkg["id"])
            print("  （已落账）")
        elif decision == "decline":
            item = store.record("user_to_her", name, STATUS_DECLINED,
                                note=str(reply.get("note", "")),
                                media=media, image_path=str(pkg.get("image_path", "")))
            store.pop_pending(pkg["id"])
            print("  （认真拒绝——已落账）")
        else:
            store.pop_pending(pkg["id"])
            item = None
            print("  （整活——不落账）")
        if on_settled:
            on_settled(pkg, decision, reply, item)
