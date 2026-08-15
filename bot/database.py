"""Database models and session management (SQLAlchemy async)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bot.config import DATABASE_URL

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Chat(Base):
    """Per-chat settings and metadata."""

    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    chat_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_mode: Mapped[str] = mapped_column(String(20), default="contains", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    rules: Mapped[List["KeywordRule"]] = relationship(
        "KeywordRule", back_populates="chat", cascade="all, delete-orphan"
    )


class KeywordRule(Base):
    """Keyword replacement rule for a specific chat."""

    __tablename__ = "keyword_rules"
    __table_args__ = (
        UniqueConstraint("chat_id", "old_keyword", name="uq_chat_old_keyword"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.chat_id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_keyword: Mapped[str] = mapped_column(String(512), nullable=False)
    new_keyword: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    chat: Mapped["Chat"] = relationship("Chat", back_populates="rules")


class AuthorizedAdmin(Base):
    """Optional extra admins who can configure the bot (in addition to OWNER_ID)."""

    __tablename__ = "authorized_admins"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


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
    """Create all tables if they do not exist."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully.")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------- Helper query functions ----------

async def get_or_create_chat(
    session: AsyncSession,
    chat_id: int,
    chat_title: Optional[str] = None,
) -> Chat:
    result = await session.execute(select(Chat).where(Chat.chat_id == chat_id))
    chat = result.scalar_one_or_none()
    if chat is None:
        chat = Chat(
            chat_id=chat_id,
            chat_title=chat_title or str(chat_id),
            enabled=True,
            case_sensitive=False,
            match_mode="contains",
        )
        session.add(chat)
        await session.flush()
        logger.info("Created new chat record: %s (%s)", chat_id, chat_title)
    else:
        if chat_title and chat.chat_title != chat_title:
            chat.chat_title = chat_title
            chat.updated_at = _utc_now()
    return chat


async def get_chat(session: AsyncSession, chat_id: int) -> Optional[Chat]:
    result = await session.execute(select(Chat).where(Chat.chat_id == chat_id))
    return result.scalar_one_or_none()


async def set_chat_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> bool:
    chat = await get_or_create_chat(session, chat_id)
    chat.enabled = enabled
    chat.updated_at = _utc_now()
    return True


async def set_case_sensitive(session: AsyncSession, chat_id: int, case_sensitive: bool) -> bool:
    chat = await get_or_create_chat(session, chat_id)
    chat.case_sensitive = case_sensitive
    chat.updated_at = _utc_now()
    return True


async def set_match_mode(session: AsyncSession, chat_id: int, mode: str) -> bool:
    if mode not in ("contains", "word"):
        return False
    chat = await get_or_create_chat(session, chat_id)
    chat.match_mode = mode
    chat.updated_at = _utc_now()
    return True


async def add_keyword_rule(
    session: AsyncSession,
    chat_id: int,
    old_keyword: str,
    new_keyword: str,
) -> KeywordRule:
    await get_or_create_chat(session, chat_id)
    result = await session.execute(
        select(KeywordRule).where(
            KeywordRule.chat_id == chat_id,
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
            chat_id=chat_id,
            old_keyword=old_keyword,
            new_keyword=new_keyword,
            enabled=True,
        )
        session.add(rule)
    await session.flush()
    return rule


async def delete_keyword_rule(
    session: AsyncSession, chat_id: int, old_keyword: str
) -> bool:
    result = await session.execute(
        delete(KeywordRule).where(
            KeywordRule.chat_id == chat_id,
            KeywordRule.old_keyword == old_keyword,
        )
    )
    return result.rowcount > 0


async def clear_keyword_rules(session: AsyncSession, chat_id: int) -> int:
    result = await session.execute(
        delete(KeywordRule).where(KeywordRule.chat_id == chat_id)
    )
    return result.rowcount


async def list_keyword_rules(
    session: AsyncSession, chat_id: int, only_enabled: bool = True
) -> List[KeywordRule]:
    stmt = select(KeywordRule).where(KeywordRule.chat_id == chat_id)
    if only_enabled:
        stmt = stmt.where(KeywordRule.enabled.is_(True))
    stmt = stmt.order_by(KeywordRule.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_enabled_rules_for_chat(
    session: AsyncSession, chat_id: int
) -> tuple[bool, bool, str, List[KeywordRule]]:
    """
    Returns (chat_enabled, case_sensitive, match_mode, rules).
    If chat does not exist, returns (False, False, "contains", []).
    """
    chat = await get_chat(session, chat_id)
    if chat is None or not chat.enabled:
        return False, False, "contains", []
    rules = await list_keyword_rules(session, chat_id, only_enabled=True)
    return True, chat.case_sensitive, chat.match_mode, rules


async def is_authorized_admin(
    session: AsyncSession, chat_id: int, user_id: int, owner_id: int
) -> bool:
    if user_id == owner_id:
        return True
    result = await session.execute(
        select(AuthorizedAdmin).where(
            AuthorizedAdmin.chat_id == chat_id,
            AuthorizedAdmin.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def add_authorized_admin(
    session: AsyncSession, chat_id: int, user_id: int, added_by: int
) -> bool:
    result = await session.execute(
        select(AuthorizedAdmin).where(
            AuthorizedAdmin.chat_id == chat_id,
            AuthorizedAdmin.user_id == user_id,
        )
    )
    if result.scalar_one_or_none():
        return False
    admin = AuthorizedAdmin(chat_id=chat_id, user_id=user_id, added_by=added_by)
    session.add(admin)
    await session.flush()
    return True


async def remove_authorized_admin(
    session: AsyncSession, chat_id: int, user_id: int
) -> bool:
    result = await session.execute(
        delete(AuthorizedAdmin).where(
            AuthorizedAdmin.chat_id == chat_id,
            AuthorizedAdmin.user_id == user_id,
        )
    )
    return result.rowcount > 0


async def list_authorized_admins(
    session: AsyncSession, chat_id: int
) -> List[AuthorizedAdmin]:
    result = await session.execute(
        select(AuthorizedAdmin).where(AuthorizedAdmin.chat_id == chat_id)
    )
    return list(result.scalars().all())
