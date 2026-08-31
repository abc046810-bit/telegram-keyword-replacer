"""DB models – global rules, per-admin rules, settings, users, admins."""

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
from bot.branding import DEFAULT_CREDIT

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _async_database_url(url: str) -> str:
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


class GlobalSettings(Base):
    __tablename__ = "global_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_mode: Mapped[str] = mapped_column(String(20), default="contains", nullable=False)
    # global | per_admin
    rule_scope: Mapped[str] = mapped_column(String(20), default="global", nullable=False)
    batch_name: Mapped[str] = mapped_column(String(512), default="Premium Batch", nullable=False)
    credit_name: Mapped[str] = mapped_column(String(512), default=DEFAULT_CREDIT, nullable=False)
    # empty = keyword-only replace; else custom template with {title} {batch} {credit} {n}
    custom_template: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class KeywordRule(Base):
    """scope_key: 'global' or str(user_id) for per-admin rules."""

    __tablename__ = "keyword_rules"
    __table_args__ = (
        UniqueConstraint("scope_key", "old_keyword", name="uq_scope_old"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
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
        db_url = _async_database_url(DATABASE_URL)
        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
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
                GlobalSettings(
                    enabled=True,
                    case_sensitive=False,
                    match_mode="contains",
                    rule_scope="global",
                    batch_name="Premium Batch",
                    credit_name=DEFAULT_CREDIT,
                    custom_template="",
                )
            )
            await session.commit()
    logger.info("Database initialized.")


async def get_settings(session: AsyncSession) -> GlobalSettings:
    result = await session.execute(select(GlobalSettings).limit(1))
    s = result.scalar_one_or_none()
    if s is None:
        s = GlobalSettings(
            enabled=True,
            rule_scope="global",
            credit_name=DEFAULT_CREDIT,
        )
        session.add(s)
        await session.flush()
    return s


async def set_enabled(session: AsyncSession, enabled: bool) -> None:
    s = await get_settings(session)
    s.enabled = enabled
    s.updated_at = _utc_now()


async def set_rule_scope(session: AsyncSession, scope: str) -> bool:
    if scope not in ("global", "per_admin"):
        return False
    s = await get_settings(session)
    s.rule_scope = scope
    s.updated_at = _utc_now()
    return True


async def set_case_sensitive(session: AsyncSession, value: bool) -> None:
    s = await get_settings(session)
    s.case_sensitive = value
    s.updated_at = _utc_now()


async def set_match_mode(session: AsyncSession, mode: str) -> bool:
    if mode not in ("contains", "word"):
        return False
    s = await get_settings(session)
    s.match_mode = mode
    s.updated_at = _utc_now()
    return True


async def set_batch_name(session: AsyncSession, name: str) -> None:
    s = await get_settings(session)
    s.batch_name = name[:512]
    s.updated_at = _utc_now()


async def set_credit_name(session: AsyncSession, name: str) -> None:
    s = await get_settings(session)
    s.credit_name = name[:512]
    s.updated_at = _utc_now()


async def set_custom_template(session: AsyncSession, template: str) -> None:
    s = await get_settings(session)
    s.custom_template = template
    s.updated_at = _utc_now()


def scope_for_user(rule_scope: str, user_id: int) -> str:
    if rule_scope == "per_admin":
        return str(user_id)
    return "global"


async def add_keyword_rule(
    session: AsyncSession, scope_key: str, old_keyword: str, new_keyword: str
) -> KeywordRule:
    result = await session.execute(
        select(KeywordRule).where(
            KeywordRule.scope_key == scope_key,
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
            scope_key=scope_key,
            old_keyword=old_keyword,
            new_keyword=new_keyword,
            enabled=True,
        )
        session.add(rule)
    await session.flush()
    return rule


async def add_keyword_pairs(
    session: AsyncSession, scope_key: str, pairs: list[tuple[str, str]]
) -> int:
    n = 0
    for old, new in pairs:
        await add_keyword_rule(session, scope_key, old, new)
        n += 1
    return n


async def delete_keyword_rule(
    session: AsyncSession, scope_key: str, old_keyword: str
) -> bool:
    result = await session.execute(
        delete(KeywordRule).where(
            KeywordRule.scope_key == scope_key,
            KeywordRule.old_keyword == old_keyword,
        )
    )
    return result.rowcount > 0


async def clear_keyword_rules(session: AsyncSession, scope_key: str) -> int:
    result = await session.execute(
        delete(KeywordRule).where(KeywordRule.scope_key == scope_key)
    )
    return result.rowcount


async def list_keyword_rules(
    session: AsyncSession, scope_key: str, only_enabled: bool = False
) -> List[KeywordRule]:
    stmt = select(KeywordRule).where(KeywordRule.scope_key == scope_key)
    if only_enabled:
        stmt = stmt.where(KeywordRule.enabled.is_(True))
    stmt = stmt.order_by(KeywordRule.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_rules_for_processing(
    session: AsyncSession, poster_id: Optional[int]
) -> tuple[bool, bool, str, List[KeywordRule]]:
    s = await get_settings(session)
    if not s.enabled:
        return False, s.case_sensitive, s.match_mode, []
    if s.rule_scope == "per_admin":
        if poster_id is None:
            return True, s.case_sensitive, s.match_mode, []
        key = str(poster_id)
    else:
        key = "global"
    rules = await list_keyword_rules(session, key, only_enabled=True)
    return True, s.case_sensitive, s.match_mode, rules


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
        row = BotUser(user_id=user_id, username=username, first_name=first_name)
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


async def list_broadcast_users(session: AsyncSession) -> List[BotUser]:
    result = await session.execute(
        select(BotUser).where(BotUser.is_blocked.is_(False)).order_by(BotUser.id)
    )
    return list(result.scalars().all())


async def count_bot_users(session: AsyncSession) -> tuple[int, int]:
    result = await session.execute(select(BotUser))
    all_u = list(result.scalars().all())
    active = sum(1 for u in all_u if not u.is_blocked)
    return len(all_u), active
