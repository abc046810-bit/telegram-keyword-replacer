"""SQLite / Postgres async DB — global keywords + admins."""

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
    delete,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.config import DATABASE_URL

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _async_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + u[len("postgresql+psycopg2://") :]
    if u.startswith("postgres://"):
        return "postgresql+asyncpg://" + u[len("postgres://") :]
    if u.startswith("postgresql://"):
        return "postgresql+asyncpg://" + u[len("postgresql://") :]
    return u


class Base(DeclarativeBase):
    pass


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_mode: Mapped[str] = mapped_column(String(20), default="contains", nullable=False)


class KeywordRule(Base):
    __tablename__ = "keyword_rules"
    __table_args__ = (UniqueConstraint("old_keyword", name="uq_old"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    old_keyword: Mapped[str] = mapped_column(String(512), nullable=False)
    new_keyword: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (UniqueConstraint("user_id", name="uq_admin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


_engine = None
_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine():
    global _engine
    if _engine is None:
        url = _async_url(DATABASE_URL)
        args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_async_engine(url, echo=False, future=True, connect_args=args)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _factory


async def init_db() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    fac = get_session_factory()
    async with fac() as s:
        r = await s.execute(select(Settings).limit(1))
        if r.scalar_one_or_none() is None:
            s.add(Settings(enabled=True, case_sensitive=False, match_mode="contains"))
            await s.commit()
    logger.info("Database initialized.")


async def get_settings(session: AsyncSession) -> Settings:
    r = await session.execute(select(Settings).limit(1))
    row = r.scalar_one_or_none()
    if row is None:
        row = Settings(enabled=True)
        session.add(row)
        await session.flush()
    return row


async def set_enabled(session: AsyncSession, enabled: bool) -> None:
    s = await get_settings(session)
    s.enabled = enabled


async def is_authorized(session: AsyncSession, user_id: int, owner_id: int) -> bool:
    if user_id == owner_id:
        return True
    r = await session.execute(select(Admin).where(Admin.user_id == user_id))
    return r.scalar_one_or_none() is not None


async def add_admin(session: AsyncSession, user_id: int, added_by: int) -> bool:
    r = await session.execute(select(Admin).where(Admin.user_id == user_id))
    if r.scalar_one_or_none():
        return False
    session.add(Admin(user_id=user_id, added_by=added_by))
    await session.flush()
    return True


async def remove_admin(session: AsyncSession, user_id: int) -> bool:
    r = await session.execute(delete(Admin).where(Admin.user_id == user_id))
    return r.rowcount > 0


async def list_admins(session: AsyncSession) -> List[Admin]:
    r = await session.execute(select(Admin).order_by(Admin.id))
    return list(r.scalars().all())


async def add_rules(session: AsyncSession, pairs: list[tuple[str, str]]) -> int:
    n = 0
    for old, new in pairs:
        old, new = old.strip(), new.strip()
        if not old:
            continue
        r = await session.execute(select(KeywordRule).where(KeywordRule.old_keyword == old))
        row = r.scalar_one_or_none()
        if row:
            row.new_keyword = new
            row.enabled = True
        else:
            session.add(KeywordRule(old_keyword=old, new_keyword=new, enabled=True))
        n += 1
    await session.flush()
    return n


async def delete_rule(session: AsyncSession, old: str) -> bool:
    r = await session.execute(delete(KeywordRule).where(KeywordRule.old_keyword == old))
    return r.rowcount > 0


async def clear_rules(session: AsyncSession) -> int:
    r = await session.execute(delete(KeywordRule))
    return r.rowcount


async def list_rules(session: AsyncSession, only_enabled: bool = False) -> List[KeywordRule]:
    stmt = select(KeywordRule)
    if only_enabled:
        stmt = stmt.where(KeywordRule.enabled.is_(True))
    stmt = stmt.order_by(KeywordRule.id)
    r = await session.execute(stmt)
    return list(r.scalars().all())


async def get_active_rules(session: AsyncSession) -> tuple[bool, bool, str, List[KeywordRule]]:
    s = await get_settings(session)
    if not s.enabled:
        return False, s.case_sensitive, s.match_mode, []
    rules = await list_rules(session, only_enabled=True)
    return True, s.case_sensitive, s.match_mode, rules
