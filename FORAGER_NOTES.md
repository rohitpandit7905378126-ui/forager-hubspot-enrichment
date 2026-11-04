# Forager API — notes from building this service

Everything below was learned by calling the live API (`api-v2.forager.ai`, account 2845)
while building the enrichment service. The public docs at `docs.forager.ai` do not state
these behaviours, and each one changed the implementation.

## 1. Company resolution has no detail endpoint

The API reference lists only `organization_search` and `organization_search/totals`.
There is no "look up an organization by domain" call, so company enrichment has to be a
search plus a best-match rule.

The trap: **searching a popular domain returns mostly junk.**

```
POST /datastorage/organization_search/  {"domains": ["openai.com"]}
  total_search_results: 37
  58315543  COLLABORATIVE CAPITALISM     (1 employee)
  60005638  DALL-E Open Ai               (10)
  60111835  ChatGPT                      (117)
  ...
```

OpenAI itself is not in the first page. But the LinkedIn filter is precise:

```
POST /datastorage/organization_search/  {"linkedin_public_identifiers": ["openai"]}
  total_search_results: 1
  12988797  OpenAI  |  openai.com  |  10480 employees  |  revenue 1600000000
```

So `resolve_organization()` derives a slug from the domain (`openai.com` → `openai`),
queries that first, and only falls back to the domain filter (picking the largest
employee count on the exact domain) and then to a description match on the company name.

## 2. `industry` from LinkedIn is not a HubSpot industry

Forager returns `linkedin_info.industry.name = "Research"`. HubSpot's `industry` property
is an enumeration whose stored values are `RESEARCH`, `COMPUTER_SOFTWARE`, … A `PATCH`
with the label fails and rejects **the whole payload**, so one bad field silently loses
the entire enrichment. The client now maps every value against the portal's property
definitions and drops what cannot be mapped.

## 3. Work email is an async job with three non-terminal states

`POST /api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/` returns
`202` with `{job_id, status, status_check_url}`. Observed statuses:

| status | meaning | what to do |
|---|---|---|
| `queued` | accepted | keep polling |
| `awaiting_provider` | handed to the upstream verifier | keep polling — this one lasts minutes |
| `failed` + `error_code: no_current_employer` | Forager has no current role for the person | retry with name + domain |
| `completed` | done, `emails: [...]` | write it |

It is **not** documented that `awaiting_provider` can hold a job for tens of minutes.
One lookup (`Bill Gates / microsoft.com`) was still `awaiting_provider` after 90 seconds;
`Brad Lightcap / openai.com` was still there after 40 minutes. Another one
(`Amin Tootoonchian / openai.com`) completed inside the same request. Because of that
spread, the service polls briefly and then hands off to a background poller plus the
callback URL, so the contact is patched whenever the address arrives.

## 4. The identity payload is exclusive, not additive

Sending both identifiers is rejected:

```
400 {"non_field_errors":["Provide either domain with first_name and last_name, or
linkedin_public_identifier, but not both. A domain and an identifier can disagree about
which company to search, and the answer would be unattributable."]}
```

And a LinkedIn-only lookup can fail even for a famous person, because Forager's role
history for them may have no open role:

```
{"status": "failed", "error_code": "no_current_employer"}
```

Name + domain worked where LinkedIn did not, so the client tries name + domain first and
falls back to the LinkedIn identifier.

## 5. `roles[].is_current` is not reliable

For Brad Lightcap every role came back `is_current: false`, including his current job,
with `end_date: 2026-09-01` (a date in the future). Treating `is_current` as the only
signal leaves the contact with no job title at all. `pick_role()` therefore prefers a
current role whose organization matches the company we already know, then any
`is_current`, then an open-ended role, then the most recently started role.

## 6. The phone endpoint returns a bare array

```
POST /datastorage/person_contacts_lookup/phone_numbers/
[{"phone_number": "+16195351351"}]
```

Not an object, and `[]` for plenty of high-profile people. `quality_tier` matters and is
undocumented beyond its own field description: `highest_quality` (default) is the
strictest verified set, `most_coverage` adds more numbers at its own credit rate.
For Brad Lightcap both tiers returned `[]`, so a contact can legitimately end up with an
email and no mobile. Phone parsing is defensive because of the bare-array shape.

## 7. Credits: pay-on-found

| Call | Credits |
|---|---|
| Work email found | 5 |
| Mobile found | 15 |
| Search / enrichment request | 1–2 |
| Reverse lookup (email/phone) | 5–15 |
| Anything with no result | 0 |
| Polling a job status | 0 |

Because empty lookups are free but successful ones are not, the service checks "does the
contact already have an email / phone?" before spending anything, and skips records that
are already enriched.

## 8. Person role search quirks

- `role_title` takes a **boolean text search query**, so the title filter is compiled to
  `Head OR Director OR "vice president" OR …`. Because the engine is fuzzy, every
  returned row is re-checked locally against `TARGET_TITLES` before a contact is created.
- `role_is_current: true` filters to open roles.
- Results are role rows (`role_title`, `organization`, `person`), not person rows, so a
  person can appear once per matching role; dedupe by `person.id`.
- Pages are zero-based and one page is 10 rows; `page: 1` is fetched when fewer than the
  requested number of people come back.

## 9. Running out of credits is a bare 402 with no balance endpoint

```
POST /datastorage/person_detail_lookup/  ->  402
{"message": "The account does not have sufficient credits remaining."}
```

There is no documented (or discoverable) endpoint that reports a balance or a usage
history: `/api/{account_id}/credits/`, `/account/`, `/users/me/` all 404. The only place
to see the number is the dashboard, so a service cannot pre-check whether a lookup will be
chargeable. The practical fix is to be conservative client side: skip records that are
already enriched, check "does this contact already have an email/phone?" before calling,
and treat a 402 as terminal for the run rather than retrying.

## 10. What would need a paid/dedicated plan

- Email verification latency: the upstream queue is the bottleneck, not the API.
- Phone coverage: thin for many companies, so a waterfall (second provider) would be
  needed for a "mobile for every contact" guarantee.
