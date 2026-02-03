import re
import streamlit as st
import pandas as pd

from kindle_curator import parse_kindle, build_docx, ChapterMark, Entry


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
        st.error("No highlights found after removing metadata.")
    else:
        trunc_count = sum(1 for e in st.session_state.entries if e.truncated)
        st.success(f"Parsed {len(st.session_state.entries)} entries. Flagged {trunc_count} as truncated (export limits).")

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

    st.subheader("Review & fix entries")
    for idx, e in enumerate(entries):
        marker = f"{e.marker_kind} {e.marker_value}" if e.marker_kind and e.marker_value is not None else "No marker"
        flag = " ⚠ truncated (replace text)" if e.truncated else ""
        with st.expander(f"{idx+1}. {marker}{flag}", expanded=bool(e.truncated)):
            e.highlight = st.text_area("Highlight", value=e.highlight, key=f"h{idx}", height=120).strip()
            e.note = st.text_area("Note (optional)", value=e.note or "", key=f"n{idx}", height=70).strip() or None

            # Re-flag truncation if phrase still present (you can remove it by replacing the text)
            e.truncated = ("some highlights have been hidden or truncated due to export limits" in e.highlight.lower())
            if e.truncated:
                st.warning("This highlight still contains the truncation message — replace it with the full text.")

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
            entries=entries,
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
