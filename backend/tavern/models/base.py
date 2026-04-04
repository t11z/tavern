from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase


class JSONB(JSON):
    """JSONB on PostgreSQL, falls back to JSON for other dialects (e.g. SQLite in tests)."""

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(JSON())


class Base(DeclarativeBase):
    pass
