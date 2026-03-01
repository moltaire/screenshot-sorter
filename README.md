# contact

AI-powered tagger for analog film scans. Set up a roll, point it at a folder of scans, and it generates descriptions, tags, and categories for each frame — writing XMP sidecars and a browsable HTML contact sheet.

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with a vision model pulled

```bash
ollama pull llama3.2-vision:11b
```

No other dependencies.

---

## Usage

```bash
# Set up a roll, then tag it
python3 contact.py --init ~/scans/tuscany/

# Tag without setting up first
python3 contact.py ~/scans/tuscany/

# Multiple rolls at once — pass several folders, or a parent folder
python3 contact.py --init ~/scans/2024/
python3 contact.py ~/scans/2024/

# Other flags
python3 contact.py ~/scans/tuscany/ --dry-run    # preview without writing
python3 contact.py ~/scans/tuscany/ --force      # re-tag already-tagged images
python3 contact.py ~/scans/tuscany/ --verbose    # show full AI output per frame
```

---

## Roll setup (`--init`)

An interactive prompt for roll-level metadata:

- **Film stock, camera** — pick from a numbered list of suggestions, or type your own
- **Lenses, locations, subjects** — toggle from previous entries, add new ones; multiple values allowed
- **Lab, lab instructions, date, notes** — free text
- **Label** *(optional)* — a short name for the roll used as the contact sheet title and folder suffix (e.g. `Oslo Summer 2024` → `2024-06_oslo-summer-2024`)

Everything is saved to a `roll.yaml` in the scan folder and used to label the XMP files and HTML index. Previous entries are remembered and suggested the next time.

---

## Output

**XMP sidecars** (one per image, written alongside the scan) contain the AI-generated description, tags, and category, plus roll metadata. Readable by Lightroom, darktable, Finder, and Spotlight.

**`index.html`** — a self-contained contact sheet with:
- Images at natural aspect ratio in a fluid masonry grid
- Roll metadata displayed as a compact monospace key/value block (date, film, camera, lens, location, lab); AI summary collapsible inline
- Full-text search across descriptions, tags, filenames, and categories (`/` or `Enter` to focus)
- Lightbox view with frame metadata; navigate with arrow keys or `j`/`k`
- Star any frame to pin it to the top

---

## How it works

Each frame goes through two stages:

1. A vision model describes what is physically visible in the image
2. A text model turns that description into a category, up to 12 tags, and a 2–3 sentence description

Roll metadata (gear, location, subjects) is kept out of the tagging stage to prevent the model from guessing at things it can't see. After all frames are processed, a short summary of the whole roll is generated and added to the HTML index.

---

## Options

| Flag | Description |
|---|---|
| `--init` | Run roll setup |
| `--model MODEL` | Vision model (default: `llama3.2-vision:11b`) |
| `--text-model MODEL` | Separate model for the synthesis stage |
| `--dry-run` | Preview without writing any files |
| `--force` | Re-tag images that already have a sidecar |
| `--verbose` | Print full AI output for each frame |
| `--no-rename-folder` | Skip renaming the folder after processing |
