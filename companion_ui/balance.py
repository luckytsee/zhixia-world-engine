# -*- coding: utf-8 -*-
"""余额查询（DeepSeek /user/balance，OpenAI 兼容系接口通用）。

从知夏桌面端提炼。任何异常都不外抛——余额只是界面上的一个数字，
断网/改接口都不该让伴侣程序崩掉或卡住。纯标准库 urllib，零额外依赖。
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

DEFAULT_TIMEOUT = 6.0
PREFERRED_CURRENCY = "USD"


@dataclass
class Balance:
    ok: bool
    amount: float = 0.0
    currency: str = ""
    is_available: bool | None = None
    error: str = ""
    at: float = 0.0

    @property
    def text(self) -> str:
        return f"{self.amount:.2f} {self.currency}" if self.ok else "—"


def api_root(base_url: str) -> str:
    """https://api.deepseek.com/v1 → https://api.deepseek.com（balance 挂在根上）。"""
    root = base_url.strip().rstrip("/")
    for suffix in ("/v1", "/openai"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
    return root


def parse_balance(payload: dict) -> Balance:
    """从接口返回 JSON 里取余额。**纯函数**，离线可测。"""
    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        return Balance(ok=False, error="返回里没有 balance_infos")
    chosen = next((i for i in infos
                   if isinstance(i, dict) and i.get("currency") == PREFERRED_CURRENCY),
                  next((i for i in infos if isinstance(i, dict)), None))
    if chosen is None:
        return Balance(ok=False, error="balance_infos 里没有对象")
    try:
        amount = float(str(chosen.get("total_balance")).strip())
    except (TypeError, ValueError):
        return Balance(ok=False, error=f"total_balance 不是数字：{chosen.get('total_balance')!r}")
    return Balance(ok=True, amount=amount,
                   currency=str(chosen.get("currency") or PREFERRED_CURRENCY),
                   is_available=payload.get("is_available"), at=time.time())


def fetch_balance(api_key: str, base_url: str, timeout: float = DEFAULT_TIMEOUT) -> Balance:
    """请求一次。**任何异常都不往外抛**。"""
    url = f"{api_root(base_url)}/user/balance"
    try:
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return Balance(ok=False, error=f"HTTP {resp.status}")
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return Balance(ok=False, error=f"{type(exc).__name__}: {exc}")
    if not isinstance(payload, dict):
        return Balance(ok=False, error="返回不是对象")
    return parse_balance(payload)


def is_low(balance: Balance, threshold: float) -> bool:
    return balance.ok and balance.amount < threshold
