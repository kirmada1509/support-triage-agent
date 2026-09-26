"""Send a demo ticket through the signed webhook, as Pylon would.

uv run python scenarios/send_ticket.py 4
uv run python scenarios/send_ticket.py --subject "..." --body "..."
"""

import argparse
import hashlib
import hmac
import json
import sys
import uuid
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.settings import settings  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("ticket", nargs="?", help="template id from scenarios/tickets.yaml")
    p.add_argument("--subject")
    p.add_argument("--body")
    p.add_argument("--tenant", default="figma-merch")
    a = p.parse_args()

    if a.ticket:
        tickets = yaml.safe_load((Path(__file__).parent / "tickets.yaml").read_text())["tickets"]
        t = next((t for t in tickets if t["id"] == a.ticket), None)
        if t is None:
            sys.exit(f"no ticket {a.ticket!r} in tickets.yaml")
        subject, body = t["subject"], t["body"]
    elif a.subject and a.body:
        subject, body = a.subject, a.body
    else:
        sys.exit("give a template id, or --subject and --body")

    payload = {
        "id": f"T-{uuid.uuid4().hex[:6].upper()}",
        "tenant_id": a.tenant,
        "subject": subject,
        "body": body,
        "requester": "ops@figma-merch.example",
    }
    raw = json.dumps(payload).encode()
    sig = hmac.new(settings.pylon_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    r = httpx.post(
        f"{settings.api_base_url}/webhooks/pylon",
        content=raw,
        headers={"x-pylon-signature": sig, "content-type": "application/json"},
    )
    r.raise_for_status()
    print(f"sent {payload['id']}: {subject}\n  {settings.api_base_url}/tickets/{payload['id']}")


if __name__ == "__main__":
    main()
