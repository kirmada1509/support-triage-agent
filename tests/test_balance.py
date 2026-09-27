"""DeepSeek balance: the adapter checks DeepSeek's answer, the endpoint says when no key is set."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.integrations import deepseek

BALANCE = {
    "is_available": True,
    "balance_infos": [
        {
            "currency": "USD",
            "total_balance": "2.75",
            "granted_balance": "0.00",
            "topped_up_balance": "2.75",
        }
    ],
}


async def test_balance_reads_deepseek_account():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=BALANCE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        account = await deepseek.balance("sk-test", client)
    assert seen == {"url": "https://api.deepseek.com/user/balance", "auth": "Bearer sk-test"}
    assert account.available is True
    assert account.balances == [deepseek.Balance(currency="USD", total=2.75)]


async def test_balance_rejects_an_unexpected_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"balance_infos": "nope"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await deepseek.balance("sk-test", client)


def test_endpoint_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    r = TestClient(main.api).get("/providers/deepseek/balance")
    assert r.status_code == 200
    assert r.json() == {
        "provider": "deepseek",
        "configured": False,
        "available": None,
        "balances": [],
    }


def test_endpoint_with_key(monkeypatch):
    async def fake(key, client=None):
        assert key == "sk-test"
        return deepseek.Account(available=True, balances=[deepseek.Balance("USD", 2.75)])

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(deepseek, "balance", fake)
    r = TestClient(main.api).get("/providers/deepseek/balance")
    assert r.json() == {
        "provider": "deepseek",
        "configured": True,
        "available": True,
        "balances": [{"currency": "USD", "total": 2.75}],
    }


def test_endpoint_reports_deepseek_failure(monkeypatch):
    async def fake(key, client=None):
        raise httpx.ConnectError("down")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(deepseek, "balance", fake)
    assert TestClient(main.api).get("/providers/deepseek/balance").status_code == 502
