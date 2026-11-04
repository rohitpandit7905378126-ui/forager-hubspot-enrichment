# Demo video script (target: 6–8 minutes)

## How to record it (read this first)

**Do not film the laptop with a phone.** Screen recording plus voice is what a technical
grader expects; a phone shot of a screen is unreadable at 720p, shows moiré, and looks
improvised. Record the screen directly.

| Tool | When to use it |
|---|---|
| **OBS Studio** (free) | Default choice. 1920x1080, 30fps, mic on, unlimited length. |
| **Zoom** — share screen, "Record on this computer" | Zero setup, no time limit, good mic capture. |
| **PowerPoint** → Insert → Screen Recording | Quick and already installed, but harder to narrate cleanly. |
| Xbox Game Bar (Win+G) | Only as a last resort. Cannot record File Explorer or the desktop. |

**Narration: yes, speak.** Silence with on-screen text reads as unfinished. Speak in clear
English (the evaluator is an agency, not a Hindi-speaking client), calm pace, no script
reading — keep a short bullet list next to the screen and say it in your own words. If you
fumble a sentence, keep going; do not restart the take.

**Before you hit record**

1. Monitor 1920x1080, browser zoom 110%, bookmarks bar hidden (`Ctrl+Shift+B`).
2. Close every tab that shows a token, key or personal inbox. The HubSpot access token and
   the Railway dashboard with `HUBSPOT_CLIENT_SECRET` visible must **not** appear on
   screen — mention them, don't show them.
3. Terminal: dark theme, font 16pt or larger, `cls` before you start.
4. Windows → Focus assist on, notifications off, WhatsApp/Outlook closed.
5. Mic test: record 15 seconds, play it back, confirm no fan noise and no clipping.
6. Do one full dry run without recording. The second pass is the one you keep.

**Order of windows to prepare (open in this order, before recording)**

1. GitHub repo page (file tree, README)
2. Terminal, repo cloned, `cd forager-hubspot-enrichment`
3. `https://web-production-2f924.up.railway.app/` (config summary)
4. HubSpot → Companies list, and a second HubSpot tab on the empty OpenAI-less company form
5. `https://web-production-2f924.up.railway.app/activity`
6. `FORAGER_NOTES.md` in the editor

Face camera from a phone is optional and only for the first 10 seconds if you want a
personal intro — landscape, window light, eye level, then cut to the screen. Not required.

---

## Narration cheat sheet (say it in your own words, roughly 6:30 total)

| Time | Say roughly this | Show |
|---|---|---|
| 0:00 | "Hi, I'm Rohit Sharma. This is a Python FastAPI service that keeps HubSpot enriched from Forager. No n8n, no no-code — all Python, deployed on Railway." | Repo tree |
| 0:40 | "Two HubSpot webhooks drive it: company creation and contact creation. Signature is checked first, then I return 200 immediately and do Forager work in the background, because Forager calls take seconds and HubSpot will not wait." | README diagram |
| 1:30 | "Bad signature gets 401. Valid v3 HMAC gets 200 and the job starts. Same URL, same payload." | Terminal, two curl runs |
| 2:00 | "Now the company flow. I create Cursor in HubSpot with just a domain." | HubSpot form |
| 2:40 | "That fires company.creation. The service resolves the domain in Forager, writes description, revenue, headcount, industry, then looks for decision makers." | `/activity` |
| 3:30 | "Back in HubSpot: company fields are filled and the people are attached with titles, LinkedIn, seniority, location." | HubSpot record |
| 4:00 | "I don't pull every contact. Discovery is filtered to CEO, CTO, founder, VP, head, director, partner — every contact costs credits, so this is a cost decision, not a limitation." | `/` config |
| 4:40 | "Run it again: nothing is re-enriched, nothing is re-charged. Enrichment state lives on the record." | `/activity` |
| 5:10 | "Contact flow: Forager work email is an async job, so I ACK, poll, then patch the contact." | Contact record |
| 5:45 | "Four things the Forager docs do not tell you." | `FORAGER_NOTES.md` |
| 6:20 | "What I'd add next: a durable queue, retry with backoff, and a per-portal credit budget. Thanks for watching." | Repo README |

---


Record with OBS or a plain screen recorder, 1080p, mic on. Keep the HubSpot tab full
width and the terminal in a second tab. Say what you are about to show *before* you show
it — graders skim.

---

## Quick path

Prefer copy-paste commands for every shot? Use `VIDEO_COMMANDS.md` — it has the exact
PowerShell/curl lines, including the signed replay.

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
