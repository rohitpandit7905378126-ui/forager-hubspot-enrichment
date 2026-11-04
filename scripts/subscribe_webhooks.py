"""Register HubSpot webhook subscriptions for this private app via the API.

Two ways to get the webhook live:

1. UI (simplest): Settings -> Integrations -> Private Apps -> your app ->
   Webhooks tab -> target URL = https://<your-service>/webhooks/hubspot ->
   subscribe to Company "Creation" and Contact "Creation".

2. This script: set HUBSPOT_APP_ID (the private app id, visible in the app's URL,
   e.g. .../private-apps/1234567) and PUBLIC_BASE_URL, then run:
       python -m scripts.subscribe_webhooks

Usage:  HUBSPOT_APP_ID=1234567 PUBLIC_BASE_URL=https://xxx.up.railway.app python -m scripts.subscribe_webhooks
"""
from __future__ import annotations

import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

API = "https://api.hubapi.com"
EVENT_TYPES = ["company.creation", "contact.creation"]


async def main() -> None:
    token = os.getenv("HUBSPOT_PRIVATE_APP_TOKEN", "")
    app_id = os.getenv("HUBSPOT_APP_ID", "").strip()
    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

    if not token:
        raise SystemExit("HUBSPOT_PRIVATE_APP_TOKEN is missing")
    if not app_id:
        raise SystemExit("HUBSPOT_APP_ID is missing (private app id from the app settings URL)")
    if not base_url:
        raise SystemExit("PUBLIC_BASE_URL is missing, e.g. https://forager-hubspot.up.railway.app")

    target = f"{base_url}/webhooks/hubspot"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        settings_resp = await client.put(
            f"{API}/webhooks/v3/{app_id}/settings",
            headers=headers,
            json={"targetUrl": target, "maxConcurrentRequests": 10},
        )
        print("settings:", settings_resp.status_code, settings_resp.text[:300])

        for event_type in EVENT_TYPES:
            resp = await client.post(
                f"{API}/webhooks/v3/{app_id}/subscriptions",
                headers=headers,
                json={
                    "eventType": event_type,
                    "active": True,
                    "properties": [],
                },
            )
            print(f"subscription {event_type}:", resp.status_code, resp.text[:300])


if __name__ == "__main__":
    asyncio.run(main())
