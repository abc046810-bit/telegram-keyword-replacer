"""Database – per-admin keywords, admins, bot users (broadcast)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.config import DATABASE_URL

logger = logging.getLogger(__name__)


def _async_database_url(url: str) -> str:
    """Ensure Postgres URL uses async driver (asyncpg)."""
    u = (url or "").strip()
    if u.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + u[len("postgresql+psycopg2://") :]
    if u.startswith("postgres://"):
        return "postgresql+asyncpg://" + u[len("postgres://") :]
    if u.startswith("postgresql://"):
        return "postgresql+asyncpg://" + u[len("postgresql://") :]
    return u


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class GlobalSettings(Base):
    __tablename__ = "global_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_mode: Mapped[str] = mapped_column(String(20), default="contains", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class KeywordRule(Base):
    __tablename__ = "keyword_rules"
    __table_args__ = (UniqueConstraint("user_id", "old_keyword", name="uq_user_old_keyword"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    old_keyword: Mapped[str] = mapped_column(String(512), nullable=False)
    new_keyword: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class AuthorizedAdmin(Base):
    __tablename__ = "authorized_admins"
    __table_args__ = (UniqueConstraint("user_id", name="uq_admin_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class BotUser(Base):
    """Users who /start the bot – for owner broadcast."""

    __tablename__ = "bot_users"
    __table_args__ = (UniqueConstraint("user_id", name="uq_bot_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


_engine = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = {}
        if DATABASE_URL.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        db_url = _async_database_url(DATABASE_URL)
        if db_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        else:
            connect_args = {}
        _engine = create_async_engine(
            db_url, echo=False, future=True, connect_args=connect_args
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session_factory


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(GlobalSettings).limit(1))
        if result.scalar_one_or_none() is None:
            session.add(
                GlobalSettings(enabled=True, case_sensitive=False, match_mode="contains")
            )
            await session.commit()
    logger.info("Database initialized.")


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


async def add_keyword_rule(
    session: AsyncSession, user_id: int, old_keyword: str, new_keyword: str
) -> KeywordRule:
    result = await session.execute(
        select(KeywordRule).where(
            KeywordRule.user_id == user_id,
            KeywordRule.old_keyword == old_keyword,
        )
    )
    rule = result.scalar_one_or_none()
    if rule:
        rule.new_keyword = new_keyword
        rule.enabled = True
        rule.updated_at = _utc_now()
    else:
        rule = KeywordRule(
            user_id=user_id, old_keyword=old_keyword, new_keyword=new_keyword, enabled=True
        )
        session.add(rule)
    await session.flush()
    return rule


async def delete_keyword_rule(session: AsyncSession, user_id: int, old_keyword: str) -> bool:
    result = await session.execute(
        delete(KeywordRule).where(
            KeywordRule.user_id == user_id,
            KeywordRule.old_keyword == old_keyword,
        )
    )
    return result.rowcount > 0


async def clear_keyword_rules(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(delete(KeywordRule).where(KeywordRule.user_id == user_id))
    return result.rowcount


async def list_keyword_rules(
    session: AsyncSession, user_id: int, only_enabled: bool = False
) -> List[KeywordRule]:
    stmt = select(KeywordRule).where(KeywordRule.user_id == user_id)
    if only_enabled:
        stmt = stmt.where(KeywordRule.enabled.is_(True))
    stmt = stmt.order_by(KeywordRule.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_active_config_for_user(
    session: AsyncSession, user_id: int
) -> tuple[bool, bool, str, List[KeywordRule]]:
    settings = await get_settings(session)
    if not settings.enabled:
        return False, settings.case_sensitive, settings.match_mode, []
    rules = await list_keyword_rules(session, user_id, only_enabled=True)
    return True, settings.case_sensitive, settings.match_mode, rules


async def is_authorized(session: AsyncSession, user_id: int, owner_id: int) -> bool:
    if user_id == owner_id:
        return True
    result = await session.execute(
        select(AuthorizedAdmin).where(AuthorizedAdmin.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def add_admin(session: AsyncSession, user_id: int, added_by: int) -> bool:
    result = await session.execute(
        select(AuthorizedAdmin).where(AuthorizedAdmin.user_id == user_id)
    )
    if result.scalar_one_or_none():
        return False
    session.add(AuthorizedAdmin(user_id=user_id, added_by=added_by))
    await session.flush()
    return True


async def remove_admin(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(
        delete(AuthorizedAdmin).where(AuthorizedAdmin.user_id == user_id)
    )
    return result.rowcount > 0


async def list_admins(session: AsyncSession) -> List[AuthorizedAdmin]:
    result = await session.execute(select(AuthorizedAdmin).order_by(AuthorizedAdmin.id))
    return list(result.scalars().all())


async def upsert_bot_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> BotUser:
    result = await session.execute(select(BotUser).where(BotUser.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = BotUser(
            user_id=user_id,
            username=username,
            first_name=first_name,
            is_blocked=False,
        )
        session.add(row)
    else:
        row.username = username or row.username
        row.first_name = first_name or row.first_name
        row.last_seen_at = _utc_now()
        row.is_blocked = False
    await session.flush()
    return row


async def mark_user_blocked(session: AsyncSession, user_id: int) -> None:
    result = await session.execute(select(BotUser).where(BotUser.user_id == user_id))
    row = result.scalar_one_or_none()
    if row:
        row.is_blocked = True
        row.last_seen_at = _utc_now()


async def list_broadcast_users(session: AsyncSession) -> List[BotUser]:
    result = await session.execute(
        select(BotUser).where(BotUser.is_blocked.is_(False)).order_by(BotUser.id)
    )
    return list(result.scalars().all())


async def count_bot_users(session: AsyncSession) -> tuple[int, int]:
    """Returns (total, active_not_blocked)."""
    result = await session.execute(select(BotUser))
    all_u = list(result.scalars().all())
    active = sum(1 for u in all_u if not u.is_blocked)
    return len(all_u), active
