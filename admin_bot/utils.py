# admin_bot/utils.py
import aiohttp
from typing import Optional

from aiolimiter import AsyncLimiter

rate_limit = AsyncLimiter(30, 1)  # 30 requests per second

async def validate_telegram_token(token: str) -> Optional[dict]:
    async with rate_limit:
        url = f"https://api.telegram.org/bot{token}/getMe"
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(url) as resp:
                    j = await resp.json()
            except Exception:
                return None
        if not j.get('ok'):
            return None
        return j['result']

async def register_token_to_backend(backend_url: str, token: str, mode: str, owner_tg_id: int) -> dict:
    """POST /admin/register_bot на бекенд. Повертає JSON від бекенду або піднімає Exception."""
    payload = {"token": token, "mode": mode, "owner_tg_ids": [owner_tg_id]}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{str(backend_url).rstrip('/')}/admin/register_bot", json=payload) as resp:
            text = await resp.text()
            try:
                j = await resp.json()
            except Exception:
                raise RuntimeError(f"Backend returned non-json: {resp.status} {text}")
            if resp.status >= 400:
                raise RuntimeError(j.get('detail') or j)
            return j