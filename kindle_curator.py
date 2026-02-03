from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from io import BytesIO

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH


TRUNC_PHRASE = "Some highlights have been hidden or truncated due to export limits."

TRUNCATION_STUB = "TRUNCATION NEEDED"


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
        =+\s*$
    )\s*$"""
)

HIGHLIGHT_HEADER_RE = re.compile(
    r"""(?ix)^\s*
    (?:[a-z]+\s+)?              # optional colour word
    (highlight|underline)\s*     # highlight / underline
    \|\s*
    (page|location)\s*:\s*([\d,]+)
    \s*.*$
    """
)




NOTE_LINE_RE = re.compile(r"(?i)^\s*note\s*:\s*(.*)$")
ELLIPSIS_END_RE = re.compile(r"(…|\.\.\.)\s*$")


def _clean_lines(raw: str) -> List[str]:
    out: List[str] = []
    for line in raw.splitlines():
        line = line.replace("\ufeff", "").replace("\u00a0", " ")
        l = line.strip()

        if not l:
            out.append("")
            continue

        # skip summary line like "58 Highlights | 8 Notes"
        if re.match(r"(?i)^\s*\d+\s+highlights?\s*\|\s*\d+\s+notes?\s*$", l):
            continue

        out.append(l)

    return out


def parse_kindle(raw: str) -> List[Entry]:
    lines = _clean_lines(raw)

    entries: List[Entry] = []
    current: Optional[Entry] = None
    in_note = False

    def flush():
        nonlocal current, in_note
        if not current:
            return

        # If trunc phrase got embedded in highlight text, flag + strip
        if TRUNC_PHRASE.lower() in (current.highlight or "").lower():
            current.truncated = True
            current.highlight = re.sub(
                re.escape(TRUNC_PHRASE), "", current.highlight, flags=re.IGNORECASE
            ).strip()

        # Ellipsis ending = likely truncated
        if ELLIPSIS_END_RE.search((current.highlight or "").strip()):
            current.truncated = True

        # Keep entry if it has highlight OR is flagged truncated (even if empty)
        if (current.highlight and current.highlight.strip()) or current.truncated:
            entries.append(current)

        current = None
        in_note = False

    for line in lines:
        l = line.strip()
        if not l:
            continue

        # Start of a new highlight entry
        m = HIGHLIGHT_HEADER_RE.match(l)
        if m:
            flush()
            kind = "Page" if m.group(2).lower() == "page" else "Location"
            val = int(m.group(3).replace(",", ""))
            current = Entry(marker_kind=kind, marker_value=val, highlight="", note=None, truncated=False)
            in_note = False
            continue

        # Ignore metadata/date stamps
        if META_LINE_RE.match(l):
            continue

        # Standalone truncation phrase line
        if current is not None and TRUNC_PHRASE.lower() in l.lower():
            current.truncated = True
            continue

        # If we're in a note, everything continues as note until next header
        if current is not None and in_note:
            nm2 = NOTE_LINE_RE.match(l)
            if nm2:
                extra = nm2.group(1).strip()
                if extra:
                    current.note = (current.note + "\n" if current.note else "") + extra
                continue

            current.note = (current.note + "\n" if current.note else "") + l
            continue

        # Start of a note
        nm = NOTE_LINE_RE.match(l)
        if nm and current is not None:
            note_text = nm.group(1).strip()
            if note_text:
                current.note = (current.note + "\n" if current.note else "") + note_text
            else:
                current.note = current.note or ""
            in_note = True
            continue

        # Otherwise it's highlight text
        if current is not None:
            current.highlight = (current.highlight + "\n" if current.highlight else "") + l
        else:
            continue

    flush()
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

        # Highlight (10pt) with truncation safety stub
        ph = doc.add_paragraph()
        _set_para_base(ph)

        highlight_text = (e.highlight or "").strip()

        if e.truncated:
            if highlight_text:
                # If highlight exists, append stub after ellipsis or at end
                if highlight_text.endswith(("…", "...")):
                    highlight_text = f"{highlight_text} {TRUNCATION_STUB}"
                else:
                    highlight_text = f"{highlight_text} … {TRUNCATION_STUB}"
            else:
                # Completely empty highlight → stub only
                highlight_text = TRUNCATION_STUB

        _add_run(ph, highlight_text, font_name, 10)

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
