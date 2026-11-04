"""Application configuration, read from environment variables on startup.

Everything tunable about the service lives here so the behaviour can be changed on
Railway without touching code.
"""
from __future__ import annotations

import os
from typing import List

DEFAULT_TITLES = [
    "ceo",
    "cto",
    "cmo",
    "coo",
    "cro",
    "cfo",
    "founder",
    "co-founder",
    "owner",
    "president",
    "vice president",
    "vp",
    "head",
    "director",
    "chief",
    "partner",
    "principal",
    "manager",
    "general manager",
]


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


class Settings:
    """Runtime settings for the enrichment service."""

    def __init__(self) -> None:
        # --- credentials -------------------------------------------------
        self.hubspot_token = _str("HUBSPOT_PRIVATE_APP_TOKEN") or _str("HUBSPOT_TOKEN")
        self.hubspot_client_secret = _str("HUBSPOT_CLIENT_SECRET")
        self.forager_api_key = _str("FORAGER_API_KEY")
        self.forager_account_id = _str("FORAGER_ACCOUNT_ID")
        self.forager_base_url = _str("FORAGER_BASE_URL", "https://api-v2.forager.ai")
        self.hubspot_base_url = _str("HUBSPOT_BASE_URL", "https://api.hubapi.com")

        # --- staff discovery ---------------------------------------------
        self.target_titles = _list("TARGET_TITLES", DEFAULT_TITLES)
        self.target_title_query = _str("TARGET_TITLE_QUERY")
        self.max_contacts_per_company = _int("MAX_CONTACTS_PER_COMPANY", 5)
        self.discover_contacts = _bool("DISCOVER_CONTACTS", True)
        self.enrich_existing_contacts = _bool("ENRICH_EXISTING_CONTACTS", True)
        self.ensure_contact_company = _bool("ENSURE_CONTACT_COMPANY", True)

        # --- contact channels --------------------------------------------
        self.enable_work_email = _bool("ENABLE_WORK_EMAIL_LOOKUP", True)
        self.enable_phone = _bool("ENABLE_PHONE_LOOKUP", True)
        self.phone_quality_tier = _str("PHONE_QUALITY_TIER", "highest_quality")
        self.email_poll_interval = _float("WORK_EMAIL_POLL_SECONDS", 3.0)
        # Forager queues work-email jobs to an upstream provider, so the job can sit
        # in "awaiting_provider" for minutes. Wait inline for a short while (fast
        # results land immediately) and then keep polling in the background.
        self.email_poll_timeout = _float("WORK_EMAIL_TIMEOUT_SECONDS", 30.0)
        self.email_background_minutes = _int("WORK_EMAIL_BACKGROUND_MINUTES", 30)
        self.public_base_url = _str("PUBLIC_BASE_URL").rstrip("/")
        self.forager_callback_token = _str("FORAGER_CALLBACK_TOKEN")

        # --- safety rails -------------------------------------------------
        self.auto_create_properties = _bool("AUTO_CREATE_PROPERTIES", True)
        self.require_webhook_signature = _bool(
            "REQUIRE_WEBHOOK_SIGNATURE", bool(self.hubspot_client_secret)
        )
        self.verify_app = _bool("VERIFY_WEBHOOK_SIGNATURES", True)
        self.credit_budget = _int("CREDIT_BUDGET", 0)  # 0 = no local cap
        self.skip_already_enriched = _bool("SKIP_ALREADY_ENRICHED", True)
        self.http_timeout = _float("HTTP_TIMEOUT_SECONDS", 45.0)
        self.log_level = _str("LOG_LEVEL", "INFO").upper()

    # ------------------------------------------------------------------
    def title_query(self) -> str:
        """Boolean text query used by the Forager role search."""
        if self.target_title_query:
            return self.target_title_query
        parts = []
        for token in self.target_titles:
            parts.append(f'"{token}"' if " " in token else token)
        return " OR ".join(parts)

    def public_summary(self) -> dict:
        """Config view that is safe to expose over HTTP (no secrets)."""
        return {
            "hubspot_token_configured": bool(self.hubspot_token),
            "forager_key_configured": bool(self.forager_api_key),
            "forager_account_id": self.forager_account_id,
            "target_titles": self.target_titles,
            "title_query": self.title_query(),
            "max_contacts_per_company": self.max_contacts_per_company,
            "discover_contacts": self.discover_contacts,
            "enrich_existing_contacts": self.enrich_existing_contacts,
            "work_email_lookup": self.enable_work_email,
            "phone_lookup": self.enable_phone,
            "phone_quality_tier": self.phone_quality_tier,
            "webhook_signature_enforced": self.verify_app and bool(self.hubspot_client_secret),
            "forager_callback_url": f"{self.public_base_url}/webhooks/forager/work-email" if self.public_base_url else None,
            "work_email_inline_wait_seconds": self.email_poll_timeout,
            "work_email_background_minutes": self.email_background_minutes,
            "credit_budget": self.credit_budget or None,
        }
