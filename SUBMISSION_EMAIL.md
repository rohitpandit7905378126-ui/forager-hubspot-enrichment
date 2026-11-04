# Submission email — copy from here

Send it as a **reply to the task email** (same thread), so the evaluator sees it in context.
Attach the CV. Nothing else needs attaching.

- Recipient: reply on the original Appagentix / OneGTM Lab task thread
- Subject: `GTM Engineer task submission — Rohit Sharma (Forager x HubSpot enrichment)`
- Placeholders to fill: `[VIDEO LINK]`

---

## Email body (copy-paste)

```
Hi,

Thanks for the task — it was a good one. Below is the submission for the Forager x HubSpot
enrichment service.

Live service:   https://web-production-2f924.up.railway.app/health
Webhook URL:    https://web-production-2f924.up.railway.app/webhooks/hubspot
Activity log:   https://web-production-2f924.up.railway.app/activity
Code:           https://github.com/rohitpandit7905378126-ui/forager-hubspot-enrichment
Demo video:     [VIDEO LINK]   (6 min, unlisted)
HubSpot portal: 247887031 — company "OpenAI" already has 5 enriched contacts

What it does

A Python FastAPI service on Railway. HubSpot fires company.creation or contact.creation, the
service verifies the HubSpot v3 signature, returns 2xx immediately, and does the Forager work
in a background task. For each company it resolves the domain in Forager, writes description,
industry, revenue, headcount, LinkedIn URL and location back to the company, then discovers
decision makers (CEO, CTO, founder, VP, head, director, partner), creates them as contacts,
associates them with the company, and fills title, LinkedIn, seniority, location and work
email. No n8n, no no-code steps — the whole pipeline is Python in the repo.

Things worth knowing

- Signature verification is enforced on the live deployment. An unsigned or wrong-secret
  request gets 401; a valid v3 HMAC gets 200 and the job starts. Demoed in the video.
- Forager work-email lookup is an async job, not a field on the person object. The service
  polls until the job leaves pending/running/empty, so the request stays fast and the contact
  gets patched when the email lands.
- Re-running is safe: enrichment state is stored on the HubSpot record, so an already-enriched
  company or contact is skipped and no credits are spent. The video shows this.
- Contact discovery is capped and title-filtered on purpose. Every contact costs credits, so
  pulling the whole company list would be wasteful.
- A Forager 402 (out of credits) is caught and logged as a skip instead of retrying, so a
  drained balance can never turn into an infinite loop.
- HubSpot's industry enum does not accept Forager's LinkedIn industry strings, so industries
  are mapped before the write; work-email payloads also need the person id, not the role id.

Forager API notes

`FORAGER_NOTES.md` in the repo has the detail the public docs do not cover, written while
building this: companies have no detail endpoint (search only), the identity payload replaces
rather than merges, roles[].is_current is unreliable, the phone endpoint returns a bare array,
credits are pay-on-found, a job status of "completed" can still mean nothing was found, and
there is no balance endpoint — a drained account just returns 402.

Known limits

Two of the five OpenAI contacts have no email in Forager at any quality tier and four have no
mobile number. That is a data-availability limit, not a pipeline failure. Webhook subscriptions
on a legacy private app cannot be created through the API, so the demo replays the exact
HubSpot payload shape against the same receiver — the signature gate, Forager calls and HubSpot
writes are all the production code path.

CV attached. Happy to walk through any part of it on a call.

Thanks,
Rohit Sharma
+91 95962 78126
sharmadigitalagency1234@gmail.com
```

---

## Before you hit send (2 minutes)

1. Paste the real video link and confirm it opens in an incognito window (unlisted is fine,
   "request access" is not).
2. Open the health URL once — it must say `{"status":"healthy"}` right before sending.
3. Repo must be public (it is) and the README renders on GitHub.
4. CV file attached — check the filename has your name in it.
5. Send as a **reply** on the task thread, not a new mail, so the CV and video stay in one place.
6. Deadline: 5 Nov 2026, 13:00 IST. Send it the night before, not at 12:50.

## What to send, at a glance

| Item | Where it comes from |
|---|---|
| Reply email body | the block above |
| Demo video link | your recording, uploaded unlisted |
| CV | original file |
| Nothing else attached | repo + live URL are linked in the body |
