<#
.SYNOPSIS
    One-shot setup for the PartnerPulse Graph transcript-ingestion app registration.

.DESCRIPTION
    Finishes provisioning the existing Entra app registration (client id below) so
    PartnerPulse can read Teams meeting transcripts of partner service calls,
    scoped to the shared organizer account ONLY.

    REVISION 2026-06-12 (after Neeraj's first run): the organizer list is now the
    single account DESManagement@itbd.net. MDEManagement@itbd.net and
    SBDManagement@itbd.net - listed as separate accounts in the original request -
    are SMTP ALIASES of the same DESManagement mailbox, not real users, which is
    why the first run failed on "Grant-CsApplicationAccessPolicy ...
    MDEManagement" with "User does not exist" (Teams policies bind to real user
    identities; aliases have none). Confirmed in the calendar data: every service
    call's join URL carries DESManagement's object id even when the event's
    organizer email shows an alias. The first run already completed Steps 1-2
    (the DESManagement grant succeeded and transcript reads are verified working);
    re-running this script skips those and completes Step 3 + verification.

    What this script does, in order:
      Step 1 - Adds the missing "OnlineMeetings.Read.All" Microsoft Graph
               application permission to the app registration and grants
               tenant-wide admin consent for it.
      Step 2 - Creates a Teams *application access policy* and grants it to the
               organizer account. Without this, every transcript read
               fails 403 ("Application is not allowed to perform operations on
               the user") even though the permission is consented.
      Step 3 - Scopes the app's calendar access to the organizer account using
               Exchange Online "RBAC for Applications" (management scope over a
               mail-enabled security group + "Application Calendars.Read" role
               assignment), then REMOVES the tenant-wide Calendars.Read consent
               in Entra. Today the app can read EVERY mailbox's calendar in the
               tenant; after this step it can read only the organizer's.
               NOTE: this deliberately does NOT use New-ApplicationAccessPolicy —
               Microsoft's docs now say "Don't create new App Access Policies";
               RBAC for Applications is the replacement.
               https://learn.microsoft.com/exchange/permissions-exo/application-rbac
      Step 4 - Verifies: prints the consented Graph roles and runs
               Test-ServicePrincipalAuthorization to prove the Exchange scoping
               (the organizer account => InScope True, any other mailbox => False).

    Background / original request: docs/IT-Request-Graph-Transcript-Access.md
    in the PartnerPulse repo.

    Command syntax verified against Microsoft Learn on 2026-06-12:
      - New-CsApplicationAccessPolicy / Grant-CsApplicationAccessPolicy: current,
        supported (MicrosoftTeams module).
      - New-MgServicePrincipalAppRoleAssignment: current documented way to grant
        application-permission admin consent programmatically.
      - New-ApplicationAccessPolicy (Exchange): now flagged "don't create new" —
        replaced here by RBAC for Applications per the migration guidance.

.NOTES
    Run as a single admin holding these roles (or split the steps among the
    right people):
      * Step 1: Global Administrator or Privileged Role Admin + Cloud
                Application Administrator (must be able to grant admin consent)
      * Step 2: Teams Administrator
      * Step 3: Exchange Administrator + member of the "Organization Management"
                role group (required to assign Application RBAC roles), plus the
                Entra consent removal at the end needs the Step 1 role again
      * Step 4: same connections as Steps 1 & 3 (reuses them when run in one go)

    Required PowerShell modules (the script offers to install missing ones,
    CurrentUser scope): Microsoft.Graph.Applications, MicrosoftTeams,
    ExchangeOnlineManagement.

    The script is idempotent - safe to re-run; existing permissions, policies,
    scopes, role assignments and group members are detected and skipped.

    Propagation: Teams application access policies can take up to ~30 minutes
    to take effect; Exchange app-permission changes are cached for 30 minutes
    to 2 hours (Test-ServicePrincipalAuthorization bypasses that cache, so
    Step 4's result is immediate and reliable).
#>

#Requires -Version 5.1

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Configuration - all values for this specific request. Adjust only if the
# app registration or the organizer accounts change.
# ---------------------------------------------------------------------------
$TenantId        = 'd3ce7374-043d-42ad-9d54-b68633f244c9'   # itbd.net
$AppClientId     = 'c7bc5538-590e-41b4-ad4f-cf0099572983'   # app: "DESManagement@itbd.net" (PartnerPulse transcripts)

# The shared account that organizes partner service calls. The app may touch
# ONLY this mailbox/its meetings once Steps 2 and 3 are in place.
# Do NOT add MDEManagement@itbd.net / SBDManagement@itbd.net here - they are
# SMTP aliases of this same mailbox, not users; Teams policy grants and
# group-membership adds fail on them ("User does not exist").
$OrganizerAccounts = @(
    'DESManagement@itbd.net'
)

$TeamsPolicyName = 'PartnerPulse-Transcripts-Policy'
$ExoGroupName    = 'PartnerPulse-Transcript-Organizers'   # mail-enabled security group = the calendar scope
$ExoGroupAlias   = 'PartnerPulseTranscriptOrganizers'
$ExoScopeName    = 'PartnerPulse-Transcript-Organizers-Scope'
$ExoCalendarRole = 'Application Calendars.Read'           # Exchange RBAC-for-Applications role (scoped Calendars.Read)

# Graph application permission still missing from the registration (needed to
# resolve an online meeting from its join URL before fetching its transcript).
$MissingGraphRole = 'OnlineMeetings.Read.All'

# Tenant-wide Entra permission to REMOVE in Step 3 once the scoped Exchange
# role replaces it (Entra + Exchange RBAC permissions are a UNION - leaving
# the tenant-wide consent in place would defeat the scoping).
$UnscopedRoleToRemove = 'Calendars.Read'

$GraphResourceAppId = '00000003-0000-0000-c000-000000000000'  # Microsoft Graph (well-known id, same in every tenant)

# ---------------------------------------------------------------------------
# Step 0 - make sure the required modules are present
# ---------------------------------------------------------------------------
Write-Host "`n=== Step 0: checking required PowerShell modules ===" -ForegroundColor Cyan
foreach ($module in 'Microsoft.Graph.Applications', 'MicrosoftTeams', 'ExchangeOnlineManagement') {
    if (-not (Get-Module -ListAvailable -Name $module)) {
        Write-Host "Module '$module' not found - installing (CurrentUser scope)..." -ForegroundColor Yellow
        Install-Module $module -Scope CurrentUser -Force -AllowClobber
    } else {
        Write-Host "Module '$module' present." -ForegroundColor Green
    }
}

# ---------------------------------------------------------------------------
# Step 1 - add OnlineMeetings.Read.All to the app registration + admin consent
# ---------------------------------------------------------------------------
# Two distinct halves, both required:
#   (a) the app registration's manifest lists the permission (what the portal
#       "API permissions" blade shows),
#   (b) an app-role ASSIGNMENT on the service principal = the actual admin
#       consent that makes tokens carry the role.
# ---------------------------------------------------------------------------
Write-Host "`n=== Step 1: Graph permission '$MissingGraphRole' + admin consent ===" -ForegroundColor Cyan
Write-Host "Sign in as an admin who can grant tenant-wide admin consent."
Connect-MgGraph -TenantId $TenantId -Scopes 'Application.ReadWrite.All', 'AppRoleAssignment.ReadWrite.All' -NoWelcome

$graphSp = Get-MgServicePrincipal -Filter "appId eq '$GraphResourceAppId'"
$appSp   = Get-MgServicePrincipal -Filter "appId eq '$AppClientId'"
$appReg  = Get-MgApplication      -Filter "appId eq '$AppClientId'"
if (-not $appSp -or -not $appReg) { throw "App registration / service principal for $AppClientId not found in tenant $TenantId." }

# Resolve the role id dynamically from Graph's own role catalogue - never
# hardcode permission GUIDs.
$role = $graphSp.AppRoles | Where-Object { $_.Value -eq $MissingGraphRole -and $_.AllowedMemberTypes -contains 'Application' }
if (-not $role) { throw "Could not resolve application role '$MissingGraphRole' on the Microsoft Graph service principal." }

# (a) Manifest: append the permission to requiredResourceAccess if absent.
$graphResource = $appReg.RequiredResourceAccess | Where-Object { $_.ResourceAppId -eq $GraphResourceAppId }
if ($graphResource -and ($graphResource.ResourceAccess | Where-Object { $_.Id -eq $role.Id })) {
    Write-Host "Manifest already lists $MissingGraphRole - skipping." -ForegroundColor Green
} else {
    $existing = @()
    if ($graphResource) { $existing = @($graphResource.ResourceAccess) }
    $updatedAccess = $existing + @(@{ Id = $role.Id; Type = 'Role' })   # Type 'Role' = application permission
    $otherResources = @($appReg.RequiredResourceAccess | Where-Object { $_.ResourceAppId -ne $GraphResourceAppId })
    $newRra = $otherResources + @(@{ ResourceAppId = $GraphResourceAppId; ResourceAccess = $updatedAccess })
    Update-MgApplication -ApplicationId $appReg.Id -RequiredResourceAccess $newRra
    Write-Host "Added $MissingGraphRole to the app registration manifest." -ForegroundColor Green
}

# (b) Consent: create the app-role assignment if absent.
$assignments = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $appSp.Id -All
if ($assignments | Where-Object { $_.AppRoleId -eq $role.Id -and $_.ResourceId -eq $graphSp.Id }) {
    Write-Host "Admin consent for $MissingGraphRole already granted - skipping." -ForegroundColor Green
} else {
    New-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $appSp.Id `
        -PrincipalId $appSp.Id -ResourceId $graphSp.Id -AppRoleId $role.Id | Out-Null
    Write-Host "Granted admin consent for $MissingGraphRole." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 2 - Teams application access policy (unblocks transcript reads)
# ---------------------------------------------------------------------------
# Graph authorizes online-meeting/transcript reads per USER: the app may only
# act on users covered by a granted application access policy. This is why
# transcript calls currently fail 403 despite the consented permission.
# (Teams still uses application access policies - the "don't create new"
# deprecation in Step 3 applies to the EXCHANGE policy mechanism only.)
# ---------------------------------------------------------------------------
Write-Host "`n=== Step 2: Teams application access policy ===" -ForegroundColor Cyan
Write-Host "Sign in as a Teams Administrator."
Connect-MicrosoftTeams -TenantId $TenantId | Out-Null

$teamsPolicy = $null
try { $teamsPolicy = Get-CsApplicationAccessPolicy -Identity $TeamsPolicyName -ErrorAction Stop } catch {}
if ($teamsPolicy) {
    Write-Host "Policy '$TeamsPolicyName' already exists - skipping creation." -ForegroundColor Green
} else {
    New-CsApplicationAccessPolicy -Identity $TeamsPolicyName -AppIds $AppClientId `
        -Description 'PartnerPulse transcript ingestion (read service-call transcripts of the shared organizer account)'
    Write-Host "Created policy '$TeamsPolicyName' for app $AppClientId." -ForegroundColor Green
}

# Granting is idempotent (re-granting just re-applies the same policy).
foreach ($account in $OrganizerAccounts) {
    Grant-CsApplicationAccessPolicy -PolicyName $TeamsPolicyName -Identity $account
    Write-Host "Granted '$TeamsPolicyName' to $account." -ForegroundColor Green
}
Write-Host "NOTE: Teams policy grants can take up to ~30 minutes to propagate." -ForegroundColor Yellow

# ---------------------------------------------------------------------------
# Step 3 - scope calendar access via Exchange "RBAC for Applications"
# ---------------------------------------------------------------------------
# Calendars.Read consented in Entra is tenant-wide. The supported way to limit
# it to specific mailboxes is now RBAC for Applications (the older
# New-ApplicationAccessPolicy is flagged "don't create new" by Microsoft):
#   3a. mail-enabled security group containing the organizer account
#       (DIRECT members only - nested groups are NOT honored by the scope)
#   3b. Exchange pointer to the app's Entra service principal
#   3c. management scope = "members of that group"
#   3d. assign the "Application Calendars.Read" role bounded by that scope
#   3e. REMOVE the tenant-wide Calendars.Read consent in Entra - Entra and
#       Exchange RBAC grants are a UNION, so leaving it would void the scoping
# ---------------------------------------------------------------------------
Write-Host "`n=== Step 3: Exchange RBAC for Applications (scoped Calendars.Read) ===" -ForegroundColor Cyan
Write-Host "Sign in as an Exchange Administrator (member of Organization Management)."
Connect-ExchangeOnline -ShowBanner:$false

# 3a. Mail-enabled security group holding the organizer account.
$group = $null
try { $group = Get-DistributionGroup -Identity $ExoGroupName -ErrorAction Stop } catch {}
if ($group) {
    Write-Host "Group '$ExoGroupName' already exists - ensuring membership." -ForegroundColor Green
} else {
    $group = New-DistributionGroup -Name $ExoGroupName -Alias $ExoGroupAlias -Type Security `
        -Members $OrganizerAccounts -Notes 'PartnerPulse transcript ingestion - calendar-read scope (shared organizer account)'
    Write-Host "Created mail-enabled security group '$ExoGroupName'." -ForegroundColor Green
}
$members = Get-DistributionGroupMember -Identity $ExoGroupName | Select-Object -ExpandProperty PrimarySmtpAddress
foreach ($account in $OrganizerAccounts) {
    if ($members -notcontains $account) {
        Add-DistributionGroupMember -Identity $ExoGroupName -Member $account
        Write-Host "Added $account to '$ExoGroupName'." -ForegroundColor Green
    }
}

# 3b. Exchange-side pointer to the app's Entra service principal.
#     IMPORTANT: -ObjectId is the ENTERPRISE APPLICATION (service principal)
#     object id - NOT the "Object ID" shown on the App Registrations blade.
#     We already resolved it in Step 1 ($appSp.Id).
$exoSp = $null
try { $exoSp = Get-ServicePrincipal -Identity $AppClientId -ErrorAction Stop } catch {}
if ($exoSp) {
    Write-Host "Exchange service principal pointer already exists - skipping." -ForegroundColor Green
} else {
    $exoSp = New-ServicePrincipal -AppId $AppClientId -ObjectId $appSp.Id -DisplayName 'PartnerPulse-Transcripts'
    Write-Host "Created Exchange service principal pointer for app $AppClientId." -ForegroundColor Green
}

# 3c. Management scope: "mailboxes that are DIRECT members of the group".
#     The filter needs the group's distinguished name.
$scope = $null
try { $scope = Get-ManagementScope -Identity $ExoScopeName -ErrorAction Stop } catch {}
if ($scope) {
    Write-Host "Management scope '$ExoScopeName' already exists - skipping." -ForegroundColor Green
} else {
    $groupDn = (Get-DistributionGroup -Identity $ExoGroupName).DistinguishedName
    New-ManagementScope -Name $ExoScopeName -RecipientRestrictionFilter "MemberOfGroup -eq '$groupDn'" | Out-Null
    Write-Host "Created management scope '$ExoScopeName' (members of '$ExoGroupName')." -ForegroundColor Green
}

# 3d. Role assignment: app gets Calendars.Read ONLY within the scope.
$existingAssignment = Get-ManagementRoleAssignment -Role $ExoCalendarRole -ErrorAction SilentlyContinue |
    Where-Object { $_.RoleAssignee -eq $exoSp.Identity -or $_.RoleAssigneeName -eq $exoSp.DisplayName }
if ($existingAssignment) {
    Write-Host "Role assignment '$ExoCalendarRole' already exists for this app - skipping." -ForegroundColor Green
} else {
    New-ManagementRoleAssignment -App $AppClientId -Role $ExoCalendarRole -CustomResourceScope $ExoScopeName | Out-Null
    Write-Host "Assigned '$ExoCalendarRole' to the app, scoped to '$ExoScopeName'." -ForegroundColor Green
}

# 3e. Remove the tenant-wide Calendars.Read consent in Entra. Without this the
#     app keeps tenant-wide calendar access regardless of the scope above
#     (grants from Entra and Exchange RBAC are additive). Calendar reads keep
#     working through the scoped Exchange role - tokens simply stop carrying
#     the Calendars.Read claim. The transcript/meeting permissions are NOT
#     touched (they're Teams-side, scoped by Step 2's policy instead).
$calRole = $graphSp.AppRoles | Where-Object { $_.Value -eq $UnscopedRoleToRemove -and $_.AllowedMemberTypes -contains 'Application' }
$calAssignment = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $appSp.Id -All |
    Where-Object { $_.AppRoleId -eq $calRole.Id -and $_.ResourceId -eq $graphSp.Id }
if ($calAssignment) {
    Remove-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $appSp.Id -AppRoleAssignmentId $calAssignment.Id
    Write-Host "Removed tenant-wide '$UnscopedRoleToRemove' consent from Entra (replaced by the scoped Exchange role)." -ForegroundColor Green
} else {
    Write-Host "Tenant-wide '$UnscopedRoleToRemove' consent already absent - skipping." -ForegroundColor Green
}
Write-Host "NOTE: Exchange app-permission changes cache for 30 min - 2 h. The test in Step 4 bypasses the cache." -ForegroundColor Yellow

# ---------------------------------------------------------------------------
# Step 4 - verification
# ---------------------------------------------------------------------------
Write-Host "`n=== Step 4: verification ===" -ForegroundColor Cyan

# 4a. Consented Graph roles on the service principal. Expected AFTER this
#     script: OnlineMeetingTranscript.Read.All, OnlineMeetingArtifact.Read.All,
#     OnlineMeetings.Read.All - and NO Calendars.Read (now served by the
#     scoped Exchange role instead).
$roleNames = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $appSp.Id -All | ForEach-Object {
    $assignment = $_
    ($graphSp.AppRoles | Where-Object { $_.Id -eq $assignment.AppRoleId }).Value
}
Write-Host "Consented Graph application permissions: $($roleNames -join ', ')"

# 4b. Exchange scoping - the organizer account must be InScope True for
#     Calendars.Read; any other mailbox must be False. This cmdlet evaluates
#     live (no propagation/cache wait).
foreach ($account in $OrganizerAccounts) {
    Test-ServicePrincipalAuthorization -Identity $AppClientId -Resource $account |
        ForEach-Object { Write-Host ("In-scope  {0}: {1} InScope={2}" -f $account, $_.RoleName, $_.InScope) }
}
Test-ServicePrincipalAuthorization -Identity $AppClientId -Resource 'Amit.Dubey@itbd.net' |
    ForEach-Object { Write-Host ("Out-of-scope Amit.Dubey@itbd.net: {0} InScope={1} (expected: False)" -f $_.RoleName, $_.InScope) }

Write-Host "`nDone. PartnerPulse will re-run its acceptance test: fetching a" -ForegroundColor Cyan
Write-Host "service-call transcript organized by DESManagement via the app identity" -ForegroundColor Cyan
Write-Host "(already verified working after the first run's Step 2 grant)." -ForegroundColor Cyan
Write-Host "`nRECOMMENDED FOLLOW-UP: the current client secret was shared over email/chat;" -ForegroundColor Yellow
Write-Host "once this setup is verified, rotate the secret in the portal (App registration" -ForegroundColor Yellow
Write-Host "> Certificates & secrets) and hand the new value over via a password manager." -ForegroundColor Yellow
