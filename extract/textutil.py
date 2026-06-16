"""Canonical name-normalization helpers shared across the pipeline.

Two distinct, deliberately-different normalizations had drifted into separate
copies across the codebase; this is the single source of truth for both:

  slugify(name)   hyphen-separated slug ("RealTime, LLC" -> "realtime-llc").
                  Used for filenames / folder matching (build_real_partners.py,
                  extract/transcripts.py, extract/build_partner.py).
  normalize(s)    separator-free key ("RealTime, LLC" -> "realtimellc"). Used for
                  loose name/folder equality checks (scripts/audit_data.py).

NOTE: a slug is NOT always slugify(display_name) for every partner (gotcha 3);
the explicit `slug` field is authoritative. These helpers are for deriving keys
and matching folders, not for canonicalizing the registry slug.
"""
import re


def slugify(name):
    """Lowercase, collapse non-alphanumerics to single hyphens, trim hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def normalize(s):
    """Lowercase and strip every non-alphanumeric character (no separator)."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
