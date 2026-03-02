# 🎞️ contact

<img src="docs/contact.png" width="100%" alt="contact screenshot">

contact is a tool to tag and archive analog film scans using locally running AI. Set up a roll, point it at a folder of scans, and it generates descriptions, tags, and categories for each frame, writing XMP sidecar files and creating a [browsable HTML contact sheet](https://moltaire.github.io/contact).

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with a vision model pulled

```bash
ollama pull llama3.2-vision:11b
```

---

## Install

```bash
uv tool install .
```

This installs two commands: `contact` (CLI) and `contact-ui` (Streamlit app).

---

## Streamlit UI

```bash
contact-ui
# or with a folder pre-loaded:
contact-ui --folder ~/scans/tuscany/
```

A guided 4-step flow:

1. **Select Folder** — type or browse to a folder of scans
2. **Roll Info** — describe the roll: film stock, camera, lens, date, location, lab
3. **Frame Analysis** — AI-tag images; select which ones to process, choose models
4. **Review & Edit** — inspect and correct the AI-generated metadata frame by frame.

After review, the **contact** sheet is generated.

---

## CLI

```bash
# Set up a roll interactively, then tag it
contact --init ~/scans/tuscany/

# Tag without setup
contact ~/scans/tuscany/

# Multiple rolls — pass several folders or a parent folder
contact --init ~/scans/2024/
contact ~/scans/2024/

# Common flags
contact ~/scans/tuscany/ --dry-run    # preview without writing
contact ~/scans/tuscany/ --force      # re-tag already-tagged images
contact ~/scans/tuscany/ --verbose    # show full AI output per frame
```

### Options

| Flag | Description |
|---|---|
| `--init` | Run interactive roll setup |
| `--model MODEL` | Vision model (default: `llama3.2-vision:11b`) |
| `--text-model MODEL` | Separate model for the synthesis stage |
| `--dry-run` | Preview without writing any files |
| `--force` | Re-tag images that already have a sidecar |
| `--verbose` | Print full AI output for each frame |
| `--no-rename-folder` | Skip renaming the folder after processing |

---

## Roll setup

Roll-level metadata is saved to `roll.yaml` in the scan folder:

- **Film stock, camera** — pick from suggestions or type your own
- **Lenses, locations, subjects** — multiple values allowed; previous entries are suggested
- **Lab, lab notes, date, notes** — free text
- **Label** — short name used as the contact sheet title (e.g. `Oslo Summer 2024`)

History is remembered across sessions in `~/.config/contact/history.json`.

---

## Output

**XMP sidecars** (one per image) contain the AI-generated description, tags, and category, plus roll metadata. Readable by Lightroom, darktable, Finder, and Spotlight.

**`index.html`** — a self-contained contact sheet with:
- Image overview and lightbox
- Roll metadata
- Full-text search across descriptions, tags, filenames, and categories (`/` or `Enter` to focus)
- Star frames to pin them to the top

---

## How it works

Each frame goes through two stages:

1. A vision model describes what is physically visible in the image
2. A text model turns that into a category, up to 12 tags, and a 2–3 sentence description

After all frames are processed, a short summary of the whole roll is written to the HTML index.

## Try it out

A sample roll is included at `docs/example/sample-roll/`. It has pre-tagged images, XMP sidecars, and a rendered `index.html`. See a live version [here](https://moltaire.github.io/contact). Or run the UI on it yourself:

```bash
# Open the contact sheet directly
open docs/example/sample-roll/index.html

# Or load it in the UI (read-only — no Ollama needed to browse)
contact-ui --folder docs/example/sample-roll/
```

To re-process it from scratch:

```bash
contact docs/example/sample-roll/ --force
```

---

## Limitations

The AI model runs locally, which I prefer for privacy, bandwidth and cost. But the smaller model also comes with limitations. Sometimes descriptions and tags are off. You can use the UI version to review and edit metadata, or just roll with the AI errors. If you have a computer with lots of RAM, feel free to load a bigger vision model and/or a separate text model for text synthesis.
