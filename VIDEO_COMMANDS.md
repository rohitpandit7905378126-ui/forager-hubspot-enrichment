# Copy-paste commands for the demo video

## The whole video, in order

| # | What you do | Where | Expected |
|---|---|---|---|
| 1 | Start recording, say who you are and what the service does | GitHub repo tab | — |
| 2 | Describe the pipeline: HubSpot -> service -> Forager -> back to HubSpot | README diagram | — |
| 3 | Unsigned POST | terminal | `401 {"detail":"invalid signature"}` |
| 4 | Create company `Cursor` / `cursor.com` in HubSpot, copy the id from the URL | HubSpot | empty record |
| 5 | Signed webhook replay for that id | terminal | `200 {"received":1,"queued":1}` |
| 6 | Watch the job run | `/activity` tab | `webhook` -> `company.start` -> `company.enriched` -> `discover.search` -> `contact.created` -> `company.done` |
| 7 | Show the filled company + attached people | HubSpot record | fields + contacts |
| 8 | Run command 5 again | terminal | `company.done ... 0 created`, no credits |
| 9 | Show the title filter | `/` | `target_titles`, `title_query` |
| 10 | Show the Forager findings | `FORAGER_NOTES.md` | — |
| 11 | Wrap up, stop recording | — | — |

Commands 3, 5 and 8 are below. Steps 4, 7 and 9 are just the browser.

---

Everything below runs against the live deployment. Windows: use **PowerShell** (or
Command Prompt — both variants given where they differ).

- Service: `https://web-production-2f924.up.railway.app`
- Demo secret: Railway → project `forager-hubspot-enrichment` → service `web` →
  **Variables** → `HUBSPOT_CLIENT_SECRET`. Signature verification is **on**, so every
  webhook POST must be signed.

---

## Shot A — signature verification (20 seconds, no credits)

**A1. Unsigned request is rejected.** Any shell, no Python needed:

```bash
curl -X POST https://web-production-2f924.up.railway.app/webhooks/hubspot ^
  -H "Content-Type: application/json" -d "[]"
```

Expected: `{"detail":"invalid signature"}` with HTTP 401.

**A2. Signed request is accepted.** Needs the repo cloned and Python 3:

```powershell
git clone https://github.com/rohitpandit7905378126-ui/forager-hubspot-enrichment
cd forager-hubspot-enrichment
$env:HUBSPOT_CLIENT_SECRET="sda-demo-secret-2026"
python scripts/replay_hubspot_webhook.py company.creation 999999999999
```

Expected: `200 {"received":1,"queued":1}`. The id is fake on purpose, so this costs no
Forager credits (it fails at the HubSpot lookup, which is the point: the request passed
the signature gate and reached the handler).

Say on camera: *"Same URL, same payload shape HubSpot sends. Without the signature it is
401, with a valid v3 HMAC it is 200 and the background job starts."*

---

## Shot B — company enrichment (this is where credits are spent)

**B1.** In HubSpot: Contacts → Companies → **Create company**, name `Cursor`,
domain `cursor.com`, leave everything else empty. Save. Copy the company id from the URL
(`/object/3602.../`).

**B2.** Trigger the exact same code path the `company.creation` webhook would run:

```powershell
curl.exe -X POST "https://web-production-2f924.up.railway.app/enrich/company/<COMPANY_ID>"
```

(If you want the webhook route instead of the direct route, use the signed replay:
`python scripts/replay_hubspot_webhook.py company.creation <COMPANY_ID>`.)

**B3.** Show the result:

```powershell
curl.exe "https://web-production-2f924.up.railway.app/activity?limit=20"
```

Then refresh the company in HubSpot: description, industry, revenue, employees filled, and
new contacts attached.

**B4.** Run it a second time and show `contacts_enriched` with no new credits spent
(skip logic): the `/activity` line reads `Contact ... already enriched, skipping`.

---

## Shot C — job-title filter (30 seconds, no credits)

```powershell
curl.exe "https://web-production-2f924.up.railway.app/"
```

Scroll to `target_titles` and `title_query` in the JSON. Say: *"Discovery only pulls
decision makers — CEO, CTO, founder, VP, head, director, partner — not the whole company
list, because every contact costs credits."*

---

## Shot D — what the OpenAI record already holds (no credits)

HubSpot → Companies → **OpenAI** → Contacts tab: 5 enriched people with titles, LinkedIn
URLs, seniority, locations; 3 work emails and 1 mobile. Also open one contact and show the
custom properties (`Forager Person ID`, `Forager Headline`, `Forager Skills`,
`Forager Seniority`, `Forager Enriched At`).

---

## If PowerShell blocks the commands

Run once:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

`curl` in PowerShell is an alias for `Invoke-WebRequest`; the examples above use
`curl.exe` explicitly so the flags behave like real curl.
