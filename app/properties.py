"""Custom HubSpot property definitions created by the service.

Standard properties are reused wherever HubSpot already has a field (name, domain,
description, industry, annualrevenue, numberofemployees, city, state, country,
phone, mobilephone, jobtitle, hs_linkedin_url). Only the Forager-specific extras are
created as custom properties, which keeps the portal tidy and avoids schema clashes.
"""
from __future__ import annotations

from typing import Any, Dict, List

CONTACT_GROUP = "contactinformation"
COMPANY_GROUP = "companyinformation"

CONTACT_PROPERTIES: List[Dict[str, Any]] = [
    {
        "name": "forager_person_id",
        "label": "Forager Person ID",
        "type": "string",
        "fieldType": "text",
        "groupName": CONTACT_GROUP,
        "description": "Forager person record id used to keep enrichments idempotent.",
    },
    {
        "name": "forager_headline",
        "label": "Forager Headline",
        "type": "string",
        "fieldType": "text",
        "groupName": CONTACT_GROUP,
        "description": "Headline from the Forager person profile.",
    },
    {
        "name": "forager_about",
        "label": "Forager About",
        "type": "string",
        "fieldType": "textarea",
        "groupName": CONTACT_GROUP,
        "description": "Profile summary returned by Forager.",
    },
    {
        "name": "forager_skills",
        "label": "Forager Skills",
        "type": "string",
        "fieldType": "textarea",
        "groupName": CONTACT_GROUP,
        "description": "Comma separated skills from Forager.",
    },
    {
        "name": "forager_linkedin_url",
        "label": "Forager LinkedIn URL",
        "type": "string",
        "fieldType": "text",
        "groupName": CONTACT_GROUP,
        "description": "LinkedIn profile URL as returned by Forager.",
    },
    {
        "name": "forager_seniority",
        "label": "Forager Seniority",
        "type": "string",
        "fieldType": "text",
        "groupName": CONTACT_GROUP,
        "description": "Seniority token that matched the configured title filter.",
    },
    {
        "name": "forager_enriched_at",
        "label": "Forager Enriched At",
        "type": "datetime",
        "fieldType": "date",
        "groupName": CONTACT_GROUP,
        "description": "Timestamp of the last successful Forager enrichment.",
    },
]

COMPANY_PROPERTIES: List[Dict[str, Any]] = [
    {
        "name": "forager_org_id",
        "label": "Forager Organization ID",
        "type": "string",
        "fieldType": "text",
        "groupName": COMPANY_GROUP,
        "description": "Forager organization record id.",
    },
    {
        "name": "forager_employee_range",
        "label": "Forager Employee Range",
        "type": "string",
        "fieldType": "text",
        "groupName": COMPANY_GROUP,
        "description": "Employee band reported by Forager, e.g. 1001 - 5000.",
    },
    {
        "name": "forager_domain_rank",
        "label": "Forager Domain Rank",
        "type": "number",
        "fieldType": "number",
        "groupName": COMPANY_GROUP,
        "description": "Tranco/similarweb style domain rank from Forager.",
    },
    {
        "name": "forager_enriched_at",
        "label": "Forager Enriched At",
        "type": "datetime",
        "fieldType": "date",
        "groupName": COMPANY_GROUP,
        "description": "Timestamp of the last successful company enrichment.",
    },
]

CONTACT_READ_PROPERTIES = [
    "email",
    "firstname",
    "lastname",
    "jobtitle",
    "company",
    "phone",
    "mobilephone",
    "city",
    "state",
    "country",
    "hs_linkedin_url",
    "forager_person_id",
    "forager_linkedin_url",
    "forager_enriched_at",
]

COMPANY_READ_PROPERTIES = [
    "name",
    "domain",
    "description",
    "industry",
    "annualrevenue",
    "numberofemployees",
    "city",
    "state",
    "country",
    "linkedin_company_page",
    "forager_org_id",
    "forager_enriched_at",
]
