# IT Request — Graph API Access to Teams Meeting Transcripts (PartnerPulse)

**Requested by:** Amit Dubey (Amit.Dubey@itbd.net)
**Date:** 2026-06-11
**For:** PartnerPulse — partner-health & churn-risk dashboard (internal)
**Tenant:** itbd.net (`d3ce7374-043d-42ad-9d54-b68633f244c9`)

---

## What we're asking for

An Entra ID (Azure AD) **app registration** with application-level Microsoft Graph
permissions to read **Teams meeting transcripts** of partner service calls, scoped to
the three shared accounts that organize those calls.

PartnerPulse analyzes partner service-call transcripts (alongside HaloPSA and TeamGPS
data) to produce churn-risk scores. Today transcripts are exported by hand from Teams
into SharePoint; we want the pipeline to pull them automatically.

## Why delegated access isn't enough (context)

Graph's transcript API authorizes against the **meeting participant roster**, not
calendar permissions. Amit has delegate access to the organizer calendars and can
enumerate every service-call event, but transcript reads return
`403 — "User does not have access to lookup meeting"` for any call he wasn't
personally invited to (verified 2026-06-11: works for Logically/Milner/ION247/
Premier/Netgain/MSP Corp; fails for Granite/Proda/Amoskeag/Atlantic PC/F12 team
calls). An application identity with an access policy is Microsoft's supported
pattern for this.

## Requested configuration

1. **App registration** (single tenant): suggested name `PartnerPulse-Transcripts`.

2. **Microsoft Graph — Application permissions** (admin consent required):
   | Permission | Purpose |
   |---|---|
   | `OnlineMeetingTranscript.Read.All` | read meeting transcripts |
   | `OnlineMeetings.Read.All` | resolve a meeting from its join URL |
   | `Calendars.Read` | enumerate service-call events on the organizer calendars |

3. **Teams application access policy** restricting the online-meeting permissions to
   the three organizer accounts only (least privilege):
   ```powershell
   New-CsApplicationAccessPolicy -Identity "PartnerPulse-Transcripts-Policy" `
       -AppIds "<app-client-id>" -Description "PartnerPulse transcript ingestion"
   Grant-CsApplicationAccessPolicy -PolicyName "PartnerPulse-Transcripts-Policy" -Identity "MDEManagement@itbd.net"
   Grant-CsApplicationAccessPolicy -PolicyName "PartnerPulse-Transcripts-Policy" -Identity "DESManagement@itbd.net"
   Grant-CsApplicationAccessPolicy -PolicyName "PartnerPulse-Transcripts-Policy" -Identity "SBDManagement@itbd.net"
   ```

4. **Exchange application access policy** similarly scoping `Calendars.Read` to the
   same three mailboxes:
   ```powershell
   New-ApplicationAccessPolicy -AppId "<app-client-id>" -PolicyScopeGroupId <mail-enabled-security-group containing the 3 accounts> `
       -AccessRight RestrictAccess -Description "PartnerPulse calendar reads"
   ```

5. **Credential:** client secret (12-month expiry is fine) or certificate — whichever
   matches org policy. It will be stored in the project's `.env` (never committed) and
   moves to a secret manager with the planned Firebase deployment.

## What the app will do (and not do)

- Read calendar events titled like partner service calls from the three accounts.
- Read the transcripts of those meetings and store them in the PartnerPulse data
  cache (same content the team already exports to SharePoint by hand today).
- **Read-only throughout. No mail access, no write access, no access to any other
  mailbox or meeting** (enforced by the two access policies above, not just by
  promise).

## Acceptance test

Once provisioned, we will validate with a single call — fetching the transcript of
"Granite Networks Inc | Monthly Service Call" (2026-06-09, organized by
MDEManagement@itbd.net), which currently 403s — and confirm the policies block any
mailbox outside the three listed accounts.

## Contact

Amit Dubey — Amit.Dubey@itbd.net. Happy to demo the dashboard or walk through the
data flow (`docs/architecture.md` in the PartnerPulse repo documents sources,
storage, and the security posture).

---

## Outcome — partially provisioned (2026-06-12)

IT created the app registration and sent credentials (stored in the repo's
gitignored `.env` as `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET`):

- **Application (client) ID:** `c7bc5538-590e-41b4-ad4f-cf0099572983`
- **App display name:** `DESManagement@itbd.net` (not the suggested
  `PartnerPulse-Transcripts`)
- **Granted application permissions:** `Calendars.Read`,
  `OnlineMeetingTranscript.Read.All`, plus `OnlineMeetingArtifact.Read.All`
  (not requested; also covers meeting recordings)

Connection test results (2026-06-12):

| Check | Result |
|---|---|
| Token (client credentials) | ✅ works |
| Calendar read, DESManagement | ✅ works |
| Resolve meeting from join URL | ❌ 404 — `OnlineMeetings.Read.All` **not granted** (item 2 of the request) |
| Transcript read | ❌ 403 "Application is not allowed to perform operations on the user" — **Teams application access policy not created** (item 3) |
| Least-privilege scoping | ❌ app can read **any** mailbox's calendar tenant-wide — **Exchange-side scoping not configured** (item 4); verified by reading an out-of-scope mailbox |

**Remediation:** `scripts/setup_graph_transcript_access.ps1` — a commented,
idempotent script for IT that completes all three missing items in one run and
verifies the Exchange scoping. After running it (allow ~30 min Teams policy
propagation), re-run the acceptance test above —
`python scripts/probe_graph_transcripts.py` automates it (token → meeting
resolution → transcript fetch; reads the `GRAPH_*` vars from `.env`).
Recommended afterwards: rotate
the client secret (it was shared over email) and hand the new value over via a
password manager.

**Update to item 4 of the original request (2026-06-12):** Microsoft now says
*"Don't create new App Access Policies"* — `New-ApplicationAccessPolicy` is
superseded by [RBAC for Applications](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac)
(cmdlet syntax verified against Microsoft Learn 2026-06-12; the Teams policy in
item 3 is unaffected and still current). The script therefore scopes calendar
access the supported way: mail-enabled security group of the 3 accounts →
`New-ManagementScope` (`MemberOfGroup` filter, direct members only) →
`New-ManagementRoleAssignment -App … -Role "Application Calendars.Read"` →
**removal of the tenant-wide `Calendars.Read` consent in Entra** (Entra +
Exchange RBAC grants are additive, so the tenant-wide consent must go for the
scope to bind; calendar reads then authorize via the Exchange role and the
token no longer carries a `Calendars.Read` claim). Verification:
`Test-ServicePrincipalAuthorization` (replaces `Test-ApplicationAccessPolicy`).
