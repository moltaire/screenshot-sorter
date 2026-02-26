# screenshot-sorter

Automatically renames and archives screenshots using a local vision model.

New screenshots land in an **inbox** folder. A scheduled job runs Ollama,
describes each image, renames it to `YYYY-MM-DD_brief-description.ext`,
moves it to your **archive**, and shuts Ollama back down. No cloud, no
manual sorting.

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

## Prerequisites

| Requirement | Notes |
|---|---|
| macOS | LaunchAgent scheduling is macOS-only |
| Python 3 | Ships with macOS; `python3 --version` to check |
| [Ollama](https://ollama.com) | Local model runner — installer can set this up |
| A vision model | Default: `llava:7b` (~4.7 GB). See model options below. |

---

## Install

Clone or download the repo, then run the installer:

```bash
git clone https://github.com/you/screenshot-sorter
cd screenshot-sorter
bash install.sh
```

The installer will:

1. Check for Python and Ollama (offer to install Ollama via Homebrew if missing)
2. Ask which vision model to use and pull it if not already present
3. Ask for your **inbox** and **archive** folder paths
4. Ask whether to keep originals after archiving
5. Ask for a schedule (daily or weekly, what time)
6. Generate and install a macOS LaunchAgent — no further action needed

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
| `--model` | `llava` | Any Ollama vision model |
| `--dry-run` | off | Preview renames without moving any files |
| `--keep-originals` | off | Copy to archive and move originals to `inbox/processed/` |

### `--dry-run`

Runs the full pipeline (starts Ollama, queries the model) but does not move
or rename anything. Useful for checking what names the model would produce
before committing.

```bash
python3 sort_screenshots.py \
  --incoming ~/Pictures/Screenshots/incoming \
  --archive  ~/Pictures/Screenshots \
  --dry-run
```

### `--keep-originals`

Copies each renamed file to the archive and moves the original (with its
original filename) to `inbox/processed/`. The originals are preserved but
won't be re-processed on the next run.

```bash
python3 sort_screenshots.py \
  --incoming ~/Pictures/Screenshots/incoming \
  --archive  ~/Pictures/Screenshots \
  --keep-originals
```

---

## How it works

- Dates are read from the filename (works with all macOS screenshot formats and
  iPhone screenshots). Falls back to file modification time for other images.
- Ollama is started only if not already running, and stopped when the job
  finishes — it won't interfere if you have it open for other reasons.
- If two files would get the same name, a counter suffix is appended
  (`_1`, `_2`, …).
- The LaunchAgent log lives next to your archive as `sorter.log`.

---

## Updating

```bash
git pull
bash install.sh   # re-run to apply any changes to the LaunchAgent
```

---

## Supported models

The installer prompts for a LLaVA variant when you choose the default model.
You can also pass any Ollama vision model via `--model`.

| Model | Size | Notes |
|---|---|---|
| `llava:7b` | ~4.7 GB | Default — fast, good for most screenshots |
| `llava:13b` | ~8.0 GB | Better descriptions, slower |
| `llava:34b` | ~20 GB | Best quality, needs ≥32 GB RAM |
| `llava-phi3` | ~2.9 GB | Lightweight alternative |
| `llama3.2-vision:11b` | ~8 GB | High quality non-LLaVA option |
| `moondream` | ~1.8 GB | Very fast but produces generic names |

Change model by re-running `install.sh` or editing the LaunchAgent plist at
`~/Library/LaunchAgents/com.screenshot-sorter.plist`.

---

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.screenshot-sorter.plist
rm ~/Library/LaunchAgents/com.screenshot-sorter.plist
```

Your inbox, archive, and screenshots are untouched.
