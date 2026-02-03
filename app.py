import re
import streamlit as st
import pandas as pd

from kindle_curator import parse_kindle, build_docx, ChapterMark, Entry, TRUNC_PHRASE


st.set_page_config(page_title="Kindle Document Curator", layout="centered")
st.title("Kindle Document Curator")

st.write(
    "Paste/upload raw Kindle highlights. Review entries (especially truncations), "
    "add a reading note + chapter map, then download a curated .docx."
)

font_choice = st.selectbox("Font", ["Calibri", "Arial"], index=0)
doc_title = st.text_input("Document title", value="Kindle Highlights")

uploaded = st.file_uploader("Upload a .txt file (optional)", type=["txt"])
raw = ""
if uploaded is not None:
    raw = uploaded.read().decode("utf-8", errors="replace")

raw = st.text_area("Raw export", value=raw, height=260, placeholder="Paste here…")

if "entries" not in st.session_state:
    st.session_state.entries = []
if "reading_note" not in st.session_state:
    st.session_state.reading_note = ""
if "chapters_df" not in st.session_state:
    st.session_state.chapters_df = pd.DataFrame(
        [{"marker_kind": "Page", "marker_value": 1, "chapter_title": "Chapter 1"}]
    )

if st.button("Parse"):
    st.session_state.entries = parse_kindle(raw)
    if not st.session_state.entries:
        st.error("No highlights found after parsing. (Check the input contains lines like 'Yellow highlight | Page: X').")
    else:
        trunc_count = sum(1 for e in st.session_state.entries if e.truncated)
        note_count = sum(1 for e in st.session_state.entries if e.note and e.note.strip())
        st.success(
            f"Parsed {len(st.session_state.entries)} entries. "
            f"Notes: {note_count}. Truncations flagged: {trunc_count}."
        )

entries: list[Entry] = st.session_state.entries

if entries:
    st.subheader("Reading note (appears at top, italic 10pt)")
    st.session_state.reading_note = st.text_area(
        "Reading note",
        value=st.session_state.reading_note,
        height=80,
        placeholder="e.g. Finished 3 Feb 2026. Read over a week. Main takeaways…"
    )

    st.subheader("Chapter map (Option A)")
    st.caption("Add rows with a Page/Location threshold and the chapter title to insert when that marker is reached.")
    st.session_state.chapters_df = st.data_editor(
        st.session_state.chapters_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "marker_kind": st.column_config.SelectboxColumn(
                "Marker kind", options=["Page", "Location"], required=True
            ),
            "marker_value": st.column_config.NumberColumn(
                "Marker number", min_value=0, step=1, required=True
            ),
            "chapter_title": st.column_config.TextColumn(
                "Chapter title", required=True
            ),
        },
        hide_index=True,
    )

    # --- Quick sanity counts ---
    total_entries = len(entries)
    notes_count = sum(1 for e in entries if e.note and e.note.strip())
    trunc_count = sum(1 for e in entries if e.truncated)

    c1, c2, c3 = st.columns(3)
    c1.metric("Entries", total_entries)
    c2.metric("Notes", notes_count)
    c3.metric("Truncations", trunc_count)

    # --- Filters ---
    show_only_truncated = st.checkbox("Show only truncated entries", value=False)
    show_only_with_notes = st.checkbox("Show only entries with notes", value=False)

    filtered_entries = entries
    if show_only_truncated:
        filtered_entries = [e for e in filtered_entries if e.truncated]
    if show_only_with_notes:
        filtered_entries = [e for e in filtered_entries if e.note and e.note.strip()]

    st.subheader("Review & fix entries")

    # Helpful prompt if filters hide everything
    if not filtered_entries:
        st.info("No entries match the current filters.")
    else:
        for idx, e in enumerate(filtered_entries):
            marker = f"{e.marker_kind} {e.marker_value}" if e.marker_kind and e.marker_value is not None else "No marker"
            trunc_flag = " ⚠ truncated" if e.truncated else ""
            note_flag = " 📝 note" if (e.note and e.note.strip()) else ""

            # Stable key so toggling filters doesn't scramble text areas
            stable_id = f"{e.marker_kind}-{e.marker_value}-{idx}"

            with st.expander(f"{idx+1}. {marker}{trunc_flag}{note_flag}", expanded=bool(e.truncated)):
                e.highlight = st.text_area(
                    "Highlight (edit this)",
                    value=e.highlight,
                    key=f"h-{stable_id}",
                    height=420 if e.truncated else 260
                ).strip()

                e.note = st.text_area(
                    "Note (optional)",
                    value=e.note or "",
                    key=f"n-{stable_id}",
                    height=140
                ).strip() or None

                # Re-flag truncation if phrase is still present (you can remove it by replacing the text)
                if TRUNC_PHRASE.lower() in e.highlight.lower():
                    e.truncated = True
                    st.warning("This highlight still contains the truncation message — replace it with the full text.")
                # If user replaces the text and removes the phrase, we leave truncation flag as-is
                # (because it may still be truncated even without the phrase). You can manually clear it if desired.

    st.divider()

    if st.button("Generate .docx"):
        # Chapters
        chapters = []
        df = st.session_state.chapters_df.copy()

        # Clean / validate rows (best effort; ignore incomplete)
        for _, row in df.iterrows():
            kind = str(row.get("marker_kind", "")).strip()
            title = str(row.get("chapter_title", "")).strip()
            try:
                val = int(row.get("marker_value", 0))
            except Exception:
                continue
            if kind in ("Page", "Location") and title:
                chapters.append(ChapterMark(kind, val, title))

        # Build
        final_title = doc_title.strip() or "Kindle Highlights"
        docx_bytes = build_docx(
            title=final_title,
            entries=entries,  # always export full set, not filtered
            reading_note=st.session_state.reading_note,
            chapters=chapters,
            font_name=font_choice,
        )

        safe_name = re.sub(r"[^A-Za-z0-9 _-]+", "", final_title).strip() or "Kindle Highlights"
        st.download_button(
            "Download curated .docx",
            data=docx_bytes,
            file_name=f"{safe_name}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
