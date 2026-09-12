"""Readiness requires the exact migration head shipped in this build."""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text


@lru_cache
def expected_heads() -> frozenset[str]:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def schema_is_current(connection) -> bool:
    actual = frozenset(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    return bool(actual) and actual == expected_heads()
