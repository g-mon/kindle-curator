import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from io import BytesIO

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH


TRUNC_PHRASE = "Some highlights have been hidden or truncated due to export limits."


@dataclass
class Entry:
    marker_kind: Optional[str]   # "Page" or "Location" or None
    marker_value: Optional[int]  # numeric for sorting/thresholds
    highlight: str
    note: Optional[str] = None
    truncated: bool = False


@dataclass
class ChapterMark:
    marker_kind: str            # "Page" or "Location"
    marker_value: int
    title: str                  # Chapter title to insert


# ---- Parsing ----
META_LINE_RE = re.compile(
    r"""(?ix)^\s*(
        options |
        added\s+on\s+.* |
        (?:yellow|blue|pink|orange)\s+highlight.* |
        highlight\s*\|\s*(?:page|location)\s*:\s*\d+.* |
        note\s*\|\s*(?:page|location)\s*:\s*\d+.* |
        =+\s*$
    )\s*$"""
)

PAGE_RE = re.compile(r"(?i)\bpage\s*[:#]?\s*(\d+)\b")
LOC_RE  = re.compile(r"(?i)\blocation\s*[:#]?\s*(\d+)\b")
NOTE_PREFIX_RE = re.compile(r"(?i)^\s*note\s*[:\-]\s*")


def _clean_lines(raw: str) -> List[str]:
    out = []
    for line in raw.splitlines():
        l = line.strip()
        if not l:
            out.append("")
            continue
        # IMPORTANT: do NOT strip TRUNC_PHRASE here; it may appear inside highlights
        if META_LINE_RE.match(l):
            continue
        out.append(l)
    return out


def _split_blocks(lines: List[str]) -> List[List[str]]:
    blocks, buf = [], []
    for l in lines:
        if l == "":
            if buf:
                blocks.append(buf)
                buf = []
        else:
            buf.append(l)
    if buf:
        blocks.append(buf)
    return blocks


def _marker_from_block(block: List[str], last_marker: Tuple[Optional[str], Optional[int]]):
    kind, val = last_marker
    for l in block:
        m = PAGE_RE.search(l)
        if m:
            return ("Page", int(m.group(1)))
        m = LOC_RE.search(l)
        if m:
            return ("Location", int(m.group(1)))
    return (kind, val)


def _strip_marker_fragments(text: str) -> str:
    text = PAGE_RE.sub("", text)
    text = LOC_RE.sub("", text)
    return text.strip(" -|")


def parse_kindle(raw: str) -> List[Entry]:
    lines = _clean_lines(raw)
    blocks = _split_blocks(lines)

    entries: List[Entry] = []
    last_marker: Tuple[Optional[str], Optional[int]] = (None, None)

    for block in blocks:
        last_marker = _marker_from_block(block, last_marker)
        kind, val = last_marker

        note = None
        highlight_lines: List[str] = []

        for l in block:
            l2 = _strip_marker_fragments(l)
            if NOTE_PREFIX_RE.match(l2):
                note = NOTE_PREFIX_RE.sub("", l2).strip()
            else:
                highlight_lines.append(l2)

        highlight = "\n".join([h for h in highlight_lines if h]).strip()
        if not highlight:
            continue

        truncated = TRUNC_PHRASE.lower() in highlight.lower()
        if truncated:
            # Remove the truncation phrase from the highlight text for output
            highlight = re.sub(re.escape(TRUNC_PHRASE), "", highlight, flags=re.IGNORECASE).strip()

        entries.append(Entry(kind, val, highlight, note=note, truncated=truncated))

    return entries


# ---- DOCX generation ----
def _set_para_base(p):
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.left_indent = Pt(0)
    pf.first_line_indent = Pt(0)
    pf.right_indent = Pt(0)
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)


def _add_run(p, text: str, font_name: str, size_pt: int, bold: bool = False, italic: bool = False):
    r = p.add_run(text)
    r.font.name = font_name
    r.font.size = Pt(size_pt)
    r.bold = bold
    r.italic = italic
    return r


def build_docx(
    title: str,
    entries: List[Entry],
    reading_note: Optional[str],
    chapters: List[ChapterMark],
    font_name: str = "Calibri"
) -> bytes:
    doc = Document()

    # Normal style: body 10pt
    normal = doc.styles["Normal"]
    normal.font.name = font_name
    normal.font.size = Pt(10)

    # Title 12pt bold
    p_title = doc.add_paragraph()
    _set_para_base(p_title)
    _add_run(p_title, title, font_name, 12, bold=True)

    # Reading note 10pt italics (if present)
    if reading_note and reading_note.strip():
        p_note = doc.add_paragraph()
        _set_para_base(p_note)
        _add_run(p_note, reading_note.strip(), font_name, 10, italic=True)

    # Small gap after header area
    doc.add_paragraph("")

    # Prepare chapter insertion pointers per marker kind
    chapters_by_kind = {"Page": [], "Location": []}
    for ch in chapters:
        if ch.marker_kind in chapters_by_kind:
            chapters_by_kind[ch.marker_kind].append(ch)

    for k in chapters_by_kind:
        chapters_by_kind[k].sort(key=lambda x: x.marker_value)

    next_idx = {"Page": 0, "Location": 0}

    def maybe_insert_chapter(kind: Optional[str], val: Optional[int]):
        if not kind or val is None:
            return
        if kind not in chapters_by_kind:
            return

        i = next_idx[kind]
        lst = chapters_by_kind[kind]
        # Insert all chapter headings whose threshold is <= current marker value
        while i < len(lst) and val >= lst[i].marker_value:
            p_ch = doc.add_paragraph()
            _set_para_base(p_ch)
            _add_run(p_ch, lst[i].title.strip(), font_name, 11, bold=True)
            doc.add_paragraph("")  # small gap after chapter heading
            i += 1
        next_idx[kind] = i

    for e in entries:
        maybe_insert_chapter(e.marker_kind, e.marker_value)

        # Marker line (bold 10pt)
        if e.marker_kind and e.marker_value is not None:
            pm = doc.add_paragraph()
            _set_para_base(pm)
            _add_run(pm, f"{e.marker_kind} {e.marker_value}", font_name, 10, bold=True)

        # Highlight (10pt)
        ph = doc.add_paragraph()
        _set_para_base(ph)
        _add_run(ph, e.highlight, font_name, 10)

        # Note: bullet, NO INDENT, 10pt; only "Note:" bold
        if e.note:
            pbn = doc.add_paragraph()
            _set_para_base(pbn)
            _add_run(pbn, "• ", font_name, 10)
            _add_run(pbn, "Note:", font_name, 10, bold=True)
            _add_run(pbn, f" {e.note}", font_name, 10)

        # Separator line BETWEEN entries only
        ps = doc.add_paragraph()
        _set_para_base(ps)
        _add_run(ps, "-" * 48, font_name, 10)

    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()
