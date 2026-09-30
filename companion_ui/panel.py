# -*- coding: utf-8 -*-
"""EmotionPanel：立绘面板骨架（从知夏桌面端提炼）。

一个无边框、置顶、可拖动、可缩放、记住位置的桌面窗口，按情绪显示对应立绘，
支持"点击热区"（截图/拍照等按钮在主项目里就是底图上的热区，不是控件）。

与私有版的关系：同一套交互骨架（拖动/缩放/位置锚点/热区命中），
素材解耦——传入什么图就显示什么图，没有图时自绘纯色面板兜底。
"""
from __future__ import annotations

import json
from pathlib import Path

# 纯函数（可测）：缩放步进
def next_scale_step(steps: list[int], current: int, up: bool) -> int | None:
    """在缩放档位表里上/下移一档；不在表里时就近取档再移动。出界返回 None。"""
    if not steps:
        return None
    if current in steps:
        i = steps.index(current)
    else:
        i = min(range(len(steps)), key=lambda k: abs(steps[k] - current))
    i = i + 1 if up else i - 1
    return steps[i] if 0 <= i < len(steps) else None


def anchored_position(x: int, y: int, saved_scale: int, new_scale: int,
                      anchor_w: int, anchor_h: int, base: int) -> tuple[int, int]:
    """换档后的窗口位置修正：锚点=界面右下角（伴侣贴着屏幕右下角站）。

    缩放时右下角不动：x' = x + anchor_w*saved/base − anchor_w*new/base（y 同理）。
    从知夏桌面端 _load_position 的锚点修正原样提炼。
    """
    k = new_scale / saved_scale
    nx = round(x + anchor_w * saved_scale / base - anchor_w * k)
    ny = round(y + anchor_h * saved_scale / base - anchor_h * k)
    return nx, ny


class EmotionPanel:
    """组装器：build(root, images={emotion: path|PIL.Image}, hotspots={name: (x,y,w,h,cb)})。

    - 无边框置顶；按住任意处拖动；双击交给输入框聚焦（由调用方绑定）；
    - Ctrl+滚轮缩放（档位表），位置+缩放存 JSON，下次启动恢复；
    - set_emotion(emotion) 换立绘；缺图时画纯色圆角面板兜底。
    需要 Pillow（显示 PNG 立绘）。
    """

    SCALE_STEPS = [80, 90, 100, 110, 125, 150]
    SCALE_BASE = 100

    def __init__(self, root, images: dict[str, str] | None = None,
                 default_size: tuple[int, int] = (760, 300),
                 position_file: str | None = None,
                 hotspots: dict[str, tuple[int, int, int, int]] | None = None) -> None:
        import tkinter as tk
        from PIL import Image, ImageTk

        self._tk, self._PIL, self._ImageTk = tk, Image, ImageTk
        self.root = root
        self.images = {k: str(v) for k, v in (images or {}).items()}
        self.hotspots = dict(hotspots or {})
        self.default_size = default_size
        self.position_file = position_file
        self.scale_pct = 100
        self._emotion = ""
        self._photo = None                    # 防 GC
        self._hotmark_ids: list[int] = []

        root.overrideredirect(True)           # 无边框
        root.attributes("-topmost", True)
        self.canvas = tk.Canvas(root, highlightthickness=0, bg="#20242B")
        self.canvas.pack(fill="both", expand=True)

        saved = self._load_position()
        self._apply_size()
        root.geometry(f"+{saved[0]}+{saved[1]}" if saved else "+100+100")

        # 拖动
        self.canvas.bind("<Button-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._do_drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)
        # Ctrl+滚轮缩放
        root.bind("<Control-MouseWheel>", self._on_scale_wheel)
        # 热区命中（普通单击且非拖动时触发）
        self._drag_moved = False

    # ---------- 尺寸/立绘 ----------
    def _apply_size(self) -> None:
        w = int(self.default_size[0] * self.scale_pct / self.SCALE_BASE)
        h = int(self.default_size[1] * self.scale_pct / self.SCALE_BASE)
        self.canvas.configure(width=w, height=h)
        self.w, self.h = w, h
        self.root.geometry(f"{w}x{h}")

    def set_emotion(self, emotion: str) -> None:
        """按情绪换立绘。缺图 → 纯色兜底（不报错，面板照常可用）。"""
        self._emotion = emotion
        self._apply_size()
        self.canvas.delete("all")
        path = self.images.get(emotion) or self.images.get("neutral")
        if path and Path(path).is_file():
            img = self._PIL.Image.open(path)
            img = img.resize((self.w, self.h))
            self._photo = self._ImageTk.PhotoImage(img)
            self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        else:
            self.canvas.create_rounded = None  # 无素材：画简单底板
            self.canvas.create_rectangle(
                0, 0, self.w, self.h, fill="#26302B", outline="#3B5F50", width=2)
            self.canvas.create_text(
                self.w - 20, self.h - 16, anchor="e",
                text=emotion or "（无立绘）", fill="#8C8A84")
        self._draw_hotspots()

    # ---------- 热区 ----------
    def _draw_hotspots(self) -> None:
        for hid in self._hotmark_ids:
            self.canvas.delete(hid)
        self._hotmark_ids = []

    def on_click(self, x: int, y: int) -> str | None:
        """命中检测：返回被点击的热区名（调用方在此触发拍照/看屏幕等动作）。"""
        for name, (hx, hy, hw, hh) in self.hotspots.items():
            if hx <= x <= hx + hw and hy <= y <= hy + hh:
                return name
        return None

    # ---------- 拖动 ----------
    def _start_drag(self, event):
        self._dx, self._dy = event.x, event.y
        self._drag_moved = False

    def _do_drag(self, event):
        self._drag_moved = True
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")

    def _end_drag(self, event):
        if not self._drag_moved:
            hit = self.on_click(event.x, event.y)
            if hit:
                self.on_hotspot(hit)
        self._save_position()

    def on_hotspot(self, name: str) -> None:
        """热区被单击的默认行为：无。调用方可覆写本方法或自行绑定。"""

    # ---------- 缩放 ----------
    def set_scale(self, pct: int) -> None:
        old = self.scale_pct
        self.scale_pct = int(pct)
        self._apply_size()
        self.set_emotion(self._emotion)
        x, y = self.root.winfo_x(), self.root.winfo_y()
        nx, ny = anchored_position(x, y, old, self.scale_pct,
                                   self.w, self.h, self.SCALE_BASE)
        self.root.geometry(f"+{nx}+{ny}")
        self._save_position()

    def _on_scale_wheel(self, event):
        up = (getattr(event, "delta", 0) or 0) > 0
        nxt = next_scale_step(self.SCALE_STEPS, self.scale_pct, up)
        if nxt is not None and nxt != self.scale_pct:
            self.set_scale(nxt)

    # ---------- 位置记忆 ----------
    def _save_position(self) -> None:
        if not self.position_file:
            return
        try:
            Path(self.position_file).parent.mkdir(parents=True, exist_ok=True)
            Path(self.position_file).write_text(json.dumps(
                {"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                 "scale": self.scale_pct}), encoding="utf-8")
        except OSError:
            pass

    def _load_position(self) -> tuple[int, int] | None:
        if not self.position_file or not Path(self.position_file).is_file():
            return None
        try:
            data = json.loads(Path(self.position_file).read_text(encoding="utf-8"))
            return int(data["x"]), int(data["y"])
        except Exception:
            return None
