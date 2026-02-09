"""
Database models and async session factory.

Tables
------
- authorized_users  – whitelist of Telegram user IDs allowed to use the bot
- accounts          – stored Telegram accounts (per owner user)
- proxies           – SOCKS5 proxy configs (per user)
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    delete,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from bot.config import DATABASE_URL

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Engine & session
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AuthorizedUser(Base):
    """Users allowed to interact with the bot."""

    __tablename__ = "authorized_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class Account(Base):
    """A stored Telegram account belonging to a bot user."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    date_added: Mapped[_dt.date] = mapped_column(
        Date, default=_dt.date.today
    )
    session_string: Mapped[str] = mapped_column(Text, nullable=False)
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "phone", name="uq_owner_phone"),
    )


class Proxy(Base):
    """SOCKS5 proxy configuration per user."""

    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    host: Mapped[str] = mapped_column(String(256), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def init_db() -> None:
    """Create all tables (idempotent)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_admin(admin_id: int) -> None:
    """Make sure the admin is in the authorized_users table."""
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).where(AuthorizedUser.telegram_id == admin_id)
        )
        if result.scalar_one_or_none() is None:
            session.add(
                AuthorizedUser(
                    telegram_id=admin_id,
                    added_by=admin_id,
                    is_admin=True,
                    label="Admin",
                )
            )
            await session.commit()


async def is_user_authorized(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).where(AuthorizedUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none() is not None


async def is_user_admin(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.telegram_id == telegram_id,
                AuthorizedUser.is_admin == True,
            )
        )
        return result.scalar_one_or_none() is not None


async def add_authorized_user(
    telegram_id: int, added_by: int, label: str | None = None
) -> bool:
    """Returns True if user was added, False if already exists."""
    async with async_session() as session:
        exists = await session.execute(
            select(AuthorizedUser).where(AuthorizedUser.telegram_id == telegram_id)
        )
        if exists.scalar_one_or_none():
            return False
        session.add(
            AuthorizedUser(telegram_id=telegram_id, added_by=added_by, label=label)
        )
        await session.commit()
        return True


async def remove_authorized_user(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            delete(AuthorizedUser).where(AuthorizedUser.telegram_id == telegram_id)
        )
        await session.commit()
        return result.rowcount > 0


async def get_authorized_users() -> list[AuthorizedUser]:
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).order_by(AuthorizedUser.added_at)
        )
        return list(result.scalars().all())


# ── Account CRUD ─────────────────────────────────────────────────────


async def add_account(
    owner_id: int,
    phone: str,
    country: str,
    session_string: str,
    tg_user_id: int | None = None,
    first_name: str | None = None,
    username: str | None = None,
) -> Account:
    async with async_session() as session:
        acc = Account(
            owner_id=owner_id,
            phone=phone,
            country=country,
            session_string=session_string,
            date_added=_dt.date.today(),
            tg_user_id=tg_user_id,
            first_name=first_name,
            username=username,
        )
        session.add(acc)
        await session.commit()
        await session.refresh(acc)
        return acc


async def get_account_by_id(account_id: int) -> Account | None:
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(Account.id == account_id)
        )
        return result.scalar_one_or_none()


async def get_accounts_by_owner(owner_id: int, active_only: bool = True) -> list[Account]:
    async with async_session() as session:
        stmt = select(Account).where(Account.owner_id == owner_id)
        if active_only:
            stmt = stmt.where(Account.is_active == True)
        stmt = stmt.order_by(Account.country, Account.date_added, Account.phone)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_countries_for_owner(owner_id: int) -> list[str]:
    async with async_session() as session:
        result = await session.execute(
            select(Account.country)
            .where(Account.owner_id == owner_id, Account.is_active == True)
            .group_by(Account.country)
            .order_by(Account.country)
        )
        return [row[0] for row in result.all()]


async def get_dates_for_country(owner_id: int, country: str) -> list[_dt.date]:
    async with async_session() as session:
        result = await session.execute(
            select(Account.date_added)
            .where(
                Account.owner_id == owner_id,
                Account.country == country,
                Account.is_active == True,
            )
            .group_by(Account.date_added)
            .order_by(Account.date_added.desc())
        )
        return [row[0] for row in result.all()]


async def get_accounts_filtered(
    owner_id: int, country: str, date_added: _dt.date
) -> list[Account]:
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(
                Account.owner_id == owner_id,
                Account.country == country,
                Account.date_added == date_added,
                Account.is_active == True,
            ).order_by(Account.phone)
        )
        return list(result.scalars().all())


async def deactivate_account(account_id: int) -> None:
    async with async_session() as session:
        acc = await session.get(Account, account_id)
        if acc:
            acc.is_active = False
            await session.commit()


async def deactivate_accounts(account_ids: list[int]) -> None:
    async with async_session() as session:
        for aid in account_ids:
            acc = await session.get(Account, aid)
            if acc:
                acc.is_active = False
        await session.commit()


async def get_statistics(owner_id: int) -> dict:
    """
    Returns nested dict:
    {
        "total": int,
        "countries": {
            "USA": {
                "total": int,
                "dates": { "2026-02-10": int, ... }
            }, ...
        }
    }
    """
    accounts = await get_accounts_by_owner(owner_id, active_only=True)
    stats: dict = {"total": 0, "countries": {}}
    for acc in accounts:
        stats["total"] += 1
        country = acc.country
        if country not in stats["countries"]:
            stats["countries"][country] = {"total": 0, "dates": {}}
        stats["countries"][country]["total"] += 1
        date_str = acc.date_added.strftime("%B %d, %Y") if isinstance(acc.date_added, _dt.date) else str(acc.date_added)
        if date_str not in stats["countries"][country]["dates"]:
            stats["countries"][country]["dates"][date_str] = 0
        stats["countries"][country]["dates"][date_str] += 1
    return stats


# ── Proxy CRUD ───────────────────────────────────────────────────────


async def add_proxy(
    user_id: int,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
    label: str | None = None,
) -> Proxy:
    async with async_session() as session:
        proxy = Proxy(
            user_id=user_id,
            host=host,
            port=port,
            username=username,
            password=password,
            label=label,
        )
        session.add(proxy)
        await session.commit()
        await session.refresh(proxy)
        return proxy


async def get_proxies(user_id: int) -> list[Proxy]:
    async with async_session() as session:
        result = await session.execute(
            select(Proxy).where(Proxy.user_id == user_id).order_by(Proxy.created_at)
        )
        return list(result.scalars().all())


async def get_default_proxy(user_id: int) -> Proxy | None:
    async with async_session() as session:
        result = await session.execute(
            select(Proxy).where(Proxy.user_id == user_id, Proxy.is_default == True)
        )
        proxy = result.scalar_one_or_none()
        if proxy is None:
            # Fallback: return first proxy
            result = await session.execute(
                select(Proxy).where(Proxy.user_id == user_id).limit(1)
            )
            proxy = result.scalar_one_or_none()
        return proxy


async def set_default_proxy(proxy_id: int, user_id: int) -> None:
    async with async_session() as session:
        # Unset all defaults for this user
        proxies = await session.execute(
            select(Proxy).where(Proxy.user_id == user_id)
        )
        for p in proxies.scalars().all():
            p.is_default = (p.id == proxy_id)
        await session.commit()


async def delete_proxy(proxy_id: int) -> None:
    async with async_session() as session:
        await session.execute(delete(Proxy).where(Proxy.id == proxy_id))
        await session.commit()


async def get_proxy_by_id(proxy_id: int) -> Proxy | None:
    async with async_session() as session:
        return await session.get(Proxy, proxy_id)
