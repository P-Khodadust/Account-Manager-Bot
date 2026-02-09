"""
Telethon-based session manager.

Handles:
- Login flow (phone → code → optional 2FA)
- Session string export/import
- Session file conversion (Telethon ↔ Pyrogram)
- Logout
- Proxy integration via SOCKS5
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    FloodWaitError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    AuthKeyUnregisteredError,
)
import python_socks

from bot.config import API_ID, API_HASH, SESSIONS_DIR

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Proxy helper
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_proxy(proxy) -> dict | None:
    """Build proxy kwargs for Telethon from a Proxy ORM object."""
    if proxy is None:
        return None
    proxy_dict = {
        "proxy_type": python_socks.ProxyType.SOCKS5,
        "addr": proxy.host,
        "port": proxy.port,
    }
    if proxy.username:
        proxy_dict["username"] = proxy.username
    if proxy.password:
        proxy_dict["password"] = proxy.password
    return proxy_dict


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Client factory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_client(
    session: str | StringSession | None = None,
    proxy=None,
) -> TelegramClient:
    """
    Create a TelegramClient with optional session string and proxy.
    """
    if session is None:
        session = StringSession()
    elif isinstance(session, str):
        session = StringSession(session)

    proxy_kwargs = _build_proxy(proxy)

    client = TelegramClient(
        session,
        API_ID,
        API_HASH,
        proxy=proxy_kwargs,
    )
    return client


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Login flow helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LoginResult:
    """Container for login step results."""

    def __init__(
        self,
        success: bool = False,
        needs_code: bool = False,
        needs_2fa: bool = False,
        error: str | None = None,
        session_string: str | None = None,
        user_info: dict | None = None,
        phone_code_hash: str | None = None,
    ):
        self.success = success
        self.needs_code = needs_code
        self.needs_2fa = needs_2fa
        self.error = error
        self.session_string = session_string
        self.user_info = user_info
        self.phone_code_hash = phone_code_hash


async def request_code(phone: str, proxy=None) -> tuple[TelegramClient, LoginResult]:
    """
    Step 1: Send login code to the phone number.
    Returns (client, result). Client must be kept alive for sign_in step.
    """
    client = create_client(proxy=proxy)
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        return client, LoginResult(
            needs_code=True,
            phone_code_hash=sent.phone_code_hash,
        )
    except PhoneNumberBannedError:
        await client.disconnect()
        return client, LoginResult(error="❌ This phone number is banned by Telegram.")
    except PhoneNumberInvalidError:
        await client.disconnect()
        return client, LoginResult(error="❌ Invalid phone number format.")
    except FloodWaitError as e:
        await client.disconnect()
        return client, LoginResult(error=f"⏳ Too many attempts. Please wait {e.seconds} seconds.")
    except Exception as e:
        await client.disconnect()
        logger.exception("request_code failed")
        return client, LoginResult(error=f"❌ Error: {e}")


async def submit_code(
    client: TelegramClient,
    phone: str,
    code: str,
    phone_code_hash: str,
) -> LoginResult:
    """
    Step 2: Submit the login code.
    May return needs_2fa=True if 2FA is enabled.
    """
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        session_string = client.session.save()
        return LoginResult(
            success=True,
            session_string=session_string,
            user_info={
                "id": me.id,
                "first_name": me.first_name or "",
                "username": me.username or "",
            },
        )
    except SessionPasswordNeededError:
        return LoginResult(needs_2fa=True)
    except PhoneCodeExpiredError:
        return LoginResult(error="❌ The login code has expired. Please request a new one.")
    except PhoneCodeInvalidError:
        return LoginResult(error="❌ Invalid login code. Please try again.")
    except FloodWaitError as e:
        return LoginResult(error=f"⏳ Too many attempts. Please wait {e.seconds} seconds.")
    except Exception as e:
        logger.exception("submit_code failed")
        return LoginResult(error=f"❌ Error: {e}")


async def submit_2fa(client: TelegramClient, password: str) -> LoginResult:
    """
    Step 3: Submit 2FA password.
    """
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        session_string = client.session.save()
        return LoginResult(
            success=True,
            session_string=session_string,
            user_info={
                "id": me.id,
                "first_name": me.first_name or "",
                "username": me.username or "",
            },
        )
    except Exception as e:
        logger.exception("submit_2fa failed")
        return LoginResult(error=f"❌ 2FA Error: {e}")


async def resend_code(client: TelegramClient, phone: str) -> LoginResult:
    """Resend login code."""
    try:
        sent = await client.send_code_request(phone)
        return LoginResult(
            needs_code=True,
            phone_code_hash=sent.phone_code_hash,
        )
    except FloodWaitError as e:
        return LoginResult(error=f"⏳ Please wait {e.seconds} seconds before requesting a new code.")
    except Exception as e:
        logger.exception("resend_code failed")
        return LoginResult(error=f"❌ Error resending code: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Logout
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def logout_account(session_string: str, proxy=None) -> bool:
    """Log out of a Telegram account using its session string."""
    client = create_client(session=session_string, proxy=proxy)
    try:
        await client.connect()
        await client.log_out()
        return True
    except AuthKeyUnregisteredError:
        # Already logged out
        return True
    except Exception:
        logger.exception("logout_account failed")
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deliver account (re-login to get code for delivery)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def request_delivery_code(
    session_string: str,
    phone: str,
    proxy=None,
) -> tuple[TelegramClient | None, LoginResult]:
    """
    For individual delivery: send a login code using the stored session.
    We create a fresh client to request the code.
    """
    client = create_client(proxy=proxy)
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        return client, LoginResult(
            needs_code=True,
            phone_code_hash=sent.phone_code_hash,
        )
    except FloodWaitError as e:
        await client.disconnect()
        return None, LoginResult(error=f"⏳ Please wait {e.seconds} seconds.")
    except Exception as e:
        await client.disconnect()
        logger.exception("request_delivery_code failed")
        return None, LoginResult(error=f"❌ Error: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Session conversion
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def telethon_string_to_session_file(
    session_string: str,
    output_path: Path,
) -> bool:
    """
    Convert a Telethon StringSession to a .session file (SQLite format).
    Returns True on success.
    """
    try:
        # Decode the string session to get auth key + DC info
        data = StringSession(session_string)

        # Create SQLite session file
        db = sqlite3.connect(str(output_path))
        cursor = db.cursor()

        cursor.execute(
            "CREATE TABLE IF NOT EXISTS version (version INTEGER PRIMARY KEY)"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  dc_id INTEGER PRIMARY KEY,"
            "  server_address TEXT,"
            "  port INTEGER,"
            "  auth_key BLOB,"
            "  takeout_id INTEGER"
            ")"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS entities ("
            "  id INTEGER PRIMARY KEY,"
            "  hash INTEGER NOT NULL,"
            "  username TEXT,"
            "  phone INTEGER,"
            "  name TEXT,"
            "  date INTEGER"
            ")"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS sent_files ("
            "  md5_digest BLOB,"
            "  file_size INTEGER,"
            "  type INTEGER,"
            "  id INTEGER,"
            "  hash INTEGER,"
            "  PRIMARY KEY(md5_digest, file_size, type)"
            ")"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS update_state ("
            "  id INTEGER PRIMARY KEY,"
            "  pts INTEGER,"
            "  qts INTEGER,"
            "  date INTEGER,"
            "  seq INTEGER"
            ")"
        )

        # Insert version
        cursor.execute("DELETE FROM version")
        cursor.execute("INSERT INTO version VALUES (7)")

        # Insert session data
        cursor.execute("DELETE FROM sessions")
        cursor.execute(
            "INSERT INTO sessions (dc_id, server_address, port, auth_key) VALUES (?, ?, ?, ?)",
            (data.dc_id, data.server_address, data.port, data.auth_key.key),
        )

        db.commit()
        db.close()
        return True
    except Exception:
        logger.exception("telethon_string_to_session_file failed")
        return False


def telethon_string_to_pyrogram_session(
    session_string: str,
    output_path: Path,
    user_id: int = 0,
) -> bool:
    """
    Convert a Telethon StringSession to a Pyrogram .session file (SQLite).
    Returns True on success.
    """
    try:
        data = StringSession(session_string)

        db = sqlite3.connect(str(output_path))
        cursor = db.cursor()

        cursor.execute(
            "CREATE TABLE IF NOT EXISTS version (number INTEGER PRIMARY KEY)"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  dc_id INTEGER PRIMARY KEY,"
            "  api_id INTEGER,"
            "  test_mode INTEGER,"
            "  auth_key BLOB,"
            "  date INTEGER NOT NULL,"
            "  user_id INTEGER,"
            "  is_bot INTEGER"
            ")"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS peers ("
            "  id INTEGER PRIMARY KEY,"
            "  access_hash INTEGER,"
            "  type TEXT NOT NULL,"
            "  phone_number TEXT,"
            "  last_update_on INTEGER NOT NULL DEFAULT(CAST(strftime('%s','now') AS INTEGER))"
            ")"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS usernames ("
            "  id INTEGER,"
            "  username TEXT,"
            "  FOREIGN KEY(id) REFERENCES peers(id)"
            ")"
        )

        # Version
        cursor.execute("DELETE FROM version")
        cursor.execute("INSERT INTO version VALUES (4)")

        # Session
        cursor.execute("DELETE FROM sessions")
        cursor.execute(
            "INSERT INTO sessions (dc_id, api_id, test_mode, auth_key, date, user_id, is_bot) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                data.dc_id,
                API_ID,
                0,
                data.auth_key.key,
                int(time.time()),
                user_id,
                0,
            ),
        )

        db.commit()
        db.close()
        return True
    except Exception:
        logger.exception("telethon_string_to_pyrogram_session failed")
        return False
