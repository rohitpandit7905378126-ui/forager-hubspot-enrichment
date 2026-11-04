"""Minimal async HubSpot CRM client (private app token auth).

Only the calls this service needs: read/update/create objects, search, v4
associations and property creation.

Every write is passed through `_sanitize`, which maps values onto the portal's real
property definitions. This matters because HubSpot *enumeration* properties (industry,
country, ...) reject human labels like "Research" and only accept the stored option
value "RESEARCH"; a hard-failing write would lose the whole enrichment payload.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Iterable, List, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.hubapi.com"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


class HubSpotError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class HubSpotClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> None:
        if not token:
            raise ValueError("HUBSPOT_PRIVATE_APP_TOKEN is required")
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self._definitions: Dict[str, Dict[str, Dict[str, Any]]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        delay = 1.0
        for attempt in range(4):
            try:
                resp = await self._client.request(method, url, json=payload, params=params)
            except httpx.HTTPError as exc:
                if attempt == 3:
                    raise HubSpotError(f"HubSpot transport error on {path}: {exc}") from exc
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if resp.status_code in (200, 201, 202, 204):
                if resp.status_code == 204 or not resp.content:
                    return None
                return resp.json()

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1") or 1)
                log.warning("HubSpot rate limit on %s, sleeping %.1fs", path, retry_after)
                await asyncio.sleep(min(retry_after, 10.0) + attempt)
                continue

            if resp.status_code >= 500 and attempt < 3:
                await asyncio.sleep(delay)
                delay *= 2
                continue

            body: Any
            try:
                body = resp.json()
            except ValueError:
                body = resp.text[:500]
            raise HubSpotError(
                f"HubSpot {method} {path} -> {resp.status_code}: {str(body)[:400]}",
                status_code=resp.status_code,
                body=body,
            )
        raise HubSpotError(f"HubSpot {method} {path} failed after retries")

    # ------------------------------------------------------------------
    # property definitions + enum-safe writes
    # ------------------------------------------------------------------
    async def property_definitions(self, object_type: str) -> Dict[str, Dict[str, Any]]:
        if object_type not in self._definitions:
            data = await self._request("GET", f"/crm/v3/properties/{object_type}")
            self._definitions[object_type] = {
                item["name"]: item for item in (data or {}).get("results", [])
            }
        return self._definitions[object_type]

    @staticmethod
    def _map_option(value: Any, options: List[Dict[str, Any]]) -> Optional[str]:
        if value is None or isinstance(value, (int, float, bool)):
            return None
        text = str(value).strip()
        for option in options:
            if option.get("value") == text:
                return option["value"]
        lowered = text.lower()
        for option in options:
            if (option.get("label") or "").lower() == lowered:
                return option["value"]
        target = _slug(text)
        for option in options:
            if _slug(option.get("value") or "") == target or _slug(option.get("label") or "") == target:
                return option["value"]
        for option in options:
            label = (option.get("label") or "").lower()
            if label and (label in lowered or lowered in label):
                return option["value"]
        return None

    async def _sanitize(self, object_type: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        defs = await self.property_definitions(object_type)
        clean: Dict[str, Any] = {}
        dropped: Dict[str, Any] = {}
        for key, value in properties.items():
            if value is None or value == "":
                continue
            definition = defs.get(key)
            if not definition:
                clean[key] = value
                continue
            options = definition.get("options") or []
            if options and definition.get("type") == "enumeration":
                mapped = self._map_option(value, options)
                if mapped is None:
                    dropped[key] = value
                    continue
                clean[key] = mapped
            else:
                clean[key] = value
        if dropped:
            log.info("Skipped unmapped enumeration values: %s", dropped)
        return clean

    # ------------------------------------------------------------------
    # objects
    # ------------------------------------------------------------------
    async def get_object(self, object_type: str, object_id: str, properties: Iterable[str]) -> Optional[Dict[str, Any]]:
        try:
            return await self._request(
                "GET",
                f"/crm/v3/objects/{object_type}/{object_id}",
                params={"properties": ",".join(properties), "associations": "companies"},
            )
        except HubSpotError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def update_object(self, object_type: str, object_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        clean = await self._sanitize(object_type, properties)
        if not clean:
            return {}
        return await self._request(
            "PATCH", f"/crm/v3/objects/{object_type}/{object_id}", {"properties": clean}
        )

    async def create_object(self, object_type: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        clean = await self._sanitize(object_type, properties)
        return await self._request("POST", f"/crm/v3/objects/{object_type}", {"properties": clean})

    async def search_objects(
        self,
        object_type: str,
        filters: List[Dict[str, Any]],
        properties: Iterable[str],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"limit": limit, "properties": list(properties)}
        if filters:
            payload["filterGroups"] = [{"filters": filters}]
        data = await self._request("POST", f"/crm/v3/objects/{object_type}/search", payload)
        return (data or {}).get("results") or []

    # ------------------------------------------------------------------
    # associations (v4)
    # ------------------------------------------------------------------
    async def associated_ids(self, from_type: str, from_id: str, to_type: str) -> List[str]:
        try:
            data = await self._request(
                "GET",
                f"/crm/v4/objects/{from_type}/{from_id}/associations/{to_type}",
                params={"limit": 200},
            )
        except HubSpotError as exc:
            if exc.status_code == 404:
                return []
            raise
        results = (data or {}).get("results") or []
        return [str(item.get("toObjectId")) for item in results if item.get("toObjectId")]

    async def associate(self, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
        try:
            await self._request(
                "PUT",
                f"/crm/v4/objects/{from_type}/{from_id}/associations/default/{to_type}/{to_id}",
            )
        except HubSpotError as exc:
            if exc.status_code in (409, 400):
                log.debug("Association %s %s -> %s %s already exists", from_type, from_id, to_type, to_id)
                return
            raise

    # ------------------------------------------------------------------
    # properties
    # ------------------------------------------------------------------
    async def ensure_property(self, object_type: str, definition: Dict[str, Any]) -> str:
        existing = await self.property_definitions(object_type)
        if definition["name"] in existing:
            return "exists"
        await self._request("POST", f"/crm/v3/properties/{object_type}", definition)
        self._definitions.pop(object_type, None)
        return "created"
