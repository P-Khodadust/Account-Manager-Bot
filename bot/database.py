"""
Database layer — SQLAlchemy async with aiosqlite.

Models: AuthorizedUser, Account, Proxy, UserSettings
Includes migration helpers for schema evolution.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    and_,
    delete,
    func,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from bot.config import DATABASE_URL

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ORM Base
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class Base(DeclarativeBase):
    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AuthorizedUser(Base):
    __tablename__ = "authorized_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    is_admin = Column(Boolean, default=False)
    added_by = Column(BigInteger, nullable=True)
    label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(BigInteger, nullable=False, index=True)
    phone = Column(String(32), nullable=False)
    country = Column(String(64), nullable=False)
    date_added = Column(Date, default=date.today)
    session_string = Column(Text, nullable=False)
    tg_user_id = Column(BigInteger, nullable=True)
    first_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    status = Column(String(16), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

    # No unique constraint — same phone can be re-added after logout


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    label = Column(String(255), nullable=True)
    is_default = Column(Boolean, default=False)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    proxy_rotation_enabled = Column(Boolean, default=False)
    proxy_rotation_counter = Column(Integer, default=0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Engine & Session
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db() -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Migrations
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def run_migrations() -> None:
    """Run all pending schema migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(_migrate_accounts_table)
    await _migrate_area_codes()
    logger.info("Migrations complete.")


def _migrate_accounts_table(connection) -> None:
    """Add status column and remove the unique constraint on accounts."""
    insp = inspect(connection)

    if "accounts" not in insp.get_table_names():
        return  # create_all will handle it for fresh databases

    columns = {col["name"] for col in insp.get_columns("accounts")}
    has_status = "status" in columns

    unique_constraints = insp.get_unique_constraints("accounts")
    has_uq = any(
        uc.get("name") == "uq_owner_phone" for uc in unique_constraints
    )

    if has_status and not has_uq:
        return  # Already migrated

    logger.info(
        "Migrating accounts table (add status=%s, drop uq=%s)...",
        not has_status,
        has_uq,
    )

    # Recreate table: add status, drop unique constraint
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS accounts_new ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  owner_id BIGINT NOT NULL,"
            "  phone VARCHAR(32) NOT NULL,"
            "  country VARCHAR(64) NOT NULL,"
            "  date_added DATE,"
            "  session_string TEXT NOT NULL,"
            "  tg_user_id BIGINT,"
            "  first_name VARCHAR(255),"
            "  username VARCHAR(255),"
            "  is_active BOOLEAN DEFAULT 1,"
            "  status VARCHAR(16) DEFAULT 'active',"
            "  created_at DATETIME"
            ")"
        )
    )

    if has_status:
        connection.execute(
            text(
                "INSERT INTO accounts_new "
                "(id, owner_id, phone, country, date_added, "
                "session_string, tg_user_id, first_name, username, "
                "is_active, status, created_at) "
                "SELECT id, owner_id, phone, country, date_added, "
                "session_string, tg_user_id, first_name, username, "
                "is_active, status, created_at "
                "FROM accounts"
            )
        )
    else:
        connection.execute(
            text(
                "INSERT INTO accounts_new "
                "(id, owner_id, phone, country, date_added, "
                "session_string, tg_user_id, first_name, username, "
                "is_active, status, created_at) "
                "SELECT id, owner_id, phone, country, date_added, "
                "session_string, tg_user_id, first_name, username, "
                "is_active, "
                "CASE WHEN is_active = 1 THEN 'active' "
                "ELSE 'logged_out' END, "
                "created_at "
                "FROM accounts"
            )
        )

    connection.execute(text("DROP TABLE accounts"))
    connection.execute(
        text("ALTER TABLE accounts_new RENAME TO accounts")
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_accounts_owner_id "
            "ON accounts (owner_id)"
        )
    )
    logger.info("Accounts table migration complete.")


async def _migrate_area_codes() -> None:
    """Fix accounts with +1354 and +1753 area codes (Canada, not USA)."""
    async with async_session() as session:
        result = await session.execute(
            update(Account)
            .where(
                and_(
                    Account.country == "USA",
                    or_(
                        Account.phone.like("+1354%"),
                        Account.phone.like("+1753%"),
                    ),
                )
            )
            .values(country="Canada")
        )
        count = result.rowcount
        await session.commit()
        if count > 0:
            logger.info(
                "Migrated %d account(s) from USA to Canada "
                "(354/753 area codes).",
                count,
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Authorized Users
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def ensure_admin(admin_id: int) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.telegram_id == admin_id
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            session.add(
                AuthorizedUser(
                    telegram_id=admin_id,
                    is_admin=True,
                    label="Main Admin",
                )
            )
            await session.commit()
            logger.info("Admin user %s created.", admin_id)


async def is_user_authorized(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.telegram_id == telegram_id
            )
        )
        return result.scalar_one_or_none() is not None


async def is_user_admin(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).where(
                and_(
                    AuthorizedUser.telegram_id == telegram_id,
                    AuthorizedUser.is_admin == True,  # noqa: E712
                )
            )
        )
        return result.scalar_one_or_none() is not None


async def add_authorized_user(
    telegram_id: int,
    added_by: int,
    label: str = "",
) -> bool:
    async with async_session() as session:
        existing = await session.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.telegram_id == telegram_id
            )
        )
        if existing.scalar_one_or_none():
            return False
        session.add(
            AuthorizedUser(
                telegram_id=telegram_id,
                added_by=added_by,
                label=label,
            )
        )
        await session.commit()
        return True


async def get_authorized_users() -> list[AuthorizedUser]:
    async with async_session() as session:
        result = await session.execute(
            select(AuthorizedUser).order_by(AuthorizedUser.created_at)
        )
        return list(result.scalars().all())


async def remove_authorized_user(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            delete(AuthorizedUser).where(
                AuthorizedUser.telegram_id == telegram_id
            )
        )
        await session.commit()
        return result.rowcount > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Accounts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def add_account(
    owner_id: int,
    phone: str,
    country: str,
    session_string: str,
    tg_user_id: int | None = None,
    first_name: str | None = None,
    username: str | None = None,
) -> Account:
    """Add a new account. Deactivates any previous active entry for the
    same phone+owner first (marks as 'replaced'), then creates a fresh row."""
    async with async_session() as session:
        # Deactivate previous active entries for same phone + owner
        await session.execute(
            update(Account)
            .where(
                and_(
                    Account.owner_id == owner_id,
                    Account.phone == phone,
                    Account.is_active == True,  # noqa: E712
                )
            )
            .values(is_active=False, status="replaced")
        )

        account = Account(
            owner_id=owner_id,
            phone=phone,
            country=country,
            session_string=session_string,
            tg_user_id=tg_user_id,
            first_name=first_name,
            username=username,
            date_added=date.today(),
            status="active",
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account


async def get_account_by_id(account_id: int) -> Account | None:
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(
                and_(
                    Account.id == account_id,
                    Account.is_active == True,  # noqa: E712
                )
            )
        )
        return result.scalar_one_or_none()


async def get_countries_for_owner(user_id: int) -> list[str]:
    async with async_session() as session:
        result = await session.execute(
            select(Account.country)
            .where(
                and_(
                    Account.owner_id == user_id,
                    Account.is_active == True,  # noqa: E712
                )
            )
            .distinct()
            .order_by(Account.country)
        )
        return [row[0] for row in result.all()]


async def get_dates_for_country(user_id: int, country: str) -> list[date]:
    async with async_session() as session:
        result = await session.execute(
            select(Account.date_added)
            .where(
                and_(
                    Account.owner_id == user_id,
                    Account.country == country,
                    Account.is_active == True,  # noqa: E712
                )
            )
            .distinct()
            .order_by(Account.date_added.desc())
        )
        return [row[0] for row in result.all()]


async def get_accounts_filtered(
    user_id: int,
    country: str,
    date_val: date,
) -> list[Account]:
    async with async_session() as session:
        result = await session.execute(
            select(Account)
            .where(
                and_(
                    Account.owner_id == user_id,
                    Account.country == country,
                    Account.date_added == date_val,
                    Account.is_active == True,  # noqa: E712
                )
            )
            .order_by(Account.id)
        )
        return list(result.scalars().all())


async def deactivate_account(
    account_id: int,
    status: str = "logged_out",
) -> None:
    async with async_session() as session:
        await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(is_active=False, status=status)
        )
        await session.commit()


async def deactivate_accounts(
    account_ids: list[int],
    status: str = "logged_out",
) -> None:
    if not account_ids:
        return
    async with async_session() as session:
        await session.execute(
            update(Account)
            .where(Account.id.in_(account_ids))
            .values(is_active=False, status=status)
        )
        await session.commit()


async def mark_account_status(account_id: int, status: str) -> None:
    """Set the status of an account (active/logged_out/removed/invalid)."""
    is_active = status == "active"
    async with async_session() as session:
        await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(is_active=is_active, status=status)
        )
        await session.commit()


async def get_all_active_accounts(user_id: int) -> list[Account]:
    """Get every active account for a user (used by session validator)."""
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(
                and_(
                    Account.owner_id == user_id,
                    Account.is_active == True,  # noqa: E712
                )
            )
        )
        return list(result.scalars().all())


async def get_statistics(user_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(
                and_(
                    Account.owner_id == user_id,
                    Account.is_active == True,  # noqa: E712
                )
            )
        )
        accounts = list(result.scalars().all())

    total = len(accounts)
    countries: dict[str, dict] = {}

    for acc in accounts:
        c = acc.country
        d = (
            acc.date_added.strftime("%B %d, %Y")
            if acc.date_added
            else "Unknown"
        )
        if c not in countries:
            countries[c] = {"total": 0, "dates": {}}
        countries[c]["total"] += 1
        countries[c]["dates"][d] = countries[c]["dates"].get(d, 0) + 1

    return {"total": total, "countries": countries}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Proxies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def add_proxy(
    user_id: int,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
    label: str = "",
) -> Proxy:
    async with async_session() as session:
        result = await session.execute(
            select(func.coalesce(func.max(Proxy.order_index), -1)).where(
                Proxy.user_id == user_id
            )
        )
        max_order = result.scalar() or -1

        proxy = Proxy(
            user_id=user_id,
            host=host,
            port=port,
            username=username,
            password=password,
            label=label,
            order_index=max_order + 1,
        )
        session.add(proxy)
        await session.commit()
        await session.refresh(proxy)
        return proxy


async def get_proxies(user_id: int) -> list[Proxy]:
    async with async_session() as session:
        result = await session.execute(
            select(Proxy)
            .where(Proxy.user_id == user_id)
            .order_by(Proxy.order_index, Proxy.created_at)
        )
        return list(result.scalars().all())


async def get_proxy_by_id(proxy_id: int) -> Proxy | None:
    async with async_session() as session:
        result = await session.execute(
            select(Proxy).where(Proxy.id == proxy_id)
        )
        return result.scalar_one_or_none()


async def get_default_proxy(user_id: int) -> Proxy | None:
    async with async_session() as session:
        result = await session.execute(
            select(Proxy).where(
                and_(
                    Proxy.user_id == user_id,
                    Proxy.is_default == True,  # noqa: E712
                )
            )
        )
        proxy = result.scalar_one_or_none()
        if proxy:
            return proxy
        result = await session.execute(
            select(Proxy)
            .where(Proxy.user_id == user_id)
            .order_by(Proxy.order_index)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def set_default_proxy(proxy_id: int, user_id: int) -> None:
    async with async_session() as session:
        await session.execute(
            update(Proxy)
            .where(Proxy.user_id == user_id)
            .values(is_default=False)
        )
        await session.execute(
            update(Proxy)
            .where(Proxy.id == proxy_id)
            .values(is_default=True)
        )
        await session.commit()


async def delete_proxy(proxy_id: int) -> None:
    async with async_session() as session:
        await session.execute(
            delete(Proxy).where(Proxy.id == proxy_id)
        )
        await session.commit()


async def get_proxy_count(user_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(func.count(Proxy.id)).where(Proxy.user_id == user_id)
        )
        return result.scalar() or 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# User Settings — Proxy Rotation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_user_settings(user_id: int) -> UserSettings:
    async with async_session() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if not settings:
            settings = UserSettings(user_id=user_id)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        return settings


async def toggle_proxy_rotation(user_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if not settings:
            settings = UserSettings(
                user_id=user_id,
                proxy_rotation_enabled=True,
                proxy_rotation_counter=0,
            )
            session.add(settings)
            await session.commit()
            return True

        new_state = not settings.proxy_rotation_enabled
        await session.execute(
            update(UserSettings)
            .where(UserSettings.user_id == user_id)
            .values(
                proxy_rotation_enabled=new_state,
                proxy_rotation_counter=0,
            )
        )
        await session.commit()
        return new_state


async def get_active_proxy(user_id: int) -> Proxy | None:
    settings = await get_user_settings(user_id)
    proxies = await get_proxies(user_id)

    if not proxies:
        return None

    if not settings.proxy_rotation_enabled or len(proxies) < 2:
        return await get_default_proxy(user_id)

    proxy_index = (settings.proxy_rotation_counter // 3) % len(proxies)
    return proxies[proxy_index]


async def increment_rotation_counter(user_id: int) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings:
            await session.execute(
                update(UserSettings)
                .where(UserSettings.user_id == user_id)
                .values(
                    proxy_rotation_counter=settings.proxy_rotation_counter
                    + 1
                )
            )
            await session.commit()
