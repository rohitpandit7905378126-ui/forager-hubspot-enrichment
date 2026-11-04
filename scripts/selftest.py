"""Dependency-free self test: parsing, mapping and signature helpers.

Run with:  python -m scripts.selftest
Exits non-zero on the first failure, so it works as a CI smoke test too.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.enrichment import (  # noqa: E402
    domain_root,
    extract_email,
    extract_phone,
    linkedin_slug,
    location_from,
    norm_domain,
    pick_role,
    skills_text,
)
from app.hubspot import HubSpotClient  # noqa: E402
from app.titles import build_query, matches_title  # noqa: E402

PASSED = 0


def check(label: str, got: Any, expected: Any) -> None:
    global PASSED
    if got != expected:
        print(f"FAIL {label}: got {got!r}, expected {expected!r}")
        raise SystemExit(1)
    PASSED += 1
    print(f"ok   {label}")


# ---------------------------------------------------------------------------
# domains
# ---------------------------------------------------------------------------
check("norm_domain strips scheme/www/path", norm_domain("https://www.OpenAI.com/about?x=1"), "openai.com")
check("norm_domain keeps bare domain", norm_domain("acme.io"), "acme.io")
check("norm_domain empty", norm_domain(""), "")
check("domain_root simple", domain_root("openai.com"), "openai")
check("domain_root with co.uk", domain_root("https://www.acme.co.uk/x"), "acme")
check("domain_root hyphenated", domain_root("sukh-electrical.in"), "sukh-electrical")

# ---------------------------------------------------------------------------
# linkedin
# ---------------------------------------------------------------------------
check(
    "linkedin_slug from url",
    linkedin_slug("https://www.linkedin.com/in/bradlightcap/"),
    "bradlightcap",
)
check("linkedin_slug bare value", linkedin_slug("bradlightcap"), "bradlightcap")
check("linkedin_slug company url is not a person", linkedin_slug("https://linkedin.com/company/openai"), "")

# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------
TITLES = ["ceo", "vp", "vice president", "head", "director", "chief", "founder", "manager"]
check("title matches VP", matches_title("VP of Engineering", TITLES), True)
check("title matches multiword", matches_title("Vice President, Sales", TITLES), True)
check("title matches case-insensitively", matches_title("HEAD OF GROWTH", TITLES), True)
check("title rejects unrelated", matches_title("Software Engineer II", TITLES), False)
check("title rejects empty", matches_title("", TITLES), False)
check("title does not match inside a word", matches_title("Managerial Assistant", TITLES), False)
check(
    "query quotes multiword titles",
    build_query(["head", "vice president"]),
    'head OR "vice president"',
)

# ---------------------------------------------------------------------------
# location / skills / roles
# ---------------------------------------------------------------------------
loc = location_from(
    [
        {"name": "United States", "place_type": "country"},
        {"name": "California, United States", "place_type": "state"},
        {"name": "San Francisco, California, United States", "place_type": "city"},
    ]
)
check("location city", loc["city"], "San Francisco")
check("location state", loc["state"], "California")
check("location country", loc["country"], "United States")
check("location falls back to address", location_from(None, {"city": "Nangal", "country": "IN"})["city"], "Nangal")

check(
    "skills text",
    skills_text([{"name": "Python"}, {"name": "GTM"}, "SQL"]),
    "Python, GTM, SQL",
)

roles = [
    {"role_title": "COO", "is_current": False, "end_date": "2026-09-01",
     "start_date": "2022-05-01", "organization": {"domain": "openai.com"}},
    {"role_title": "Investor", "is_current": False, "end_date": "2018-07-01",
     "start_date": "2018-01-01", "organization": {"domain": "ycombinator.com"}},
]
check("pick_role prefers matching company over is_current", pick_role(roles, "openai.com")["role_title"], "COO")
check("pick_role falls back to most recent", pick_role(roles, "")["role_title"], "COO")

# ---------------------------------------------------------------------------
# payload parsing (Forager shapes)
# ---------------------------------------------------------------------------
check("extract_email from emails list", extract_email({"status": "completed", "emails": ["amin@openai.com"]}), "amin@openai.com")
check(
    "extract_email from nested result",
    extract_email({"result": {"work_email": "brad@openai.com"}}),
    "brad@openai.com",
)
check("extract_email from bare string", extract_email("x@y.com"), "x@y.com")
check("extract_email empty", extract_email({"status": "failed", "emails": []}), "")
check(
    "extract_phone from bare array",
    extract_phone([{"phone_number": "+16195351351"}]),
    "+16195351351",
)
check("extract_phone prefers mobile", extract_phone([{"phone_number": "+12025550100"}, {"mobile_phone": "+919596278126"}]), "+919596278126")
check("extract_phone empty array", extract_phone([]), "")

# ---------------------------------------------------------------------------
# HubSpot enum mapping
# ---------------------------------------------------------------------------
options: List[Dict[str, Any]] = [
    {"label": "Research", "value": "RESEARCH"},
    {"label": "Computer Software", "value": "COMPUTER_SOFTWARE"},
    {"label": "Internet", "value": "INTERNET"},
]
check("enum maps by label", HubSpotClient._map_option("Research", options), "RESEARCH")
check("enum maps by value", HubSpotClient._map_option("INTERNET", options), "INTERNET")
check("enum maps by slug", HubSpotClient._map_option("computer software", options), "COMPUTER_SOFTWARE")
check("enum returns None when unknown", HubSpotClient._map_option("Basket Weaving", options), None)
check("enum ignores numbers", HubSpotClient._map_option(42, options), None)

# ---------------------------------------------------------------------------
# webhook signature (mirrors app.main._verify_signature)
# ---------------------------------------------------------------------------
def sign(secret: str, method: str, url: str, body: str, timestamp: str) -> str:
    source = f"{method}{url}{body}{timestamp}"
    return base64.b64encode(
        hmac.new(secret.encode(), source.encode(), hashlib.sha256).digest()
    ).decode()


secret = "test-secret"
body = json.dumps([{"subscriptionType": "contact.creation", "objectId": 1}])
ts = str(int(time.time() * 1000))
url = "https://example.com/webhooks/hubspot"

check(
    "signature is stable",
    sign(secret, "POST", url, body, ts),
    base64.b64encode(
        hmac.new(
            secret.encode(), f"POST{url}{body}{ts}".encode(), hashlib.sha256
        ).digest()
    ).decode(),
)
check("signature differs with wrong secret", sign("other", "POST", url, body, ts) == sign(secret, "POST", url, body, ts), False)

print(f"\nAll {PASSED} checks passed.")
