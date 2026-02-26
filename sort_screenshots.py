#!/usr/bin/env python3
"""
sort_screenshots.py
───────────────────
Scans an inbox folder for images and renames each one to YYYY-MM-DD_brief-description.ext
using a three-stage pipeline:

  1. Vision model (Ollama)  — describes image content
  2. Tesseract OCR          — extracts any text in the image
  3. Text LLM (Ollama)      — synthesizes both into a concise slug

Starts Ollama if it isn't already running, and stops it again when done
(unless it was already running before the script started).

Usage:
    python3 sort_screenshots.py --inbox /path/to/inbox --archive /path/to/archive
    python3 sort_screenshots.py --inbox /path/to/inbox --archive /path/to/archive --model llama3.2-vision:11b
    python3 sort_screenshots.py --inbox /path/to/inbox --archive /path/to/archive --text-model mistral
    python3 sort_screenshots.py --inbox /path/to/inbox --archive /path/to/archive --dry-run --verbose
    python3 sort_screenshots.py --inbox /path/to/inbox --archive /path/to/archive --no-ocr
"""

import argparse
import base64
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
OLLAMA_BASE = "http://localhost:11434"


# ── Ollama helpers ────────────────────────────────────────────────────────────


def ollama_ready() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def wait_for_ollama(timeout: int = 30) -> bool:
    for _ in range(timeout):
        if ollama_ready():
            return True
        time.sleep(1)
    return False


# ── Prompts ───────────────────────────────────────────────────────────────────

VISION_SYSTEM = (
    "You are an image analysis assistant. "
    "Describe what you see concisely and factually."
)

VISION_PROMPT = (
    "Describe the main content of this image in 1-2 sentences. "
    "Include any visible titles, labels, axis names, or prominent text you can read. "
    "Be specific. Do not start with 'The image shows' — just describe directly."
)

SYNTHESIS_SYSTEM = (
    "You are a file-naming assistant. "
    "You only ever output a single hyphenated slug of 3-5 lowercase words. "
    "Never explain, never describe your reasoning, never repeat instructions."
)

SYNTHESIS_PROMPT_TMPL = """\
Create a 3-5 word hyphenated filename slug for a screenshot.

Visual description: {visual}
Text found in image (OCR): {ocr}

Rules:
- Use specific content from titles, labels, or key terms when available
- Never use generic words like "screenshot", "image", "figure", or "file"
- Output only the slug, nothing else

Examples: flowchart-data-pipeline, python-error-traceback, eeg-frequency-spectrum,
dictator-game-stimulus, github-pull-request-diff, bar-chart-reaction-times

Slug:"""

# Fallback: ask the vision model directly for a slug (bypasses synthesis step)
FALLBACK_SYSTEM = (
    "You are a file-naming assistant. "
    "You only ever output a single hyphenated slug of 3-5 lowercase words. "
    "Never explain, never describe your reasoning, never repeat instructions."
)

FALLBACK_PROMPT = "3-5 word slug for this image. Only output the slug. Slug:"


# ── Ollama API calls ──────────────────────────────────────────────────────────


def _call_vision(b64: str, model: str, prompt: str, system: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "system": system,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["response"].strip()


def _call_text(model: str, prompt: str, system: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "system": system,
            "prompt": prompt,
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["response"].strip()


# ── OCR ───────────────────────────────────────────────────────────────────────


def extract_text_ocr(path: Path) -> str:
    """Extract text from an image using Tesseract (eng+deu). Returns '' if unavailable."""
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "eng+deu", "--psm", "11"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            # Collapse runs of whitespace; discard near-empty results
            text = " ".join(result.stdout.split())
            return text if len(text) > 3 else ""
        return ""
    except FileNotFoundError:
        return ""  # tesseract not installed
    except subprocess.TimeoutExpired:
        return ""


# ── Slug helpers ──────────────────────────────────────────────────────────────

_BAD_PREFIXES = (
    "the-image",
    "this-image",
    "the-photo",
    "the-picture",
    "the-following",
    "screenshot",
    "scientific-figures",
    "i-",
    "here-is",
    "sure-",
    "slug-",
)
_BAD_WORDS = {"slug", "hyphenated", "caption"}
_FILLERS = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "and",
    "or",
    "with",
    "from",
    "by",
}


def _to_slug(raw: str) -> str:
    """Sanitise raw model output to a clean hyphenated slug."""
    first_line = raw.splitlines()[0]
    slug = re.sub(r"[^a-z0-9]+", "-", first_line.lower()).strip("-")
    words = [w for w in slug.split("-") if w and w not in _FILLERS]
    slug = "-".join(words)
    if len(slug) > 60:
        slug = slug[:61].rsplit("-", 1)[0]
    return slug


def _looks_bad(slug: str) -> bool:
    """Return True if the slug looks like a prompt echo or verbose sentence."""
    words = set(slug.split("-"))
    return (
        not slug
        or any(slug.startswith(p) for p in _BAD_PREFIXES)
        or slug.count("-") > 7
        or bool(words & _BAD_WORDS)
    )


# ── Main pipeline ─────────────────────────────────────────────────────────────


def describe_image(
    path: Path,
    vision_model: str,
    text_model: str,
    use_ocr: bool,
    verbose: bool,
) -> str:
    """Three-stage pipeline: vision description + OCR → text LLM → slug."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    # Stage 1: vision description
    visual_desc = _call_vision(b64, vision_model, VISION_PROMPT, VISION_SYSTEM)
    if verbose:
        print(f"    [vision] {visual_desc}")

    # Stage 2: OCR
    ocr_text = ""
    if use_ocr:
        ocr_text = extract_text_ocr(path)
        if verbose:
            if ocr_text:
                preview = ocr_text[:120] + ("…" if len(ocr_text) > 120 else "")
                print(f"    [ocr]    {preview}")
            else:
                print("    [ocr]    (nothing extracted)")

    # Stage 3: synthesize into slug
    synthesis_prompt = SYNTHESIS_PROMPT_TMPL.format(
        visual=visual_desc or "(no description)",
        ocr=ocr_text or "(none)",
    )
    raw_slug = _call_text(text_model, synthesis_prompt, SYNTHESIS_SYSTEM)
    slug = _to_slug(raw_slug)
    if verbose:
        print(f"    [slug]   {slug}")

    if _looks_bad(slug):
        # Fallback: ask vision model directly for a slug
        if verbose:
            print("    [slug]   looks bad, retrying with fallback…")
        raw_slug = _call_vision(b64, vision_model, FALLBACK_PROMPT, FALLBACK_SYSTEM)
        slug = _to_slug(raw_slug)
        if verbose:
            print(f"    [slug]   {slug} (fallback)")

    return slug or "untitled"


# ── Filename helpers ──────────────────────────────────────────────────────────


def extract_date(path: Path) -> str:
    """
    Pull YYYY-MM-DD from a macOS screenshot filename if present,
    otherwise fall back to the file's modification time.

    Handles:
      Screenshot 2026-02-26 at 10.19.30.png   (modern macOS)
      Screenshot 2013-11-04 11.24.07.png       (older macOS)
      SCR-20220213-x0u.png                     (iPhone/iPad)
    """
    name = path.name
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1)
    m = re.search(r"SCR-(\d{4})(\d{2})(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def unique_dest(archive: Path, stem: str, suffix: str) -> Path:
    """Return a destination path that doesn't collide with existing files."""
    dest = archive / f"{stem}{suffix}"
    n = 1
    while dest.exists():
        dest = archive / f"{stem}_{n}{suffix}"
        n += 1
    return dest


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Rename and archive screenshots using a local vision model."
    )
    parser.add_argument(
        "--inbox",
        required=True,
        metavar="DIR",
        help="Folder where new screenshots land (inbox).",
    )
    parser.add_argument(
        "--archive",
        required=True,
        metavar="DIR",
        help="Folder where renamed screenshots are stored.",
    )
    parser.add_argument(
        "--model",
        default="llama3.2-vision:11b",
        metavar="MODEL",
        help="Ollama vision model (default: llama3.2-vision:11b).",
    )
    parser.add_argument(
        "--text-model",
        default=None,
        metavar="MODEL",
        help="Ollama text model for slug synthesis (default: same as --model).",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Skip Tesseract OCR (useful if tesseract is not installed).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving any files.",
    )
    parser.add_argument(
        "--keep-originals",
        action="store_true",
        help="Keep originals in inbox/processed/ instead of removing them.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print vision description, OCR output, and slug for each image.",
    )
    args = parser.parse_args()

    vision_model = args.model
    text_model = args.text_model or args.model
    use_ocr = not args.no_ocr

    inbox = Path(args.inbox).expanduser().resolve()
    archive = Path(args.archive).expanduser().resolve()
    processed = inbox / "processed"

    if not args.dry_run:
        archive.mkdir(parents=True, exist_ok=True)
        inbox.mkdir(parents=True, exist_ok=True)
        if args.keep_originals:
            processed.mkdir(parents=True, exist_ok=True)

    images = sorted(
        f for f in inbox.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )

    if not images:
        print("Nothing to process.")
        return

    if args.dry_run:
        print("[dry-run] No files will be moved.\n")

    print(f"Vision model : {vision_model}")
    print(f"Text model   : {text_model}")
    print(f"OCR          : {'enabled (eng+deu)' if use_ocr else 'disabled'}")
    print()

    already_running = ollama_ready()
    ollama_proc = None
    if not already_running:
        print("Starting Ollama…")
        ollama_proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for_ollama():
            print("Error: Ollama failed to start.")
            ollama_proc.terminate()
            return

    try:
        print(f"Processing {len(images)} image(s)…\n")
        for img in images:
            print(f"  {img.name}")
            try:
                date = extract_date(img)
                slug = describe_image(
                    img, vision_model, text_model, use_ocr, args.verbose
                )
                dest = unique_dest(archive, f"{date}_{slug}", img.suffix.lower())
                if args.dry_run:
                    print(f"  → {dest.name}  [dry-run, not moved]\n")
                elif args.keep_originals:
                    shutil.copy2(img, dest)
                    img.rename(processed / img.name)
                    print(f"  → {dest.name}  (original kept in processed/)\n")
                else:
                    img.rename(dest)
                    print(f"  → {dest.name}\n")
            except Exception as e:
                print(f"  ✗ error: {e}\n")
    finally:
        if ollama_proc:
            print("Stopping Ollama…")
            ollama_proc.terminate()
            ollama_proc.wait()


if __name__ == "__main__":
    main()
