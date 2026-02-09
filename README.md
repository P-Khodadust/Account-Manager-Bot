# Telegram Account Manager Bot

A powerful Telegram bot for storing, managing, and delivering Telegram accounts with multi-user support, country-based categorization, and SOCKS5 proxy integration.

## Features

- **Account Management** — Add Telegram accounts via login flow (phone + code + optional 2FA)
- **Automatic Country Detection** — Detects country from phone prefix with special Canada/USA area code handling
- **Date-based Categorization** — Accounts grouped by country and date added
- **Two Delivery Methods:**
  - Individual account delivery with login code
  - Bulk session file export (Telethon / Pyrogram formats) as ZIP
- **SOCKS5 Proxy Support** — Per-user proxy configuration for all operations
- **Multi-User Access Control** — Admin whitelist system with isolated data per user
- **Real-time Statistics** — Breakdown by country and date
- **Modern UI** — Glass-style buttons with emojis throughout

## Project Structure

```
Account Manager/
├── main.py                    # Entry point
├── bot/
│   ├── config.py              # Configuration (loads .env)
│   ├── database.py            # SQLAlchemy models & CRUD operations
│   ├── handlers/
│   │   ├── start.py           # /start command & main menu
│   │   ├── add_account.py     # Account addition flow (FSM)
│   │   ├── add_user.py        # User management (admin)
│   │   ├── statistics.py      # Statistics display
│   │   ├── deliver.py         # Individual & bulk delivery
│   │   └── proxy.py           # SOCKS5 proxy management
│   └── utils/
│       ├── country_detector.py # Phone → country detection
│       ├── keyboards.py        # Inline keyboard builders
│       ├── session_manager.py  # Telethon session operations
│       └── decorators.py       # Auth access control
├── requirements.txt
├── .env.example
└── .gitignore
```

## Prerequisites

- Python 3.11+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Telegram API credentials (from [my.telegram.org](https://my.telegram.org))

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/account-manager-bot.git
cd account-manager-bot
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable       | Description                                  |
| -------------- | -------------------------------------------- |
| `BOT_TOKEN`    | Telegram bot token from @BotFather           |
| `API_ID`       | Telegram API ID from my.telegram.org         |
| `API_HASH`     | Telegram API hash from my.telegram.org       |
| `ADMIN_ID`     | Your Telegram numeric user ID                |
| `DATABASE_URL` | Database connection string (default: SQLite) |

### 5. Run the Bot

```bash
python main.py
```

## Usage

### For Admins

1. Start the bot with `/start`
2. Use **Manage Users** to add authorized Telegram user IDs
3. Add proxies via **Proxy Settings** before adding accounts
4. Use **Grant Account Access** to add Telegram accounts

### For Authorized Users

1. Configure your proxy in **Proxy Settings**
2. Add accounts with **Grant Account Access**
3. View metrics in **Statistics**
4. Export accounts via **Deliver Accounts**

### Delivery Methods

**Individual:** Select country → date → account → receive login code → get session

**Bulk:** Choose format (Telethon/Pyrogram) → country → date → quantity → receive ZIP file

## Database

Default: SQLite (stored in `data/bot.db`). To use PostgreSQL, update `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname
```

And install the async driver:

```bash
pip install asyncpg
```

## Deployment on Ubuntu 24

```bash
# Install Python
sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip -y

# Setup
git clone https://github.com/your-username/account-manager-bot.git
cd account-manager-bot
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # fill in your values

# Run with systemd
sudo tee /etc/systemd/system/account-bot.service << 'EOF'
[Unit]
Description=Telegram Account Manager Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/account-manager-bot
ExecStart=/home/ubuntu/account-manager-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable account-bot
sudo systemctl start account-bot

# Check status
sudo systemctl status account-bot
journalctl -u account-bot -f
```

## Security Notes

- Session strings are stored in the database — keep your database secure
- Never share your `.env` file
- The `.gitignore` excludes sensitive files by default
- Set `ENCRYPTION_KEY` in `.env` for an additional layer of session protection
- Use proxy rotation to avoid Telegram rate limits and bans

## License

MIT
