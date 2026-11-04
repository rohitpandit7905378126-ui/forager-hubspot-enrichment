#!/usr/bin/env python3
"""Replay a HubSpot-shaped webhook event against the deployed receiver.

Why this exists
---------------
A legacy private app can only have webhook subscriptions edited by hand in the HubSpot
UI; there is no API to create them. When that UI is not available on an account, this
script sends the *exact* payload shape HubSpot sends, so the receiver under test is the
same code path the real subscription would hit. Say that out loud in the demo: it is a
replay of HubSpot's payload, not a faked result.

Usage
-----
    # company.creation for a real company id
    python scripts/replay_hubspot_webhook.py company.creation 360217205438

    # contact.creation
    python scripts/replay_hubspot_webhook.py contact.creation 584752293622

    # point somewhere else / sign the request
    BASE_URL=http://localhost:8000 HUBSPOT_CLIENT_SECRET=... \
        python scripts/replay_hubspot_webhook.py company.creation 123

If HUBSPOT_CLIENT_SECRET is set the request is signed with the v3 scheme HubSpot uses
(HMAC-SHA256 over method + uri + body + timestamp). That is what proves the 401 path:
run once with a wrong secret, once with the right one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://web-production-2f924.up.railway.app"
WEBHOOK_PATH = "/webhooks/hubspot"
PORTAL_ID = 247887031


def build_event(subscription_type: str, object_id: str) -> list[dict]:
    return [
        {
            "objectId": int(object_id) if object_id.isdigit() else object_id,
            "propertyName": "hs_object_id",
            "propertyValue": str(object_id),
            "changeSource": "CRM",
            "eventId": int(time.time() * 1000),
            "subscriptionId": 1,
            "portalId": PORTAL_ID,
            "appId": 1,
            "occurredAt": int(time.time() * 1000),
            "subscriptionType": subscription_type,
            "attemptNumber": 0,
        }
    ]


def sign(secret: str, method: str, uri: str, body: bytes, timestamp: str) -> str:
    source = f"{method}{uri}{body.decode()}{timestamp}".encode()
    return hmac.new(secret.encode(), source, hashlib.sha256).hexdigest()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    subscription_type, object_id = sys.argv[1], sys.argv[2]
    base_url = os.environ.get("BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    secret = os.environ.get("HUBSPOT_CLIENT_SECRET", "")

    body = json.dumps(build_event(subscription_type, object_id)).encode()
    url = base_url + WEBHOOK_PATH
    headers = {"Content-Type": "application/json"}
    if secret:
        timestamp = str(int(time.time() * 1000))
        headers["X-HubSpot-Signature-v3"] = sign(secret, "POST", WEBHOOK_PATH, body, timestamp)
        headers["X-HubSpot-Request-Timestamp"] = timestamp

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    print(f"POST {url}")
    print(f"  event: {subscription_type}  objectId: {object_id}  signed: {bool(secret)}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"  {response.status} {response.read().decode()}")
    except urllib.error.HTTPError as exc:  # 401 for a bad signature is the point
        print(f"  {exc.code} {exc.read().decode()}")

    print(f"\nWatch the result land:  {base_url}/activity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
