# Submission pack

Deadline: **5 Nov 2026, 13:00** (IST). Reply to the Appagentix / OneGTM Lab task email.

## Deliverables from the brief → where they are

| Required | Status | Where |
|---|---|---|
| Demo video | record from `DEMO_SCRIPT.md` | link to share |
| Live deployment URL | deploy on Railway, then paste | `https://<railway-domain>/health` |
| GitHub repo | push this folder | `https://github.com/<you>/forager-hubspot-enrichment` |
| HubSpot portal with OpenAI company + 5 enriched contacts | done (portal 247887031) | Companies → OpenAI |
| Note on extra Forager details | written | `FORAGER_NOTES.md` |
| CV attached | attach the original file | reply email |

## Pre-send check (10 minutes)

1. `https://<railway-domain>/health` returns `{"status":"healthy"}`.
2. `https://<railway-domain>/` shows the config summary with no secrets.
3. HubSpot company **OpenAI**: description, industry, annual revenue, employees,
   city/state/country, LinkedIn URL all filled.
4. OpenAI company → Contacts tab: **5 contacts** with job titles, LinkedIn URLs,
   locations. Reference state recorded on 4 Nov: work emails on 3 of 5
   (`amin@`, `harrison@`, `brad@openai.com`) and one mobile (`+15104026750`). Forager has
   no mobile for the other four at either `quality_tier`, and no email at all for Remus
   Moraru / Wojciech Zaremba — that is a data limit, not a pipeline failure.
5. A contact record shows the custom properties `Forager Person ID`, `Forager Headline`,
   `Forager Skills`, `Forager Seniority`, `Forager Enriched At`.
6. Repo README renders on GitHub and the video link in the email is public (unlisted is
   fine, "request access" is not).

## Email draft

Subject: **GTM Engineer evaluation — Forager × HubSpot enrichment service**

> Hi <name>,
>
> Submitting the Forager × HubSpot enrichment task.
>
> **Live service:** https://<railway-domain>/health
> **Repo:** https://github.com/<you>/forager-hubspot-enrichment
> **Demo video:** <link>
>
> It's a Python FastAPI service (no no-code tools) with two HubSpot webhooks:
>
> - **company.creation** — enriches the company from Forager (description, industry,
>   revenue, headcount, location, LinkedIn), enriches the contacts already on it, then
>   discovers and enriches new people at that domain filtered by job title.
> - **contact.creation** — enriches the contact (name, title, company, location, LinkedIn,
>   work email, mobile) and finds or creates plus enriches their company.
>
> Webhooks are verified with HubSpot's v3 HMAC signature and acknowledged immediately, with
> the Forager work happening asynchronously. Enrichment is idempotent and de-duplicated,
> which matters because Forager only charges when it finds data (15 credits per mobile,
> 5 per work email).
>
> The HubSpot portal has the demo records: the **OpenAI** company fully enriched with five
> enriched contacts under it.
>
> `FORAGER_NOTES.md` in the repo covers what I learned beyond Forager's documentation —
> the domain search returns mostly junk records so companies are resolved through the
> LinkedIn slug, the work-email endpoint rejects mixed identifiers and fails with
> `no_current_employer` on LinkedIn-only lookups, and the phone endpoint returns a bare
> array that is often empty (Forager has no mobile for Brad Lightcap at all).
>
> CV attached. Happy to walk through the code or the credit trade-offs on a call.
>
> Best,
> Rohit Sharma
> Sharma Digital Agency · +91 95962 78126

## If Railway is not up yet

Send the repo + video + a local run screenshot instead, and say the deployment URL is
coming. A missing live URL with everything else complete scores better than a rushed
broken deploy, but try to get it live: on Railway it is a GitHub connect plus 6 env vars.

## Environment variables for Railway

```
HUBSPOT_PRIVATE_APP_TOKEN=pat-...
FORAGER_API_KEY=...
FORAGER_ACCOUNT_ID=2845
HUBSPOT_CLIENT_SECRET=...
PUBLIC_BASE_URL=https://<railway-domain>
TARGET_TITLES=ceo,cto,cmo,coo,cro,cfo,founder,co-founder,owner,president,vice president,vp,head,director,chief,partner,principal,manager
MAX_CONTACTS_PER_COMPANY=5
ENABLE_WORK_EMAIL_LOOKUP=true
ENABLE_PHONE_LOOKUP=true
PHONE_QUALITY_TIER=highest_quality
WORK_EMAIL_TIMEOUT_SECONDS=30
WORK_EMAIL_BACKGROUND_MINUTES=30
```
