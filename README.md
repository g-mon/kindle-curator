# Kindle Document Curator

Paste Kindle highlights → Fix truncations → Add reading note → Add chapter map → Download DOCX.

📌 KINDLE CURATOR REBOOT CONTEXT

Project: Kindle Document Curator
Stack: Python + Streamlit + python-docx
Purpose: Convert raw Kindle exports into structured, formatted DOCX documents.

Core Features

Regex + state-machine parser (NOT AI parsing)

Extract:

Page / Location markers

Highlights

Notes (multi-line)

Truncation detection

Handles:

colour/no-colour highlight headers

comma location numbers

standalone truncation phrase lines

ellipsis truncation

Entry model:
Entry(marker_kind, marker_value, highlight, note, truncated)

Export Rules

Title: Bold 12pt

Reading note: Italic 10pt

Chapter headings: Bold 11pt

Body: 10pt

Notes:

bullet

only "Note:" bold

Separator line between entries

Truncation safety:

unresolved truncations export with "TRUNCATION NEEDED"

resolved ones do not

UI Features

Metrics: entries / notes / truncations

Filters:

show truncated only

show notes only

Review editing before export

Philosophy

Deterministic parsing → optional AI enrichment → deterministic export.
