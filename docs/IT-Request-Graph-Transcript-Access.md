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
