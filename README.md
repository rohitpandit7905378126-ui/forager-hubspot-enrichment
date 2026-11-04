# Forager × HubSpot Enrichment Service

A Python (FastAPI) service that keeps HubSpot enriched with Forager data. It listens to
HubSpot webhooks, enriches what arrives from Forager, and writes clean, de-duplicated
values back into the CRM. No no-code tools: all logic is plain Python in this repo.

Built for the Appagentix / OneGTM Lab GTM Engineer evaluation task.

---

**Live:** https://web-production-2f924.up.railway.app/health

## 1. What it does

### Trigger A — `company.creation`

1. Reads the new company from HubSpot (name + domain).
2. Enriches it from Forager: **description, industry, revenue, headcount**, employee
   band, domain rank, LinkedIn URL, city / state / country.
3. Enriches the company's **existing** associated contacts.
4. If the company has fewer than `MAX_CONTACTS_PER_COMPANY` contacts, it **discovers**
   new people at that company from Forager, filtered by job title
   (`TARGET_TITLES`), creates them as HubSpot contacts, associates them to the company,
   and enriches each one.

### Trigger B — `contact.creation`

1. Resolves the person in Forager by LinkedIn URL → email → name + company domain.
2. Writes back: **name, job title, company, city / state / country, LinkedIn URL**,
   plus headline, summary, skills and a seniority tag.
3. Fills a **work email** (async Forager job, see §6) and a **mobile number** when
   Forager holds one.
4. Finds or creates the person's company in HubSpot, associates it, and enriches it.

Both flows are idempotent: a record that already carries `forager_enriched_at` (and
`forager_person_id`) is skipped, and duplicate webhook events are dropped by `eventId`.

---

## 2. Architecture

```
HubSpot webhook ──► POST /webhooks/hubspot  (HMAC v3 signature check, returns 2xx in ms)
                          │
                          └─ background task ──► EnrichmentService
                                                    ├── ForagerClient (api-v2.forager.ai)
                                                    └── HubSpotClient (api.hubapi.com)
Forager work-email job ──► POST /webhooks/forager/work-email  (fills the email later)
```

```
app/
  main.py        FastAPI app, webhook endpoints, signature verification, activity log
  enrichment.py  orchestration: company flow, contact flow, discovery, mapping
  forager.py     async Forager API client (retries, job polling)
  hubspot.py     async HubSpot client (v3 objects, v4 associations, enum-safe writes)
  properties.py  custom property definitions + read property lists
  titles.py      job-title filter (boolean query builder + local re-check)
  config.py      every knob, read from env
scripts/
  create_properties.py    creates the custom HubSpot properties
  subscribe_webhooks.py   registers the webhook subscriptions through the API
  demo.py                 runs the OpenAI demo without waiting for a webhook
```

Design points worth calling out:

- **Webhook ACK is instant.** Forager + HubSpot calls take seconds, so the route only
  validates, de-duplicates and enqueues; the work happens in a background task.
- **Enum-safe writes.** HubSpot rejects `industry: "Research"` (it stores `RESEARCH`).
  Every write is mapped onto the portal's real property definitions, and values with no
  match are dropped instead of failing the whole record. This was the single biggest
  source of 400s during development.
- **Standard properties are reused** (`name`, `domain`, `description`, `industry`,
  `annualrevenue`, `numberofemployees`, `city`, `state`, `country`, `jobtitle`,
  `hs_linkedin_url`, `phone`, `mobilephone`). Only Forager-specific extras are custom.

---

## 3. Setup

### 3.1 HubSpot private app

Settings → Integrations → Private Apps → **Create a private app**, then grant:

| Scope | Why |
|---|---|
| `crm.objects.companies.read` / `.write` | read + enrich companies |
| `crm.objects.contacts.read` / `.write` | read + enrich / create contacts |
| `crm.schemas.companies.read` / `.write` | create the custom company properties |
| `crm.schemas.contacts.read` / `.write` | create the custom contact properties |

Copy the access token (`pat-...`). If you want webhook signature verification, also copy
the app's **client secret**.

### 3.2 Forager

Sign up at `app.forager.ai`, open **API**, create a key. The account id is the number in
the URL of that section.

### 3.3 Environment

Copy `.env.example` to `.env` and fill in:

```
HUBSPOT_PRIVATE_APP_TOKEN=pat-...
FORAGER_API_KEY=...
FORAGER_ACCOUNT_ID=...
HUBSPOT_CLIENT_SECRET=...        # optional but recommended
PUBLIC_BASE_URL=https://<your-service>   # enables Forager email callbacks
```

### 3.4 Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.create_properties      # creates the 11 custom properties
uvicorn app.main:app --reload --port 8000
curl localhost:8000/health
```

Sanity check the parsing / mapping helpers (no network, 37 asserts):

```bash
python -m scripts.selftest
```

Run the whole company flow without waiting for a webhook:

```bash
python -m scripts.demo        # OpenAI: company + existing contacts + discovery
# or, against a running server:
curl -X POST "localhost:8000/enrich/company-by-domain?domain=openai.com"
```

---

## 4. Deploy to Railway

1. Push this repo to GitHub.
2. Railway → **New Project → Deploy from GitHub repo** → pick the repo.
3. Railway reads `railway.json` / `Procfile` and starts
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Add the variables from §3.3, with `PUBLIC_BASE_URL=https://<railway-domain>`.
5. Settings → Networking → **Generate domain**, then open `/health`.

### 4.1 Point HubSpot at the service

Settings → Integrations → Private Apps → your app → **Webhooks** tab:

- Target URL: `https://<railway-domain>/webhooks/hubspot`
- Subscribe to: **Company → creation**, **Contact → creation**

Or register them from the API:

```bash
HUBSPOT_APP_ID=1234567 PUBLIC_BASE_URL=https://<railway-domain> \
  python -m scripts.subscribe_webhooks
```

If `HUBSPOT_CLIENT_SECRET` is set, every request must carry a valid
`X-HubSpot-Signature-v3` header (HMAC-SHA256 over `method + url + body + timestamp`,
5-minute window) and anything else is rejected with `401`.

---

## 5. Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | service info + effective config (no secrets) |
| GET | `/health` | Railway healthcheck |
| POST | `/webhooks/hubspot` | HubSpot webhook receiver (signature verified) |
| POST | `/webhooks/forager/work-email` | Forager async email callback |
| POST | `/enrich/company/{id}` | re-run the company flow (`?force=true`) |
| POST | `/enrich/contact/{id}` | re-run the contact flow (`?force=true`) |
| POST | `/enrich/company-by-domain?domain=openai.com` | create-if-missing + company flow |
| POST | `/setup/properties` | create the custom properties |
| GET | `/activity?limit=50` | in-memory activity log for demos/debugging |

---

## 6. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TARGET_TITLES` | ceo, cto, cmo, coo, cro, cfo, founder, co-founder, owner, president, vice president, vp, head, director, chief, partner, principal, manager, general manager | the job-title filter |
| `TARGET_TITLE_QUERY` | derived | override the boolean query sent to Forager |
| `MAX_CONTACTS_PER_COMPANY` | 5 | cap on contacts per company (existing + discovered) |
| `DISCOVER_CONTACTS` | true | create new contacts from Forager |
| `ENRICH_EXISTING_CONTACTS` | true | enrich contacts already on the company |
| `ENSURE_CONTACT_COMPANY` | true | link/enrich the contact's company |
| `ENABLE_WORK_EMAIL_LOOKUP` | true | fill missing work emails |
| `ENABLE_PHONE_LOOKUP` | true | fill missing mobiles |
| `PHONE_QUALITY_TIER` | highest_quality | `highest_quality` or `most_coverage` |
| `WORK_EMAIL_TIMEOUT_SECONDS` | 30 | inline wait before handing off to background |
| `WORK_EMAIL_BACKGROUND_MINUTES` | 30 | how long the background poller keeps trying |
| `SKIP_ALREADY_ENRICHED` | true | idempotency guard |
| `VERIFY_WEBHOOK_SIGNATURES` | true | enforce the HMAC check when a secret is set |
| `CREDIT_BUDGET` | 0 (off) | optional local cap on estimated Forager credits |
| `PUBLIC_BASE_URL` | – | enables the Forager email callback URL |

---

## 7. Work email: why it is asynchronous

Forager's work-email endpoint returns **`202` with a job id** immediately, because the
address is verified upstream. The service therefore:

1. submits the job (and passes its own callback URL when `PUBLIC_BASE_URL` is set),
2. polls inline for `WORK_EMAIL_TIMEOUT_SECONDS`,
3. if the job is still `awaiting_provider`, keeps polling in the background for
   `WORK_EMAIL_BACKGROUND_MINUTES` **and** accepts the Forager callback, so the contact
   is patched whenever the address lands.

In testing, some addresses resolved in under 20 seconds (`amin@openai.com`) while others
sat in `awaiting_provider` for a long time. That spread is exactly why the flow is
non-blocking.

---

## 8. Notes on Forager (things the docs do not spell out)

See [`FORAGER_NOTES.md`](FORAGER_NOTES.md) for the full list, including:

- `organization_search` by domain returns dozens of junk records for popular domains
  (`openai.com` → 37 records, largest being a ChatGPT GPT with 117 employees). The
  LinkedIn-slug lookup (`linkedin_public_identifiers: ["openai"]`) returns the real
  OpenAI record, so the resolver tries that first.
- Work-email lookups accept **either** `linkedin_public_identifier` **or**
  `first_name + last_name + domain`, never both (400 otherwise), and a LinkedIn-only
  lookup fails with `no_current_employer` when Forager has no current role for the person.
- The phone endpoint returns a **bare JSON array** (not an object), and returns `[]`
  for many people even on `most_coverage`.
- Credit economics: 15 per mobile found, 5 per work email found, 1–2 per search /
  enrichment, 0 when nothing is found; polling a job is free.

---

## 8b. Repo documents

- [`FORAGER_NOTES.md`](FORAGER_NOTES.md) — undocumented Forager behaviours found while building
- [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) — the walkthrough used for the demo video
- [`SUBMISSION.md`](SUBMISSION.md) — deliverable checklist and the submission email

---

## 9. Known limitations

- Idempotency and event de-duplication are in-process; a multi-replica deployment would
  need Redis or a small table for that state.
- Company resolution is a heuristic (no "organization detail" endpoint exists in the
  Forager API). It is logged, and `/activity` shows the miss when no match is found.
- Forager phone coverage is thin for some companies: a contact can legitimately end up
  with an email and no mobile.
- Only `company.creation` and `contact.creation` are consumed. Property-change
  subscriptions are ignored on purpose to keep credit spend predictable.

### Credit state during the demo build

The free Forager balance (150 credits) was spent while building and testing this service,
and Forager then returns `402 {"message":"The account does not have sufficient credits
remaining."}` on every lookup. The service detects that and pauses cleanly instead of
retrying in a loop (`forager_credits_exhausted` on `GET /`). Two consequences worth
knowing:

- The HubSpot demo records were enriched while credits were live. They keep their data.
- A grader triggering a *new* webhook against this deployment will get a 200 from the
  service plus a `credits` entry in `/activity`, not fresh enrichment, until the balance
  is topped up.

Fill gaps later without re-spending on person/phone lookups:

```bash
python -m scripts.backfill_emails     # contacts with a Forager id but no email
```
