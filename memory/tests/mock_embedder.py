"""确定性字符袋向量：共享字符越多余弦越高。测试专用，零网络零模型。"""

from __future__ import annotations

import math


class MockEmbedder:
    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for ch in text:
                vec[ord(ch) % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0.0:
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors

    __call__ = embed
