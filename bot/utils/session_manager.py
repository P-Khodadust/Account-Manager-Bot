"""
Telethon session management:
  - Client creation with proxy support
  - Login code request / submission / 2FA
  - Background code listener for account delivery (Issue #1)
  - Account logout
  - Session format conversion (Telethon / Pyrogram files)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    UserDeactivatedBanError,
)
from telethon.tl.functions.auth import LogOutRequest

from bot.config import API_ID, API_HASH

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class CodeResult:
    """Result of a login / code submission operation."""

    success: bool = False
    needs_code: bool = False
    needs_2fa: bool = False
    error: str | None = None
    phone_code_hash: str | None = None
    session_string: str | None = None
    user_info: dict | None = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Active Code Listeners (module-level registry)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Maps user_id -> listener info dict
_active_listeners: dict[int, dict[str, Any]] = {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Client Factory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _build_proxy_kwargs(proxy) -> dict:
    """Convert a Proxy ORM object to Telethon-compatible proxy kwargs."""
    if proxy is None:
        return {}
    try:
        import socks

        proxy_type = socks.SOCKS5
    except ImportError:
        # Fallback: numeric value for SOCKS5 (PySocks convention)
        proxy_type = 2

    proxy_tuple: tuple
    if proxy.username:
        proxy_tuple = (
            proxy_type,
            proxy.host,
            proxy.port,
            True,
            proxy.username,
            proxy.password or "",
        )
    else:
        proxy_tuple = (proxy_type, proxy.host, proxy.port, True)

    return {"proxy": proxy_tuple}


def create_client(
    session: str | None = None,
    proxy=None,
) -> TelegramClient:
    """Create a Telethon client with optional StringSession and proxy."""
    sess = StringSession(session) if session else StringSession()
    kwargs = _build_proxy_kwargs(proxy)
    client = TelegramClient(sess, API_ID, API_HASH, **kwargs)
    return client


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Account Addition Flow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def request_code(
    phone: str,
    proxy=None,
) -> tuple[TelegramClient, CodeResult]:
    """Send a login code request to the given phone number.

    Used during the *account addition* flow (the bot actively sends the code).
    Returns ``(client, result)``.
    """
    client = create_client(proxy=proxy)
    result = CodeResult()

    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        result.needs_code = True
        result.phone_code_hash = sent.phone_code_hash
        return client, result

    except FloodWaitError as e:
        result.error = (
            f"\u23f3 Too many attempts. Please wait <b>{e.seconds}</b> seconds."
        )
        return client, result

    except Exception as e:
        logger.exception("Error requesting code for %s", phone)
        result.error = f"\u274c Error: {e}"
        return client, result


async def submit_code(
    client: TelegramClient,
    phone: str,
    code: str,
    phone_code_hash: str,
) -> CodeResult:
    """Submit the login code received by the user."""
    result = CodeResult()

    try:
        await client.sign_in(
            phone=phone, code=code, phone_code_hash=phone_code_hash
        )
        me = await client.get_me()
        result.success = True
        result.session_string = client.session.save()
        result.user_info = {
            "id": me.id,
            "first_name": me.first_name or "",
            "username": me.username or "",
        }
        return result

    except SessionPasswordNeededError:
        result.needs_2fa = True
        return result

    except PhoneCodeInvalidError:
        result.error = "\u274c Invalid code. Please try again."
        return result

    except PhoneCodeExpiredError:
        result.error = "\u23f0 Code expired. Please request a new one."
        return result

    except FloodWaitError as e:
        result.error = f"\u23f3 Too many attempts. Wait <b>{e.seconds}s</b>."
        return result

    except Exception as e:
        logger.exception("Error submitting code")
        result.error = f"\u274c Error: {e}"
        return result


async def submit_2fa(
    client: TelegramClient,
    password: str,
) -> CodeResult:
    """Submit 2FA cloud password."""
    result = CodeResult()

    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        result.success = True
        result.session_string = client.session.save()
        result.user_info = {
            "id": me.id,
            "first_name": me.first_name or "",
            "username": me.username or "",
        }
        return result

    except PasswordHashInvalidError:
        result.error = "\u274c Wrong password. Please try again."
        return result

    except FloodWaitError as e:
        result.error = f"\u23f3 Too many attempts. Wait <b>{e.seconds}s</b>."
        return result

    except Exception as e:
        logger.exception("Error submitting 2FA")
        result.error = f"\u274c Error: {e}"
        return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Issue #1 — Background Code Listener for Delivery
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def start_code_listener(
    session_string: str,
    phone: str,
    account_id: int,
    user_id: int,
    bot,
    chat_id: int,
    proxy=None,
    timeout: int = 300,
    has_next: bool = False,
) -> tuple[bool, str | None]:
    """
    Connect to the account and listen for incoming login codes from
    Telegram (user ID 777000).

    When a code arrives the bot sends it to the user automatically.
    Returns ``(success, error_message)``.
    """
    # Stop any existing listener for this user first
    await stop_code_listener(user_id)

    try:
        client = create_client(session=session_string, proxy=proxy)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return False, (
                "\u274c Session has expired. The account may need to be "
                "re-added."
            )

    except AuthKeyUnregisteredError:
        return False, (
            "\u274c Session is no longer valid. Please re-add the account."
        )
    except UserDeactivatedBanError:
        return False, (
            "\u274c This account has been banned or deactivated."
        )
    except Exception as e:
        logger.exception("Error connecting to account %s", phone)
        return False, f"\u274c Connection error: {e}"

    # --- Set up event-based code capture ---
    code_event = asyncio.Event()
    captured: dict[str, str | None] = {"code": None}

    @client.on(events.NewMessage(from_users=777000))
    async def _on_login_code(event):  # type: ignore[misc]
        text = event.raw_text or ""
        match = re.search(r"(\d{5,6})", text)
        if match and not code_event.is_set():
            captured["code"] = match.group(1)
            code_event.set()

    # --- Background task that waits for the code ---
    async def _listener_task() -> None:
        try:
            await asyncio.wait_for(code_event.wait(), timeout=timeout)
            if captured["code"]:
                from bot.utils.keyboards import code_received_kb

                await bot.send_message(
                    chat_id,
                    (
                        "\U0001f511 <b>Login Code Captured!</b>\n"
                        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                        f"\U0001f4f1  Phone: <b>{phone}</b>\n"
                        f"\U0001f510  Code: <code>{captured['code']}</code>"
                        "\n\n"
                        "\U0001f4cb <i>Tap the code to copy it.</i>"
                    ),
                    parse_mode="HTML",
                    reply_markup=code_received_kb(
                        account_id, has_next=has_next
                    ),
                )
        except asyncio.TimeoutError:
            from bot.utils.keyboards import account_actions_kb

            await bot.send_message(
                chat_id,
                (
                    "\u23f0 <b>Listener Timed Out</b>\n"
                    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                    f"No login code was received for\n"
                    f"<b>{phone}</b> within "
                    f"{timeout // 60} minutes.\n\n"
                    "You can try again using the button below."
                ),
                parse_mode="HTML",
                reply_markup=account_actions_kb(
                    account_id, has_next=has_next
                ),
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Listener task error for account %s", phone)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            _active_listeners.pop(user_id, None)

    task = asyncio.create_task(_listener_task())
    _active_listeners[user_id] = {
        "client": client,
        "task": task,
        "account_id": account_id,
        "phone": phone,
    }
    return True, None


async def stop_code_listener(user_id: int) -> None:
    """Stop any active code listener for the given user."""
    info = _active_listeners.pop(user_id, None)
    if info:
        info["task"].cancel()
        try:
            await info["client"].disconnect()
        except Exception:
            pass


def is_listener_active(user_id: int) -> bool:
    """Check whether a listener is running for a user."""
    return user_id in _active_listeners


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Account Logout
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2FA Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_account_has_2fa(
    session_string: str,
    proxy=None,
) -> bool | None:
    """Check whether an account has 2FA enabled.

    Returns ``True`` / ``False``, or ``None`` if the check failed.
    """
    client = create_client(session=session_string, proxy=proxy)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return None
        from telethon.tl.functions.account import GetPasswordRequest

        pwd = await client(GetPasswordRequest())
        return pwd.has_password
    except Exception:
        logger.exception("Error checking 2FA status")
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def enable_2fa_on_account(
    session_string: str,
    password: str,
    proxy=None,
) -> tuple[bool, str]:
    """Enable 2FA on an account.

    Returns ``(success, reason)`` where *reason* is one of:
    ``"enabled"``, ``"already_has_2fa"``, ``"session_expired"``,
    ``"flood_wait:N"``, or an error string.
    """
    client = create_client(session=session_string, proxy=proxy)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "session_expired"

        from telethon.tl.functions.account import (
            GetPasswordRequest,
            UpdatePasswordSettingsRequest,
        )
        from telethon.tl.types import InputCheckPasswordEmpty
        from telethon.tl.types.account import PasswordInputSettings
        from telethon.password import compute_digest

        pwd = await client(GetPasswordRequest())

        if pwd.has_password:
            return False, "already_has_2fa"

        # Extend salt1 with 32 random bytes (required by Telegram)
        pwd.new_algo.salt1 += os.urandom(32)
        new_hash = compute_digest(pwd.new_algo, password)

        await client(
            UpdatePasswordSettingsRequest(
                password=InputCheckPasswordEmpty(),
                new_settings=PasswordInputSettings(
                    new_algo=pwd.new_algo,
                    new_password_hash=new_hash,
                    hint="",
                ),
            )
        )
        return True, "enabled"

    except FloodWaitError as e:
        return False, f"flood_wait:{e.seconds}"
    except Exception as e:
        logger.exception("Error enabling 2FA")
        return False, str(e)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def disable_2fa_on_account(
    session_string: str,
    password: str,
    proxy=None,
) -> tuple[bool, str]:
    """Disable 2FA on an account.

    Returns ``(success, reason)`` where *reason* is one of:
    ``"disabled"``, ``"no_2fa"``, ``"wrong_password"``,
    ``"session_expired"``, ``"flood_wait:N"``, or an error string.
    """
    client = create_client(session=session_string, proxy=proxy)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "session_expired"

        from telethon.tl.functions.account import (
            GetPasswordRequest,
            UpdatePasswordSettingsRequest,
        )
        from telethon.tl.types.account import PasswordInputSettings
        from telethon.password import compute_check

        pwd = await client(GetPasswordRequest())

        if not pwd.has_password:
            return False, "no_2fa"

        check = compute_check(pwd, password)

        await client(
            UpdatePasswordSettingsRequest(
                password=check,
                new_settings=PasswordInputSettings(
                    new_algo=pwd.new_algo,
                    new_password_hash=b"",
                    hint="",
                ),
            )
        )
        return True, "disabled"

    except PasswordHashInvalidError:
        return False, "wrong_password"
    except FloodWaitError as e:
        return False, f"flood_wait:{e.seconds}"
    except Exception as e:
        logger.exception("Error disabling 2FA")
        return False, str(e)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Terminate Other Sessions (keep bot's session only)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def terminate_other_sessions(
    session_string: str,
    proxy=None,
) -> tuple[bool, int, str]:
    """Kill all sessions except the bot's own session for an account.

    Returns ``(success, terminated_count, error_or_empty_str)``.
    """
    client = create_client(session=session_string, proxy=proxy)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, 0, "session_expired"

        from telethon.tl.functions.account import (
            GetAuthorizationsRequest,
            ResetAuthorizationRequest,
        )

        auths = await client(GetAuthorizationsRequest())
        terminated = 0

        for auth in auths.authorizations:
            # Skip the current (bot's) session
            if getattr(auth, "current", False) or auth.hash == 0:
                continue
            try:
                await client(ResetAuthorizationRequest(hash=auth.hash))
                terminated += 1
            except Exception:
                pass  # individual termination errors are non-fatal

        return True, terminated, ""

    except Exception as e:
        logger.exception("Error terminating other sessions")
        return False, 0, str(e)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Account Logout
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def logout_account(session_string: str, proxy=None) -> bool:
    """Log out of an account and invalidate the session."""
    try:
        client = create_client(session=session_string, proxy=proxy)
        await client.connect()
        await client(LogOutRequest())
        await client.disconnect()
        return True
    except Exception:
        logger.exception("Error during logout")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Session Format Conversion
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def telethon_string_to_session_file(
    session_string: str,
    output_path: Path,
) -> bool:
    """Convert a Telethon StringSession to a ``.session`` SQLite file."""
    try:
        data = StringSession(session_string)

        conn = sqlite3.connect(str(output_path))
        c = conn.cursor()

        c.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  dc_id INTEGER PRIMARY KEY,"
            "  server_address TEXT,"
            "  port INTEGER,"
            "  auth_key BLOB,"
            "  takeout_id INTEGER"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS entities ("
            "  id INTEGER PRIMARY KEY,"
            "  hash INTEGER NOT NULL,"
            "  username TEXT,"
            "  phone TEXT,"
            "  name TEXT,"
            "  date INTEGER"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS sent_files ("
            "  md5_digest BLOB,"
            "  file_size INTEGER,"
            "  type INTEGER,"
            "  id INTEGER,"
            "  hash INTEGER,"
            "  PRIMARY KEY (md5_digest, file_size, type)"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS update_state ("
            "  id INTEGER PRIMARY KEY,"
            "  pts INTEGER,"
            "  qts INTEGER,"
            "  date INTEGER,"
            "  seq INTEGER"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS version "
            "(version INTEGER PRIMARY KEY)"
        )
        c.execute("INSERT OR REPLACE INTO version VALUES (7)")

        # auth_key is an AuthKey object; extract raw bytes via .key
        auth_key_bytes = (
            data.auth_key.key
            if hasattr(data.auth_key, "key")
            else bytes(data.auth_key)
        )
        c.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?)",
            (
                data.dc_id,
                data.server_address,
                data.port,
                auth_key_bytes,
                None,
            ),
        )

        conn.commit()
        conn.close()
        return True

    except Exception:
        logger.exception("Error converting to Telethon session file")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Session Validation (auto-detection of removed / invalid accounts)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def validate_session(
    session_string: str,
    proxy=None,
) -> str:
    """
    Quick health-check for a stored session.

    Returns a status string:
      * ``"active"``  – session is valid and authorised
      * ``"removed"`` – auth key unregistered (user removed the session)
      * ``"invalid"`` – account deactivated / banned
      * ``"unknown"`` – could not determine (network error, etc.)
    """
    client = create_client(session=session_string, proxy=proxy)
    try:
        await client.connect()
        if await client.is_user_authorized():
            return "active"
        return "invalid"
    except AuthKeyUnregisteredError:
        return "removed"
    except UserDeactivatedBanError:
        return "invalid"
    except Exception:
        # Network errors, timeouts, etc. — assume still valid to
        # avoid false positives.
        return "unknown"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def telethon_string_to_pyrogram_session(
    session_string: str,
    output_path: Path,
    user_id: int = 0,
) -> bool:
    """Convert a Telethon StringSession to a Pyrogram ``.session`` file."""
    try:
        data = StringSession(session_string)

        conn = sqlite3.connect(str(output_path))
        c = conn.cursor()

        c.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  dc_id INTEGER,"
            "  api_id INTEGER,"
            "  test_mode INTEGER,"
            "  auth_key BLOB,"
            "  date INTEGER NOT NULL DEFAULT 0,"
            "  user_id INTEGER NOT NULL DEFAULT 0,"
            "  is_bot INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS peers ("
            "  id INTEGER PRIMARY KEY,"
            "  access_hash INTEGER,"
            "  type TEXT NOT NULL,"
            "  username TEXT,"
            "  phone_number TEXT,"
            "  last_update_on INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS usernames ("
            "  id INTEGER,"
            "  username TEXT,"
            "  FOREIGN KEY (id) REFERENCES peers(id)"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS version "
            "(number INTEGER PRIMARY KEY)"
        )
        c.execute("INSERT OR REPLACE INTO version VALUES (4)")

        auth_key_bytes = (
            data.auth_key.key
            if hasattr(data.auth_key, "key")
            else bytes(data.auth_key)
        )
        c.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                data.dc_id,
                API_ID,
                0,
                auth_key_bytes,
                0,
                user_id,
                0,
            ),
        )

        conn.commit()
        conn.close()
        return True

    except Exception:
        logger.exception("Error converting to Pyrogram session file")
        return False
