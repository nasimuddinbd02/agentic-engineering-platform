"""Portable column types.

``JsonList``/``JsonDict`` give us JSON columns on both PostgreSQL and SQLite.

``Embedding`` stores a float vector.  On the POC it is JSON text, which keeps
the ORM identical on both engines; the Postgres migration ships a commented
``ALTER TABLE ... USING`` that swaps the column to ``vector(N)`` once pgvector
ANN search is turned on (section 13, phase 9).  Retrieval code never touches
the storage format directly - it goes through :mod:`retrieval.search.vector`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Text
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware UTC on the way in and out.

    PostgreSQL round-trips ``timestamptz`` correctly; SQLite silently drops the
    offset, which turns every ``lease_expires_at < now`` comparison into a
    TypeError.  Normalising in one column type keeps the lease and duration
    logic identical on both engines.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class _JsonType(TypeDecorator):
    impl = Text
    cache_ok = True
    _default: Any = None

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return self._default() if callable(self._default) else self._default
        return json.loads(value)


class JsonList(_JsonType):
    _default = list


class JsonDict(_JsonType):
    _default = dict


class Embedding(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        return json.loads(value)
