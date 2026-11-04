"""Fill in missing work emails for contacts that Forager already matched.

Useful right before recording the demo: work-email jobs queue upstream at Forager, so a
contact can be fully enriched but still have no email. This script re-runs only the email
lookup (no credits are spent on person or phone lookups again) and patches the contact
when an address comes back.

Usage:
  python -m scripts.backfill_emails              # contacts missing an email
  python -m scripts.backfill_emails --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings  # noqa: E402
from app.enrichment import EnrichmentService, norm_domain, pick_role  # noqa: E402

PROPS = ["email", "firstname", "lastname", "forager_person_id", "hs_linkedin_url", "company"]


async def main(limit: int) -> None:
    service = EnrichmentService(Settings())
    try:
        contacts = await service.hubspot.search_objects(
            "contacts",
            [
                {"propertyName": "forager_person_id", "operator": "HAS_PROPERTY"},
                {"propertyName": "email", "operator": "NOT_HAS_PROPERTY"},
            ],
            PROPS,
            limit=limit,
        )
        print(f"{len(contacts)} contact(s) missing an email")
        for row in contacts:
            cid = str(row["id"])
            props = row.get("properties") or {}
            person_id = props.get("forager_person_id")
            person = await service.forager.person_detail(person_id=person_id)
            if not person:
                print(f"- {cid}: no Forager person record")
                continue
            role = pick_role(person.get("roles") or [])
            domain = norm_domain(((role or {}).get("organization") or {}).get("domain", ""))
            email = await service.lookup_work_email(person, props, domain, contact_id=cid)
            if email:
                await service.hubspot.update_object("contacts", cid, {"email": email})
                print(f"+ {props.get('firstname')} {props.get('lastname')}: {email}")
            else:
                print(
                    f"~ {props.get('firstname')} {props.get('lastname')}: still queued at Forager"
                    " (the running service polls it, or use PUBLIC_BASE_URL for the callback)"
                )
    finally:
        await service.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.limit))
