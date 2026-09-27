"""DeepSeek account balance, so the console can show how much credit the demo has left."""

from dataclasses import dataclass

import httpx

from app.settings import settings


@dataclass(frozen=True)
class Balance:
    currency: str
    total: float


@dataclass(frozen=True)
class Account:
    available: bool  # DeepSeek's is_available: whether the balance covers API calls
    balances: list[Balance]


async def balance(key: str, client: httpx.AsyncClient | None = None) -> Account:
    if client is None:
        async with httpx.AsyncClient(timeout=10) as owned:
            return await balance(key, owned)
    response = await client.get(
        f"{settings.deepseek_api_url}/user/balance", headers={"Authorization": f"Bearer {key}"}
    )
    response.raise_for_status()
    payload = response.json()
    infos = payload.get("balance_infos")
    if not isinstance(infos, list):
        raise ValueError(f"unexpected DeepSeek balance answer: {payload!r}")
    return Account(
        available=bool(payload.get("is_available")),
        balances=[Balance(str(i["currency"]), float(i["total_balance"])) for i in infos],
    )
