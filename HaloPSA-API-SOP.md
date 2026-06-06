# Halo PSA REST API — Standard Operating Procedure (ITBD tenant)

> Purpose: a single self-contained reference an LLM (or developer) can use to
> work against the **ITBD Halo PSA** REST API quickly and correctly. It captures
> the auth flow, request conventions, every reachable endpoint, the data model
> (incl. how *internal vs partner/customer* is segregated), the lookup decode
> tables, and the non-obvious quirks that otherwise cost hours.
>
> Everything here was verified empirically against the live tenant on
> 2026-06-06. Counts drift over time; treat them as orders of magnitude.

---

## Overview

Halo PSA is a PSA/ITSM platform. The REST API is **not** the "Open API" style of
TeamGPS — it is Halo's own product API. Key facts:

| | |
|---|---|
| **Tenant / Base URL** | `https://itbd.halopsa.com` |
| **API root** | `https://itbd.halopsa.com/api` |
| **Auth token URL** | `https://itbd.halopsa.com/auth/token` |
| **Auth model** | OAuth2 **client_credentials** (Bearer token, 1-hour expiry) |
| **Format** | JSON for all responses |
| **Official docs** | `https://halo.haloservicedesk.com/apidoc/info` and the Swagger at `https://itbd.halopsa.com/api/swagger` (often gated) |
| **Access level (these credentials)** | **READ-ONLY** — token grants only `read:*` scopes |

> ⚠️ The current API credentials are scoped read-only. `POST`/`PUT`/`DELETE`
> calls will fail with 401/403. Do not attempt writes; plan around GET only.

---

## Authentication

`client_credentials` grant. POST form-encoded body to the token endpoint, then
send the returned `access_token` as a Bearer header on every API call.

**Credentials** (store in env / secret manager, never in code):
```
HALO_BASE_URL    = https://itbd.halopsa.com
HALO_CLIENT_ID   = ***REMOVED***
HALO_CLIENT_SECRET = ***REMOVED***
HALO_SCOPE       = all
```

**Token request — curl**:
```bash
curl -s -X POST "https://itbd.halopsa.com/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$HALO_CLIENT_ID" \
  -d "client_secret=$HALO_CLIENT_SECRET" \
  -d "scope=all"
```

**Token response** (1-hour token):
```json
{
  "token_type": "Bearer",
  "expires_in": 3600,
  "access_token": "eyJhbGci...",
  "id_token": "eyJhbGci...",
  "scope": "openid email profile offline_access roles read:tickets read:customers read:sales read:sos read:pos read:distributionlists read:mailcampaign read:events read:assets read:kb read:software read:timesheets read:quotes read:reporting read:projects read:items read:suppliers read:contracts read:calendar read:crm read:invoices read:softwarelicensing"
}
```

**Granted scopes (read-only):** tickets, customers, sales, sos, pos,
distributionlists, mailcampaign, events, assets, kb, software, timesheets,
quotes, reporting, projects, items, suppliers, contracts, calendar, crm,
invoices, softwarelicensing. **Not granted:** any write scope, `webhook`,
`servicestatus` admin.

**Using the token — curl**:
```bash
curl -s "https://itbd.halopsa.com/api/Tickets?page_size=5&page_no=1&pageinate=true" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Accept: application/json"
```

**Python (full pattern with refresh)**:
```python
import time, requests

BASE = "https://itbd.halopsa.com"
_token, _exp = None, 0

def token():
    global _token, _exp
    if _token and time.time() < _exp - 60:
        return _token
    r = requests.post(f"{BASE}/auth/token", data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "scope": "all",
    })
    r.raise_for_status()
    j = r.json()
    _token, _exp = j["access_token"], time.time() + j["expires_in"]
    return _token

def get(path, **params):
    r = requests.get(f"{BASE}/api/{path}",
                     headers={"Authorization": f"Bearer {token()}"},
                     params=params, timeout=40)
    r.raise_for_status()
    return r.json()

tickets = get("Tickets", page_size=5, page_no=1, pageinate=True)
```

**JavaScript**:
```javascript
const BASE = "https://itbd.halopsa.com";
async function token() {
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: CLIENT_ID, client_secret: CLIENT_SECRET, scope: "all",
  });
  const r = await fetch(`${BASE}/auth/token`, { method: "POST", body });
  return (await r.json()).access_token;
}
const t = await token();
const res = await fetch(`${BASE}/api/Tickets?page_size=5&page_no=1&pageinate=true`,
  { headers: { Authorization: `Bearer ${t}`, Accept: "application/json" } });
const data = await res.json();
```

---

## Request conventions

- **All endpoints live under `/api/`** and use **PascalCase** resource names:
  `/api/Tickets`, `/api/Client`, `/api/Users`, `/api/Asset`, `/api/Agent`.
- **Singular vs plural is inconsistent** by design. It is `Client` (singular)
  but `Tickets`, `Users`, `Projects` (plural). Use the exact names in the
  Data Inventory table below.
- **A single record** is fetched at `/api/{Resource}/{id}` (e.g.
  `/api/Tickets/750606`). Always add `includedetails=true` to get the full
  record (see quirks).

### Pagination

| Param | Meaning |
|---|---|
| `pageinate` | `true` to enable paging (note the Halo spelling: **pageinate**) |
| `page_no` | 1-based page number |
| `page_size` | rows per page (use up to ~100–200; some endpoints ignore it) |
| `count` | hard cap on number of rows returned (⚠️ overrides record_count — see quirks) |

**List response shape** — a wrapper object with a total and a data array whose
**key name varies per endpoint**:
```json
{ "record_count": 761193, "tickets": [ { ... }, { ... } ] }
```
The data-array key is e.g. `tickets`, `clients`, `users`, `assets`, `sites`,
`contracts`, `invoices`, `items`, `suppliers`, `articles`, `reports`,
`quotes`, `salesorders`, `purchaseorders`, `tree` (Toplevel), `results` (Agent).
**Some endpoints return a bare JSON array** (Status, Priority, TicketType,
Category, Lookup, FieldInfo, etc.) with no wrapper.

> ✅ Robust parsing rule: if the body is a list, use it directly; if it's a
> dict, read `record_count` and then take the first value that is a non-empty
> list of objects.

### Common query parameters

| Param | Applies to | Meaning |
|---|---|---|
| `search` | most list endpoints | case-insensitive substring filter (summary/name/etc.) |
| `includedetails` | detail + some lists | return the full record incl. nested arrays & custom fields |
| `includeinactive` | Client, Users, Asset… | include `inactive=true` rows (default excludes them) |
| `includeactivity` | Tickets | include action/activity data |
| `ticket_id` | Actions | **required** — actions are always scoped to a ticket |
| `client_id`, `site_id`, `user_id` | Tickets, Site, Users… | scope by parent |
| `count` | list | cap rows (see quirk) |
| `order` / `orderdesc` | many | sort field / direction |

---

## ⚠️ Critical quirks & gotchas (read this first)

These are the things that trip people up on Halo's API:

1. **The data-array key changes per endpoint** (`tickets`, `clients`, `results`,
   `tree`, …). Never hard-code one key. Opportunities & Projects return their
   array under **`tickets`** because they are ticket subtypes.

2. **`Opportunities` and `Projects` ARE tickets.** They share the ticket schema
   (~110 fields) and live in the same table, filtered by ticket type. To fetch
   one fully, use `/api/Tickets/{id}` as well.

3. **Custom fields only appear on the DETAIL call.** List responses (e.g.
   `/api/Client`, `/api/Tickets`) return `customfields: null`. You must call
   `/api/{Resource}/{id}?includedetails=true` to get the `customfields[]` array
   (each item: `{id, name, value, display, type}`).

4. **`/api/Actions` returns HTTP 500 with no params.** It requires
   `?ticket_id={id}`. For the richest note content (body, email headers,
   attachments, time/charges) fetch each action at `/api/Actions/{action_id}?ticket_id={id}`
   (≈100 fields vs ≈55 in the list).

5. **`/api/Team` and `/api/Department` return empty / are out of scope** for
   these credentials. Reconstruct the org tree from **`/api/Agent`** instead:
   each agent embeds `teams[]` (`team_id`, `team_name`, `department_id`) and
   `departments[]`. (See "Internal org" below.)

6. **`/api/Lookup` ignores pagination** — every page returns the *entire* set.
   Fetch once with a large `page_size` and **dedupe by `(lookupid, id)`**.
   Group by `lookupid` to get individual lookup tables.

7. **`count` overrides `record_count`.** If you pass `count=1` to peek, the
   response's `record_count` becomes 1, not the true total. To read true totals,
   use `page_size=1` (and do **not** pass `count`).

8. **Read-only.** Writes fail. `Webhook`→401, `ServiceStatus`→403.

9. **`includeinactive=true`** is needed to see deactivated clients/users/assets;
   the default view hides them.

10. **`search` is server-side substring, case-insensitive**, and works on
    Tickets/Client/Site/Users/Asset/etc., but **`Agent` ignores `search`** —
    pull all agents and filter locally.

---

## ⚠️ Addendum — verified findings (2026-06-06 build session)

These corrected or refined the notes above while building a live tickets cache.
Trust these over any conflicting statement earlier in this doc.

1. **`record_count` is NOT reliable, and `page_size=1` does NOT give the true
   total.** On `/api/Tickets` both a 30-day filter and the all-time call returned
   `record_count: 50` regardless of `page_size`. The only way to get a real count
   is to **paginate by `page_no` until an empty/repeating page** and dedupe by
   `id`. (Supersedes quirk #7's "use page_size=1" tip.)

2. **`page_size` is effectively capped/erratic (~50) on `/api/Tickets`.** It is
   often ignored: `page_size=1,5,100,500` all returned 50 rows. Paginate with
   `page_no`; treat page size as advisory. (Some runs did honor 100 — inconsistent.)

3. **Real 30-day volume:** ~**31,535** tickets (paginated, deduped) for the
   2026-05-07→06-06 window. ~1,000 tickets/day (lots of automated NOC/RMM rows).
   Full detail+actions for all of them is NOT cacheable in one pass — cache the
   list, fetch each dossier (detail + `/api/Actions`) live on demand.

4. **List rows carry IDs only — NO decode names.** `/api/Tickets` list rows have
   `status_id`/`priority_id`/`tickettype_id`/`agent_id` but **no** `status_name`,
   `priority_name`, `tickettype_name`, or `agent_name` (client/site/user names
   *are* present). Decode IDs yourself from Status / Priority / TicketType / Agent.

5. **Priority decode is special:** a `/api/Priority` row's own `id` is a **GUID**;
   the ticket's numeric `priority_id` matches the row's **`priorityid`** field
   (not `id`). Build the map keyed on `priorityid`. Observed: 1=Critical, 2=High,
   3=Medium, 4=Priority 4 - Scheduled Maintenance (rows duplicate per priorityid).

6. **`deadlinedate` is a `1900-01-01T00:00:00` null-sentinel** when unset — do not
   treat it as a real deadline. The real SLA targets are **`fixbydate`** (fix-by)
   and **`respondbydate`** (respond-by). Null out any pre-2000 date.

7. **No closed flag on `/api/Status`.** The `type` field is NOT it (type 0 holds
   both "New" and "Closed"/"Completed"/"Cancelled"). Detect closed by **name
   heuristic** (`closed|resolved|complete|cancel`) — ~15 of 163 statuses match.

8. **Departments have NO name in the API.** `/api/Agent` `teams[]` gives only
   `department_id` (and `departments[]` has no name either). Single-team
   departments can be auto-named from their one team; multi-team need a curated
   map. Full decode table below (section D updated).

---

## Data Inventory (reachable endpoints)

Counts as of 2026-06-06 on the ITBD tenant. "—" = count not reported by the API
for that endpoint (usually a bare-array reference table).

| Module | Records | Endpoint | Array key | Category |
|---|---|---|---|---|
| Tickets | 761,193 | `/api/Tickets` | `tickets` | Service Desk |
| Users (contacts) | 31,065 | `/api/Users` | `users` | CRM |
| Assets / CIs | 22,627 | `/api/Asset` | `assets` | Assets |
| Recurring invoices | 2,341 | `/api/RecurringInvoice` | `invoices` | Finance |
| Projects | 1,415 | `/api/Projects` | `tickets` | Projects |
| Sites | 1,230 | `/api/Site` | `sites` | CRM |
| Client contracts | 1,074 | `/api/ClientContract` | `contracts` | CRM |
| Clients (accounts) | 838 | `/api/Client` | `clients` | CRM |
| Report definitions | 539 | `/api/Report` | `reports` | Reporting |
| Agents (staff) | 253 | `/api/Agent` | `results` | Org / Staff |
| Catalogue items | 243 | `/api/Item` | `items` | Finance |
| KB articles | 173 | `/api/KBArticle` | `articles` | Knowledge |
| Service catalogue | 21 | `/api/Service` | `services` | Assets |
| Suppliers | 12 | `/api/Supplier` | `suppliers` | Finance |
| Opportunities | 9 | `/api/Opportunities` | `tickets` | CRM |
| Top Levels | 3 | `/api/Toplevel` | `tree` | CRM |
| Invoices | (large) | `/api/Invoice` | `invoices` | Finance |
| Timesheet events | ~4,410 | `/api/TimesheetEvent` | (array) | Service Desk |
| Timesheets | ~3,456 | `/api/Timesheet` | (array) | Service Desk |
| **Reference / config tables** | | | | |
| Custom field defs | ~1,428 | `/api/FieldInfo` | (array) | Config |
| Lookup tables | 169 tables / ~1,529 rows | `/api/Lookup` | (array) | Config |
| Statuses | ~163 | `/api/Status` | (array) | Config |
| Categories | ~318 | `/api/Category` | (array) | Config |
| Ticket types | ~83 | `/api/TicketType` | (array) | Config |
| Priorities | ~20 | `/api/Priority` | (array) | Config |
| Email templates | ~141 | `/api/EmailTemplate` | (array) | Config |
| Workflows | ~31 | `/api/Workflow` | (array) | Config |
| Asset types | ~19 | `/api/AssetType` | (array) | Assets |
| Asset groups | ~20 | `/api/AssetGroup` | (array) | Assets |
| SLAs | ~5 | `/api/Sla` | (array) | Config |
| Roles | ~26 | `/api/Roles` | (array) | Org / Staff |
| Holidays | ~355 | `/api/Holiday` | (array) | Org / Staff |
| Currencies | 2 | `/api/Currency` | (array) | Finance |
| Organisations | 1–2 | `/api/Organisation` | (array) | CRM |
| Approval processes | ~9 | `/api/ApprovalProcess` | (array) | Service Desk |

**Empty on this tenant** (reachable, 0 rows): `Quotation`, `SalesOrder`,
`PurchaseOrder`, `TaxRule`, `CustomButton`, `Team`.

> `Attachment` returns 0 rows **only without a filter** — it requires
> `?ticket_id={id}` and then works (incl. downloading the file bytes). See the
> dedicated "Attachment" endpoint section below.

**Not present / out of scope**: `Department`, `Area`, `ToplevelView`, `Stock`,
`Warehouse`, `NominalCode`, `CostCentre`, `PaymentMethod`, `Software`,
`Renewal`, `Distributionlist`, `Notice`, `ReportData`, `Webhook` (401),
`ServiceStatus` (403).

---

## Endpoint reference

For each endpoint the field lists below are the **list-view** fields. The
**detail view** (`/{id}?includedetails=true`) returns many more (Tickets detail
≈313 fields, plus `customfields[]`, `outcomes[]`, `workflow_history[]`,
`viewers[]`, `extratabs[]`).

### 1. Tickets  `/api/Tickets`

The core object. Also the storage for Opportunities and Projects (subtypes).

**List params**: `pageinate`, `page_no`, `page_size`, `search`,
`client_id`, `site_id`, `user_id`, `agent_id`, `status_id`, `tickettype_id`,
`team`, `category_1`, `open_only`, `closed_only`, `includeinactive`,
`includeactivity`, `datesearch` + `startdate`/`enddate`, `order`, `orderdesc`.

**Detail**: `/api/Tickets/{id}?includedetails=true&includelastaction=true`

**Key list fields** (106): `id`, `summary`, `details`, `tickettype_id`,
`status_id`, `priority_id`, `impact`, `urgency`, `client_id`, `client_name`,
`site_id`, `site_name`, `user_id`, `user_name`, `user_email`, `agent_id`,
`team`, `team_id`, `department_id`, `category_1..4`, `dateoccurred`,
`deadlinedate`, `fixbydate`, `respondbydate`, `lastactiondate`, `dateassigned`,
`sla_id`, `source`, `reportedby`, `emailtolist`, `emailcclist`, `child_count`,
`attachment_count`, `cost`, `estimate`, `ticket_tags`, `workflow_id`,
`workflow_step`, `merged_into_id`, `userdef1..5`.

**Detail-only adds**: `status_name`, `priority_name`, `tickettype_name`,
`agent_name`, `category_1` (name), `customfields[]`, `actions/last action`,
SLA timers, `workflow_history[]`, billing lines, linked assets/users.

**Sample (list row, trimmed)**:
```json
{
  "id": 750606, "summary": "Monthly Feedback For Scout",
  "tickettype_id": 30, "status_id": 9, "priority_id": 4,
  "client_id": 246, "client_name": "Pegasus Tech Solutions",
  "site_id": 553, "site_name": "Main",
  "user_id": 37343, "user_name": "Scout Kalra",
  "agent_id": 415, "team": "DES",
  "dateoccurred": "2026-04-23T19:42:21Z",
  "lastactiondate": "2026-04-23T20:05:27Z",
  "category_1": "Internal IT", "attachment_count": 0
}
```

**Actions (the conversation)** — `/api/Actions?ticket_id={id}` then
`/api/Actions/{action_id}?ticket_id={id}` for full detail. Useful action fields:
`id`, `who`, `datetime`, `outcome`, `note` (HTML body), `new_status_name`,
`old_status`, `hiddenfromuser` (private note), `emailfrom`, `emailto`,
`emailsubject`, `timetaken`, `actionchargehours`, `attachment_count`.

---

### 1b. Attachment  `/api/Attachment`  (ticket files — service-review decks)

Ticket attachments **are** reachable on read-only credentials (they ride on
`read:tickets`; there is no separate `attachments` scope). This is how we pull
the **bi-weekly service-review decks** (PDF or PPTX) for downstream MarkItDown →
Markdown conversion. Verified live on the ITBD tenant 2026-06-07.

> ⚠️ The bare `/api/Attachment` call returns 0 rows — it **requires a filter**
> (`ticket_id`). This is what the inventory table means by "needs a filter".

**Step 1 — list a ticket's attachments**:
```
GET /api/Attachment?ticket_id={ticket_id}
```
Returns a wrapper object (note the array key is **`attachments`**, plus a
`folders` array):
```json
{
  "ticket_id": 740408, "record_count": 1, "folders": [],
  "attachments": [
    {
      "id": 632243,
      "filename": "Logically_Bi-Weekly_ServiceReview_ 22nd May 2026.pdf",
      "filesize": 1751223, "type": 0, "isimage": false, "note": ""
    }
  ]
}
```
Useful fields: `id`, `filename` (carries the real extension — `.pdf` / `.pptx`),
`filesize`, `type`, `isimage`, `note`. A ticket's `attachment_count` (on the
ticket detail) tells you whether it's worth calling. Note: open/in-progress
review tickets often have **no deck yet** — the deck is attached when the call is
written up and the ticket closed (look for the `"I have attached the Deck"` line
in the closing action note).

**Step 2 — download the bytes** (two delivery modes — handle both):
```
GET /api/Attachment/{attachment_id}
```
The same endpoint returns the file **two different ways** depending on where Halo
stores it:

1. **Inline** — responds with the **raw bytes** directly
   (`Content-Type: APPLICATION/octet-stream`; body begins e.g. `%PDF-1.7…`).
   Observed for the smaller PDF decks.
2. **CDN redirect** — responds with **JSON** containing a pre-signed CloudFront
   URL instead of bytes:
   ```json
   { "link": "https://us-cdn.haloservicedesk.com/itbydesign/Attachments/<guid>.pptx?Expires=…&Signature=…&Key-Pair-Id=…" }
   ```
   You must then `GET` that `link` (it is already authenticated via the signature
   — send **no** `Authorization` header) to retrieve the actual bytes. Observed
   for the larger PPTX decks. The pre-signed URL is time-limited (`Expires`).

Robust client logic: fetch `/api/Attachment/{id}`; if the response is JSON with a
`link` key (or the body starts with `{"link"`), follow the link; otherwise treat
the body as the file. See `extract/halo.py::download_attachment`.

```bash
# list
curl -s "https://itbd.halopsa.com/api/Attachment?ticket_id=740408" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
# download (inline case → file bytes; CDN case → {"link": "..."} to follow)
curl -s "https://itbd.halopsa.com/api/Attachment/632243" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -o deck.pdf
```

---

### 2. Client  `/api/Client`  (accounts / customers)

**List params**: `pageinate`, `page_no`, `page_size`, `search`,
`includeinactive`, `toplevel_id`, `client_ids`, `order`.

**Detail**: `/api/Client/{id}?includedetails=true` (adds `customfields[]`).

**Key fields** (67): `id`, `name`, `ref`, `toplevel_id`, `toplevel_name`,
`customertype` (→ lookup 33; see segregation), `is_account`, `is_vip`,
`inactive`, `customer_relationship`, `customer_relationship_list`,
`accountmanagertech`, `accountownertech`, `pritech`, `sectech`,
`client_to_invoice`, `clientcurrency`, `default_currency_code`,
`messagegroup_id`, `colour`, `notes`, and many integration IDs
(`qbo_company_id`, `xero_tenant_id`, `itglue_id`, `connectwiseid`,
`autotaskid`, `cautomateid`, `sentinel_*`).

**Sample**:
```json
{
  "id": 246, "name": "Pegasus Tech Solutions", "ref": "PTS",
  "toplevel_id": 1, "toplevel_name": "IT By Design",
  "customertype": 7, "is_account": false, "inactive": false,
  "accountmanagertech": 112, "pritech": 415
}
```

> Service line per client is stored in custom field **`CFProduct`** (detail
> call), decoded via lookup 76 (MDE / NOC / Team GPS / Managed IT / …).

---

### 3. Users  `/api/Users`  (end-user contacts)

31k+ contacts. **Use `search`** to find people by name/email.

**Key fields** (50): `id`, `name`, `firstname`, `surname`, `emailaddress`,
`login`, `client_id`, `client_name`, `site_id`, `site_name`, `phonenumber`,
`mobilenumber`, `title`, `inactive`, `is_prospect`, `isserviceaccount`,
`linked_agent_id` (if the contact is also an agent), `date_of_birth`,
`other1..5`, integration IDs (`azureoid`, `connectwiseid`, `autotaskid`).

**Example — find a person**:
```bash
curl -s "https://itbd.halopsa.com/api/Users?search=Scout%20Kalra&page_size=5" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

---

### 4. Asset  `/api/Asset`  (configuration items)

22k+ CIs. **Key fields** (56): `id`, `inventory_number`/`key_field`,
`assettype_id`, `assettype_name`, `client_id`, `client_name`, `site_id`,
`site_name`, `status_id`, `criticality`, `business_owner_id/name`,
`technical_owner_id/name`, `supplier_id`, `item_id`, `username`, plus RMM/tool
linkage IDs (`datto_id`, `ninjarmm_id`, `automate_id`, `addigy_id`,
`auvik_device_id`, `ncentral_details_id`, `syncroid`, `device42_id`).
Use `includeinactive=true` for retired assets. Detail: `/api/Asset/{id}?includedetails=true`.

---

### 5. Site  `/api/Site`

**Key fields** (27): `id`, `name`, `client_id`, `client_name`, `phonenumber`,
`timezone`, `geocoord1/2`, `maincontact_id`, `sla_id`, `isinvoicesite`,
`isstocklocation`, `inactive`, `messagegroup_id`. Filter by `client_id`.

---

### 6. Agent  `/api/Agent`  (internal staff) — also the org-tree source

253 agents. **Ignores `search`** — pull all and filter locally. Critically,
each agent embeds the **team & department membership** used to reconstruct the
org structure.

**Key fields** (39): `id`, `name`, `firstname`, `surname`, `email`, `jobtitle`,
`team` (primary/“ALL”), **`teams[]`**, **`departments[]`**, `is_agent`,
`isdisabled`, `licence_type`, `linemanager`, `chargerate`, `costprice`,
`lastlogindate`, integration IDs.

**`teams[]` item**: `{ team_id, team_name, department_id, role_id, fortickets,
forprojects, foropps, unassigned_access }`
**`departments[]` item**: `{ department_id, membershiplevel, role_id }`

---

### 7. ClientContract  `/api/ClientContract`

**Key fields** (34): `id`, `ref`, `client_id`, `client_name`, `site_id`,
`contracttype`, `contracttype_name`, `contract_status`/`status`, `start_date`,
`end_date`, `expired`, `active`, `billingperiod`, `billingcategory`,
`billingdescription`, `periodchargeamount`, `next_invoice_date`,
`cost_calculation`, `sla_id`. Filter by `client_id`.

---

### 8. Item  `/api/Item`  (product/service catalogue)

112 fields incl. `id`, `name`, `description`, `type`, `baseprice`, `costprice`,
`recurringprice`, `recurringcost`, `taxcode`, `nominalcode`, `supplier_id/name`,
`quantity_in_stock`, `isrecurringitem`, `iscontractitem`, and a large set of
accounting-integration fields (QBO/Xero/Sage/Exact/KashFlow/Snelstart).

---

### 9. Invoice  `/api/Invoice`  &  RecurringInvoice  `/api/RecurringInvoice`

110/116 fields: `id`, `invoicenumber`, `client_id`, `client_name`,
`invoice_date`, `duedate`, `total`, `tax_total`, `amountdue`, `amountpaid`,
`paymentstatus`, `currency`, `contract_id`, `ticket_id`, `salesorder_id`,
`posted`, `voided`, accounting-sync IDs. RecurringInvoice adds
`period_start_date`, `period_end_date`, `nextcreationperiod`.

---

### 10. KBArticle  `/api/KBArticle`

24 fields: `id`, `name`, `description`, `type`, `kb_tags`/`tag_string`,
`date_created`, `date_edited`, `next_review_date`, `view_count`,
`useful_count`, `notuseful_count`, `inactive`, `ticket_template_id`.

---

### 11. Reference / config endpoints (bare arrays)

| Endpoint | Use |
|---|---|
| `/api/Status` | ticket status id→name, colours, types |
| `/api/Priority` | priority id→name, SLA targets |
| `/api/TicketType` | request types (id→name), incl. Opp/Project types |
| `/api/Category` | category trees (`type_id` filters which tree) |
| `/api/Sla` | SLA definitions |
| `/api/Workflow` | workflow/process definitions |
| `/api/Roles` | security roles |
| `/api/AssetType`, `/api/AssetGroup` | asset taxonomy |
| `/api/EmailTemplate` | email templates |
| `/api/FieldInfo` | **all custom field definitions** (~1,428) — `id`, `name`, `label`, `type`, usage flags |
| `/api/Lookup` | **all lookup tables** (see decode section) |
| `/api/Report` | 539 saved report definitions (gateway to ad-hoc data) |

---

## The ITBD data model — internal vs partner/customer segregation

This is the part most people get wrong. There is **no single "is_partner"
boolean**. Segregation is layered:

### A. Top Level (`/api/Toplevel`, key `tree`) — division grouping
Only **3** top levels, all under one Organisation ("IT by Design"):

| id | name |
|---|---|
| 1 | IT By Design |
| 34 | IT By Design - Noida |
| 12 | Team GPS |

⚠️ **~99% of clients sit under Top Level 1**, so Top Level is *not* the working
segregation axis. Fields: `id`, `name`, `organisation_id`, `organisation_name`,
`org_department_name`, `long_name`, `type`, `customfields[]`.

### B. `Client.customertype` → **lookup 33** — the explicit account class
The closest thing to an internal/partner flag. Decode the integer:

| value | meaning | ~clients |
|---|---|---|
| 0 | (unset) | ~714 |
| 10 | Customer | ~97 |
| 7 | Customer-Managed IT | ~31 |
| 8 | BHN Customer | ~25 |
| 11 | **Internal** | ~3 |
| 12 | **Partner** | ~2 |
| 9 | Owner | ~2 |
| 13 | Other | ~2 |
| 1–6 | industry verticals (Education, Retail, Manufacturing, Finance, Construction, Food) | few |

> Reality: `customertype` is **sparsely populated** (most clients are 0/unset).
> Don't rely on it alone.

### C. `Client.CFProduct` (custom field) → **lookup 76** — service line / BU
The real operational segmentation. Custom field on the client (detail call only).
Lookup 76 values: **Team GPS, MDE, MSP NOC & HD, IMS, Managed IT, Dedicated
Services India, Dedicated Services PH, Cost+ India, Cost+ PH, Co-Managed,
Self Managed, Shared Service India, Flex**.

Other relevant client fields: `is_account`, `is_vip`, `customer_relationship`,
`accountmanagertech`/`pritech`/`sectech` (assigned staff), `inactive`.

### D. Internal org — Departments & Teams (reconstruct from `/api/Agent`)
`/api/Team` and `/api/Department` are empty for these creds. Rebuild from each
agent's `teams[]`/`departments[]`. Result on this tenant: **45 teams across ~34
departments**. Major departments:

| Dept id | Function | Notable teams |
|---|---|---|
| 3 | Service Delivery (largest, ~153) | MSP Business Helpdesk, BHD Implementations/Pro Services, Escalations, Change/Problem Mgmt, ITBD Proactive Maintenance, MSP SOC Alerts, QA, Service Management |
| 40 | Support Team (~110) | Support Team |
| 15 | NOC (~45) | Backups, NOC RMM Critical, NOC RMM Urgent |
| 22 | Projects (~39) | Projects |
| 23 | RMM Admin (~40) | RMM Admin Services |
| 16 | DES (~32) | DES, DES Change Management, DES CSAT Monthly |
| 38 | Automation & AI (~34) | Automation & AI, AI Ideas |
| 13 | Internal IT (~15) | Internal HelpDesk, Change Management - Internal |
| 8 | Sales/Marketing | Sales, Leads, Marketing |
| 10 | Finance | Accounting, Accounting India, Finance - PH |
| 11 | HR/Admin | Human Resources - India, Admin-Ops, Training |
| 32 | Team GPS | Team GPS Support |
| 2 | Operations | Operations |
| 24 | PH Admin | PH Admin |
| 26 | L&D (Learning & Dev) | L&D |
| 35 | HR PH | HR PH |

> ⚠️ **The API exposes no department NAME** — only `department_id` on each agent's
> `teams[]`. Names above are reconstructed: multi-team departments (3, 15, 16…) use
> the curated names here; **single-team departments take their one team's name**
> (e.g. 2→Operations, 24→PH Admin, 26→L&D, 35→HR PH). Build the `department_id →
> name` map programmatically from `/api/Agent` and fall back to `Dept {id}` for any
> unmapped id.

---

## Lookup decode catalog

Fetch once: `GET /api/Lookup?page_size=5000` → dedupe by `(lookupid,id)` →
group by `lookupid`. Each row: `{ lookupid, id, name, value4..6, custom1, custom2 }`.

| lookupid | Meaning |
|---|---|
| **33** | Client `customertype` (Customer / Internal / Partner / verticals) |
| **76** | Service line / business unit (Team GPS, MDE, MSP NOC & HD, Managed IT, Cost+, Co-Managed, Flex…) |
| 82 | CRM lifecycle stage (Subscriber, Lead, MQL, SQL, Opportunity, Customer, Evangelist) |
| 147 | Revenue / service category |
| 162 | Internal division (BuildIT, Executive Leadership, Finance, HR, Sales) |
| 196 | AIBD Internal vs AIBD Pro Services |
| 123 | Provider relationship (Us / In House Team / Small/Medium/Large Provider) |
| 21 | Ticket request types |
| 71 | Opportunity stage |
| 61 | Asset status |

To find which lookup a coded field uses: collect the field's distinct integer
values and match them against each lookup's id-set (that's how 33↔customertype
and 76↔CFProduct were identified).

---

## Common recipes

**Find the true total for any list** (no download):
```bash
curl -s "https://itbd.halopsa.com/api/Tickets?page_size=1" -H "Authorization: Bearer $T" | jq .record_count
```

**Search every place a keyword appears** (per endpoint that supports `search`):
```
GET /api/Tickets?search=Scout&page_size=50&page_no=1   # then page_no=2,3...
GET /api/Users?search=Scout
GET /api/Client?search=Acme
```

**Full ticket dossier** (everything Halo knows):
```
GET /api/Tickets/{id}?includedetails=true&includelastaction=true
GET /api/Actions?ticket_id={id}
GET /api/Actions/{action_id}?ticket_id={id}   # for each action, full body
```

**Tickets for a client** (last 90 days, open):
```
GET /api/Tickets?client_id=246&open_only=true&datesearch=dateoccurred&startdate=2026-03-08&page_size=100&page_no=1&pageinate=true
```

**Decode a client's class & service line**:
```
GET /api/Client/{id}?includedetails=true
# customertype -> lookup 33 ; customfields[].CFProduct -> lookup 76
```

**Paginate everything** (Python):
```python
def fetch_all(path, page_size=100, **params):
    out, page = [], 1
    while True:
        body = get(path, pageinate=True, page_no=page, page_size=page_size, **params)
        rows = body if isinstance(body, list) else next(
            (v for v in body.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])
        out += rows
        if len(rows) < page_size: break
        page += 1
    return out
```

**Reconstruct the org tree**:
```python
agents = fetch_all("Agent")
teams = {}
for a in agents:
    for tm in a.get("teams", []):
        teams[tm["team_id"]] = (tm.get("team_name"), tm.get("department_id"))
```

---

## Error responses

| Status | Meaning / typical cause |
|---|---|
| 200 | Success |
| 400 | Bad request — malformed/invalid parameter |
| 401 | Unauthorized — missing/expired token, or scope not granted (e.g. Webhook) |
| 403 | Forbidden — endpoint not permitted for this client (e.g. ServiceStatus) |
| 404 | Not found — wrong resource name/casing, or endpoint absent on tenant |
| 429 | Rate limited — honour `Retry-After`, back off exponentially |
| 500 | Server error — often a required param is missing (e.g. `/api/Actions` without `ticket_id`) |

Be polite: small delays between calls, exponential backoff on 429/5xx, and cache
the token for its full hour.

---

## Tips

- ⚠️ `record_count` is unreliable on `/api/Tickets` (returns 50 regardless) — to
  get a true total, paginate by `page_no` and dedupe by `id` (see Addendum #1–2).
- Always `includedetails=true` when you need custom fields or nested data.
- `includeinactive=true` to see deactivated records.
- Resource names are **PascalCase and case-sensitive**; mixed singular/plural.
- Opportunities/Projects are tickets — reuse ticket tooling.
- For anything not exposed as a first-class endpoint, check `/api/Report`
  (539 saved reports) — many datasets are reachable via reporting.
- Dates are ISO-8601 (`2026-06-06T19:42:21Z`); range filters use
  `datesearch=<field>&startdate=&enddate=`.

---

## Companion local artifacts (in `C:\temp\New folder\`)

These were generated while mapping the API and stay useful as living references:

| File | What it is |
|---|---|
| `halo_api_schema.json` / `.md` | **Living schema** — every endpoint, every field ever seen (types, fill rate, example), record counts, decoded lookup catalog, run history. Merged/updated on each run. |
| `halo_explore.py` | Read-only explorer: auth → endpoint map → segregation analysis → schema. `python halo_explore.py` |
| `halo_search.py` | Keyword sweep across endpoints → `halo_search_results/<ts>/`. `python halo_search.py --terms Foo` |
| `halo_ticket_dump.py` | Full ticket dossiers (ticket + every action at full detail) → `halo_ticket_dossiers/<ts>/`. |
| `halo_report.py` | Builds a self-contained `halo_report.html` viewer from the above. |

To regenerate the authoritative field-level schema at any time:
```bash
python halo_explore.py            # refreshes halo_api_schema.json (+ .md)
```

---

_Last verified: 2026-06-06 against `https://itbd.halopsa.com`. Credentials are
read-only; rotate the client secret if this document is shared._
