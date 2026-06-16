#!/usr/bin/env python3
"""Load the pipeline secrets into Secret Manager — WITHOUT printing their values.

Reads the current credentials from extract.config (which loads .env + the
in-repo fallbacks), creates each Secret Manager secret if missing, and adds a
new version. Idempotent: re-run after rotating a key to publish a new version
(the Cloud Run Job reads `:latest`).

    pip install google-cloud-secret-manager
    gcloud auth application-default login      # or run as an Owner
    python scripts/seed_secrets.py [--project <id>]

Prints only secret NAMES and a ✓/✗ per secret — never the values.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Secret Manager id -> the credential value (pulled from config).
SECRETS = {
    "halo-client-id":      config.HALO_CLIENT_ID,
    "halo-client-secret":  config.HALO_CLIENT_SECRET,
    "teamgps-api-key":     config.TEAMGPS_API_KEY,
    "azure-openai-key":    config.AZURE_OPENAI_KEY,
    "graph-tenant-id":     config._env("GRAPH_TENANT_ID"),
    "graph-client-id":     config._env("GRAPH_CLIENT_ID"),
    "graph-client-secret": config._env("GRAPH_CLIENT_SECRET"),
}


def default_project():
    rc = ROOT / ".firebaserc"
    if rc.exists():
        try:
            return json.loads(rc.read_text(encoding="utf-8")).get("projects", {}).get("default")
        except (ValueError, OSError):
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=default_project())
    args = ap.parse_args()
    if not args.project:
        sys.exit("no project — set .firebaserc default or pass --project")

    from google.cloud import secretmanager
    from google.api_core import exceptions

    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{args.project}"

    missing = [k for k, v in SECRETS.items() if not v]
    if missing:
        sys.exit(f"refusing to seed — empty value(s) for: {', '.join(missing)}. "
                 f"Check .env / extract/config.py.")

    for sid, value in SECRETS.items():
        try:
            client.create_secret(parent=parent, secret_id=sid,
                                  secret={"replication": {"automatic": {}}})
            created = True
        except exceptions.AlreadyExists:
            created = False
        client.add_secret_version(parent=f"{parent}/secrets/{sid}",
                                   payload={"data": value.encode("utf-8")})
        print(f"  + {sid}  ({'created' if created else 'updated'}, "
              f"{len(value)} bytes)")

    print(f"done - {len(SECRETS)} secrets in {args.project}.")


if __name__ == "__main__":
    main()
