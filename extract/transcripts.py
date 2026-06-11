"""Transcript (.docx) and deck (.pdf) -> Markdown / structured dialogue.

Uses Microsoft MarkItDown for both file types (SOP §1, Option A). Transcript
markdown is parsed into the dashboard's transcript schema:
  {filename, title, date, duration, dialogue:[{speaker, timestamp, text}], markdown}
Deck PDFs are converted to Markdown and cached on disk for both the AI layer and
the per-partner UI.
"""
import re
from pathlib import Path

from markitdown import MarkItDown

from . import config

_md = MarkItDown()

# Strip inline base64 image placeholders MarkItDown emits for transcript avatars.
_IMG_RE = re.compile(r"!\[\]\(data:image[^)]*\)\s*")
# A dialogue turn header:  **Speaker Name** 12:34
_TURN_RE = re.compile(r"\*\*(?P<speaker>[^*]+?)\*\*\s+(?P<ts>\d{1,2}:\d{2})\b")


def _clean(text: str) -> str:
    return _IMG_RE.sub("", text)


def docx_to_markdown(path) -> str:
    return _clean(_md.convert(str(path)).text_content)


def parse_transcript(path) -> dict:
    """Parse a .docx transcript into title/date/duration + dialogue turns."""
    path = Path(path)
    raw = docx_to_markdown(path)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    # Metadata: first bolded line is the title; next two non-turn lines are
    # date and duration (SOP §1 schema).
    title = date = duration = ""
    meta = []
    for ln in lines[:6]:
        if _TURN_RE.search(ln):
            break
        clean = re.sub(r"\*+", "", ln)
        clean = re.sub(r"\\([*_\\])", r"\1", clean)      # unescape md
        meta.append(clean.strip())
    if meta:
        title = meta[0]
    if len(meta) > 1:
        date = meta[1]
    if len(meta) > 2:
        duration = meta[2]

    # Dialogue: split the whole doc on turn headers, keep the text after each.
    dialogue = []
    matches = list(_TURN_RE.finditer(raw))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        text = raw[start:end]
        text = re.sub(r"\\([*_])", r"\1", text)          # unescape md
        text = " ".join(text.split()).strip()
        if text:
            dialogue.append({
                "speaker": m.group("speaker").strip(),
                "timestamp": m.group("ts"),
                "text": text,
            })

    return {
        "filename": path.name,
        "title": title or path.stem,
        "date": date,
        "duration": duration,
        "dialogue": dialogue,
        "markdown": raw,
    }


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def resolve_partner_dir(partner_name: str):
    """Find the Transcripts/ subfolder for a partner: exact name first, then a
    case/punctuation-insensitive match — so 'Realtime IT' finds 'realtime it',
    'RealTime-IT', etc. Returns a Path or None."""
    d = config.TRANSCRIPTS_DIR / partner_name
    if d.is_dir():
        return d
    want = _norm(partner_name)
    if want and config.TRANSCRIPTS_DIR.is_dir():
        for sub in config.TRANSCRIPTS_DIR.iterdir():
            if sub.is_dir() and _norm(sub.name) == want:
                return sub
    return None


def list_partner_transcripts(transcript_dir: str):
    """All .docx transcripts for a partner folder, sorted by name."""
    d = resolve_partner_dir(transcript_dir)
    if d is None:
        return []
    return sorted(d.glob("*.docx"))


def parse_partner_transcripts(transcript_dir: str):
    out = []
    for p in list_partner_transcripts(transcript_dir):
        try:
            out.append(parse_transcript(p))
        except Exception as e:  # don't let one bad file kill the run
            out.append({"filename": p.name, "title": p.stem, "date": "",
                        "duration": "", "dialogue": [], "markdown": "",
                        "error": str(e)})
    return out


# --- Deck PDFs ---------------------------------------------------------------
def deck_to_markdown(deck_bytes: bytes, out_basename: str, ext: str = "pdf") -> dict:
    """Persist a deck file (PDF or PPTX) and its Markdown conversion under
    data/decks/. `ext` must be the real source extension so MarkItDown picks the
    right converter. Returns {src_path, md_path, markdown, filename}."""
    config.DECKS_DIR.mkdir(parents=True, exist_ok=True)
    ext = (ext or "pdf").lstrip(".").lower()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", out_basename).strip("_")
    src_path = config.DECKS_DIR / f"{safe}.{ext}"
    md_path = config.DECKS_DIR / f"{safe}.md"
    src_path.write_bytes(deck_bytes)

    markdown = _md.convert(str(src_path)).text_content
    md_path.write_text(markdown, encoding="utf-8")
    return {
        "filename": out_basename,
        "src_path": str(src_path),
        "md_path": str(md_path),
        "markdown": markdown,
    }
