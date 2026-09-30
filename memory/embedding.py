"""本地向量化：懒加载 sentence-transformers，禁止云端 embedding API。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

EmbedFn = Callable[[list[str]], list[list[float]]]

HF_CACHE_DIR = os.environ.get("HF_CACHE_DIR") or str(Path.home() / ".cache" / "hf")
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
# SentenceTransformer 会把它解析成带组织名的仓库名（日志里可见）
MODEL_REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_default_embedder: EmbedFn | None = None
_load_attempted = False


def _cached_locally() -> bool:
    """模型是否已在本地缓存。

    ⚠️ **必须用文件系统判断，不能 import huggingface_hub 去问**——因为
    `HF_HUB_OFFLINE` 是 huggingface_hub **被 import 时**读取的，问完再设已经晚了。
    """
    name = "models--" + MODEL_REPO.replace("/", "--")
    base = Path(os.environ.get("HF_HUB_CACHE") or HF_CACHE_DIR)
    snapshots = base / name / "snapshots"
    try:
        return snapshots.is_dir() and any(snapshots.iterdir())
    except OSError:
        return False


def _prefer_offline_if_cached() -> None:
    """缓存已存在就强制离线加载。

    不这么做的话：**每次启动都会联网去 huggingface 确认**，网络（代理）不通时
    会重试 5 次、**卡约 3 分钟**才回落到本地缓存（2026-09-24 实测：用户日志
    11:24:55→11:27:54；跑单测时我这边卡 >6 分钟）。
    ⚠️ 缓存**不存在时保持在线**——这样换机器 / 清缓存后仍能自动下载，不把路堵死。
    """
    if _cached_locally():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def get_default_embedder() -> EmbedFn:
    """懒加载本地 embedding 模型。首次调用前设置 HF 缓存目录。

    失败（无网络 / 未安装）时抛出原始异常，由调用方决定降级策略。
    """
    global _default_embedder, _load_attempted

    if _load_attempted:
        if _default_embedder is None:
            raise RuntimeError("sentence-transformers 模型此前加载失败，本进程不再重试")
        return _default_embedder

    _load_attempted = True

    cache_dir = Path(HF_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", HF_CACHE_DIR)
    os.environ.setdefault("HF_HUB_CACHE", HF_CACHE_DIR)
    # ⚠️ 必须在 import sentence_transformers **之前**（离线开关是 import 时读的）
    _prefer_offline_if_cached()

    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

    model = SentenceTransformer(MODEL_NAME)

    def embed(texts: list[str]) -> list[list[float]]:
        vectors = model.encode(texts, convert_to_numpy=True)
        return [[float(x) for x in vec] for vec in vectors]

    _default_embedder = embed
    return embed
