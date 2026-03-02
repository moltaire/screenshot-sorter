#!/usr/bin/env python3
"""
app.py
──────
Streamlit UI for contact — analog film scan tagger.

Run with:
    streamlit run app.py
    streamlit run app.py -- --folder /path/to/roll
"""

import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from PIL import Image, ImageOps

from processor.html import write_roll_html
from processor.roll import (
    IMAGE_EXTS,
    KNOWN_CAMERAS,
    KNOWN_FILM_STOCKS,
    _history_sorted,
    _join_list_field,
    _load_history,
    _record,
    _save_history,
    _split_list_field,
    load_roll_yaml,
    write_roll_yaml,
)
from processor.sidecar import _read_xmp_meta, write_xmp
from processor.tagger import VALID_CATEGORIES, analyze_image, write_roll_summary

st.set_page_config(page_title="contact", layout="wide")

_VISION_KEYWORDS = {"vision", "llava", "minicpm", "bakllava", "moondream", "cogvlm"}

_CSS = """
<style>
[data-testid="stImage"] { position: relative; }
[data-testid="stImage"] > button {
    position: absolute !important;
    top: 0.4rem !important; right: 0.4rem !important;
    left: auto !important; bottom: auto !important;
}
</style>
"""

_STEPS = [
    (1, "Select Folder"),
    (2, "Roll Info"),
    (3, "Frame Analysis"),
    (4, "Review & Edit"),
    (5, "Contact Sheet"),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_ollama_models() -> list[str]:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return []
        lines = r.stdout.strip().split("\n")
        return [line.split()[0] for line in lines[1:] if line.split()]
    except Exception:
        return []


def _is_vision_model(name: str) -> bool:
    return any(kw in name.lower() for kw in _VISION_KEYWORDS)


def _thumb(path: Path, size: int = 300) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((size, size))
    return img


def _dedup(items: list) -> list:
    seen: set = set()
    out: list = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _pick_folder_dialog() -> str:
    """Open a native folder picker. Returns path string or empty string."""
    import platform
    try:
        if platform.system() == "Darwin":
            # osascript is the reliable choice on macOS — no threading issues
            r = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose folder with prompt "Select roll folder")'],
                capture_output=True, text=True, timeout=60,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        else:
            # On Linux/Windows run tkinter in a subprocess to avoid main-thread issues
            r = subprocess.run(
                [sys.executable, "-c",
                 "import tkinter; from tkinter import filedialog; "
                 "root = tkinter.Tk(); root.withdraw(); "
                 "root.wm_attributes('-topmost', True); "
                 "print(filedialog.askdirectory(), end=''); root.destroy()"],
                capture_output=True, text=True, timeout=60,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _init_state():
    defaults: dict = {
        "step": 1,
        "folder": None,
        "roll": {},
        "images": [],
        "vision_model": "llama3.2-vision:11b",
        "text_model": "llama3.2-vision:11b",
        "folder_input_initialized": False,
        "review_idx": 0,
        "browser_opened_for": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _cli_folder() -> str:
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--folder" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--folder="):
            return arg[len("--folder="):]
    return ""


def _clear_folder_state():
    for key in [
        "film_sel", "cam_sel", "lab_sel",
        "ms_lens", "ms_location", "ms_subjects",
        "label_input", "date_input", "lab_notes_input", "notes_input",
        "selected_images",
    ]:
        st.session_state.pop(key, None)
    for key in [k for k in list(st.session_state.keys()) if k.startswith(("rev_", "sel_", "confirm_"))]:
        del st.session_state[key]
    st.session_state.review_idx = 0


def _html_pairs(folder: Path) -> list:
    return [
        (img, _read_xmp_meta(img.with_suffix(".xmp")))
        for img in sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS)
        if img.with_suffix(".xmp").exists()
    ]


def _select_all(images: list):
    st.session_state.selected_images = {img.name for img in images}
    for img in images:
        st.session_state[f"sel_{img.name}"] = True


def _select_none(images: list):
    st.session_state.selected_images = set()
    for img in images:
        st.session_state[f"sel_{img.name}"] = False


# ── Step renderers ─────────────────────────────────────────────────────────────

def _render_folder():
    st.caption("Choose a folder containing your scanned film images.")

    browse_col, input_col = st.columns([0.7, 4], gap="small")
    with browse_col:
        if st.button("Browse…", use_container_width=True):
            picked = _pick_folder_dialog()
            if picked:
                st.session_state["folder_input"] = picked
                st.rerun()
    with input_col:
        folder_val: str = st.text_input(
            "folder",
            key="folder_input",
            placeholder="/path/to/scans/roll_01",
            label_visibility="collapsed",
        )

    folder = st.session_state.folder
    if folder_val:
        fp = Path(folder_val).expanduser().resolve()
        if fp.is_dir():
            new_images = sorted(
                f for f in fp.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS
            )
            new_roll = load_roll_yaml(fp) if (fp / "roll.yaml").exists() else {}
            n_tagged_new = sum(1 for img in new_images if img.with_suffix(".xmp").exists())

            if folder != fp:
                _clear_folder_state()
                st.session_state.folder = fp
                st.session_state.roll = new_roll
                st.session_state.images = new_images
                st.session_state.browser_opened_for = None
                st.session_state.step = 2
                st.rerun()

            parts = [f"{len(new_images)} image{'s' if len(new_images) != 1 else ''}"]
            if n_tagged_new:
                parts.append(f"{n_tagged_new} tagged")
            parts.append("roll.yaml found" if new_roll else "no roll.yaml")
            st.caption("✓ " + " · ".join(parts))
        else:
            st.error("Folder not found.")


def _render_roll():
    folder = st.session_state.folder
    if folder is None:
        st.info("Select a folder first.")
        return

    roll = st.session_state.roll
    history = _load_history()

    st.caption("Describe the roll — film stock, camera, date, location.")

    _, _, _rc = st.columns(3)
    with _rc:
        save_clicked = st.button("Save and continue", type="primary", use_container_width=True)

    label = st.text_input(
        "Label", value=roll.get("label", ""),
        placeholder="e.g. Oslo Summer 2024", key="label_input",
    )

    current_film = roll.get("film", "")
    film_hist = _history_sorted(history, "film")
    film_opts = _dedup(([current_film] if current_film else []) + film_hist + KNOWN_FILM_STOCKS)
    film = st.selectbox(
        "Film stock", film_opts,
        index=film_opts.index(current_film) if current_film in film_opts else None,
        accept_new_options=True, key="film_sel",
        placeholder="Select or type a film stock…",
    )

    current_cam = roll.get("camera", "")
    cam_hist = _history_sorted(history, "camera")
    cam_opts = _dedup(([current_cam] if current_cam else []) + cam_hist + KNOWN_CAMERAS)
    camera = st.selectbox(
        "Camera", cam_opts,
        index=cam_opts.index(current_cam) if current_cam in cam_opts else None,
        accept_new_options=True, key="cam_sel",
        placeholder="Select or type a camera…",
    )

    current_lens = _split_list_field(roll.get("lens", ""))
    lens_opts = _dedup(current_lens + _history_sorted(history, "lens"))
    lens_sel = st.multiselect(
        "Lens", options=lens_opts, default=current_lens,
        accept_new_options=True, key="ms_lens",
    )

    date = st.text_input(
        "Date", value=roll.get("date", ""),
        placeholder="YYYY-MM or YYYY-MM-DD", key="date_input",
    )

    current_location = _split_list_field(roll.get("location", ""))
    loc_opts = _dedup(current_location + _history_sorted(history, "location"))
    location_sel = st.multiselect(
        "Location", options=loc_opts, default=current_location,
        accept_new_options=True, key="ms_location",
    )

    current_subjects = _split_list_field(roll.get("subjects", ""))
    subj_opts = _dedup(current_subjects + _history_sorted(history, "subjects"))
    subjects_sel = st.multiselect(
        "Subjects", options=subj_opts, default=current_subjects,
        accept_new_options=True, key="ms_subjects",
    )

    current_lab = roll.get("lab", "")
    lab_opts = _dedup(([current_lab] if current_lab else []) + _history_sorted(history, "lab"))
    lab = st.selectbox(
        "Lab", lab_opts,
        index=lab_opts.index(current_lab) if current_lab in lab_opts else None,
        accept_new_options=True, key="lab_sel",
        placeholder="Select or type a lab…",
    )

    lab_notes = st.text_input(
        "Lab notes", value=roll.get("lab_notes", ""),
        placeholder="e.g. push 1 stop", key="lab_notes_input",
    )
    notes = st.text_input("Notes", value=roll.get("notes", ""), key="notes_input")

    if save_clicked:
        lens = _join_list_field(lens_sel)
        location = _join_list_field(location_sel)
        subjects = _join_list_field(subjects_sel)
        data = {
            "film": film or "", "camera": camera or "", "lens": lens, "date": date,
            "location": location, "subjects": subjects, "lab": lab or "",
            "lab_notes": lab_notes, "notes": notes, "label": label,
        }
        write_roll_yaml(folder, data)
        _record(history, "film", film or "")
        _record(history, "camera", camera or "")
        for item in _split_list_field(lens):
            _record(history, "lens", item)
        for item in _split_list_field(location):
            _record(history, "location", item)
        for item in _split_list_field(subjects):
            _record(history, "subjects", item)
        _record(history, "lab", lab or "")
        _record(history, "lab_notes", lab_notes)
        _save_history(history)
        st.session_state.roll = load_roll_yaml(folder)
        st.session_state.step = 3
        st.rerun()


def _render_images():
    folder = st.session_state.folder
    if folder is None:
        st.info("Select a folder first.")
        return

    images = st.session_state.images
    roll = st.session_state.roll

    if not images:
        st.info("No images found in this folder.")
        return

    if "selected_images" not in st.session_state:
        st.session_state.selected_images = {img.name for img in images}

    st.caption(
        "AI tagging analyzes each image with a vision model and writes a description, "
        "category, and tags as sidecar metadata. Select images to include, then tag."
    )

    # ── Action buttons ────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        tag_untagged = st.button("Tag untagged", type="primary", use_container_width=True,
                                 help="AI-tag images that don't have metadata yet.")
    with c2:
        retag_selected = st.button("Re-tag selected", use_container_width=True,
                                   help="Force AI re-tagging on all checked images.")
    with c3:
        continue_btn = st.button("Continue", use_container_width=True,
                                 help="Proceed to review without tagging.")

    # ── Model settings ────────────────────────────────────────────────────────
    with st.expander("Model settings"):
        all_models = _get_ollama_models()
        vision_models = [m for m in all_models if _is_vision_model(m)]
        text_models = all_models
        col1, col2 = st.columns(2)
        with col1:
            if vision_models:
                vm_idx = vision_models.index(st.session_state.vision_model) if st.session_state.vision_model in vision_models else 0
                st.selectbox("Vision model", vision_models, index=vm_idx, key="vision_model")
            else:
                st.text_input("Vision model", key="vision_model")
        with col2:
            if text_models:
                tm_idx = text_models.index(st.session_state.text_model) if st.session_state.text_model in text_models else 0
                st.selectbox("Text model", text_models, index=tm_idx, key="text_model")
            else:
                st.text_input("Text model", key="text_model")

    # ── Selection line ────────────────────────────────────────────────────────
    n_sel = len(st.session_state.selected_images)
    sc1, sc2, sc3 = st.columns([3, 1, 1.4], gap="small")
    with sc1:
        st.markdown(
            f"<div style='font-size:0.8rem; color:#888; padding-top:0.45rem;'>"
            f"{n_sel} of {len(images)} selected</div>",
            unsafe_allow_html=True,
        )
    with sc2:
        if st.button("select all", key="sel_all", use_container_width=True):
            _select_all(images)
            st.rerun()
    with sc3:
        if st.button("clear selection", key="sel_clear", use_container_width=True):
            _select_none(images)
            st.rerun()

    # ── Continue (no tagging) ─────────────────────────────────────────────────
    if continue_btn:
        st.session_state.step = 4
        st.rerun()

    # ── AI processing — runs BEFORE grid so progress appears above images ─────
    if tag_untagged or retag_selected:
        selected_images = [img for img in images if img.name in st.session_state.selected_images]
        to_process = (
            selected_images if retag_selected
            else [img for img in selected_images if not img.with_suffix(".xmp").exists()]
        )
        if not to_process:
            st.info(
                "No images to process. "
                + ("All selected images are already tagged — use **Re-tag selected** to force."
                   if not retag_selected else "Select at least one image.")
            )
        else:
            n = len(to_process)
            prog = st.progress(0, text=f"Starting… (0 / {n})")
            all_meta: list = []

            for i, img in enumerate(to_process):
                prog.progress(i / n, text=f"{img.name}  ({i + 1} / {n})")
                try:
                    meta = analyze_image(
                        img,
                        st.session_state.vision_model,
                        st.session_state.text_model,
                        roll,
                        verbose=False,
                    )
                    write_xmp(img, meta, roll)
                    all_meta.append(meta)
                except Exception as e:
                    st.error(f"{img.name}: {e}")

            prog.progress(1.0, text="Finalizing…")
            if all_meta:
                write_roll_summary(
                    folder, all_meta, roll,
                    st.session_state.vision_model,
                    st.session_state.text_model,
                )
            pairs = _html_pairs(folder)
            if pairs:
                write_roll_html(folder, pairs, roll)
            prog.empty()

            for key in [k for k in list(st.session_state.keys()) if k.startswith(("rev_", "confirm_"))]:
                del st.session_state[key]
            st.session_state.review_idx = 0
            st.session_state.step = 4
            st.rerun()

    # ── Image grid (thumbnail above, checkbox + name below) ───────────────────
    grid_cols = st.columns(4)
    for i, img in enumerate(images):
        with grid_cols[i % 4]:
            tagged = img.with_suffix(".xmp").exists()
            try:
                st.image(_thumb(img), width="stretch")
            except Exception:
                pass
            checked = st.checkbox(
                ("✓ " if tagged else "") + img.name,
                key=f"sel_{img.name}",
                value=img.name in st.session_state.selected_images,
            )
            if checked:
                st.session_state.selected_images.add(img.name)
            else:
                st.session_state.selected_images.discard(img.name)

def _render_metadata():
    folder = st.session_state.folder
    if folder is None:
        st.info("Select a folder first.")
        return

    images = st.session_state.images
    tagged_images = [img for img in images if img.with_suffix(".xmp").exists()]
    roll = st.session_state.roll

    if not tagged_images:
        st.info("No tagged images yet. Tag images in the Frame Analysis step first.")
        return

    for img in tagged_images:
        if f"rev_cat_{img.name}" not in st.session_state:
            meta = _read_xmp_meta(img.with_suffix(".xmp"))
            st.session_state[f"rev_cat_{img.name}"] = meta.get("category", "other")
            st.session_state[f"rev_desc_{img.name}"] = meta.get("description", "")
            st.session_state[f"rev_tags_{img.name}"] = meta.get("tags", [])

    all_known_tags = sorted({
        tag
        for img in tagged_images
        for tag in st.session_state.get(f"rev_tags_{img.name}", [])
    })

    n = len(tagged_images)
    review_idx = st.session_state.review_idx

    st.caption(
        "Review and edit the AI-generated metadata for each image. "
        "Open a frame, adjust if needed, and press Save to move to the next."
    )

    _, _, _rc = st.columns(3)
    with _rc:
        continue_all = st.button(
            "Save and continue",
            type="primary",
            use_container_width=True,
            help="Save all as-is and proceed to the contact sheet.",
        )

    if continue_all:
        for img in tagged_images:
            write_xmp(img, {
                "category": st.session_state[f"rev_cat_{img.name}"],
                "description": st.session_state[f"rev_desc_{img.name}"],
                "tags": list(st.session_state[f"rev_tags_{img.name}"]),
            }, roll)
        pairs = _html_pairs(folder)
        if pairs:
            write_roll_html(folder, pairs, roll)
        st.session_state.step = 5
        st.rerun()

    sorted_cats = sorted(VALID_CATEGORIES)
    for i, img in enumerate(tagged_images):
        is_current = (i == review_idx)
        exp_label = ("✓ " if i < review_idx else "") + img.name
        with st.expander(exp_label, expanded=is_current):
            c1, c2 = st.columns([1, 2])
            with c1:
                try:
                    st.image(_thumb(img, 800), width="stretch")
                except Exception:
                    pass
            with c2:
                st.selectbox("Category", sorted_cats, key=f"rev_cat_{img.name}")

                desc_text = st.session_state.get(f"rev_desc_{img.name}", "")
                desc_lines = max(4, len(desc_text) // 55 + desc_text.count("\n") + 1)
                st.text_area(
                    "Description",
                    key=f"rev_desc_{img.name}",
                    height=desc_lines * 22,
                )

                st.multiselect(
                    "Tags",
                    options=all_known_tags,
                    accept_new_options=True,
                    key=f"rev_tags_{img.name}",
                )

                if is_current:
                    is_last = (i == n - 1)
                    btn_label = "Save metadata" if is_last else "Save"
                    if st.button(btn_label, key=f"confirm_{img.name}", type="primary"):
                        write_xmp(img, {
                            "category": st.session_state[f"rev_cat_{img.name}"],
                            "description": st.session_state[f"rev_desc_{img.name}"],
                            "tags": list(st.session_state[f"rev_tags_{img.name}"]),
                        }, roll)
                        if is_last:
                            pairs = _html_pairs(folder)
                            if pairs:
                                write_roll_html(folder, pairs, roll)
                            st.session_state.step = 5
                        else:
                            st.session_state.review_idx = i + 1
                        st.rerun()


def _render_contact_sheet():
    folder = st.session_state.folder
    if folder is None:
        st.info("Select a folder first.")
        return

    roll = st.session_state.roll
    index_path = folder / "index.html"

    st.caption("Open your contact sheet in the browser, or rebuild it from existing metadata.")

    _, _mc, _rc = st.columns(3)
    with _mc:
        rebuild_btn = st.button(
            "Rebuild contact sheet",
            use_container_width=True,
            help="Regenerate HTML from existing metadata — no AI.",
        )
    with _rc:
        open_btn = st.button(
            "Open in browser",
            type="primary",
            use_container_width=True,
            disabled=not index_path.exists(),
        )

    if open_btn:
        webbrowser.open(index_path.as_uri())

    if index_path.exists() and st.session_state.browser_opened_for != str(folder):
        webbrowser.open(index_path.as_uri())
        st.session_state.browser_opened_for = str(folder)

    if rebuild_btn:
        pairs = _html_pairs(folder)
        if pairs:
            write_roll_html(folder, pairs, roll)
            st.success(f"Rebuilt — {len(pairs)} frames.")
        else:
            st.info("No tagged images found.")

    if not index_path.exists():
        st.info("No contact sheet yet — tag some images first, or press Rebuild.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _init_state()
    st.markdown(_CSS, unsafe_allow_html=True)

    if not st.session_state.folder_input_initialized:
        st.session_state.folder_input_initialized = True
        cli_f = _cli_folder()
        if cli_f:
            st.session_state["folder_input"] = cli_f

    st.title("contact")

    folder = st.session_state.folder
    images = st.session_state.images
    tagged_images = [img for img in images if img.with_suffix(".xmp").exists()]

    available = {
        1: True,
        2: folder is not None,
        3: folder is not None,
        4: bool(tagged_images),
        5: True,
    }

    nav_cols = st.columns(len(_STEPS))
    for col, (step_num, step_name) in zip(nav_cols, _STEPS):
        with col:
            if st.button(
                step_name,
                key=f"nav_{step_num}",
                type="primary" if st.session_state.step == step_num else "secondary",
                disabled=not available[step_num],
                use_container_width=True,
            ):
                st.session_state.step = step_num
                st.rerun()

    st.divider()

    step = st.session_state.step
    if step == 1:
        _render_folder()
    elif step == 2:
        _render_roll()
    elif step == 3:
        _render_images()
    elif step == 4:
        _render_metadata()
    elif step == 5:
        _render_contact_sheet()


if __name__ == "__main__":
    main()
