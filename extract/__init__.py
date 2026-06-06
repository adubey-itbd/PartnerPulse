"""PartnerPulse extraction engine.

Builds the unified per-partner data cache consumed by the dashboard, by pulling
from HaloPSA (client/users/tickets/actions/attachments), TeamGPS (CSAT/NPS),
local .docx transcripts, and Halo deck PDFs (converted to Markdown via MarkItDown).

See ../docs/Data-Extraction-SOP.md for the source-of-truth workflow.
"""
