"""FastAPI entrypoint: HubSpot webhooks + manual enrichment endpoints."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .enrichment import EnrichmentService
from .hubspot import HubSpotError

settings = Settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("app")

# event ids already accepted, so HubSpot retries do not re-run the same job
_seen_events: Dict[str, float] = {}
_seen_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = EnrichmentService(settings)
    app.state.service = service
    log.info("Service starting with config: %s", settings.public_summary())
    if settings.auto_create_properties:
        try:
            await service.ensure_properties()
        except HubSpotError as exc:
            log.warning("Could not ensure custom properties on startup: %s", exc)
    yield
    await service.aclose()


app = FastAPI(title="Forager x HubSpot Enrichment", version="1.0.0", lifespan=lifespan)


def _service(request: Request) -> EnrichmentService:
    return request.app.state.service


# ---------------------------------------------------------------------------
# webhook signature (HubSpot v3)
# ---------------------------------------------------------------------------
def _verify_signature(request: Request, raw_body: bytes, secret: str) -> bool:
    signature = request.headers.get("x-hubspot-signature-v3")
    timestamp = request.headers.get("x-hubspot-request-timestamp")
    if not signature or not timestamp:
        return False
    try:
        if abs(time.time() - int(timestamp) / 1000.0) > 300:
            return False
    except (TypeError, ValueError):
        return False
    url = str(request.url).replace("http://", "https://", 1) if request.url.scheme == "http" else str(request.url)
    source = f"{request.method}{url}{raw_body.decode('utf-8', 'ignore')}{timestamp}"
    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), source.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def _remember_event(event_id: str) -> bool:
    """Return False when this event id was already handled."""
    if not event_id:
        return True
    async with _seen_lock:
        if event_id in _seen_events:
            return False
        _seen_events[event_id] = time.time()
        if len(_seen_events) > 5000:
            cutoff = time.time() - 3600
            for key in [k for k, ts in _seen_events.items() if ts < cutoff]:
                _seen_events.pop(key, None)
        return True


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.get("/")
async def index(request: Request) -> Dict[str, Any]:
    service = _service(request)
    return {
        "service": "Forager x HubSpot enrichment",
        "status": "ok",
        "endpoints": {
            "webhook": "POST /webhooks/hubspot",
            "enrich_company": "POST /enrich/company/{company_id}",
            "enrich_contact": "POST /enrich/contact/{contact_id}",
            "enrich_by_domain": "POST /enrich/company-by-domain?domain=openai.com",
            "activity": "GET /activity",
        },
        "config": settings.public_summary(),
        "estimated_credits_spent_this_process": service.credits_spent,
        "forager_credits_exhausted": service.credits_exhausted,
    }


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "healthy"}


@app.get("/activity")
async def activity(request: Request, limit: int = 50) -> Dict[str, Any]:
    service = _service(request)
    return {
        "events": service.activity.recent(limit),
        "estimated_credits_spent_this_process": service.credits_spent,
    }


@app.get("/webhooks/hubspot")
async def hubspot_webhook_info() -> JSONResponse:
    """Browser-friendly explanation of the receiver.

    HubSpot only ever POSTs here. Opening the URL in a browser sends GET, and
    without this route that looks like a broken endpoint ("Method Not Allowed").
    """
    enforcing = bool(settings.hubspot_client_secret)
    return JSONResponse(
        {
            "endpoint": "HubSpot webhook receiver",
            "status": "live and listening",
            "method_required": "POST",
            "why_you_see_this_page": (
                "You opened the URL in a browser, which sends GET. HubSpot sends POST, "
                "so this page is only an explanation of the endpoint."
            ),
            "signature_verification": "enforced" if enforcing else "disabled (HUBSPOT_CLIENT_SECRET not set)",
            "handles_events": ["company.creation", "contact.creation"],
            "expected_payload": [
                {
                    "subscriptionType": "company.creation",
                    "objectId": "360217205438",
                    "eventId": "1",
                    "portalId": 247887031,
                }
            ],
            "how_to_test": {
                "curl": (
                    "curl -X POST '" + settings.public_base_url + "/webhooks/hubspot' "
                    "-H 'Content-Type: application/json' "
                    "-d '[{\"subscriptionType\":\"company.creation\",\"objectId\":\"<company_id>\"}]'"
                ),
                "browser_friendly": "POST /enrich/company/{company_id} or watch GET /activity",
            },
            "see_what_happened": "/activity",
            "health": "/health",
        }
    )


@app.post("/webhooks/hubspot")
async def hubspot_webhook(request: Request, background: BackgroundTasks) -> JSONResponse:
    raw = await request.body()
    if settings.verify_app and settings.hubspot_client_secret:
        if not _verify_signature(request, raw, settings.hubspot_client_secret):
            log.warning("Rejected webhook with invalid signature")
            raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(raw or b"[]")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")

    events: List[Dict[str, Any]] = payload if isinstance(payload, list) else [payload]

    accepted: List[Dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("eventId") or "")
        if await _remember_event(event_id):
            accepted.append(event)

    if accepted:
        # HubSpot expects a 2xx within a few seconds; do the work after responding.
        background.add_task(_service(request).handle_events, accepted)

    return JSONResponse({"received": len(events), "queued": len(accepted)})


@app.post("/enrich/company/{company_id}")
async def enrich_company(company_id: str, request: Request, force: bool = False) -> Dict[str, Any]:
    return await _service(request).enrich_company(company_id, trigger="manual", force=force)


@app.post("/enrich/contact/{contact_id}")
async def enrich_contact(contact_id: str, request: Request, force: bool = False) -> Dict[str, Any]:
    return await _service(request).enrich_contact(contact_id, force=force)


@app.post("/enrich/company-by-domain")
async def enrich_company_by_domain(
    request: Request,
    domain: str,
    name: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Create the company in HubSpot if needed, then run the full company flow.

    Handy for a demo (and for backfilling companies that never fired a webhook).
    """
    service = _service(request)
    found = await service.hubspot.search_objects(
        "companies",
        [{"propertyName": "domain", "operator": "EQ", "value": domain}],
        ["id", "name", "domain"],
        limit=1,
    )
    if found:
        company_id = str(found[0].get("id"))
        created = False
    else:
        company = await service.hubspot.create_object(
            "companies", {"name": name or domain, "domain": domain}
        )
        company_id = str(company.get("id"))
        created = True
        service._processed.discard(f"company:{company_id}")

    result = await service.enrich_company(company_id, trigger="manual-domain", force=force)
    result["company_created"] = created
    return result


@app.post("/webhooks/forager/work-email")
async def forager_email_callback(
    request: Request, contact_id: str = "", token: str = ""
) -> Dict[str, Any]:
    """Callback target handed to Forager when a work-email job is submitted.

    Forager queues work-email jobs upstream and can take minutes, so the service
    registers this URL instead of blocking. `?contact_id=` travels in the query
    string (Forager never echoes it back), which is why the token is checked here.
    """
    if settings.forager_callback_token and token != settings.forager_callback_token:
        raise HTTPException(status_code=401, detail="invalid callback token")

    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        payload = {"raw": raw.decode("utf-8", "ignore")}

    target = contact_id or str(payload.get("contact_id") or "")
    if not target:
        raise HTTPException(status_code=400, detail="contact_id is required")
    return await _service(request).handle_forager_email_callback(target, payload)


@app.post("/setup/properties")
async def setup_properties(request: Request) -> Dict[str, Any]:
    return await _service(request).ensure_properties()
