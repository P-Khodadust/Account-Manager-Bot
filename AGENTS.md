# Repository Guidelines

## Project Structure & Module Organization

`main.py` configures logging, initializes the database, registers aiogram routers, and starts polling. Application code lives under `bot/`:

- `bot/config.py` loads environment variables and defines runtime paths.
- `bot/database.py` contains SQLAlchemy models, migrations, and data-access helpers.
- `bot/handlers/` groups Telegram command, callback, and FSM flows by feature.
- `bot/utils/` contains shared session, proxy, cryptography, keyboard, authorization, and country-detection helpers.

Runtime data is created in `data/` and `sessions/`; neither should be committed. Add tests under `tests/`, mirroring the package structure (for example, `tests/utils/test_country_detector.py`).

## Build, Test, and Development Commands

Use Python 3.11+ and an isolated environment:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

`python main.py` initializes the database and runs long polling. There is no build step. Check syntax without contacting Telegram with `python -m compileall main.py bot`. Run the dependency-free unit suite with `python -m unittest discover -s tests -v`.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation, type annotations for public interfaces, and concise docstrings for non-obvious behavior. Use `snake_case` for modules, functions, variables, and callback identifiers; `PascalCase` for classes; and `UPPER_CASE` for configuration constants. Keep handlers feature-focused and register new routers in `main.py` in deliberate order because FSM matching is order-sensitive. Prefer async database and network operations; do not block the event loop.

## Testing Guidelines

Tests use Python's `unittest` framework. Test utility and database logic independently from Telegram where possible. Name files `test_*.py` and tests `test_<behavior>`. Mock bot, Telethon, Pyrogram, and proxy calls; tests must not use real accounts or credentials. Include regression coverage with bug fixes and exercise both successful and failure paths.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subjects such as `Fix country flag emojis` and `Improve account delivery and session management`. Keep each commit focused and explain behavioral or schema changes in its body. Pull requests should summarize the change, list verification commands, note environment or migration impacts, and link relevant issues. Include screenshots for user-visible Telegram flow changes.

## Security & Configuration

Never commit `.env`, session files, database files, bot tokens, API credentials, proxy passwords, or encryption keys. Update `.env.example` when adding configuration, using placeholders only. Treat logs and test fixtures as sensitive because phone numbers and session identifiers may appear in them.
