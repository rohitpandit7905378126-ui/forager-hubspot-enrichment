# Demo video script (target: 6–8 minutes)

Record with OBS or a plain screen recorder, 1080p, mic on. Keep the HubSpot tab full
width and the terminal in a second tab. Say what you are about to show *before* you show
it — graders skim.

---

## 0:00 – 0:40  What this is

> "This is a Python FastAPI service that keeps HubSpot enriched from Forager. Two HubSpot
> webhooks drive it: company creation and contact creation. No n8n, no automation
> platform — the logic is Python in this repo, deployed on Railway."

Show the repo tree on screen (`app/`, `scripts/`, `README.md`, `FORAGER_NOTES.md`).

---

## 0:40 – 1:30  Architecture in one slide

Draw or show the diagram from the README:

```
HubSpot webhook → signature check → 200 ACK → background task
                                                   ├── Forager
                                                   └── HubSpot
Forager email job → callback / background poll → contact patched
```

Mention: "webhook ACKs in milliseconds because Forager calls take seconds". Signature
verification is **enforced on the live deployment** — show it (20 seconds, no credits):

```bash
curl -X POST https://web-production-2f924.up.railway.app/webhooks/hubspot -H "Content-Type: application/json" -d "[]"
# {"detail":"invalid signature"} 401

HUBSPOT_CLIENT_SECRET=<value> python scripts/replay_hubspot_webhook.py company.creation <id>
# 200 {"received":1,"queued":1}
```

---

## 1:30 – 3:00  Company flow, live

1. HubSpot → Contacts → Companies → **Create company**: name `OpenAI`, domain
   `openai.com`, leave everything else blank. Save.
2. Switch to the terminal and show the log lines arriving:
   `company.creation received` → `company.enriched` → `discover.search` →
   `contact.created` → `contact.done`.
3. Back to HubSpot, open the company record and read the filled fields out loud:
   description, industry, **annual revenue**, **employees**, city/state/country,
   LinkedIn URL.
4. Open the **Contacts** tab of the company: the enriched people are associated.

> "Nothing was typed into these fields. The company webhook fetched firmographics from
> Forager, then enriched the contacts already on the company, then looked up senior
> people at that domain and created them."

---

## 3:00 – 4:00  The title filter

Show `TARGET_TITLES` in the Railway variables (or `.env`).

> "This is the job-title filter. It is compiled into a boolean query for Forager's role
> search — `head OR director OR "vice president" OR chief …` — and every returned row is
> re-checked locally before a contact is created, so the filter holds even though the
> search engine is fuzzy."

Change it live to something narrow, e.g. `chief,founder`, redeploy or restart, and rerun
the flow on a fresh company. Fewer contacts, only matching titles. Change it back.

---

## 4:00 – 5:00  Contact flow, live

1. Create a contact manually: first name, last name, and the LinkedIn URL. Save.
2. Show the log: `contact.creation` → `contact.start` → `contact.email` /
   `contact.phone` → `contact.done`.
3. Open the contact record: name normalised, **job title**, company, location, LinkedIn,
   and the Forager custom properties (headline, skills, seniority, enriched-at).
4. Point at the email: "work email came from Forager's async job — it's queued upstream,
   so the service polls briefly and then keeps a background poller plus a callback
   endpoint, which is why the address can appear a minute after the webhook."

---

## If the HubSpot subscription is not available (fallback path)

A legacy private app cannot have webhook subscriptions created through an API — HubSpot
only allows editing them by hand in the app's Webhooks tab. If that tab is not usable on
this portal, do not fake a result. Say this on camera:

> "HubSpot sends this exact payload when a company is created. I'm replaying the same
> payload at the receiver, because subscriptions on this legacy private app can only be
> configured by hand and this portal does not expose the tab. Everything after the POST
> is the real handler: real signature check, real Forager calls, real HubSpot writes."

Then run:

```bash
python scripts/replay_hubspot_webhook.py company.creation <company_id>
```

The same script proves the security path: with `HUBSPOT_CLIENT_SECRET` set it signs the
request with the v3 HMAC scheme. Show one unsigned/wrong-secret run returning **401**,
then the correctly signed run returning **200**. That is stronger evidence than a
subscription firing, because it shows the rejection path too.

## 5:00 – 5:45  Reliability, in 45 seconds

- Create the same company twice → the log says `contact.skip` / already enriched, and the
  `/activity` view shows no duplicate credit spend.
- Resend the same webhook payload with the same `eventId` → `{"queued": 0}`, deduped.
- Open `/activity?limit=50` and `/` (config summary, no secrets).

> "Idempotency matters here because Forager charges only when it finds data: 15 credits
> per mobile, 5 per work email. Re-processing a record would burn credits for nothing."

---

## 5:45 – 6:30  The Forager findings note

Open `FORAGER_NOTES.md` and read two or three headings:

> "Three things that aren't in the docs and cost me real time: a domain search for
> `openai.com` returns 37 junk records so I resolve companies through the LinkedIn slug
> instead; the work-email endpoint rejects a payload that mixes a LinkedIn id with
> name+domain, and a LinkedIn-only lookup fails with `no_current_employer`; and the phone
> endpoint returns a bare array that's empty for a lot of people — Brad Lightcap has no
> mobile in Forager at all."

---

## 6:30 – 7:00  Wrap

- Show the live Railway URL and `/health`.
- Show the 11 custom properties (Settings → Properties → Contact / Company).
- One line on next steps: "with a paid Forager plan the email latency goes away; the next
  thing I'd add is a Redis-backed idempotency store so it can run on several replicas."

---

### Checklist before you upload

- [ ] OpenAI company record shows description, revenue, headcount, location, LinkedIn.
- [ ] Five enriched people on the OpenAI company, at least one with email + phone.
- [ ] Custom properties visible on a contact and a company.
- [ ] `/health` and `/` open on the public Railway URL.
- [ ] Video under 10 minutes, audible, no secrets visible (blur the token fields).
