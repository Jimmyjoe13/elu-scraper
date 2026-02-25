import json
import os
import aiofiles

CACHE_FILE = "cache_diff.json"

class DiffCacheManager:
    @staticmethod
    async def load() -> dict:
        if not os.path.exists(CACHE_FILE):
            return {}
        async with aiofiles.open(CACHE_FILE, mode="r", encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content) if content else {}

    @staticmethod
    async def save(cache: dict):
        async with aiofiles.open(CACHE_FILE, mode="w", encoding="utf-8") as f:
            await f.write(json.dumps(cache, indent=2))
