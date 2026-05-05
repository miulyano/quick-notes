import os

# Set env vars BEFORE any test imports bot.config (Settings() runs at import time).
# os.environ takes precedence over .env in pydantic-settings, so local secrets
# won't leak into tests.
os.environ["BOT_TOKEN"] = "test_token"
os.environ["ALLOWED_USER_IDS"] = "111,222"

import pytest_asyncio

from bot.storage import db


@pytest_asyncio.fixture
async def fresh_db():
    """Open a clean in-memory DB for each test that touches storage."""
    conn = await db.init_db(":memory:")
    try:
        yield conn
    finally:
        await db.close_db()
