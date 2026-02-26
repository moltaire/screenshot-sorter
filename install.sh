#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# screenshot-sorter installer
#
# Run once from the repo directory:
#   bash install.sh
#
# What it does:
#   1. Checks for Ollama and Tesseract; offers to install them via Homebrew.
#   2. Asks which vision model to use and pulls it if not already present.
#   3. Optionally asks for a separate text model for the synthesis step.
#   4. Asks where your screenshot inbox and archive folders are.
#   5. Asks for a schedule (daily or weekly).
#   6. Generates and installs a macOS LaunchAgent that runs the sorter
#      automatically on that schedule.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="$REPO_DIR/sort_screenshots.py"
PLIST_LABEL="com.screenshot-sorter"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
DEFAULT_MODEL="llama3.2-vision:11b"

# ── helpers ───────────────────────────────────────────────────────────────────

ask() {
    # ask PROMPT DEFAULT
    local prompt="$1" default="$2" answer
    read -r -p "$prompt [$default]: " answer
    echo "${answer:-$default}"
}

confirm() {
    # confirm PROMPT  → returns 0 for yes, 1 for no
    local answer
    read -r -p "$1 [Y/n]: " answer
    [[ "${answer:-Y}" =~ ^[Yy] ]]
}

separator() { echo; echo "────────────────────────────────────────"; echo; }

# ── header ────────────────────────────────────────────────────────────────────

echo
echo "  screenshot-sorter installer"
echo "  ────────────────────────────"
echo

# ── 1. Python ─────────────────────────────────────────────────────────────────

PYTHON=$(command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
    echo "✗ python3 not found. Please install Python 3 and re-run."
    exit 1
fi
echo "✓ Python: $PYTHON ($($PYTHON --version 2>&1))"

# ── 2. Ollama ─────────────────────────────────────────────────────────────────

if command -v ollama &>/dev/null; then
    echo "✓ Ollama: $(ollama --version 2>/dev/null | head -1)"
else
    echo "✗ Ollama not found."
    if confirm "  Install Ollama via Homebrew?"; then
        if ! command -v brew &>/dev/null; then
            echo "  Homebrew not found. Install it from https://brew.sh, then re-run."
            exit 1
        fi
        brew install ollama
        echo "✓ Ollama installed."
    else
        echo "  Skipping. You can install Ollama manually from https://ollama.com"
        echo "  Then re-run this installer."
        exit 0
    fi
fi

# ── 3. Tesseract ──────────────────────────────────────────────────────────────

OCR_ENABLED=true
if command -v tesseract &>/dev/null; then
    echo "✓ Tesseract: $(tesseract --version 2>&1 | head -1)"
    # Warn if the German language data is missing
    if ! tesseract --list-langs 2>/dev/null | grep -q "^deu$"; then
        echo "  ⚠ German language data not found."
        echo "  Run: brew install tesseract-lang   (or set TESSDATA_PREFIX manually)"
        echo "  OCR will fall back to English only until deu is available."
    fi
else
    echo "✗ Tesseract not found."
    if confirm "  Install Tesseract (+ language packs) via Homebrew?"; then
        if ! command -v brew &>/dev/null; then
            echo "  Homebrew not found. Install it from https://brew.sh, then re-run."
            exit 1
        fi
        brew install tesseract tesseract-lang
        echo "✓ Tesseract installed."
    else
        echo "  Skipping. OCR will be disabled (--no-ocr) in the LaunchAgent."
        OCR_ENABLED=false
    fi
fi

separator

# ── 4. Vision model ───────────────────────────────────────────────────────────

echo "Which vision model should describe screenshots?"
echo
echo "  1) llama3.2-vision:11b  ~8 GB  (default) — strong descriptions and text reading"
echo "  2) llava:7b              ~4.7 GB           — lighter alternative"
echo "  3) llava:13b             ~8.0 GB           — LLaVA at similar size"
echo "  4) llava-phi3            ~2.9 GB           — lightweight"
echo "  5) moondream             ~1.8 GB           — very fast, more generic names"
echo "  6) Enter a custom model name"
echo
read -r -p "  Choice [1]: " MODEL_CHOICE

case "${MODEL_CHOICE:-1}" in
    2) MODEL="llava:7b" ;;
    3) MODEL="llava:13b" ;;
    4) MODEL="llava-phi3" ;;
    5) MODEL="moondream" ;;
    6) MODEL=$(ask "  Model name" "$DEFAULT_MODEL") ;;
    *) MODEL="$DEFAULT_MODEL" ;;
esac
echo "  Vision model: $MODEL"

# Pull the vision model if not already available
if ollama list 2>/dev/null | grep -q "^${MODEL}"; then
    echo "✓ Model '$MODEL' already available."
else
    echo "  Model '$MODEL' not found locally."
    if confirm "  Pull '$MODEL' now? (may take a few minutes)"; then
        ollama pull "$MODEL"
        echo "✓ Model '$MODEL' ready."
    else
        echo "  Skipping pull. Run 'ollama pull $MODEL' before using the sorter."
    fi
fi

separator

# ── 5. Text model (optional) ──────────────────────────────────────────────────

echo "The vision model also handles slug synthesis by default."
echo "A smaller text-only model is faster and equally capable for this step."
echo
TEXT_MODEL=""
if confirm "  Use a separate text model for slug synthesis?"; then
    echo
    echo "  Suggested options:"
    echo "    1) llama3.2:3b   ~2 GB  — fast, good quality"
    echo "    2) mistral       ~4 GB  — reliable instruction follower"
    echo "    3) gemma3:4b     ~3 GB  — good alternative"
    echo "    4) Enter a custom model name"
    echo
    read -r -p "  Choice [1]: " TEXT_CHOICE
    case "${TEXT_CHOICE:-1}" in
        2) TEXT_MODEL="mistral" ;;
        3) TEXT_MODEL="gemma3:4b" ;;
        4) TEXT_MODEL=$(ask "  Text model name" "llama3.2:3b") ;;
        *) TEXT_MODEL="llama3.2:3b" ;;
    esac
    echo "  Text model: $TEXT_MODEL"

    if ollama list 2>/dev/null | grep -q "^${TEXT_MODEL}"; then
        echo "✓ Model '$TEXT_MODEL' already available."
    else
        echo "  Model '$TEXT_MODEL' not found locally."
        if confirm "  Pull '$TEXT_MODEL' now?"; then
            ollama pull "$TEXT_MODEL"
            echo "✓ Model '$TEXT_MODEL' ready."
        else
            echo "  Skipping pull. Run 'ollama pull $TEXT_MODEL' before using the sorter."
        fi
    fi
else
    echo "  Using '$MODEL' for synthesis as well."
fi

separator

# ── 6. Folders ────────────────────────────────────────────────────────────────

echo "Where should screenshots land before sorting (the inbox)?"
INBOX=$(ask "  Inbox folder" "$HOME/Pictures/Screenshots/inbox")
INBOX="${INBOX/#\~/$HOME}"   # expand ~ manually for reliability

echo
echo "Where should sorted screenshots be archived?"
ARCHIVE=$(ask "  Archive folder" "$HOME/Pictures/Screenshots")
ARCHIVE="${ARCHIVE/#\~/$HOME}"

mkdir -p "$INBOX" "$ARCHIVE"
echo
echo "✓ Inbox:   $INBOX"
echo "✓ Archive: $ARCHIVE"

echo
KEEP_ORIGINALS=false
if confirm "  Keep originals in $INBOX/processed/ after archiving?"; then
    KEEP_ORIGINALS=true
    echo "✓ Originals will be moved to $INBOX/processed/"
fi

separator

# ── 7. Schedule ───────────────────────────────────────────────────────────────

echo "How often should the sorter run?"
echo "  1) Daily"
echo "  2) Weekly (every Monday)"
read -r -p "  Choice [1]: " SCHED_CHOICE
SCHED_CHOICE="${SCHED_CHOICE:-1}"

HOUR=$(ask "  Run at hour (0–23, 24h)" "9")

if [[ "$SCHED_CHOICE" == "2" ]]; then
    SCHEDULE_XML="    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>"
    SCHEDULE_DESC="every Monday at ${HOUR}:00"
else
    SCHEDULE_XML="    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>"
    SCHEDULE_DESC="daily at ${HOUR}:00"
fi

separator

# ── 8. Generate and install the LaunchAgent plist ─────────────────────────────

LOG_FILE="$ARCHIVE/sorter.log"

mkdir -p "$HOME/Library/LaunchAgents"

# Build optional argument lines for the plist
PLIST_EXTRA_ARGS=""
if [[ -n "$TEXT_MODEL" ]]; then
    PLIST_EXTRA_ARGS="$PLIST_EXTRA_ARGS
        <string>--text-model</string>
        <string>$TEXT_MODEL</string>"
fi
if ! $OCR_ENABLED; then
    PLIST_EXTRA_ARGS="$PLIST_EXTRA_ARGS
        <string>--no-ocr</string>"
fi
if $KEEP_ORIGINALS; then
    PLIST_EXTRA_ARGS="$PLIST_EXTRA_ARGS
        <string>--keep-originals</string>"
fi

cat > "$PLIST_DST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

    <key>Label</key>
    <string>$PLIST_LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_PATH</string>
        <string>--inbox</string>
        <string>$INBOX</string>
        <string>--archive</string>
        <string>$ARCHIVE</string>
        <string>--model</string>
        <string>$MODEL</string>$PLIST_EXTRA_ARGS
    </array>

$SCHEDULE_XML

    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>

    <key>RunAtLoad</key>
    <false/>

</dict>
</plist>
EOF

# Reload (unload first in case it was already installed)
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✓ LaunchAgent installed  →  $PLIST_DST"
echo "  Schedule: $SCHEDULE_DESC"
echo "  Log:      $LOG_FILE"

separator

# ── 9. macOS screenshot save location reminder ────────────────────────────────

echo "One manual step: point macOS screenshots to your inbox."
echo
echo "  macOS 14+:  Settings → Keyboard → Keyboard Shortcuts → Screenshots"
echo "              (or open the Screenshot app → Options → Save to)"
echo "  Set 'Save to' →  $INBOX"
echo

separator

# ── 10. Summary and manual command ────────────────────────────────────────────

echo "Done! To run the sorter manually at any time:"
echo
MANUAL_CMD="  python3 \"$SCRIPT_PATH\" \\
    --inbox \"$INBOX\" \\
    --archive  \"$ARCHIVE\" \\
    --model    \"$MODEL\""
if [[ -n "$TEXT_MODEL" ]]; then
    MANUAL_CMD="$MANUAL_CMD \\
    --text-model \"$TEXT_MODEL\""
fi
if ! $OCR_ENABLED; then
    MANUAL_CMD="$MANUAL_CMD \\
    --no-ocr"
fi
if $KEEP_ORIGINALS; then
    MANUAL_CMD="$MANUAL_CMD \\
    --keep-originals"
fi
echo "$MANUAL_CMD"
echo
echo "Add --dry-run --verbose to preview renames and inspect each pipeline stage."
echo
