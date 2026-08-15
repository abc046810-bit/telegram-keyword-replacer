"""Database models and session management (SQLAlchemy async).

GLOBAL rules model:
- Keywords are global (apply to every chat where the bot is admin)
- Enable/disable and case/match settings are also global
- Owner configures everything in private chat with the bot
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    delete,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.config import DATABASE_URL

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class GlobalSettings(Base):
    """Single-row global settings."""

    __tablename__ = "global_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_mode: Mapped[str] = mapped_column(String(20), default="contains", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class KeywordRule(Base):
    """Global keyword replacement rule."""

    __tablename__ = "keyword_rules"
    __table_args__ = (
        UniqueConstraint("old_keyword", name="uq_old_keyword"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    old_keyword: Mapped[str] = mapped_column(String(512), nullable=False)
    new_keyword: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


# Engine & session factory
_engine = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = {}
        if DATABASE_URL.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            future=True,
            connect_args=connect_args,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Ensure one global settings row exists
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(GlobalSettings).limit(1))
        if result.scalar_one_or_none() is None:
            session.add(GlobalSettings(enabled=True, case_sensitive=False, match_mode="contains"))
            await session.commit()
    logger.info("Database initialized successfully.")


# ---------- Settings helpers ----------

async def get_settings(session: AsyncSession) -> GlobalSettings:
    result = await session.execute(select(GlobalSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = GlobalSettings(enabled=True, case_sensitive=False, match_mode="contains")
        session.add(settings)
        await session.flush()
    return settings


async def set_enabled(session: AsyncSession, enabled: bool) -> None:
    s = await get_settings(session)
    s.enabled = enabled
    s.updated_at = _utc_now()


async def set_case_sensitive(session: AsyncSession, case_sensitive: bool) -> None:
    s = await get_settings(session)
    s.case_sensitive = case_sensitive
    s.updated_at = _utc_now()


async def set_match_mode(session: AsyncSession, mode: str) -> bool:
    if mode not in ("contains", "word"):
        return False
    s = await get_settings(session)
    s.match_mode = mode
    s.updated_at = _utc_now()
    return True


# ---------- Keyword rule helpers ----------

async def add_keyword_rule(
    session: AsyncSession,
    old_keyword: str,
    new_keyword: str,
) -> KeywordRule:
    result = await session.execute(
        select(KeywordRule).where(KeywordRule.old_keyword == old_keyword)
    )
    rule = result.scalar_one_or_none()
    if rule:
        rule.new_keyword = new_keyword
        rule.enabled = True
        rule.updated_at = _utc_now()
    else:
        rule = KeywordRule(
            old_keyword=old_keyword,
            new_keyword=new_keyword,
            enabled=True,
        )
        session.add(rule)
    await session.flush()
    return rule


async def delete_keyword_rule(session: AsyncSession, old_keyword: str) -> bool:
    result = await session.execute(
        delete(KeywordRule).where(KeywordRule.old_keyword == old_keyword)
    )
    return result.rowcount > 0


async def clear_keyword_rules(session: AsyncSession) -> int:
    result = await session.execute(delete(KeywordRule))
    return result.rowcount


async def list_keyword_rules(
    session: AsyncSession, only_enabled: bool = False
) -> List[KeywordRule]:
    stmt = select(KeywordRule)
    if only_enabled:
        stmt = stmt.where(KeywordRule.enabled.is_(True))
    stmt = stmt.order_by(KeywordRule.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_active_config(
    session: AsyncSession,
) -> tuple[bool, bool, str, List[KeywordRule]]:
    """
    Returns (enabled, case_sensitive, match_mode, enabled_rules).
    """
    settings = await get_settings(session)
    if not settings.enabled:
        return False, settings.case_sensitive, settings.match_mode, []
    rules = await list_keyword_rules(session, only_enabled=True)
    return True, settings.case_sensitive, settings.match_mode, rules
