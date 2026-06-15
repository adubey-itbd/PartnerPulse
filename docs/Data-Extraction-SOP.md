# SOP: Data Extraction & Integration Pattern for PartnerPulse Dashboard

This document details the standardized multi-source data extraction, cleaning, and integration pattern that was successfully established for Logically (Client ID: 106). This procedure should be implemented programmatically for all other partners to populate the unified sentiment and risk analysis dashboard.

---

## Data Integration Architecture

```mermaid
flowchart TD
    subgraph Local Storage
        Transcripts["Meeting Transcripts (.docx)"]
    end

    subgraph TeamGPS API
        CSAT_API["CSAT Endpoint"]
        NPS_API["NPS Client Endpoint"]
    end

    subgraph HaloPSA API
        Client_API["Client Details Endpoint"]
        Users_API["Users (Contacts) Endpoint"]
        Tickets_API["Tickets Endpoint"]
        Actions_API["Actions (Notes) Endpoint"]
    end

    subgraph Integration Engine
        DocxParser["Docx XML Text Extractor"]
        EmailMatcher["Email & Domain Matcher"]
        NoteCleaner["HTML Tag & Entity Stripper"]
        NotesFilter["Meeting Summary Filter"]
    end

    subgraph Output
        JSONArchive["Unified Partner JSON Cache"]
        Dashboard["Risk & Sentiment Dashboard"]
    end

    Transcripts --> DocxParser
    CSAT_API --> EmailMatcher
    NPS_API --> EmailMatcher
    Users_API --> EmailMatcher
    Client_API --> JSONArchive
    Tickets_API --> NotesFilter
    Actions_API --> NoteCleaner --> NotesFilter
    
    DocxParser & EmailMatcher & NotesFilter --> JSONArchive
    JSONArchive --> Dashboard
```

---

## 1. Local Meeting Transcripts

Meeting transcripts provide qualitative, raw conversational context. They are stored as Word documents (`.docx`).

### Directory Structure
```
C:/Temp/PartnerPulse/Transcripts/{PartnerName}/
```
*Example*: `C:/Temp/PartnerPulse/Transcripts/Logically/Logically  _ ITBD Service Call (1).docx`

### Extraction & Parsing Logic

There are two recommended approaches to parse the Word transcripts:

#### Option A: Microsoft MarkItDown (Recommended)
Microsoft's [MarkItDown](https://github.com/microsoft/markitdown) is an open-source Python utility designed to convert Word (.docx), PDF, Excel, and other file types directly into formatted Markdown. This is highly useful for feeding clean document structures (including tables and lists) directly to LLMs.

**Installation**:
```bash
pip install markitdown
```

**Usage**:
```python
from markitdown import MarkItDown

def extract_docx_markdown(docx_path):
    md = MarkItDown()
    result = md.convert(docx_path)
    return result.text_content
```

#### Option B: Zero-Dependency Custom Parser (Fallback)
If external packages are restricted or unavailable, `.docx` files can be treated as standard zip archives and parsed using Python's standard library (`zipfile` and `xml.etree.ElementTree`):

```python
import zipfile
import xml.etree.ElementTree as ET

def extract_docx_text(docx_path):
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with zipfile.ZipFile(docx_path) as docx:
        tree = ET.parse(docx.open('word/document.xml'))
        root = tree.getroot()
        
        paragraphs = []
        for p in root.findall('.//w:p', ns):
            p_text = []
            for t in p.findall('.//w:t', ns):
                if t.text:
                    p_text.append(t.text)
            if p_text:
                paragraphs.append("".join(p_text))
        return "\n".join(paragraphs)
```

### Transcript Information Schema
The first 3-5 lines of the parsed text contain metadata that should be extracted:
* **Line 1 (Title)**: `Logically   ITBD Service Call-20260403_145929UTC-Meeting Recording` (regex matches: `{PartnerName} ... Service Call-{Date}_{Time}`)
* **Line 2 (Date)**: `April 3, 2026, 2:59PM`
* **Line 3 (Duration)**: `19m 37s`
* **Dialogue Speakers**: Regex match `^([A-Z][a-zA-Z'\-\s]+)\s+\d+:\d+` (e.g. `Akhilesh Shukla   0:27`) to compile a speaker list and map user utterances.

### Option C: Teams WEBVTT transcripts pulled from call recordings (Graph / M365 connector)

The service-call recordings live in `desmanagement@itbd.net`'s OneDrive `Recordings/` folder as `.mp4` — useless for text. The **transcript** is retrieved from the Teams meeting itself via Microsoft Graph, which the Claude Microsoft 365 connector exposes (verified 2026-06-11). This is an **agent-driven flow** (no Graph credentials exist in `extract/config.py`), so an LLM session with the M365 connector performs it:

1. `outlook_calendar_search` with `calendarOwnerEmail=desmanagement@itbd.net` (delegated access) for the meeting subject + date window.
2. `read_resource` on the event URI → take the `meetingTranscriptUrl` field verbatim.
3. `read_resource` on that URI → `transcripts[].content` is the full **WEBVTT** with `<v Speaker>text</v>` voice tags.
4. Save it verbatim to `Transcripts/{Partner}/<subject>-<YYYYMMDD>.vtt`, inserting `NOTE title:` / `NOTE date:` / `NOTE duration:` metadata lines after the leading `WEBVTT` line.

`extract/transcripts.py: parse_vtt` parses `.vtt` natively (no markitdown): NOTE metadata, cue timestamps → `M:SS`, consecutive same-speaker cues merged into dialogue turns — same schema as the `.docx` path.

> ⚠️ **Access constraint:** Graph returns **403 "User does not have access to lookup meeting"** unless the signed-in connector user was an **invitee/participant** of that meeting. (Verified: Atlantic PC's calls are not retrievable by `Amit.Dubey@itbd.net`, who is not invited; Logically/Milner/ION247/Premier/Netgain/MSP Corp CRDS are.) Delegated calendar access is enough to *find* the events but not to *read transcripts* of meetings you didn't attend. **Option D supersedes this for bulk pulls** — the app identity has no attendee constraint.

### Option D: Bulk app-only Graph pull — `scripts/pull_graph_transcripts.py` (preferred since 2026-06-13)

Uses the `DESManagement@itbd.net` app registration (client-credentials, `GRAPH_*` in `.env`; see `docs/IT-Request-Graph-Transcript-Access.md`) to pull **every partner service call organized under the DES Teams identity — no attendee constraint**, unlike Option C. Dry run first, then `--write`:

```powershell
python scripts/pull_graph_transcripts.py            # plan only
python scripts/pull_graph_transcripts.py --write     # download + save
```

Flow: page DES `/events` (the `onlineMeeting.joinUrl` is reliable there — `/calendarView` intermittently drops it) → keep partner service/review/business calls (`CALL_RE`), drop interviews/onboarding/internal (`EXCLUDE_RE`) → dedupe to unique series by join URL → resolve each by the organizer's **object id** (the `Oid` in the join URL's `context` param; addressing by UPN returns a masking 404) → list transcripts → per occurrence ≥ `--since`, fetch `/content?$format=text/vtt`, keep the longest when a day has split recordings → write `Transcripts/{Partner}/<subject>-<YYYYMMDD>.vtt` with the same NOTE header Option C produces. Partner-folder routing reuses `resolve_partner_dir` (matches existing folders; new partners get their own folder).

Verified limits (2026-06-13 first full pull — 148 written across ~70 folders):
- **Content retention ~90 days.** A series *lists* every occurrence back years, but `/content` 404s ("content expired") for calls older than ~3 months. The first pull recovered Apr–Jun 2026 cleanly; Jan–early-Mar were all expired. **Run monthly** so nothing ages out.
- **QBRs 403.** `ITBD x <Partner> : Quarterly Business Review` and similar are organized under a *different* identity than DES, so the Teams policy doesn't cover them — they fail to resolve. Granting the policy to that organizer would be needed.
- **`.docx` folders deferred by default.** Folders that already hold manual `.docx` exports (MSPCorp, Premier, Stasmayer) are skipped to avoid the double-ingest bug (freeform `.docx` dates can't be matched); pull them with `--include-docx-folders` after checking date overlap.

---

## 2. Customer Satisfaction (CSAT) — TeamGPS

CSAT reviews provide ticket-level feedback from end users on completed service requests.

* **Base URL**: `https://api.team-gps.net/open-api/v1`
* **Endpoint**: `GET /csat/`
* **Headers**: `X-API-KEY: {api_key}`
* **Query Parameters**:
  * `company`: `{exact_match_client_name}` (e.g. `Logically`)
  * `page_size`: `1000`
  * `page`: `1` (increment if paginating)

### Response Schema (CSAT List)
> [!WARNING]
> **Schema Quirk**: The CSAT endpoint wraps its results list in `data.results`.

```json
{
  "message": "CSAT reviews fetched successfully.",
  "data": {
    "current": 1,
    "total": 509,
    "total_pages": 1,
    "results": [
      {
        "id": 877283,
        "rating": "Positive",       // Or "Neutral", "Negative"
        "comment": "He did a great job resolving this issue.",
        "company": "Logically",
        "contact_name": "Tim Ramos",
        "contact_email": "tim.ramos@logically.com",
        "submitted_date": "2026-04-23T20:05:26.752444Z",
        "ticket_id": "720701",
        "ticket_name": "Monthly Feedback for Renz Santos"
      }
    ]
  }
}
```

---

## 3. Net Promoter Score (NPS) — TeamGPS

NPS client surveys capture high-level strategic satisfaction.

* **Base URL**: `https://api.team-gps.net/open-api/v1`
* **Endpoint**: `GET /survey/nps-client/`
* **Headers**: `X-API-KEY: {api_key}`
* **Query Parameters**:
  * `page_size`: `1000`
  * `page`: `1` (NPS endpoint must be fully retrieved and filtered locally, as there is no server-side company/client filter)

### Response Schema (NPS List)
> [!WARNING]
> **Schema Quirk**: Unlike CSAT, the NPS endpoint wraps its results list in `data.data`.

```json
{
  "message": "NPS Client responses fetched successfully.",
  "data": {
    "pagination": {
      "page": 1,
      "page_size": 1000,
      "total_count": 1759,
      "total_pages": 2
    },
    "data": [
      {
        "id": 963345,
        "nps_score": 9,
        "nps_category": "Promoter", // Or "Passive", "Detractor"
        "comment": "ITBD is a great partner.",
        "respondent_email": "jmcguigan@logically.com",
        "submitted_date": "2026-06-03T12:28:55.855280Z"
      }
    ]
  }
}
```

### Locally Filtering NPS by Partner
Since the API returns all client NPS reviews, filter the results in the integration code:
1. Fetch all user records for the client from HaloPSA (see Section 4).
2. Collect the set of exact `emailaddress` values and the set of email domain names (e.g. `{'logically.com', 'obviam.com'}`).
3. Filter NPS records where `respondent_email` matches a client contact email or the domain matches.

---

## 4. Client Metadata & Users — HaloPSA

Client-level fields and contact lists must be pulled from HaloPSA to establish RAG statuses, account managers, and domains.

* **Base URL**: `https://itbd.halopsa.com/api`
* **Headers**: `Authorization: Bearer {token}` (Cached OAuth2 client credentials token)

### A. Client Details
* **Endpoint**: `GET /api/Client/{client_id}?includedetails=true`
* **Key Fields to Extract**:
  * `inactive` (bool): Filter out deactivated accounts.
  * `is_vip` (bool): Alert for VIP accounts.
  * Custom fields in the `customfields[]` array:
    * `CFCancelationRisk`: 1 (High) / 2 (Medium) / 3 (Low)
    * `CFMDERAG`: RAG status (1=Red, 2=Amber, 3=Green)
    * `CFHealthReason`: Explains RAG status downgrades (e.g., "Engineer performance")
    * `CFNextStep`: Explains remediation plans (e.g., "Mazid's SIP - 2 weeks monitoring")
    * `CFSIPTicketMDE`: Ticket ID of the active SIP

### B. Client Users (Contacts)
* **Endpoint**: `GET /api/Users?client_id={client_id}&page_size=1000&pageinate=true&includeinactive=true`
* **Extraction**: Collect all `emailaddress` strings to compile user lists and domain sets for TeamGPS NPS filtering.

---

## 5. Ticket notes & Action Items — HaloPSA

Official review meeting notes, summaries, and action items are captured in the notes section of the bi-weekly review tickets.

* **Base URL**: `https://itbd.halopsa.com/api`
* **Headers**: `Authorization: Bearer {token}`

### A. Step 1: Find Service Review Tickets
* **Endpoint**: `GET /api/Tickets?client_id={client_id}&search=Bi-Weekly Service call&page_size=5&pageinate=true`
* **Usage**: Retrieve the list of recent service call tickets. Halo returns these newest-first, so `page_size=5` still covers the most recent calls.

### B. Step 2: Fetch Actions for Each Ticket
* **Endpoint**: `GET /api/Actions?ticket_id={ticket_id}`
* **Response**: A bare JSON list of actions containing `id`, `who`, `datetime`, and a brief note.

### C. Step 3: Fetch Action Details & Clean Content
Because list summaries are truncated, query the detail endpoint for every action in the ticket:
* **Endpoint**: `GET /api/Actions/{action_id}?ticket_id={ticket_id}`

#### HTML Cleaning Logic
The `note` returned is HTML. Clean it using Python standard regex:
```python
import re

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    cleantext = cleantext.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
    return cleantext.strip()
```

#### Meeting Notes Identifier
Filter the cleaned action notes for key markers: `"meeting summary"`, `"action items"`, `"discussion points"`, or `"join the call"`. This isolates the actual meeting write-up from automated system logs (such as status changes or email auto-responses).

#### Call date = the meeting NOTE's datetime (NOT the ticket's `dateoccurred`)
**Changed 2026-06-13.** Each `historical_calls` entry's `date` is the **latest matching action note's `datetime`**, not the ticket's `dateoccurred`. Recurring/bi-weekly service tickets keep an early `dateoccurred` (set at creation) while the actual call note is appended later — e.g. Logically ticket `0755301`: `dateoccurred` 2026-05-27, note `2026-06-12`. Using `dateoccurred` made "last call" stale for every recurring-ticket partner. See `extract/build_partner.py` / `scripts/build_real_partners.py` and `docs/HaloPSA-API-SOP.md` Addendum (2026-06-13). `build_overview.py` then takes the union of these note dates and transcript dates for the dashboard's "last call".

#### Incremental rebuild (cost/time control)
**Added 2026-06-13.** `extract/ai.py:analyze()` caches the gpt-5.4 result by a hash of its input (`build_context`) — unchanged partners reuse the cached churn analysis (no LLM call, no score drift). Deck markdown is reused by attachment id (no re-`markitdown`). So a re-sync re-fetches Halo/TeamGPS (to detect changes) but only re-runs the LLM / deck conversion for partners whose inputs actually changed. `extract.build_all --force-ai` (or `build_real_partners.py --force-ai`) forces a full re-analysis.

#### Batch resilience (continue-on-failure)
**Added 2026-06-15.** Halo intermittently returns transient **5xx/429** (notably `GET /api/Tickets?client_id=…&search=Service Call`). `extract/halo.get()` now retries those with backoff, and `build_real_partners.py` wraps the per-client service-ticket fetch in continue-on-failure — a client whose ticket list keeps erroring still builds (transcripts + CSAT/NPS + AI), just without Halo call-notes, instead of aborting the whole batch. See `docs/HaloPSA-API-SOP.md` Addendum (2026-06-15).

#### Roster sourcing (who is a DES/MDE partner)
**Added 2026-06-15.** The partner roster in `scripts/build_real_partners.py` NEW is sourced from HaloPSA **report 364 "DES RAG Status"** — filter `Area.CFMDERAG >= 1` (every RAG-managed account). Report *rows* aren't fetchable via the API (only the SQL definition), so reproduce the filter by enumerating clients (`/api/Client` with `pageinate=true`) and reading `CFMDERAG` per client. See `docs/HaloPSA-API-SOP.md` Addendum (2026-06-15).

---

## 5b. SIP Counts — HaloPSA

Each partner's all-time **Service Improvement Plan** counts (open vs. closed) come from Halo ticket type **99**. There is no server-side ticket-type filter, so the engine (`extract/halo.py: count_sips`) searches three free-text terms, filters rows client-side on `tickettype_id == 99`, and runs a second pass over SIPs mis-filed under ITBD's own client record (id 12) whose summary names the partner. Open/closed is a status-name heuristic. Full details and quirks: **HaloPSA-API-SOP.md → "Addendum — SIP / ticket-type filtering findings"**. Output lands as `client.sip_open` / `client.sip_closed` in the partner JSON.

---

## 6. Execution Workflow for a Partner Run

To scan a new partner in the system, the dashboard engine must execute these steps sequentially:

```
[Start]
  │
  ├─► 1. Get HaloPSA token via OAuth client_credentials flow.
  │
  ├─► 2. Query Client details (GET Client/{id}) & verify custom fields (RAG, Risk).
  │
  ├─► 3. Query Client Users list & construct set of emails and domain extensions.
  │
  ├─► 4. Count SIP tickets (type 99) for the client — open vs. closed (see §5b).
  │
  ├─► 5. Fetch all CSAT reviews filtered by company name matching client.
  │
  ├─► 6. Fetch NPS client reviews & filter locally using the user email/domain sets.
  │
  ├─► 7. Search for the 5 most recent 'Bi-Weekly Service call' tickets for the client.
  │
  ├─► 8. For each ticket:
  │      ├─ Fetch actions list.
  │      └─ Fetch action details, clean HTML, and extract meeting summaries & action items.
  │
  ├─► 9. Parse the local directory for transcripts matching the client's name
  │      (.docx Teams exports + .vtt Graph pulls — see §1).
  │
  ├─► 10. Merge and cache all extracted data into a unified Partner JSON payload.
  │
  └─► [End: Render Dashboard UI]
```
