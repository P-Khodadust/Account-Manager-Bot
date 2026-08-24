# Repository Guidelines

## What This Is

Telegram account-manager bot (aiogram 3.x) that stores/delivers Telegram accounts via session strings. `main.py` is the entry point: logging, DB init, router registration, polling, plus a background task that validates sessions every 6 hours. Code lives under `bot/`:

- `bot/config.py` — env loading (`BOT_TOKEN`, `API_ID`, `API_HASH`, `ADMIN_ID`, `DATABASE_URL`) and paths
- `bot/database.py` — SQLAlchemy async models, CRUD, **and all migrations**
- `bot/handlers/` — one module per feature flow (start, add_account, add_user, statistics, deliver, proxy, twofa)
- `bot/utils/` — shared helpers: session_manager (Telethon), crypto, keyboards, decorators (auth), country_detector, status_workflow

## Critical Gotchas

- **Env vars are required at import time**: `bot/config.py` raises `RuntimeError` on import if `BOT_TOKEN`/`API_ID`/`API_HASH`/`ADMIN_ID` are missing. Anything importing it transitively fails without `.env`. To keep code testable, put pure logic in dependency-free modules (like `bot/utils/status_workflow.py`) and keep Telegram/DB imports out of them.
- **Migrations are hand-rolled** — there is no Alembic. Schema changes require adding a migration step to `run_migrations()` in `bot/database.py` (see `_migrate_accounts_table`, `_add_twofa_columns` for the inspect-then-alter pattern).
- **FSM router order matters**: routers are registered in `main.py`; first match wins for FSM states, so add new routers deliberately.
- **Default parse mode is HTML** (set via `DefaultBotProperties`) — message text uses HTML tags, not Markdown.
- **2FA passwords are Fernet-encrypted with a key derived from `BOT_TOKEN`** (`bot/utils/crypto.py`). Changing `BOT_TOKEN` breaks decryption of stored passwords. `ENCRYPTION_KEY` is loaded in config but currently unused.
- `data/` and `sessions/` are auto-created at import and gitignored; both hold sensitive runtime state (DB, session files).

## Commands

```bash
python -m compileall main.py bot          # syntax check without touching Telegram
python -m unittest discover -s tests -v   # unit suite (dependency-free, runs without .env)
```

Run the app: Python 3.11+ venv, `pip install -r requirements.txt`, `cp .env.example .env`, then `python main.py` (initializes DB, runs migrations, starts long polling). No build step, no lint/typecheck tooling configured.

## Conventions

- PEP 8, four-space indent, type annotations on public interfaces.
- Handlers stay feature-focused; prefer async DB/network operations — never block the event loop.
- Tests use `unittest`, live flat in `tests/test_*.py`, and must not hit Telegram, real accounts, or credentials — mock Telethon/Pyrogram/bot/proxy calls. Cover failure paths and regressions alongside fixes.

## Commits & Security

Short imperative subjects (`Fix country flag emojis`, `Improve account delivery...`), focused commits, behavioral/schema changes explained in the body.

Never commit `.env`, session files, database files, tokens, or proxy credentials. Update `.env.example` (placeholders only) when adding config. Logs and fixtures may contain phone numbers/session IDs — treat them as sensitive.
