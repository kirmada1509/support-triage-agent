"""Pylon reply and internal-note calls, using customer-visible message IDs for threading."""

from html import escape
from urllib.parse import quote

import httpx

from app.settings import settings


async def send_reply(
    token: str,
    issue_id: str,
    body: str,
    requester: str | None,
    client: httpx.AsyncClient | None = None,
    message_id: str | None = None,
) -> str:
    if client is None:
        async with httpx.AsyncClient(base_url=settings.pylon_api_base_url, timeout=20) as owned:
            return await send_reply(token, issue_id, body, requester, owned, message_id)
    path = f"/issues/{quote(issue_id, safe='')}"
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(f"{path}/messages", headers=headers)
    response.raise_for_status()
    messages = response.json().get("data", [])
    public = [m for m in messages if m.get("id") and m.get("is_private") is False]
    selected = next((m for m in public if m["id"] == message_id), None) if message_id else None
    if message_id and selected is None:
        raise ValueError("Pylon message ID is not customer-visible on this issue")
    if selected is None:
        selected = next(
            (m for m in reversed(public) if (m.get("author") or {}).get("contact")), None
        )
    if selected is None:
        raise ValueError("Pylon issue has no customer-visible message to reply to")
    payload = {"message_id": selected["id"], "body_html": escape(body).replace("\n", "<br>")}
    if selected.get("source") == "email" or selected.get("email_info") is not None:
        contact = (selected.get("author") or {}).get("contact") or {}
        recipient = contact.get("email") or requester
        if not recipient:
            raise ValueError("Pylon email reply needs a recipient")
        payload["email_info"] = {"to_emails": [recipient]}
    response = await client.post(f"{path}/reply", headers=headers, json=payload)
    response.raise_for_status()
    message = response.json().get("data", {})
    if not message.get("id"):
        raise ValueError("Pylon reply response has no message ID")
    return message["id"]


async def send_note(
    token: str,
    issue_id: str,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    if client is None:
        async with httpx.AsyncClient(base_url=settings.pylon_api_base_url, timeout=20) as owned:
            return await send_note(token, issue_id, body, owned)
    response = await client.post(
        f"/issues/{quote(issue_id, safe='')}/note",
        headers={"Authorization": f"Bearer {token}"},
        json={"body_html": escape(body).replace("\n", "<br>"), "thread_name": "Account manager"},
    )
    response.raise_for_status()
    note = response.json().get("data", {})
    if not note.get("id"):
        raise ValueError("Pylon note response has no message ID")
    return note["id"]
