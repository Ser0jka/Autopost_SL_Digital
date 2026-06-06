import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_config


async def main() -> None:
    config = get_config()
    if not config.TELETHON_API_ID or not config.TELETHON_API_HASH:
        raise RuntimeError("Set TELETHON_API_ID and TELETHON_API_HASH in .env first")

    client = TelegramClient(
        config.TELETHON_SESSION_NAME,
        config.TELETHON_API_ID,
        config.TELETHON_API_HASH,
    )

    await client.start()
    me = await client.get_me()
    print(f"Telethon session is ready: {me.id} @{me.username or ''}".strip())
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
