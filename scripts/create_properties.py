"""Create the custom HubSpot properties this service writes to.

Usage:  python -m scripts.create_properties
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings  # noqa: E402
from app.enrichment import EnrichmentService  # noqa: E402


async def main() -> None:
    service = EnrichmentService(Settings())
    try:
        result = await service.ensure_properties()
        print("created :", result["created"])
        print("existing:", result["existing"])
    finally:
        await service.aclose()


if __name__ == "__main__":
    asyncio.run(main())
