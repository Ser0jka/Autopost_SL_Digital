import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_config


async def main() -> None:
    config = get_config()
    if not config.TELETHON_API_ID or not config.TELETHON_API_HASH:
        raise RuntimeError("Set TELETHON_API_ID and TELETHON_API_HASH first")

    client = TelegramClient(
        config.TELETHON_SESSION_NAME,
        config.TELETHON_API_ID,
        config.TELETHON_API_HASH,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "File session is not authorized. Run scripts/login_telethon.py locally first."
            )
        session_string = StringSession.save(client.session)
        print(session_string)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
