"""Async client for the Forager.ai public API (api-v2).

Endpoints used (all POST unless noted), documented at https://docs.forager.ai :
  /api/{account_id}/datastorage/organization_search/          company search + firmographics
  /api/{account_id}/datastorage/person_detail_lookup/         full person profile
  /api/{account_id}/datastorage/person_detail_reverse_lookup/by_email/
  /api/{account_id}/datastorage/person_detail_reverse_lookup/by_phone_number/
  /api/{account_id}/datastorage/person_role_search/           people by title / company
  /api/{account_id}/datastorage/person_contacts_lookup/phone_numbers/
  /api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/   (async job)
  GET  <status_check_url>                                     job polling
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api-v2.forager.ai"


class ForagerError(RuntimeError):
    """Raised when Forager returns an unexpected response."""


class ForagerClient:
    def __init__(
        self,
        api_key: str,
        account_id: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 45.0,
    ) -> None:
        if not api_key:
            raise ValueError("FORAGER_API_KEY is required")
        if not account_id:
            raise ValueError("FORAGER_ACCOUNT_ID is required")
        self._base_url = base_url.rstrip("/")
        self._account_id = str(account_id)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------
    @property
    def _prefix(self) -> str:
        return f"/api/{self._account_id}/datastorage"

    @property
    def _v2_prefix(self) -> str:
        return f"/api/v2/{self._account_id}/datastorage"

    async def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        delay = 1.0
        last_error: Optional[str] = None
        for attempt in range(3):
            try:
                resp = await self._client.request(method, url, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if resp.status_code in (200, 201, 202):
                try:
                    return resp.json()
                except ValueError:
                    return None
            if resp.status_code == 404:
                return None
            if resp.status_code in (408, 425, 429, 500, 502, 503, 504):
                last_error = f"{resp.status_code}: {resp.text[:200]}"
                log.warning("Forager %s %s -> %s, retrying", method, path, resp.status_code)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            raise ForagerError(f"Forager {method} {path} -> {resp.status_code}: {resp.text[:300]}")

        raise ForagerError(f"Forager {method} {path} failed after retries ({last_error})")

    async def _post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("POST", path, payload or {})

    async def _get(self, path: str) -> Any:
        return await self._request("GET", path, None)

    # ------------------------------------------------------------------
    # companies
    # ------------------------------------------------------------------
    async def organization_search(self, **filters: Any) -> Dict[str, Any]:
        payload = {k: v for k, v in filters.items() if v not in (None, [], "")}
        payload.setdefault("page", 0)
        return await self._post(f"{self._prefix}/organization_search/", payload) or {}

    async def organization_by_domain(self, domain: str) -> List[Dict[str, Any]]:
        data = await self.organization_search(domains=[domain])
        return data.get("search_results") or []

    async def organization_by_linkedin(self, slug: str) -> List[Dict[str, Any]]:
        data = await self.organization_search(linkedin_public_identifiers=[slug])
        return data.get("search_results") or []

    # ------------------------------------------------------------------
    # people
    # ------------------------------------------------------------------
    async def person_detail(
        self,
        person_id: Optional[int] = None,
        linkedin_public_identifier: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if person_id:
            payload["person_id"] = int(person_id)
        if linkedin_public_identifier:
            payload["linkedin_public_identifier"] = linkedin_public_identifier
        if not payload:
            return None
        return await self._post(f"{self._prefix}/person_detail_lookup/", payload)

    async def person_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self._post(
            f"{self._prefix}/person_detail_reverse_lookup/by_email/", {"email": email}
        )

    async def person_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        return await self._post(
            f"{self._prefix}/person_detail_reverse_lookup/by_phone_number/", {"phone_number": phone}
        )

    async def person_role_search(self, page: int = 0, **filters: Any) -> Dict[str, Any]:
        payload = {k: v for k, v in filters.items() if v not in (None, [], "")}
        payload["page"] = page
        data = await self._post(f"{self._prefix}/person_role_search/", payload) or {}
        return data

    async def people_at_company(self, domain: str, title_query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return current role rows for people at `domain` whose title matches the query."""
        data = await self.person_role_search(
            organization_domains=[domain],
            role_title=title_query,
            role_is_current=True,
            page=0,
        )
        results = data.get("search_results") or []
        if len(results) < limit:
            # second page is cheap and makes discovery more useful for small companies
            more = await self.person_role_search(
                organization_domains=[domain],
                role_title=title_query,
                role_is_current=True,
                page=1,
            )
            results.extend(more.get("search_results") or [])
        return results

    # ------------------------------------------------------------------
    # contact channels
    # ------------------------------------------------------------------
    async def phone_numbers(
        self,
        person_id: Optional[int] = None,
        linkedin_public_identifier: Optional[str] = None,
        quality_tier: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if person_id:
            payload["person_id"] = int(person_id)
        if linkedin_public_identifier:
            payload["linkedin_public_identifier"] = linkedin_public_identifier
        if quality_tier:
            payload["quality_tier"] = quality_tier
        if not payload:
            return None
        return await self._post(f"{self._prefix}/person_contacts_lookup/phone_numbers/", payload)

    async def start_work_email(
        self,
        first_name: str = "",
        last_name: str = "",
        domain: str = "",
        linkedin_public_identifier: str = "",
        webhook_url: str = "",
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        # Forager rejects a payload that mixes a LinkedIn identifier with a
        # name+domain pair (the two can point at different companies), so pick one.
        if linkedin_public_identifier:
            payload["linkedin_public_identifier"] = linkedin_public_identifier
        elif first_name and last_name and domain:
            payload["first_name"] = first_name
            payload["last_name"] = last_name
            payload["domain"] = domain
        else:
            return None
        if webhook_url:
            payload["webhook_url"] = webhook_url
        return await self._post(f"{self._v2_prefix}/person_contacts_lookup/work_emails/", payload)

    async def work_email_result(self, status_check_url: str) -> Optional[Dict[str, Any]]:
        return await self._get(status_check_url)

    async def wait_for_work_email(self, status_check_url: str, interval: float, timeout: float) -> Optional[Dict[str, Any]]:
        """Poll a work-email job until it completes. Polling is free in Forager."""
        waited = 0.0
        terminal = {"completed", "success", "done", "failed", "error", "not_found", "no_result"}
        while waited <= timeout:
            data = await self.work_email_result(status_check_url)
            if data:
                status = str(data.get("status", "")).lower()
                if status in terminal:
                    return data
                # anything else ("queued", "awaiting_provider", ...) means keep waiting
            await asyncio.sleep(interval)
            waited += interval
        log.warning("Work email job timed out after %.0fs", timeout)
        return None
