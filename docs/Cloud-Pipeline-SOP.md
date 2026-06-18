# Cloud Pipeline SOP — PartnerPulse

How the data pipeline runs **fully in the cloud, unattended** — a nightly
**Cloud Run Job** that rebuilds every partner and republishes Firestore, on a
**Cloud Scheduler** trigger. No local machine, no manual "Sync Data" button
(that was removed — see changelog 2026-06-16).

Project: **`operational-intelligence-ebe23`** · Region: **`us-central1`** (matches Firestore).

## Architecture

```
Cloud Scheduler  ── daily 21:00 America/New_York ──▶  Cloud Run Job: partnerpulse-nightly
   (HTTP → run.jobs.run, OAuth as pipeline SA)              │  container = this repo + scripts/cloud_sync.py
                                                            │
   1. pull state  ← gs://…-pipeline-state (data/ + Transcripts/)
   2. pull_graph_transcripts --write   (Microsoft Graph)
   3. extract.build_all                (Halo + TeamGPS + Grok, incremental)
   4. build_real_partners.py           (extra Halo clients)
   5. extract.build_all --reindex      (_index.json)
   6. build_overview.py                (_overview.json — dashboard feed)
   7. upload_firebase_data.py          (publish sharded tree)  ──▶ Cloud Firestore
   8. push state  → gs://…-pipeline-state
```

Secrets come from **Secret Manager**; Firestore/Storage auth is the job's
**attached service account** (keyless — no JSON key files). State persistence
keeps the Grok AI cache (no score drift) and transcript history (Teams ~90-day
content retention). Steps 2–6 are continue-on-failure; 1/7/8 are hard.

## Names (edit here if you rename anything)

| Thing | Value |
|------|-------|
| Region | `us-central1` |
| Artifact Registry repo | `partnerpulse` |
| Image | `us-central1-docker.pkg.dev/operational-intelligence-ebe23/partnerpulse/pipeline:latest` |
| Cloud Run Job | `partnerpulse-nightly` |
| State bucket | `gs://operational-intelligence-ebe23-pipeline-state` |
| Pipeline service account | `partnerpulse-pipeline@operational-intelligence-ebe23.iam.gserviceaccount.com` |
| Scheduler job | `partnerpulse-nightly-trigger` |
| Secrets | `halo-client-id`, `halo-client-secret`, `teamgps-api-key`, `ai-api-key`, `graph-tenant-id`, `graph-client-id`, `graph-client-secret` |
| AI env vars (non-secret) | `AI_BASE_URL=https://daku.services.ai.azure.com/openai/v1/`, `AI_MODEL=grok-4-1-fast-reasoning` (set via `--set-env-vars`, not Secret Manager) |

## One-time setup

Run from the repo root, authenticated as a project **Owner**
(`gcloud auth login`; `gcloud config set project operational-intelligence-ebe23`).

```bash
PROJECT=operational-intelligence-ebe23
REGION=us-central1
SA=partnerpulse-pipeline@$PROJECT.iam.gserviceaccount.com
BUCKET=$PROJECT-pipeline-state
IMAGE=$REGION-docker.pkg.dev/$PROJECT/partnerpulse/pipeline:latest

# 1. Enable APIs
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com storage.googleapis.com

# 2. Artifact Registry repo
gcloud artifacts repositories create partnerpulse --repository-format=docker \
  --location=$REGION --description="PartnerPulse pipeline images"

# 3. Secrets (values loaded by scripts/seed_secrets.py — never echoed)
pip install google-cloud-secret-manager   # once — the seeder needs the client lib
python scripts/seed_secrets.py            # creates/updates the 7 secrets above

# 4. State bucket + seed with current local caches (run after a local build).
#    Object Versioning is ON so a bad nightly run can be rolled back (see Rollback).
gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access
gcloud storage buckets update gs://$BUCKET --versioning
gcloud storage rsync -r data         gs://$BUCKET/data
gcloud storage rsync -r Transcripts  gs://$BUCKET/Transcripts

# 5. Pipeline service account + IAM
gcloud iam service-accounts create partnerpulse-pipeline \
  --display-name="PartnerPulse nightly pipeline"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role=roles/datastore.user
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member="serviceAccount:$SA" --role=roles/storage.objectAdmin
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role=roles/run.invoker

# 6. Build the image (Cloud Build — no local Docker needed)
gcloud builds submit --tag $IMAGE

# 7. Create the Cloud Run Job
gcloud run jobs create partnerpulse-nightly \
  --image=$IMAGE --region=$REGION --service-account=$SA \
  --task-timeout=3600 --max-retries=1 --memory=2Gi --cpu=2 \
  --set-env-vars="STATE_BUCKET=$BUCKET,AI_BASE_URL=https://daku.services.ai.azure.com/openai/v1/,AI_MODEL=grok-4-1-fast-reasoning" \
  --set-secrets="HALO_CLIENT_ID=halo-client-id:latest,HALO_CLIENT_SECRET=halo-client-secret:latest,TEAMGPS_API_KEY=teamgps-api-key:latest,AI_API_KEY=ai-api-key:latest,GRAPH_TENANT_ID=graph-tenant-id:latest,GRAPH_CLIENT_ID=graph-client-id:latest,GRAPH_CLIENT_SECRET=graph-client-secret:latest"

# 8. Schedule it: 21:00 America/New_York (DST-aware → 9pm Eastern year-round)
gcloud scheduler jobs create http partnerpulse-nightly-trigger \
  --location=$REGION --schedule="0 21 * * *" --time-zone="America/New_York" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/partnerpulse-nightly:run" \
  --http-method=POST --oauth-service-account-email=$SA
```

## Operate

```bash
# Run it now (test / on-demand refresh)
gcloud run jobs execute partnerpulse-nightly --region=us-central1

# Tail the latest execution
gcloud run jobs executions list --job=partnerpulse-nightly --region=us-central1
gcloud beta run jobs executions logs <execution-id> --region=us-central1

# Redeploy after code changes: rebuild + the job picks up :latest on next run
gcloud builds submit --tag us-central1-docker.pkg.dev/operational-intelligence-ebe23/partnerpulse/pipeline:latest

# Pause / resume the schedule
gcloud scheduler jobs pause  partnerpulse-nightly-trigger --location=us-central1
gcloud scheduler jobs resume partnerpulse-nightly-trigger --location=us-central1
```

## Rollback

A bad nightly run (e.g. an upstream data glitch that publishes wrong numbers) is
recoverable because the **state bucket has Object Versioning enabled** — every
overwrite of `data/`/`Transcripts/` keeps the prior generation.

```bash
BUCKET=operational-intelligence-ebe23-pipeline-state

# 1. Pause the schedule so the next nightly run can't re-clobber the state.
gcloud scheduler jobs pause partnerpulse-nightly-trigger --location=us-central1

# 2. Find the last-good generations of the affected objects.
gcloud storage ls -a gs://$BUCKET/data/_overview.json     # lists generation numbers

# 3. Restore an earlier generation over the live object (repeat per object/prefix).
gcloud storage cp gs://$BUCKET/data/_overview.json#<generation> \
                  gs://$BUCKET/data/_overview.json

# 4. Republish that restored snapshot to Firestore (runs locally or in the job).
#    Locally: pull the restored state down, then upload_firebase_data.py.
gcloud storage rsync -r gs://$BUCKET/data data
python scripts/upload_firebase_data.py --dry-run
python scripts/upload_firebase_data.py

# 5. Resume the schedule once the root cause is fixed.
gcloud scheduler jobs resume partnerpulse-nightly-trigger --location=us-central1
```

Firestore itself keeps only the latest published snapshot, so "rolling back the
data" means restoring the bucket inputs and re-running `upload_firebase_data.py`.
For a code regression, roll back the **image** instead: rebuild `:latest` from a
good commit (`gcloud builds submit --tag …/pipeline:latest`) — the Job picks it up
next run. UI/rules rollback is in `docs/Firebase-Deploy-SOP.md` (Rollback).

## Notes / gotchas

- **Schedule timezone:** `America/New_York` auto-handles DST, so it fires at 9pm
  Eastern wall-clock all year (= 01:00/02:00 UTC depending on season). If you
  literally need fixed UTC-5, use `--time-zone=Etc/GMT+5`.
- **Secrets:** currently the live keys lifted into Secret Manager as-is (reused,
  not rotated — decision 2026-06-16). Rotation is still owed: rotate in each
  source system, then `gcloud secrets versions add <name> --data-file=-` and the
  job picks up `:latest` next run. The in-repo fallbacks in `extract/config.py`
  remain a separate liability — see Firebase-Deploy-SOP §0.
- **Keyless:** the job uses its attached SA via ADC. Do **not** add a service
  account JSON key — it's an unnecessary long-lived credential.
- **Data refresh ≠ redeploy:** the job writes Firestore directly; signed-in users
  see new data on next load. `firebase deploy` is only for UI/rules changes.
- **First run** seeds nothing new if step 4 already ran locally; subsequent runs
  are incremental off the bucket-persisted cache (fast, ~minutes).
- **AI engine:** **Grok `grok-4-1-fast-reasoning`** via the Azure AI Foundry
  OpenAI-compatible endpoint (`AI_BASE_URL` + `AI_API_KEY` + `AI_MODEL`; OpenAI SDK,
  not the AzureOpenAI client). **Rate limit: 50k TPM / 50 RPM** — a full re-score is
  throttled, so the OpenAI client retries 429s with backoff (`_MAX_RETRIES` in
  `extract/ai.py`). The incremental cache means a normal nightly run only re-scores
  changed partners, staying well inside the limit. A model change (`AI_MODEL`)
  invalidates the AI cache and forces a clean re-score.
- **Cost:** Run Job a few min/day + Scheduler (free tier) + tiny bucket ≈ pennies/mo;
  the Grok calls are the real cost and are cached/incremental.
- **Outstanding follow-ups:** no **budget alert** is set on the Grok / Azure AI
  Foundry resource — add a Cost Management budget so a full rebuild can't run up token
  cost unnoticed. Two dashboard-side hardening items are also open (tracked in
  `Firebase-Deploy-SOP.md` "Outstanding follow-ups"): **Firebase App Check** and
  **MFA** on the `@itbd.net` sign-in are not yet enabled.
