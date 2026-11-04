"""Run the OpenAI demo end to end without needing the webhook.

Creates (or reuses) the OpenAI company in HubSpot and runs the exact same code path
the company.creation webhook triggers: company enrichment, existing contacts,
contact discovery filtered by job title, then contact enrichment.

Usage:  python -m scripts.demo
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings  # noqa: E402
from app.enrichment import EnrichmentService  # noqa: E402

DOMAIN = os.getenv("DEMO_DOMAIN", "openai.com")
NAME = os.getenv("DEMO_COMPANY_NAME", "OpenAI")


async def main() -> None:
    service = EnrichmentService(Settings())
    try:
        await service.ensure_properties()

        found = await service.hubspot.search_objects(
            "companies",
            [{"propertyName": "domain", "operator": "EQ", "value": DOMAIN}],
            ["id", "name", "domain"],
            limit=1,
        )
        if found:
            company_id = str(found[0]["id"])
            print(f"Using existing company {company_id} ({found[0]['properties'].get('name')})")
        else:
            company = await service.hubspot.create_object(
                "companies", {"name": NAME, "domain": DOMAIN}
            )
            company_id = str(company["id"])
            print(f"Created company {company_id}")

        result = await service.enrich_company(company_id, trigger="demo", force=True)
        print(json.dumps(result, indent=2))

        print("\n--- activity log ---")
        for entry in service.activity.recent(60):
            print(f"{entry['at']}  {entry['kind']:<16} {entry['message']}")
        print(f"\nEstimated credits used: {service.credits_spent}")
    finally:
        await service.aclose()


if __name__ == "__main__":
    asyncio.run(main())
