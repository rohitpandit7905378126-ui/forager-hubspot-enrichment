"""The enrichment orchestration: HubSpot <-> Forager.

Two flows, exactly as specified in the evaluation brief:

  * company.creation  -> enrich the company, enrich its existing contacts, and
                         discover + enrich new contacts filtered by job title.
  * contact.creation  -> enrich the contact (name, LinkedIn, title, company,
                         location, email, phone) and link/enrich its company.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Set

from .config import Settings
from .forager import ForagerClient, ForagerError
from .hubspot import HubSpotClient, HubSpotError
from .properties import (
    COMPANY_PROPERTIES,
    COMPANY_READ_PROPERTIES,
    CONTACT_PROPERTIES,
    CONTACT_READ_PROPERTIES,
)
from .titles import build_query, first_match, matches_title

log = logging.getLogger(__name__)

LINKEDIN_PERSON_RE = re.compile(r"linkedin\.com/in/([^/?#]+)", re.I)
DOMAIN_RE = re.compile(r"^(?:https?://)?(?:www\.)?([^/?#]+)", re.I)


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_domain(value: str) -> str:
    """'https://www.OpenAI.com/about' -> 'openai.com'."""
    if not value:
        return ""
    match = DOMAIN_RE.match(str(value).strip())
    host = (match.group(1) if match else str(value)).lower()
    host = host.split("@")[-1]
    return host.strip(".")


def domain_root(domain: str) -> str:
    """'openai.com' -> 'openai' (used as a LinkedIn slug guess)."""
    host = norm_domain(domain)
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "ac", "gov"}:
        label = parts[-3]
    else:
        label = parts[0]
    return re.sub(r"[^a-z0-9\-]", "", label)


def linkedin_slug(value: str) -> str:
    if not value:
        return ""
    match = LINKEDIN_PERSON_RE.search(str(value))
    if match:
        return match.group(1).strip("/")
    if "linkedin.com" not in str(value) and str(value).strip():
        return str(value).strip().strip("/")
    return ""


def pick_role(roles: List[Dict[str, Any]], company_domain: str = "") -> Optional[Dict[str, Any]]:
    if not roles:
        return None
    target = norm_domain(company_domain)
    if target:
        for role in roles:
            org = role.get("organization") or {}
            if norm_domain(org.get("domain", "")) == target and (
                role.get("is_current") or not role.get("end_date")
            ):
                return role
    for role in roles:
        if role.get("is_current"):
            return role
    open_roles = [r for r in roles if not r.get("end_date")]
    if open_roles:
        return open_roles[0]
    return sorted(roles, key=lambda r: r.get("start_date") or "", reverse=True)[0]


def location_from(osm_locations: Optional[List[Dict[str, Any]]], address: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    city = state = country = ""
    for loc in osm_locations or []:
        place_type = (loc.get("place_type") or "").lower()
        name = (loc.get("name") or "").split(",")[0].strip()
        if not name:
            continue
        if place_type == "country" and not country:
            country = name
        elif place_type == "state" and not state:
            state = name
        elif place_type == "city" and not city:
            city = name
    if address:
        city = city or (address.get("city") or "")
        state = state or (address.get("state") or "")
        country = country or (address.get("country") or "")
    return {"city": city, "state": state, "country": country}


def skills_text(skills: Optional[List[Any]], limit: int = 25) -> str:
    names: List[str] = []
    for item in skills or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title")
            if name:
                names.append(str(name))
        elif item:
            names.append(str(item))
    return ", ".join(names[:limit])


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _plausible_email(value: str) -> bool:
    return "@" in value and "." in value.split("@")[-1] and " " not in value.strip()


def extract_email(payload: Any) -> str:
    """Find the first plausible email address anywhere in a Forager response.

    The work-email job returns `{"emails": ["a@b.com"]}` on success, but the shape
    can change between tiers, so accept a plain string, a list of strings, a list of
    objects, or a nested dict.
    """
    if isinstance(payload, str) and _plausible_email(payload):
        return payload.strip()
    if isinstance(payload, list):
        for item in payload:
            found = extract_email(item)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    for key, value in payload.items():
        lowered = key.lower()
        if isinstance(value, str) and "email" in lowered and _plausible_email(value):
            return value.strip()
        if isinstance(value, (list, dict)) and ("email" in lowered or lowered in {"result", "results", "data"}):
            found = extract_email(value)
            if found:
                return found
    for node in _walk(payload):
        for key, value in node.items():
            if isinstance(value, str) and _plausible_email(value) and "email" in key.lower():
                return value.strip()
    return ""


def extract_phone(payload: Any) -> str:
    """Find the first plausible phone number, preferring mobiles."""
    mobiles: List[str] = []
    others: List[str] = []
    for node in _walk(payload):
        for key, value in node.items():
            if not isinstance(value, str):
                continue
            lowered = key.lower()
            if "phone" not in lowered and "mobile" not in lowered:
                continue
            digits = re.sub(r"[^\d]", "", value)
            if len(digits) < 8 or len(digits) > 16:
                continue
            is_mobile = bool(node.get("is_mobile") or node.get("mobile") or "mobile" in lowered)
            (mobiles if is_mobile else others).append(value.strip())
    if mobiles:
        return mobiles[0]
    return others[0] if others else ""


# ----------------------------------------------------------------------------
# activity log (handy for the demo video and for debugging on Railway)
# ----------------------------------------------------------------------------
class ActivityLog:
    def __init__(self, maxlen: int = 300) -> None:
        self._items: Deque[Dict[str, Any]] = deque(maxlen=maxlen)

    def add(self, kind: str, message: str, **extra: Any) -> None:
        entry = {"at": now_iso(), "kind": kind, "message": message}
        entry.update({k: v for k, v in extra.items() if v is not None})
        self._items.appendleft(entry)
        log.info("[%s] %s %s", kind, message, extra or "")

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._items)[:limit]


# ----------------------------------------------------------------------------
# service
# ----------------------------------------------------------------------------
class EnrichmentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.forager = ForagerClient(
            settings.forager_api_key,
            settings.forager_account_id,
            base_url=settings.forager_base_url,
            timeout=settings.http_timeout,
        )
        self.hubspot = HubSpotClient(
            settings.hubspot_token,
            base_url=settings.hubspot_base_url,
            timeout=settings.http_timeout,
        )
        self.activity = ActivityLog()
        self._processed: Set[str] = set()
        self._pending_email_jobs: Dict[str, str] = {}
        self._background_tasks: Set[Any] = set()
        self.credits_spent = 0
        self.credits_exhausted = False

    def note_forager_error(self, exc: Exception) -> None:
        """A 402 means the Forager credit balance is empty: stop burning API calls."""
        message = str(exc).lower()
        if "insufficient credits" in message or "not have sufficient credits" in message:
            if not self.credits_exhausted:
                self.credits_exhausted = True
                self.activity.add(
                    "credits",
                    "Forager credit balance is empty - enrichment paused until credits are topped up",
                )

    async def aclose(self) -> None:
        await self.forager.aclose()
        await self.hubspot.aclose()

    # ------------------------------------------------------------------
    # setup helpers
    # ------------------------------------------------------------------
    async def ensure_properties(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {"created": [], "existing": []}
        for object_type, definitions in (
            ("contacts", CONTACT_PROPERTIES),
            ("companies", COMPANY_PROPERTIES),
        ):
            for definition in definitions:
                status = await self.hubspot.ensure_property(object_type, definition)
                if status == "created":
                    result["created"].append(f"{object_type}.{definition['name']}")
                else:
                    result["existing"].append(f"{object_type}.{definition['name']}")
        if result["created"]:
            self.activity.add("setup", f"Created {len(result['created'])} HubSpot properties")
        return result

    # ------------------------------------------------------------------
    # company resolution
    # ------------------------------------------------------------------
    async def resolve_organization(self, domain: str, name: str = "") -> Optional[Dict[str, Any]]:
        """Find the best Forager organization record for a HubSpot company.

        Forager has no 'detail by domain' endpoint, so this tries the LinkedIn slug
        derived from the domain first (precise, returns a single strong match), then
        the domain filter and picks the largest organization on that domain.
        """
        domain = norm_domain(domain)
        if domain:
            slug = domain_root(domain)
            if slug:
                try:
                    rows = await self.forager.organization_by_linkedin(slug)
                except ForagerError as exc:
                    log.warning("LinkedIn org lookup failed for %s: %s", slug, exc)
                    rows = []
                exact = [r for r in rows if norm_domain(r.get("domain", "")) == domain]
                if len(exact) == 1:
                    return exact[0]
                if exact:
                    return max(exact, key=lambda r: r.get("employees_amount") or 0)

            try:
                rows = await self.forager.organization_by_domain(domain)
            except ForagerError as exc:
                log.warning("Domain org lookup failed for %s: %s", domain, exc)
                rows = []
            exact = [r for r in rows if norm_domain(r.get("domain", "")) == domain]
            if exact:
                return max(exact, key=lambda r: r.get("employees_amount") or 0)

        if name:
            try:
                data = await self.forager.organization_search(description=f'"{name}"')
            except ForagerError as exc:
                log.warning("Name org lookup failed for %s: %s", name, exc)
                data = {}
            rows = data.get("search_results") or []
            for row in rows:
                if (row.get("name") or "").strip().lower() == name.strip().lower():
                    return row
        return None

    def company_props(self, org: Dict[str, Any]) -> Dict[str, Any]:
        linkedin = org.get("linkedin_info") or {}
        industry = (linkedin.get("industry") or {}).get("name") or ""
        addresses = org.get("addresses") or []
        address = addresses[0] if addresses else None
        location = location_from((org.get("location") or {}).get("osm_locations"), address)
        finance = org.get("finance_info") or {}
        employees = org.get("employees_amount")
        return {
            "name": org.get("name"),
            "domain": norm_domain(org.get("domain", "")),
            "description": org.get("description"),
            "industry": industry,
            "annualrevenue": finance.get("revenue"),
            "numberofemployees": employees,
            "city": location["city"],
            "state": location["state"],
            "country": location["country"],
            "linkedin_company_page": linkedin.get("public_profile_url"),
            "forager_org_id": str(org.get("id")) if org.get("id") else None,
            "forager_employee_range": org.get("employees_range"),
            "forager_domain_rank": org.get("domain_rank"),
            "forager_enriched_at": now_iso(),
        }

    # ------------------------------------------------------------------
    # person resolution
    # ------------------------------------------------------------------
    async def find_person(
        self,
        email: str = "",
        linkedin: str = "",
        first_name: str = "",
        last_name: str = "",
        domain: str = "",
        company_name: str = "",
    ) -> Optional[Dict[str, Any]]:
        slug = linkedin_slug(linkedin)
        if slug:
            try:
                person = await self.forager.person_detail(linkedin_public_identifier=slug)
                if person:
                    return person
            except ForagerError as exc:
                log.warning("Person lookup by LinkedIn failed (%s): %s", slug, exc)

        if email:
            try:
                person = await self.forager.person_by_email(email)
                if person:
                    return person
            except ForagerError as exc:
                log.warning("Person lookup by email failed (%s): %s", email, exc)

        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        if full_name:
            filters: Dict[str, Any] = {"person_name": full_name, "role_is_current": True}
            if domain:
                filters["organization_domains"] = [norm_domain(domain)]
            elif company_name:
                filters["organization_description"] = f'"{company_name}"'
            try:
                data = await self.forager.person_role_search(**filters)
            except ForagerError as exc:
                log.warning("Person search failed for %s: %s", full_name, exc)
                data = {}
            for row in data.get("search_results") or []:
                person = row.get("person") or {}
                if person and (person.get("full_name") or "").strip().lower() == full_name.lower():
                    detail = await self.forager.person_detail(person_id=person.get("id"))
                    return detail or person
        return None

    def person_props(self, person: Dict[str, Any], role: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        linkedin = person.get("linkedin_info") or {}
        location = location_from((person.get("location") or {}).get("osm_locations"))
        title = (role or {}).get("role_title") or ""
        org = (role or {}).get("organization") or {}
        company_name = (role or {}).get("organization_name") or org.get("name") or ""
        return {
            "firstname": person.get("first_name"),
            "lastname": person.get("last_name"),
            "jobtitle": title,
            "company": company_name,
            "city": location["city"],
            "state": location["state"],
            "country": location["country"],
            "hs_linkedin_url": linkedin.get("public_profile_url"),
            "forager_linkedin_url": linkedin.get("public_profile_url"),
            "forager_person_id": str(person.get("id")) if person.get("id") else None,
            "forager_headline": person.get("headline"),
            "forager_about": person.get("description"),
            "forager_skills": skills_text(person.get("skills")),
            "forager_seniority": first_match(title, self.settings.target_titles),
            "forager_enriched_at": now_iso(),
        }

    # ------------------------------------------------------------------
    # contact channels
    # ------------------------------------------------------------------
    def _callback_url(self, contact_id: str) -> str:
        """Forager POSTs the finished job here, so nothing has to poll forever."""
        if not self.settings.public_base_url:
            return ""
        url = f"{self.settings.public_base_url}/webhooks/forager/work-email?contact_id={contact_id}"
        if self.settings.forager_callback_token:
            url += f"&token={self.settings.forager_callback_token}"
        return url

    async def lookup_work_email(
        self,
        person: Optional[Dict[str, Any]],
        contact_props: Dict[str, Any],
        domain: str,
        contact_id: str = "",
    ) -> str:
        linkedin = linkedin_slug(
            ((person or {}).get("linkedin_info") or {}).get("public_identifier", "")
            or contact_props.get("forager_linkedin_url", "")
            or contact_props.get("hs_linkedin_url", "")
        )
        first_name = (person or {}).get("first_name") or contact_props.get("firstname") or ""
        last_name = (person or {}).get("last_name") or contact_props.get("lastname") or ""
        target_domain = norm_domain(domain)

        # Forager rejects a payload that mixes both identities. Name + domain is the
        # more reliable of the two (a LinkedIn-only lookup fails with
        # "no_current_employer" when the dataset has no current role), so try it first
        # and fall back to the LinkedIn identifier.
        attempts: List[Dict[str, str]] = []
        if first_name and last_name and target_domain:
            attempts.append(
                {"first_name": first_name, "last_name": last_name, "domain": target_domain}
            )
        if linkedin:
            attempts.append({"linkedin_public_identifier": linkedin})

        for index, attempt in enumerate(attempts):
            job = await self.forager.start_work_email(
                webhook_url=self._callback_url(contact_id) if contact_id else "",
                **attempt,
            )
            if not job or not job.get("status_check_url"):
                continue
            result = await self.forager.wait_for_work_email(
                job["status_check_url"],
                interval=self.settings.email_poll_interval,
                timeout=self.settings.email_poll_timeout,
            )
            email = extract_email(result)
            if email:
                self.credits_spent += 5  # Forager: 5 credits per work email found
                return email

            status = str((result or {}).get("status", "")).lower()
            error_code = str((result or {}).get("error_code") or "")
            if status == "failed" and error_code and index + 1 < len(attempts):
                self.activity.add(
                    "email.retry",
                    f"Work email attempt failed ({error_code}), trying the other identifier",
                )
                continue
            if status not in {"failed", "completed", "not_found", "no_result"}:
                # still queued with the upstream provider - keep checking in the background
                self._register_pending_email(contact_id, job["status_check_url"])
                self.activity.add(
                    "email.queued",
                    "Work email still processing at Forager, will update the contact when it lands",
                )
            return ""
        return ""

    def _register_pending_email(self, contact_id: str, status_url: str) -> None:
        if not contact_id or contact_id in self._pending_email_jobs:
            return
        self._pending_email_jobs[contact_id] = status_url
        task = asyncio.create_task(self._poll_pending_email(contact_id, status_url))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _poll_pending_email(self, contact_id: str, status_url: str) -> None:
        deadline = self.settings.email_background_minutes * 60
        waited = 0
        while waited < deadline:
            await asyncio.sleep(30)
            waited += 30
            try:
                data = await self.forager.work_email_result(status_url)
            except ForagerError as exc:
                log.debug("Pending email poll failed: %s", exc)
                continue
            email = extract_email(data)
            if email:
                await self._apply_email(contact_id, email)
                self._pending_email_jobs.pop(contact_id, None)
                return
            status = str((data or {}).get("status", "")).lower()
            if status in {"failed", "not_found", "no_result"}:
                self.activity.add(
                    "email.miss", f"Work email not found for contact {contact_id} ({status})"
                )
                self._pending_email_jobs.pop(contact_id, None)
                return
        self._pending_email_jobs.pop(contact_id, None)

    async def _apply_email(self, contact_id: str, email: str) -> None:
        try:
            existing = await self.hubspot.get_object("contacts", contact_id, ["email"])
            current = ((existing or {}).get("properties") or {}).get("email")
            if current:
                return
            await self.hubspot.update_object("contacts", contact_id, {"email": email})
            self.credits_spent += 5
            self.activity.add("contact.email", f"Work email filled: {email}", contact_id=contact_id)
        except HubSpotError as exc:
            log.warning("Could not apply email to %s: %s", contact_id, exc)

    async def handle_forager_email_callback(self, contact_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Forager posts the finished work-email job here."""
        email = extract_email(payload)
        self.activity.add(
            "email.callback",
            f"Forager email callback received ({payload.get('status')})",
            contact_id=contact_id,
            email=email or None,
        )
        if email and contact_id:
            await self._apply_email(contact_id, email)
            return {"status": "applied", "email": email}
        return {"status": "no_email"}

    async def lookup_phone(self, person: Optional[Dict[str, Any]]) -> str:
        if not person:
            return ""
        linkedin = ((person.get("linkedin_info") or {}).get("public_identifier")) or ""
        try:
            payload = await self.forager.phone_numbers(
                person_id=person.get("id"),
                linkedin_public_identifier=linkedin or None,
                quality_tier=self.settings.phone_quality_tier,
            )
        except ForagerError as exc:
            log.warning("Phone lookup failed: %s", exc)
            return ""
        phone = extract_phone(payload)
        if phone:
            self.credits_spent += 15  # Forager: 15 credits per mobile found
        return phone

    # ------------------------------------------------------------------
    # company flow
    # ------------------------------------------------------------------
    async def enrich_company(
        self,
        company_id: str,
        trigger: str = "webhook",
        force: bool = False,
        discover: Optional[bool] = None,
        enrich_contacts: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if self.credits_exhausted:
            return {"status": "skipped", "reason": "Forager credits exhausted"}
        key = f"company:{company_id}"
        if not force and self.settings.skip_already_enriched and key in self._processed:
            return {"status": "skipped", "reason": "already processed in this process"}
        self._processed.add(key)

        discover = self.settings.discover_contacts if discover is None else discover
        enrich_contacts = (
            self.settings.enrich_existing_contacts if enrich_contacts is None else enrich_contacts
        )

        company = await self.hubspot.get_object("companies", company_id, COMPANY_READ_PROPERTIES)
        if not company:
            self.activity.add("error", f"Company {company_id} not found in HubSpot", trigger=trigger)
            return {"status": "error", "reason": "company not found"}

        props = company.get("properties") or {}
        name = props.get("name") or ""
        domain = norm_domain(props.get("domain") or "")
        self.activity.add(
            "company.start",
            f"Enriching company '{name or company_id}'",
            trigger=trigger,
            company_id=company_id,
            domain=domain,
        )

        org = await self.resolve_organization(domain, name)
        result: Dict[str, Any] = {
            "status": "ok",
            "company_id": company_id,
            "domain": domain,
            "org_found": bool(org),
            "contacts_enriched": 0,
            "contacts_created": 0,
        }

        if org:
            mapped = self.company_props(org)
            await self.hubspot.update_object("companies", company_id, mapped)
            domain = norm_domain(mapped.get("domain") or "") or domain
            result["org_id"] = mapped.get("forager_org_id")
            self.activity.add(
                "company.enriched",
                f"Company enriched: {mapped.get('name')} ({domain})",
                employees=mapped.get("numberofemployees"),
                revenue=mapped.get("annualrevenue"),
                industry=mapped.get("industry"),
            )
            company_name = mapped.get("name") or name
        else:
            self.activity.add(
                "company.miss",
                f"No Forager match for '{name or domain}', contact discovery skipped",
                trigger=trigger,
            )
            company_name = name

        # --- existing contacts on the company -------------------------
        existing_contacts = await self.hubspot.associated_ids("companies", company_id, "contacts")
        known_people: Set[str] = set()
        if enrich_contacts:
            for contact_id in existing_contacts:
                try:
                    detail = await self.hubspot.get_object("contacts", contact_id, CONTACT_READ_PROPERTIES)
                    person_id = ((detail or {}).get("properties") or {}).get("forager_person_id")
                    if person_id:
                        known_people.add(str(person_id))
                    await self.enrich_contact(contact_id, company_domain=domain)
                    result["contacts_enriched"] += 1
                except (HubSpotError, ForagerError) as exc:
                    log.warning("Contact %s enrichment failed: %s", contact_id, exc)
                    self.activity.add("error", f"Contact {contact_id} failed: {exc}")

        # --- discover new contacts ------------------------------------
        if discover and org and domain:
            created = await self.discover_contacts(
                company_id=company_id,
                domain=domain,
                org=org,
                company_name=company_name,
                known_people=known_people,
                existing_count=len(existing_contacts),
            )
            result["contacts_created"] = created
            result["contacts_enriched"] += created

        self.activity.add(
            "company.done",
            f"Company flow finished for {company_name or company_id}: "
            f"{result['contacts_enriched']} contacts enriched, {result['contacts_created']} created",
            company_id=company_id,
        )
        return result

    async def discover_contacts(
        self,
        company_id: str,
        domain: str,
        org: Dict[str, Any],
        company_name: str,
        known_people: Set[str],
        existing_count: int,
    ) -> int:
        limit = max(self.settings.max_contacts_per_company - existing_count, 0)
        if limit <= 0:
            self.activity.add(
                "discover.skip",
                f"Company already has {existing_count} contacts, discovery not needed",
            )
            return 0

        query = self.settings.title_query() or build_query(self.settings.target_titles)
        try:
            rows = await self.forager.people_at_company(domain, query, limit=limit * 3)
        except ForagerError as exc:
            self.activity.add("error", f"People search failed for {domain}: {exc}")
            return 0

        self.activity.add(
            "discover.search",
            f"Found {len(rows)} people matching titles at {domain}",
            title_filter=query,
        )

        created = 0
        for row in rows:
            if created >= limit:
                break
            title = row.get("role_title") or ""
            person = row.get("person") or {}
            if not person:
                continue
            if not matches_title(title, self.settings.target_titles):
                continue
            person_id = str(person.get("id") or "")
            if not person_id or person_id in known_people:
                continue
            if await self._contact_exists_for_person(person):
                continue

            contact_props = {
                "firstname": person.get("first_name"),
                "lastname": person.get("last_name"),
                "jobtitle": title,
                "company": company_name or (row.get("organization_name") or ""),
                "hs_linkedin_url": ((person.get("linkedin_info") or {}).get("public_profile_url")),
                "forager_person_id": person_id,
                "forager_linkedin_url": ((person.get("linkedin_info") or {}).get("public_profile_url")),
            }
            try:
                contact = await self.hubspot.create_object("contacts", contact_props)
            except HubSpotError as exc:
                log.warning("Could not create contact for person %s: %s", person_id, exc)
                continue

            contact_id = str(contact.get("id"))
            known_people.add(person_id)
            self._processed.add(f"contact:{contact_id}")
            try:
                await self.hubspot.associate("contacts", contact_id, "companies", company_id)
            except HubSpotError as exc:
                log.warning("Association failed for contact %s: %s", contact_id, exc)

            self.activity.add(
                "contact.created",
                f"Created {person.get('full_name')} - {title}",
                contact_id=contact_id,
                person_id=person_id,
            )
            await self.enrich_contact(
                contact_id,
                company_domain=domain,
                force=True,
                person_hint=person,
                role_hint=row,
            )
            created += 1

        self.activity.add("discover.done", f"Discovered and enriched {created} new contacts at {domain}")
        return created

    async def _contact_exists_for_person(self, person: Dict[str, Any]) -> bool:
        person_id = str(person.get("id") or "")
        if person_id:
            try:
                found = await self.hubspot.search_objects(
                    "contacts",
                    [{"propertyName": "forager_person_id", "operator": "EQ", "value": person_id}],
                    ["id"],
                    limit=1,
                )
                if found:
                    return True
            except HubSpotError as exc:
                log.debug("forager_person_id search failed: %s", exc)
        full_name = (person.get("full_name") or "").strip()
        if full_name and " " in full_name:
            first, last = full_name.split(" ", 1)
            try:
                found = await self.hubspot.search_objects(
                    "contacts",
                    [
                        {"propertyName": "firstname", "operator": "EQ", "value": first},
                        {"propertyName": "lastname", "operator": "EQ", "value": last},
                    ],
                    ["id"],
                    limit=1,
                )
                return bool(found)
            except HubSpotError:
                return False
        return False

    # ------------------------------------------------------------------
    # contact flow
    # ------------------------------------------------------------------
    async def enrich_contact(
        self,
        contact_id: str,
        company_domain: str = "",
        force: bool = False,
        person_hint: Optional[Dict[str, Any]] = None,
        role_hint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self.credits_exhausted:
            return {"status": "skipped", "reason": "Forager credits exhausted"}
        key = f"contact:{contact_id}"
        if not force and self.settings.skip_already_enriched and key in self._processed:
            return {"status": "skipped", "reason": "already processed in this process"}
        self._processed.add(key)

        contact = await self.hubspot.get_object("contacts", contact_id, CONTACT_READ_PROPERTIES)
        if not contact:
            self.activity.add("error", f"Contact {contact_id} not found in HubSpot")
            return {"status": "error", "reason": "contact not found"}

        props = contact.get("properties") or {}
        if (
            not force
            and self.settings.skip_already_enriched
            and props.get("forager_enriched_at")
            and props.get("forager_person_id")
        ):
            self.activity.add(
                "contact.skip",
                f"Contact {contact_id} already enriched, skipping",
                contact_id=contact_id,
            )
            return {"status": "skipped", "reason": "already enriched"}

        email_hint = props.get("email") or ""
        slug = linkedin_slug(props.get("hs_linkedin_url") or props.get("forager_linkedin_url") or "")
        self.activity.add(
            "contact.start",
            f"Enriching contact '{props.get('firstname') or ''} {props.get('lastname') or ''}'".strip(),
            contact_id=contact_id,
            email=email_hint or None,
            linkedin=slug or None,
        )

        person = person_hint or await self.find_person(
            email=email_hint,
            linkedin=slug,
            first_name=props.get("firstname") or "",
            last_name=props.get("lastname") or "",
            domain=company_domain or norm_domain(props.get("company") or ""),
            company_name=props.get("company") or "",
        )

        result: Dict[str, Any] = {"status": "ok", "contact_id": contact_id, "person_found": bool(person)}
        updates: Dict[str, Any] = {}

        role: Optional[Dict[str, Any]] = role_hint
        if person:
            if not role:
                role = pick_role(person.get("roles") or [], company_domain)
            updates.update(self.person_props(person, role))
            org = (role or {}).get("organization") or {}
            org_domain = norm_domain(org.get("domain") or "")
            company_domain = company_domain or org_domain
        else:
            self.activity.add(
                "contact.miss",
                f"No Forager person match for {props.get('email') or contact_id}",
                contact_id=contact_id,
            )
            org = {}

        # --- work email (only when the contact has none) --------------
        if self.settings.enable_work_email and not email_hint and (person or props.get("lastname")):
            try:
                work_email = await self.lookup_work_email(
                    person, {**props, **updates}, company_domain, contact_id=contact_id
                )
            except ForagerError as exc:
                work_email = ""
                log.warning("Work email lookup failed: %s", exc)
            if work_email:
                updates["email"] = work_email
                result["email"] = work_email
                self.activity.add("contact.email", f"Work email found: {work_email}", contact_id=contact_id)

        # --- mobile number -------------------------------------------
        if self.settings.enable_phone and person and not props.get("mobilephone") and not props.get("phone"):
            phone = await self.lookup_phone(person)
            if phone:
                updates["mobilephone"] = phone
                updates["phone"] = phone
                result["phone"] = phone
                self.activity.add("contact.phone", f"Mobile found: {phone}", contact_id=contact_id)

        if updates:
            try:
                await self.hubspot.update_object("contacts", contact_id, updates)
            except HubSpotError as exc:
                log.warning("Contact update failed for %s: %s", contact_id, exc)
                self.activity.add("error", f"Contact update failed: {exc}", contact_id=contact_id)
                result["status"] = "partial"

        # --- make sure the contact is attached to an enriched company -
        if self.settings.ensure_contact_company and org:
            try:
                await self._link_company(contact_id, org, company_domain)
            except (HubSpotError, ForagerError) as exc:
                log.warning("Company link failed for contact %s: %s", contact_id, exc)

        self.activity.add(
            "contact.done",
            f"Contact {contact_id} enriched"
            + (f" - {updates.get('jobtitle')}" if updates.get("jobtitle") else ""),
            contact_id=contact_id,
        )
        return result

    async def _link_company(self, contact_id: str, org: Dict[str, Any], domain: str) -> None:
        domain = norm_domain(domain or org.get("domain") or "")
        if not domain:
            return
        found = await self.hubspot.search_objects(
            "companies",
            [{"propertyName": "domain", "operator": "EQ", "value": domain}],
            ["id", "name", "domain", "forager_enriched_at"],
            limit=1,
        )
        if found:
            company_id = str(found[0].get("id"))
            await self.hubspot.associate("contacts", contact_id, "companies", company_id)
            if not (found[0].get("properties") or {}).get("forager_enriched_at"):
                await self.enrich_company(company_id, trigger="contact-linked", discover=False, enrich_contacts=False)
            return

        created = await self.hubspot.create_object("companies", self.company_props(org))
        company_id = str(created.get("id"))
        self._processed.add(f"company:{company_id}")
        await self.hubspot.associate("contacts", contact_id, "companies", company_id)
        self.activity.add(
            "company.created",
            f"Created company '{org.get('name')}' from contact enrichment",
            company_id=company_id,
        )

    # ------------------------------------------------------------------
    # webhook entry point
    # ------------------------------------------------------------------
    async def handle_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary = {"companies": 0, "contacts": 0, "ignored": 0, "errors": 0}
        for event in events:
            subscription_type = (event.get("subscriptionType") or "").lower()
            object_id = str(event.get("objectId") or "")
            if not object_id:
                summary["ignored"] += 1
                continue
            self.activity.add("webhook", f"{subscription_type} received", object_id=object_id)
            try:
                if subscription_type == "company.creation":
                    await self.enrich_company(object_id, trigger="company.creation")
                    summary["companies"] += 1
                elif subscription_type == "contact.creation":
                    await self.enrich_contact(object_id)
                    summary["contacts"] += 1
                else:
                    summary["ignored"] += 1
            except (HubSpotError, ForagerError) as exc:
                self.note_forager_error(exc)
                summary["errors"] += 1
                log.exception("Webhook handling failed for %s %s", subscription_type, object_id)
                self.activity.add(
                    "error",
                    f"{subscription_type} {object_id} failed: {exc}",
                )
        return summary
