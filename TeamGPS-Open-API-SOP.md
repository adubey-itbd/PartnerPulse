# TeamGPS Open API — Standard Operating Procedure

## Overview

TeamGPS provides a public REST API for programmatic access to your company's data. This document covers authentication, all available endpoints, parameters, and example requests.

**Base URL**: `https://api.team-gps.net/open-api/v1`
**Swagger UI**: https://api.team-gps.net/open-api/v1/swagger/
**Rate Limit**: 60 requests per minute (per API key)
**Format**: All responses are JSON

---

## Authentication

Every request requires the `X-API-KEY` header.

**API Key**:
```
***REMOVED***
```

**Usage in curl**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/csat/?page=1&page_size=10" \
  -H "X-API-KEY: ***REMOVED***" \
  -H "Accept: application/json"
```

**Usage in Python**:
```python
import requests

API_KEY = "***REMOVED***"
headers = {"X-API-KEY": API_KEY, "Accept": "application/json"}

response = requests.get(
    "https://api.team-gps.net/open-api/v1/csat/?page=1&page_size=10",
    headers=headers
)
data = response.json()
```

**Usage in JavaScript**:
```javascript
const API_KEY = '***REMOVED***';

const res = await fetch('https://api.team-gps.net/open-api/v1/csat/?page=1&page_size=10', {
  headers: { 'X-API-KEY': API_KEY, 'Accept': 'application/json' }
});
const data = await res.json();
```

---

## Pagination

Most list endpoints return paginated results. Standard fields:

| Field | Description |
|---|---|
| `page` | Current page number |
| `total` | Total number of records |
| `total_pages` | Total number of pages |
| `results` or `data` | Array of records for the current page |

Use `page` and `page_size` query parameters to navigate. Maximum `page_size` is typically 1000.

**Example**: Get page 2 with 50 results per page:
```
?page=2&page_size=50
```

---

## Data Inventory

| Module | Records | Endpoint |
|---|---|---|
| CSAT Reviews | 17,595 | `/csat/` |
| NPS Client | 1,710 | `/survey/nps-client/` |
| NPS Client Summary | - | `/survey/nps-client/summary/` |
| NPS Employee | 1 | `/survey/nps-employee/` |
| NPS Employee Summary | - | `/survey/nps-employee/summary/` |
| Goals | 927 | `/goals/` |
| 1:1 Meetings | 12,110 | `/meetings/one-o-one-meetings/` |
| Group Meetings | 52 | `/meetings/group-meetings/` |
| Group Meeting Events | 746 | `/meetings/group-meetings/events/` |
| Tasks | 4,201 | `/tasks/` |
| Employees | 1,736 | `/organisation/employees/` |
| Strategy | 4 | `/strategy/` |
| Performance Review Cycles | 53 | `/performance-management/review-cycles/` |
| Performance Reviews | per cycle | `/performance-management/reviews/` |
| Social Feeds | requires dates | `/social-feeds/` |
| Manual Points | 1,546 | `/social-feeds/manual-points/` |
| Redemption Transactions | 26,736 | `/social-feeds/redemption-transactions/` |
| Custom Rewards Redemptions | 0 | `/rewards/custom-rewards/redemptions/` |
| Custom Survey (Client) | 35 | `/survey/custom-survey-client/` |
| Custom Survey (Employee) | 55 | `/survey/custom-survey-employee/` |
| Trend Scorecard | POST | `/trend-scorecard/` |

---

## Endpoints

### 1. CSAT Reviews

List customer satisfaction survey reviews from PSA integrations.

**Endpoint**: `GET /open-api/v1/csat/`

**Parameters**:

| Parameter | Required | Type | Description |
|---|---|---|---|
| `page` | Yes | int | Page number (default: 1) |
| `page_size` | No | int | Results per page (default: 10, max: 1000) |
| `from_created_at` | No | date | Records created from this date (YYYY-MM-DD) |
| `to_created_at` | No | date | Records created until this date |
| `from_submitted_date` | No | date | Responses submitted from (only responded records) |
| `to_submitted_date` | No | date | Responses submitted until |
| `from_last_updated_at` | No | date | Last updated from |
| `to_last_updated_at` | No | date | Last updated until |
| `from_reviewed_at` | No | date | Reviewed from |
| `to_reviewed_at` | No | date | Reviewed until |
| `reviewed_by_email` | No | string | Filter by reviewer email |
| `is_reviewed` | No | bool | true/false for reviewed status |
| `company` | No | string | Filter by company name (exact match) |
| `ticket_queue` | No | string | Filter by ticket queue (exact match) |
| `ticket_type` | No | string | Filter by ticket type (exact match) |
| `is_responded` | No | bool | true=submitted only, false=pending only |

**Example — Get responded CSAT reviews from last 30 days**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/csat/?page=1&page_size=10&from_submitted_date=2026-03-25&to_submitted_date=2026-04-24&is_responded=true" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "message": "CSAT reviews fetched successfully.",
  "data": {
    "current": 1,
    "total": 244,
    "total_pages": 25,
    "results": [
      {
        "id": 877283,
        "rating": "Positive",
        "comment": "",
        "company": "IT by Design",
        "contact_name": "Manas Pathak",
        "contact_email": "manas.pathak@itbd.net",
        "submitted_date": "2026-04-23T20:05:26.752444Z",
        "team_members": [
          { "is_internal_user": false, "identifier": "ujwal sharma" }
        ],
        "ticket_id": "720701",
        "ticket_type": "Incident - Internal IT",
        "ticket_name": "LAN Cable Request",
        "tags": [],
        "ticket_queue": "Internal HelpDesk",
        "site": "Main",
        "source": "Ticket",
        "psa_tool": "HaloPSA",
        "departments": [],
        "managers": [],
        "created_at": "2026-04-23T19:42:21.117296Z",
        "last_updated_at": "2026-04-23T20:05:27.730889Z",
        "notes": null
      }
    ]
  }
}
```

---

### 2. NPS Client

List Net Promoter Score survey responses from clients.

**Endpoint**: `GET /open-api/v1/survey/nps-client/`

**Parameters**:

| Parameter | Required | Type | Description |
|---|---|---|---|
| `page` | No | int | Page number (default: 1) |
| `page_size` | No | int | Results per page (default: 10, max: 1000) |
| `from_created_at` / `to_created_at` | No | date | Filter by creation date |
| `from_submitted_date` / `to_submitted_date` | No | date | Filter by submission date (responded only) |
| `from_reviewed_at` / `to_reviewed_at` | No | date | Filter by review date |
| `reviewed_by_email` | No | string | Filter by reviewer email |
| `is_reviewed` | No | bool | Reviewed status |
| `nps_category` | No | string | `Promoter`, `Passive`, or `Detractor` |
| `nps_rating` | No | string | Comma-separated scores 0-10 (e.g., `9,10`) |
| `submitted_by` | No | string | Respondent email (partial match) |
| `campaign_name` | No | string | Campaign name (partial match) |
| `campaign_status` | No | string | `Draft`, `Active`, `Inactive`, or `Scheduled` |
| `campaign_end_date` | No | date | Filter by campaign end date (YYYY-MM-DD) |
| `is_anonymous` | No | bool | Anonymous responses |
| `is_responded` | No | bool | Submitted vs pending |

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/survey/nps-client/?page=1&page_size=5&nps_category=Promoter" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "message": "NPS Client surveys fetched successfully.",
  "data": {
    "current": 1,
    "total": 1710,
    "results": [
      {
        "id": 800377,
        "nps_score": 10,
        "nps_category": "Promoter",
        "comment": "Communication has been really good...",
        "respondent_email": "shaine@vcs.tech",
        "respondent_name": null,
        "is_anonymous": false,
        "is_responded": true,
        "campaign_name": "Q4 2025 NPS IMS",
        "campaign_status": "Inactive",
        "campaign_start_date": "2026-01-12",
        "campaign_end_date": "2026-03-31",
        "submitted_date": "2026-03-10T15:46:58.629666Z"
      }
    ]
  }
}
```

---

### 3. NPS Client Summary

Get aggregated NPS score and breakdown.

**Endpoint**: `GET /open-api/v1/survey/nps-client/summary/`

**Parameters**: Same filters as NPS Client list (except pagination), including `campaign_end_date` and `campaign_status` (`Draft`, `Active`, `Inactive`, `Scheduled`).

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/survey/nps-client/summary/" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "data": {
    "nps_score": 78.39,
    "total_responses": 1694,
    "total_surveys_sent": 1710,
    "response_rate": 99.06,
    "promoters": { "count": 1381, "percentage": 81.52 },
    "passives": { "count": 260, "percentage": 15.35 },
    "detractors": { "count": 53, "percentage": 3.13 }
  }
}
```

---

### 4. NPS Employee

**Endpoint**: `GET /open-api/v1/survey/nps-employee/`
**Summary**: `GET /open-api/v1/survey/nps-employee/summary/`

Same parameters as NPS Client (including `campaign_end_date` and `campaign_status`: `Draft`, `Active`, `Inactive`, `Scheduled`). Returns internal employee NPS with department, designation, and manager info.

---

### 5. Goals

List organizational, department, individual, and Life By Design goals.

**Endpoint**: `GET /open-api/v1/goals/`
**Detail**: `GET /open-api/v1/goals/{id}/` (supports `include_comments=true|false`, default: `true`)

**Parameters**:

| Parameter | Required | Type | Description |
|---|---|---|---|
| `page` / `page_size` | No | int | Pagination |
| `goal_type` | No | string | `company`, `department`, `individual`, `life_by_design` |
| `status` | No | string | `open`, `on_track`, `completed`, `off_track` |
| `strategic_focus` | No | string | `Growth and Scale`, `Customer Excellence`, `Operational Efficiency`, `People`, `Other` |
| `lbd_focus_area` | No | string | `Health`, `Family`, `Career`, `Legacy` (Life By Design goals only) |
| `owner_email` | No | string | Goal owner email |
| `department` | No | string | Department name |
| `is_archived` | No | string | `true` or `false` (default: false) |
| `start_date_from` / `start_date_to` | No | date | Start date range |
| `due_date_from` / `due_date_to` | No | date | Due date range |
| `source` | No | string | `personal` or `group_meeting` |
| `goal_objective` | No | string | Partial match on title |
| `ordering` | No | string | `created_at`, `-created_at`, `due_date`, `-due_date` (default: `-created_at`) |

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/goals/?page=1&page_size=5&status=Open&goal_type=Individual" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "data": {
    "total": 927,
    "results": [
      {
        "id": 5723,
        "goal_type": "Individual",
        "goal_objective": "Increase Participation in Employee Engagement Activities.",
        "status": "Open",
        "completion_percentage": "0",
        "strategic_focus": "People",
        "start_date": "2026-04-24",
        "end_date": "2026-06-30",
        "goal_owner": {
          "full_name": "Subhranshu Chopra",
          "email": "subhranshu.chopra@itbd.net",
          "designation": "Senior Manager HRBP"
        },
        "milestones": { "total": 0, "completed": 0 }
      }
    ]
  }
}
```

---

### 6. 1:1 Meetings

List one-on-one meetings between managers and employees.

**Endpoint**: `GET /open-api/v1/meetings/one-o-one-meetings/`
**Detail**: `GET /open-api/v1/meetings/one-o-one-meetings/{id}/`

**Parameters**:

| Parameter | Required | Type | Description |
|---|---|---|---|
| `page` / `page_size` | No | int | Pagination |
| `status` | No | string | `Upcoming`, `Completed`, `Overdue` (default: Completed) |
| `frequency` | No | string | `Never`, `Daily`, `Weekly`, `Monthly` |
| `from_date` / `to_date` | No | date | Meeting start_time range |
| `creator_email` | No | string | Organizer email |
| `recipient_email` | No | string | Participant email |
| `meeting_title` | No | string | Title (partial match) |
| `department` | No | string | Pool filter: creator OR recipient in this dept |
| `designation` | No | string | Pool filter: by job title |
| `manager_email` | No | string | Pool filter: direct reports of this manager |
| `secondary_manager_email` | No | string | Pool filter: secondary manager's reports |
| `hierarchical_manager_email` | No | string | Pool filter: full reporting chain |
| `series_group_id` | No | string | UUID for recurring series |

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/meetings/one-o-one-meetings/?page=1&page_size=5&status=Completed&from_date=2026-04-01" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "data": {
    "total": 12110,
    "results": [
      {
        "id": "e6745557-80ad-4bf8-b936-240dd193c7ec",
        "meeting_title": "Monthly 1:1 Connect",
        "status": "Upcoming",
        "start_time": "2026-06-17T18:00:00+00:00",
        "end_time": "2026-06-17T18:30:00+00:00",
        "duration_minutes": 30,
        "frequency": "Monthly",
        "creator": { "full_name": "Ayra Mariel Macatol", "email": "ayra.macatol@itbd.net" },
        "recipient": { "full_name": "Edrian Alexis Santos", "email": "edrian.santos@itbd.net" },
        "agenda": { "total": 8, "completed": 0 },
        "task": { "total": 0, "completed": 0 }
      }
    ]
  }
}
```

---

### 7. Group Meetings

**List**: `GET /open-api/v1/meetings/group-meetings/`
**Events**: `GET /open-api/v1/meetings/group-meetings/events/`
**Event Detail**: `GET /open-api/v1/meetings/group-meetings/events/{event_id}/`

**List Parameters**: `page`, `page_size`, `title`, `created_by_email`, `attendee_email`, `from_date`, `to_date`, `ordering`

**Events Parameters**: `page`, `page_size`, `group_meeting_id`, `status` (`completed`, `ongoing`), `attendee_email`, `from_date`, `to_date`, `ordering`

**Event Detail Parameters**: `trend_type` (`WEEKLY`, `MONTHLY`, `QUARTERLY`), `date_from`, `date_to`

**Example — Get completed events for a specific group meeting**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/meetings/group-meetings/events/?group_meeting_id=168&status=Completed&page_size=5" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "data": {
    "total": 746,
    "results": [
      {
        "id": 2458,
        "title": "Internal IT L10",
        "status": "Completed",
        "event_start_time": "2026-04-23T16:33:10.933925+00:00",
        "duration_minutes": 89.7,
        "leader": { "full_name": "Ramesh Kumar", "email": "ramesh.kumar@itbd.net" },
        "participant_count": 13,
        "present_count": 11,
        "attendance_rate": 0.85,
        "avg_rating": 8.85,
        "tasks_completed_count": 0,
        "issues_solved_count": 1
      }
    ]
  }
}
```

---

### 8. Tasks

List tasks created from meetings, goals, or manually.

**Endpoint**: `GET /open-api/v1/tasks/`
**Detail**: `GET /open-api/v1/tasks/{id}/`

**Parameters**:

| Parameter | Required | Type | Description |
|---|---|---|---|
| `page` / `page_size` | No | int | Pagination |
| `status` | No | string | `Open`, `Completed` |
| `task_type` | No | string | `Personal`, `1:1 Meeting`, `Group Meeting` |
| `from_due_date` / `to_due_date` | No | date | Due date range |
| `assignee_email` | No | string | Assignee email |
| `creator_email` | No | string | Creator email |
| `ordering` | No | string | Sort (default: `-created_at`) |
| `include_description` | No | string | `true`/`false` (default: true) |

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/tasks/?page=1&page_size=5&status=Open&assignee_email=abhishek.thakur@itbd.net" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "data": {
    "total": 4201,
    "results": [
      {
        "id": 8888,
        "name": "Need to work with Team GPS for CSAT Data",
        "status": "Open",
        "task_type": "Group Meeting",
        "due_date": "2026-04-30",
        "created_by": { "full_name": "Ramesh Kumar", "email": "ramesh.kumar@itbd.net" },
        "assignee": { "full_name": "Abhishek Thakur", "email": "abhishek.thakur@itbd.net" },
        "source": { "type": "Group Meeting", "meeting_id": 168, "meeting_title": "Internal IT L10" }
      }
    ]
  }
}
```

---

### 9. Employees

List all employees in the organization.

**Endpoint**: `GET /open-api/v1/organisation/employees/`

**Parameters**:

| Parameter | Required | Type | Description |
|---|---|---|---|
| `page` / `page_size` | No | int | Pagination (default page_size: 100) |
| `name` | No | string | Full name (partial match) |
| `email` | No | string | Email (exact match) |
| `is_active` | No | string | `true` or `false` |
| `department` | No | string | Department name (exact) |
| `designation` | No | string | Job title (exact) |
| `psa_member_identifier` | No | string | PSA identifier (exact) |
| `manager_name` | No | string | Manager name (partial) |
| `manager_email` | No | string | Manager email (exact) |
| `timezone` | No | string | e.g., `EST`, `IST` |
| `country` | No | string | Country name |
| `office_location` | No | string | Office/site name |
| `date_of_joining_from` / `date_of_joining_to` | No | date | Join date range |
| `date_of_birth_from` / `date_of_birth_to` | No | date | Date of birth range |
| `role` | No | string | `Admin`, `Manager`, `Employee` |

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/organisation/employees/?page=1&page_size=5&department=HR%20Ops" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

**Sample Response**:
```json
{
  "data": {
    "pagination": { "page": 1, "page_size": 5, "total_count": 1736, "total_pages": 348 },
    "data": [
      {
        "id": 287,
        "full_name": "Aadika Sharma",
        "email": "aadika.sharma@itbd.net",
        "role": "Admin, Employee",
        "is_active": true,
        "departments": ["HR Ops"],
        "designation": "Manager-HR Operations",
        "country": "India",
        "timezone": "EST",
        "manager": { "full_name": "Suhrid Rana", "email": "suhrid.rana@itbd.net" },
        "psa_member_identifier": null,
        "date_of_joining": "2016-12-12"
      }
    ]
  }
}
```

---

### 10. Strategy

List and view strategic plans.

**List**: `GET /open-api/v1/strategy/`
**Detail**: `GET /open-api/v1/strategy/{id}/`

**Parameters**: `page`, `page_size`, `name` (partial match), `from_date`, `to_date`, `ordering`

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/strategy/?page=1&page_size=10" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

---

### 11. Performance Management

**Review Cycles**: `GET /open-api/v1/performance-management/review-cycles/`
**Reviews**: `GET /open-api/v1/performance-management/reviews/?review_cycle_id={id}`
**Review Detail**: `GET /open-api/v1/performance-management/reviews/{self_review_id}/`

**Review Cycles Parameters**: `page`, `page_size`, `review_type` (`on_fixed_date`, `by_joining_date`), `frequency` (`quarterly`, `semi_annual`, `annual`, `custom`), `created_by_email`, `master_review_cycle_name`, `start_date_from`, `start_date_to`, `ordering`

**Reviews Parameters**: `review_cycle_id` (REQUIRED), `page`, `page_size`, `self_review_status` (`open`, `in_progress`, `completed`, `past_due`), `manager_review_status` (`open`, `in_progress`, `completed`, `past_due`), `employee_email`, `manager_email`, `employee_name`, `employee_designation`, `employee_department`, `ordering`

**Review Detail Parameters**: `include_manager_review` (`true`/`false`, default: `true`)

**Example — List review cycles then get reviews**:
```bash
# Step 1: Get review cycles
curl -s "https://api.team-gps.net/open-api/v1/performance-management/review-cycles/?page=1&page_size=5" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"

# Step 2: Get reviews for a specific cycle (use id from step 1)
curl -s "https://api.team-gps.net/open-api/v1/performance-management/reviews/?review_cycle_id=888&page=1&page_size=5" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

---

### 12. Social Feeds (Recognition)

List shoutouts, awards, and recognition events.

**List**: `GET /open-api/v1/social-feeds/` (requires `from_date` and `to_date`, max 366 days)
**Detail**: `GET /open-api/v1/social-feeds/{feed_id}/`

**Parameters**: `page`, `page_size`, `from_date` (REQUIRED), `to_date` (REQUIRED), `feed_type` (`shoutout`, `award`, `manual_point`), `award_sub_type` (`birthday`, `work_anniversary`, `joining_date`, `csat_review_award`, `ces_review_award`)

**Example**:
```bash
curl -s "https://api.team-gps.net/open-api/v1/social-feeds/?from_date=2026-04-01&to_date=2026-04-24&page=1&page_size=10" \
  -H "X-API-KEY: $API_KEY" -H "Accept: application/json"
```

---

### 13. Manual Points

List admin-granted point additions and deductions.

**Endpoint**: `GET /open-api/v1/social-feeds/manual-points/`

**Parameters**: `page`, `page_size`, `from_date`, `to_date`, `transaction_type` (`addition`, `deduction`), `category`, `employee_email`

---

### 14. Redemption Transactions

List gift card and reward redemptions.

**Endpoint**: `GET /open-api/v1/social-feeds/redemption-transactions/`

**Parameters**: `page`, `page_size`, `from_date`, `to_date`, `source` (`gift_card`, `manual_deduction`, `custom_reward`), `employee_email`

---

### 15. Custom Rewards Redemptions

List custom reward redemption requests.

**Endpoint**: `GET /open-api/v1/rewards/custom-rewards/redemptions/`

**Parameters**: `page`, `page_size`, `status` (`Pending`, `Fulfilled`, `Declined`), `reward_name`, `requester_email`, `from_date`, `to_date`, `ordering`

---

### 16. Custom Surveys (Client)

**List campaigns**: `GET /open-api/v1/survey/custom-survey-client/`
**Responses**: `GET /open-api/v1/survey/custom-survey-client/{id}/responses/`
**Statistics**: `GET /open-api/v1/survey/custom-survey-client/{id}/statistics/`

**List Parameters**: `page`, `page_size`, `campaign_name`, `campaign_status` (`Active`, `Inactive`, `Scheduled`), date range filters, `is_anonymous`

**Responses Parameters**: `page`, `page_size`, `is_responded`, `from_submitted_date`, `to_submitted_date`, `from_created_at`, `to_created_at`, `submitted_by`

---

### 17. Custom Surveys (Employee)

**List campaigns**: `GET /open-api/v1/survey/custom-survey-employee/`
**Responses**: `GET /open-api/v1/survey/custom-survey-employee/{id}/responses/`
**Statistics**: `GET /open-api/v1/survey/custom-survey-employee/{id}/statistics/`

**List Parameters**: Same as Custom Survey Client, plus `campaign_status` (`Active`, `Inactive`, `Scheduled`)

**Responses Parameters**: `page`, `page_size`, `is_responded`, `from_submitted_date`, `to_submitted_date`, `from_created_at`, `to_created_at`, `submitted_by`

**Additional Parameters**: `include_meeting_surveys` (bool), `is_meeting_survey` (bool)

---

### 18. Trend Scorecard (POST)

Fetch KPI trend data for specific employees.

**Endpoint**: `POST /open-api/v1/trend-scorecard/`

**Request Body**:
```json
{
  "member_identifiers": ["john.doe"],
  "emails": ["john.doe@itbd.net"],
  "trend_type": "WEEKLY",
  "date_from": "2026-01-01",
  "date_to": "2026-04-24"
}
```

**Example**:
```bash
curl -s -X POST "https://api.team-gps.net/open-api/v1/trend-scorecard/" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"emails": ["aadika.sharma@itbd.net"], "trend_type": "MONTHLY"}'
```

---

## Common Date Formats

All date parameters use `YYYY-MM-DD` format (e.g., `2026-04-24`).

## Error Responses

| Status | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad request (invalid parameters) |
| 401 | Unauthorized (missing or invalid API key) |
| 404 | Endpoint not found |
| 429 | Rate limit exceeded (60 requests/minute) |
| 500 | Server error |

## Tips

- Use `page_size=1` to quickly check total record counts without downloading data
- The `ordering` parameter accepts `-field_name` for descending (e.g., `-created_at`)
- Date range filters are inclusive on both ends
- `submitted_date` filters only return responded records (non-responded have no submission date)
- For large exports, loop through pages: page 1, 2, 3... until `page > total_pages`
