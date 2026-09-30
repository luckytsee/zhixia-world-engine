"""pytest fixtures：临时 DB + MockEmbedder，保证测试全离线。"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.store import SQLiteMemoryStore
from memory.tests.mock_embedder import MockEmbedder


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "memory.db"


@pytest.fixture()
def store_factory(db_path: Path):
    def make(**kwargs) -> SQLiteMemoryStore:
        kwargs.setdefault("db_path", str(db_path))
        kwargs.setdefault("embedder", MockEmbedder())
        return SQLiteMemoryStore(**kwargs)

    return make


@pytest.fixture()
def store(store_factory) -> SQLiteMemoryStore:
    return store_factory()
