"""
Database layer — SQLAlchemy async with aiosqlite.

Models: AuthorizedUser, Account, Proxy, UserSettings
Includes migration helpers for schema evolution.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
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

_SQL_IN_BATCH_SIZE = 500


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
    status = Column(String(32), default="active")
    has_2fa = Column(Boolean, default=False)
    spam_status = Column(String(8), default="unknown")
    spam_checked_at = Column(DateTime, nullable=True)
    is_suspicious = Column(Boolean, default=False)
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
    twofa_password = Column(Text, nullable=True)  # encrypted


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
        await conn.run_sync(_add_twofa_columns)
        await conn.run_sync(_add_health_columns)
        await conn.run_sync(_widen_status_column)
    await _migrate_area_codes()
    await _restore_auto_removed_spam_accounts()
    logger.info("Migrations complete.")


def _widen_status_column(connection) -> None:
    """Widen accounts.status from VARCHAR(16) to VARCHAR(32).

    'delivered_removed' is 17 characters — SQLite never enforced the old
    width, but PostgreSQL would reject inserts. Rebuilds the table with
    the same DDL except the widened column.
    """
    insp = inspect(connection)

    if "accounts" not in insp.get_table_names():
        return

    status_col = next(
        (
            c
            for c in insp.get_columns("accounts")
            if c["name"] == "status"
        ),
        None,
    )
    if status_col is None or "VARCHAR(16)" not in str(
        status_col.get("type", "")
    ).upper():
        return  # nothing to do (fresh DBs already use VARCHAR(32))

    create_sql = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='accounts'"
    ).scalar()
    if not create_sql:
        return

    new_sql = create_sql.replace(
        "accounts", "accounts_new"
    ).replace("VARCHAR(16)", "VARCHAR(32)")

    logger.info("Widening accounts.status to VARCHAR(32)...")

    connection.exec_driver_sql(new_sql)
    columns = ", ".join(c["name"] for c in insp.get_columns("accounts"))
    connection.exec_driver_sql(
        f"INSERT INTO accounts_new ({columns}) "
        f"SELECT {columns} FROM accounts"
    )
    connection.exec_driver_sql("DROP TABLE accounts")
    connection.exec_driver_sql(
        "ALTER TABLE accounts_new RENAME TO accounts"
    )


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
            "  status VARCHAR(32) DEFAULT 'active',"
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


def _add_twofa_columns(connection) -> None:
    """Add has_2fa to accounts and twofa_password to user_settings."""
    insp = inspect(connection)

    if "accounts" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("accounts")}
        if "has_2fa" not in cols:
            connection.execute(
                text(
                    "ALTER TABLE accounts "
                    "ADD COLUMN has_2fa BOOLEAN DEFAULT 0"
                )
            )
            logger.info("Added has_2fa column to accounts.")

    if "user_settings" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("user_settings")}
        if "twofa_password" not in cols:
            connection.execute(
                text(
                    "ALTER TABLE user_settings "
                    "ADD COLUMN twofa_password TEXT"
                )
            )
            logger.info("Added twofa_password column to user_settings.")


def _add_health_columns(connection) -> None:
    """Add spam_status, spam_checked_at, is_suspicious columns."""
    insp = inspect(connection)

    if "accounts" not in insp.get_table_names():
        return

    cols = {c["name"] for c in insp.get_columns("accounts")}
    if "spam_status" not in cols:
        connection.execute(
            text(
                "ALTER TABLE accounts "
                "ADD COLUMN spam_status VARCHAR(8) DEFAULT 'unknown'"
            )
        )
        logger.info("Added spam_status column to accounts.")
    if "spam_checked_at" not in cols:
        connection.execute(
            text("ALTER TABLE accounts ADD COLUMN spam_checked_at DATETIME")
        )
        logger.info("Added spam_checked_at column to accounts.")
    if "is_suspicious" not in cols:
        connection.execute(
            text(
                "ALTER TABLE accounts "
                "ADD COLUMN is_suspicious BOOLEAN DEFAULT 0"
            )
        )
        logger.info("Added is_suspicious column to accounts.")


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


async def _restore_auto_removed_spam_accounts() -> None:
    """Undo the legacy sweep behavior that deactivated Red accounts."""
    async with async_session() as session:
        result = await session.execute(
            update(Account)
            .where(Account.status == "auto_removed_red")
            .values(is_active=True, status="active")
        )
        await session.commit()
        if result.rowcount:
            logger.info(
                "Restored %d account(s) previously auto-removed by "
                "spam sweeps.",
                result.rowcount,
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


async def get_account_by_id(
    account_id: int,
    *,
    owner_id: int | None = None,
    include_inactive: bool = False,
) -> Account | None:
    """Return an account by ID with optional owner and activity guards."""
    async with async_session() as session:
        filters = [Account.id == account_id]
        if owner_id is not None:
            filters.append(Account.owner_id == owner_id)
        if not include_inactive:
            filters.append(Account.is_active == True)  # noqa: E712
        result = await session.execute(select(Account).where(and_(*filters)))
        return result.scalar_one_or_none()


async def get_accounts_by_ids(
    user_id: int,
    account_ids: list[int],
    *,
    include_inactive: bool = False,
) -> list[Account]:
    """Return owner-scoped accounts in the same order as ``account_ids``.

    Status workflows may opt into inactive rows because an account can be
    removed from statistics immediately after delivery and classified later.
    """
    if not account_ids:
        return []

    accounts_by_id: dict[int, Account] = {}
    async with async_session() as session:
        for offset in range(0, len(account_ids), _SQL_IN_BATCH_SIZE):
            batch = account_ids[offset:offset + _SQL_IN_BATCH_SIZE]
            filters = [
                Account.owner_id == user_id,
                Account.id.in_(batch),
            ]
            if not include_inactive:
                filters.append(Account.is_active == True)  # noqa: E712
            result = await session.execute(
                select(Account).where(and_(*filters))
            )
            accounts_by_id.update(
                {
                    account.id: account
                    for account in result.scalars().all()
                }
            )
    return [
        accounts_by_id[account_id]
        for account_id in account_ids
        if account_id in accounts_by_id
    ]


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
    *,
    user_id: int | None = None,
) -> int:
    """Deactivate accounts and return the number of affected rows.

    Pass ``user_id`` for user-triggered operations so IDs from another owner
    can never be changed through stale or forged callback state.
    """
    if not account_ids:
        return 0
    affected = 0
    async with async_session() as session:
        for offset in range(0, len(account_ids), _SQL_IN_BATCH_SIZE):
            batch = account_ids[offset:offset + _SQL_IN_BATCH_SIZE]
            filters = [
                Account.id.in_(batch),
                Account.is_active == True,  # noqa: E712
            ]
            if user_id is not None:
                filters.append(Account.owner_id == user_id)
            result = await session.execute(
                update(Account)
                .where(and_(*filters))
                .values(is_active=False, status=status)
            )
            if result.rowcount and result.rowcount > 0:
                affected += result.rowcount
        await session.commit()
        return affected


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


async def get_all_accounts_for_owner(user_id: int) -> list[Account]:
    """Active accounts for a user (any country, any date)."""
    return await get_all_active_accounts(user_id)


async def get_accounts_for_country(
    user_id: int, country: str
) -> list[Account]:
    """Active accounts in a country across every date."""
    async with async_session() as session:
        result = await session.execute(
            select(Account)
            .where(
                and_(
                    Account.owner_id == user_id,
                    Account.country == country,
                    Account.is_active == True,  # noqa: E712
                )
            )
            .order_by(Account.date_added.desc(), Account.id)
        )
        return list(result.scalars().all())


async def get_suspicious_accounts(user_id: int) -> list[Account]:
    """All accounts (active or not) flagged is_suspicious for a user."""
    async with async_session() as session:
        result = await session.execute(
            select(Account)
            .where(
                and_(
                    Account.owner_id == user_id,
                    Account.is_suspicious == True,  # noqa: E712
                )
            )
            .order_by(Account.id.desc())
        )
        return list(result.scalars().all())


async def set_spam_status(
    account_id: int,
    spam_status: str,
    *,
    user_id: int | None = None,
) -> None:
    """Persist a spam-status classification (green/yellow/red/unknown)."""
    filters = [Account.id == account_id]
    if user_id is not None:
        filters.append(Account.owner_id == user_id)
    async with async_session() as session:
        await session.execute(
            update(Account)
            .where(and_(*filters))
            .values(
                spam_status=spam_status,
                spam_checked_at=datetime.utcnow(),
            )
        )
        await session.commit()


async def mark_suspicious(account_id: int, suspicious: bool = True) -> None:
    """Flag an account as suspicious without changing is_active."""
    async with async_session() as session:
        await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(is_suspicious=suspicious)
        )
        await session.commit()


async def clear_suspicious_flags(user_id: int) -> int:
    """Reset is_suspicious on every flagged account of this owner."""
    async with async_session() as session:
        result = await session.execute(
            update(Account)
            .where(
                and_(
                    Account.owner_id == user_id,
                    Account.is_suspicious == True,  # noqa: E712
                )
            )
            .values(is_suspicious=False)
        )
        await session.commit()
        return result.rowcount or 0


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


async def set_default_proxy(proxy_id: int, user_id: int) -> bool:
    """Mark one of *user_id's* proxies as default. Returns False when the
    proxy does not belong to this user."""
    async with async_session() as session:
        await session.execute(
            update(Proxy)
            .where(Proxy.user_id == user_id)
            .values(is_default=False)
        )
        result = await session.execute(
            update(Proxy)
            .where(
                and_(
                    Proxy.id == proxy_id,
                    Proxy.user_id == user_id,
                )
            )
            .values(is_default=True)
        )
        await session.commit()
        return result.rowcount > 0


async def delete_proxy(proxy_id: int, user_id: int | None = None) -> bool:
    """Delete a proxy, optionally scoped to its owner. Returns whether a
    row was removed."""
    async with async_session() as session:
        filters = [Proxy.id == proxy_id]
        if user_id is not None:
            filters.append(Proxy.user_id == user_id)
        result = await session.execute(
            delete(Proxy).where(and_(*filters))
        )
        await session.commit()
        return result.rowcount > 0


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

    proxy_index = settings.proxy_rotation_counter % len(proxies)
    return proxies[proxy_index]


async def increment_rotation_counter(user_id: int) -> None:
    """Atomically bump the rotation counter (safe under concurrency)."""
    await get_user_settings(user_id)  # ensures row exists
    async with async_session() as session:
        await session.execute(
            update(UserSettings)
            .where(UserSettings.user_id == user_id)
            .values(
                proxy_rotation_counter=UserSettings.proxy_rotation_counter
                + 1
            )
        )
        await session.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# User Settings — 2FA Password
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def set_twofa_password(
    user_id: int,
    encrypted_password: str,
) -> None:
    """Store an encrypted 2FA password for a user."""
    await get_user_settings(user_id)  # ensures row exists
    async with async_session() as session:
        await session.execute(
            update(UserSettings)
            .where(UserSettings.user_id == user_id)
            .values(twofa_password=encrypted_password)
        )
        await session.commit()


async def get_twofa_password(user_id: int) -> str | None:
    """Return the encrypted 2FA password (or None)."""
    settings = await get_user_settings(user_id)
    return settings.twofa_password


async def update_account_2fa(account_id: int, has_2fa: bool) -> None:
    """Set the has_2fa flag for a single account."""
    async with async_session() as session:
        await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(has_2fa=has_2fa)
        )
        await session.commit()
