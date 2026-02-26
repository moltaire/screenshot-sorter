# screenshot-sorter

Automatically renames and archives screenshots using local AI models — no cloud,
no manual sorting.

New screenshots land in an **inbox** folder. A scheduled job describes each image,
extracts any text in it, synthesizes a concise name, renames the file to
`YYYY-MM-DD_brief-description.ext`, and moves it to your **archive**.

```
inbox/
  Screenshot 2026-02-26 at 10.19.30.png
  Screenshot 2026-02-24 at 09.05.11.png

          ↓  runs overnight  ↓

archive/
  2026-02-26_multi-panel-behavioral-results.png
  2026-02-24_concert-listing-berlin.png
```

---

## How it works

Each image goes through a three-stage pipeline:

1. **Vision model** (Ollama) — describes the visual content in 1–2 sentences,
   including any titles, labels, or axis names it can see
2. **OCR** (Tesseract) — independently extracts all text from the image; supports
   English and German out of the box
3. **Text LLM** (Ollama) — combines the visual description and extracted text into
   a concise 3–5 word hyphenated slug

Splitting the jobs this way makes each model do what it's best at: the vision
model interprets structure and context, Tesseract reliably lifts text it might
miss, and the language model synthesizes both into a clean filename.

Additional details:

- Dates are read from the filename (works with modern macOS, older macOS, and
  iPhone screenshot formats). Falls back to file modification time for other images.
- Ollama is started only if not already running, and stopped when the job
  finishes — it won't interfere if you already have it open for other reasons.
- If two files would get the same name, a counter suffix is appended (`_1`, `_2`, …).
- The LaunchAgent log lives next to your archive as `sorter.log`.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| macOS | LaunchAgent scheduling is macOS-only |
| Python 3 | Ships with macOS; `python3 --version` to check |
| [Ollama](https://ollama.com) | Local model runner — installer can set this up |
| A vision model | Default: `llama3.2-vision:11b` (~8 GB). See model options below. |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | OCR engine — installer can set this up |

---

## Install

Clone or download the repo, then run the installer:

```bash
git clone https://github.com/you/screenshot-sorter
cd screenshot-sorter
bash install.sh
```

The installer will:

1. Check for Python, Ollama, and Tesseract (offer to install missing tools via Homebrew)
2. Ask which vision model to use and pull it if not already present
3. Optionally configure a separate, lighter text model for the synthesis step
4. Ask for your **inbox** and **archive** folder paths
5. Ask whether to keep originals after archiving
6. Ask for a schedule (daily or weekly, what time)
7. Generate and install a macOS LaunchAgent — no further action needed

After install, point macOS to save screenshots to your inbox:
**macOS Settings → Keyboard Shortcuts → Screenshots → Save to → [your inbox]**
(or open the Screenshot app → Options → Save to)

---

## Manual usage

```bash
python3 sort_screenshots.py \
  --incoming /path/to/inbox \
  --archive  /path/to/archive
```

Optional flags:

| Flag | Default | Description |
|---|---|---|
| `--model` | `llama3.2-vision:11b` | Ollama vision model |
| `--text-model` | same as `--model` | Separate Ollama text model for slug synthesis |
| `--no-ocr` | off | Skip Tesseract OCR |
| `--dry-run` | off | Preview renames without moving any files |
| `--keep-originals` | off | Copy to archive and move originals to `inbox/processed/` |
| `--verbose` | off | Print vision description, OCR output, and slug for each image |

### `--dry-run`

Runs the full pipeline (starts Ollama, queries the model, runs OCR) but does not
move or rename anything. Useful for checking what names the model would produce
before committing.

```bash
python3 sort_screenshots.py \
  --incoming ~/Pictures/Screenshots/incoming \
  --archive  ~/Pictures/Screenshots \
  --dry-run
```

### `--verbose`

Prints the intermediate output of each pipeline stage. Pair with `--dry-run` to
inspect and tune behaviour without touching any files.

```bash
python3 sort_screenshots.py \
  --incoming ~/Pictures/Screenshots/incoming \
  --archive  ~/Pictures/Screenshots \
  --dry-run --verbose
```

Output example:
```
  Screenshot 2026-02-26 at 10.19.30.png
    [vision] A bar chart titled "Reaction Times by Condition" with four groups on the x-axis.
    [ocr]    Reaction Times by Condition ms Control Low High Very High p < 0.001
    [slug]   bar-chart-reaction-times
  → 2026-02-26_bar-chart-reaction-times.png  [dry-run, not moved]
```

### `--text-model`

By default the same model handles all three stages. If you want a faster, lighter
model for the synthesis step:

```bash
python3 sort_screenshots.py \
  --incoming ~/Pictures/Screenshots/incoming \
  --archive  ~/Pictures/Screenshots \
  --model llama3.2-vision:11b \
  --text-model llama3.2:3b
```

### `--keep-originals`

Copies each renamed file to the archive and moves the original (with its original
filename) to `inbox/processed/`. The originals are preserved but won't be
re-processed on the next run.

---

## Supported models

### Vision models

| Model | Size | Notes |
|---|---|---|
| `llama3.2-vision:11b` | ~8 GB | **Default** — strong visual understanding and text reading |
| `llava:7b` | ~4.7 GB | Lighter alternative |
| `llava:13b` | ~8.0 GB | LLaVA at similar size to the default |
| `llava-phi3` | ~2.9 GB | Lightweight, weaker descriptions |
| `moondream` | ~1.8 GB | Very fast but produces generic names |

### Text models (for slug synthesis)

By default the vision model also handles synthesis. If you specify `--text-model`,
any Ollama text model works. Smaller models are plenty capable for this task:

| Model | Size | Notes |
|---|---|---|
| `llama3.2:3b` | ~2 GB | Fast, good quality |
| `mistral` | ~4 GB | Reliable instruction follower |
| `gemma3:4b` | ~3 GB | Good alternative |

Change model by re-running `install.sh` or editing the LaunchAgent plist at
`~/Library/LaunchAgents/com.screenshot-sorter.plist`.

---

## Updating

```bash
git pull
bash install.sh   # re-run to apply any changes to the LaunchAgent
```

---

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.screenshot-sorter.plist
rm ~/Library/LaunchAgents/com.screenshot-sorter.plist
```

Your inbox, archive, and screenshots are untouched.
