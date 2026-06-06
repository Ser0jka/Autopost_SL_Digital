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
        raise RuntimeError("Set TELETHON_API_ID and TELETHON_API_HASH in .env first")

    client = TelegramClient(
        StringSession(), 
        config.TELETHON_API_ID, 
        config.TELETHON_API_HASH
    )
    
    await client.start()
    print(client.session.save())
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
