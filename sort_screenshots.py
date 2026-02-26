#!/usr/bin/env python3
"""
sort_screenshots.py
───────────────────
Scans an inbox folder for images, asks a local vision model (via Ollama) to
describe each one, renames it to YYYY-MM-DD_brief-description.ext, and moves
it to an archive folder.

Starts Ollama if it isn't already running, and stops it again when done
(unless it was already running before the script started).

Usage:
    python3 sort_screenshots.py --incoming /path/to/inbox --archive /path/to/archive
    python3 sort_screenshots.py --incoming /path/to/inbox --archive /path/to/archive --model llava
    python3 sort_screenshots.py --incoming /path/to/inbox --archive /path/to/archive --dry-run
    python3 sort_screenshots.py --incoming /path/to/inbox --archive /path/to/archive --keep-originals
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


SYSTEM_PROMPT = (
    "You are a file-naming assistant. "
    "You only ever output a single hyphenated slug of 3-5 lowercase words. "
    "Never explain, never describe your reasoning, never repeat instructions."
)

MAIN_PROMPT = (
    "Output a 3-5 word hyphenated slug describing the main content of this image.\n"
    "If the image contains a caption, title, or label, use that text as the primary "
    "basis for the slug — it usually describes the content better than visual inference.\n"
    "Only describe what you can clearly see. Do not guess or infer content that is not visible.\n\n"
    "Examples:\n"
    "  flowchart-data-pipeline\n"
    "  bar-chart-reaction-times\n"
    "  github-pull-request-diff\n"
    "  python-error-traceback\n"
    "  eeg-frequency-spectrum\n"
    "  dictator-game-stimulus\n\n"
    "Slug:"
)

FALLBACK_PROMPT = "3-5 word slug for this image. Only output the slug. Slug:"

# Slugs that indicate the model described the prompt rather than the image
_BAD_PREFIXES = (
    "the-image", "this-image", "the-photo", "the-picture",
    "the-following", "screenshot", "scientific-figures",
    "i-", "here-is", "sure-", "slug-",
)
# Individual words that indicate prompt echo regardless of position
_BAD_WORDS = {"slug", "hyphenated", "caption"}

# Filler words stripped before truncating so meaningful words aren't crowded out
_FILLERS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "with", "from", "by"}


def _call_ollama(b64: str, model: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "system": SYSTEM_PROMPT,
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
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read())["response"].strip()


def _to_slug(raw: str) -> str:
    """Sanitise raw model output to a clean hyphenated slug."""
    # Keep only the first line (model sometimes adds explanation after a newline)
    first_line = raw.splitlines()[0]
    slug = re.sub(r"[^a-z0-9]+", "-", first_line.lower()).strip("-")
    # Strip filler words so meaningful words aren't crowded out by the char limit
    words = [w for w in slug.split("-") if w and w not in _FILLERS]
    slug = "-".join(words)
    # Trim to 60 chars without cutting a word in half
    if len(slug) > 60:
        slug = slug[:61].rsplit("-", 1)[0]
    return slug


def _looks_bad(slug: str) -> bool:
    """Return True if the slug looks like a prompt echo or verbose sentence."""
    words = set(slug.split("-"))
    return (
        not slug
        or any(slug.startswith(p) for p in _BAD_PREFIXES)
        or slug.count("-") > 7  # more than 8 words → probably a sentence
        or bool(words & _BAD_WORDS)
    )


def describe_image(path: Path, model: str) -> str:
    """Ask the vision model for a short slug description of the image."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    slug = _to_slug(_call_ollama(b64, model, MAIN_PROMPT))

    if _looks_bad(slug):
        # One retry with a stripped-down prompt
        slug = _to_slug(_call_ollama(b64, model, FALLBACK_PROMPT))

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
        "--incoming",
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
        default="llava",
        metavar="MODEL",
        help="Ollama vision model to use (default: llava).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving any files.",
    )
    parser.add_argument(
        "--keep-originals",
        action="store_true",
        help=(
            "Keep original files in an incoming/processed/ subfolder "
            "instead of removing them after archiving."
        ),
    )
    args = parser.parse_args()

    incoming = Path(args.incoming).expanduser().resolve()
    archive = Path(args.archive).expanduser().resolve()
    processed = incoming / "processed"

    if not args.dry_run:
        archive.mkdir(parents=True, exist_ok=True)
        incoming.mkdir(parents=True, exist_ok=True)
        if args.keep_originals:
            processed.mkdir(parents=True, exist_ok=True)

    images = sorted(
        f for f in incoming.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )

    if not images:
        print("Nothing to process.")
        return

    if args.dry_run:
        print("[dry-run] No files will be moved.\n")

    # Start Ollama only if it isn't already running
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
        print(f"Processing {len(images)} image(s) with {args.model}…\n")
        for img in images:
            print(f"  {img.name}")
            try:
                date = extract_date(img)
                slug = describe_image(img, args.model)
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
