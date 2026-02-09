"""
Bot configuration — loads settings from .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "data"
SESSIONS_DIR = BASE_DIR / "sessions"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)

# ── Load environment ─────────────────────────────────────────────────
load_dotenv(ENV_PATH)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}\n"
            f"Copy .env.example → .env and fill in your values."
        )
    return value


# ── Telegram Bot ─────────────────────────────────────────────────────
BOT_TOKEN: str = _require("BOT_TOKEN")

# ── Telegram API (for Telethon / Pyrogram) ───────────────────────────
API_ID: int = int(_require("API_ID"))
API_HASH: str = _require("API_HASH")

# ── Admin ────────────────────────────────────────────────────────────
ADMIN_ID: int = int(_require("ADMIN_ID"))

# ── Database ─────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{DATA_DIR / 'bot.db'}",
)

# ── Encryption ───────────────────────────────────────────────────────
ENCRYPTION_KEY: str | None = os.getenv("ENCRYPTION_KEY") or None
