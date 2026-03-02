"""
processor/tagger.py
───────────────────
Ollama API helpers, prompts, per-frame analysis, and roll summary generation.
"""

import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .roll import _split_list_field, GENERATED_MARKER
from .sidecar import _load_image_b64

# ── Constants ─────────────────────────────────────────────────────────────────

OLLAMA_BASE = "http://localhost:11434"
VALID_CATEGORIES = {
    "landscape", "portrait", "street", "architecture",
    "nature", "abstract", "other",
}
SYNTHESIS_KEYS = {"CATEGORY", "TAGS", "DESCRIPTION"}

# ── Prompts ───────────────────────────────────────────────────────────────────

VISION_SYSTEM = (
    "You are an image analysis assistant. "
    "Describe what you see accurately and in detail."
)

VISION_PROMPT = (
    "Describe the content of this photograph: subject, composition, lighting, and setting. "
    "Be specific and concrete. Describe only what is visually present — "
    "do not infer mood, atmosphere, or emotional tone. "
    "Do not start with 'The image shows' — just describe directly."
)

VISION_PROMPT_FALLBACK = (
    "In one or two sentences, name the main subject and setting of this photograph. "
    "Be brief and concrete."
)

SYNTHESIS_SYSTEM = (
    "You are a metadata assistant for analog film photography. "
    "You output exactly three lines in KEY: VALUE format and nothing else."
)

SYNTHESIS_PROMPT_TMPL = """\
Output exactly these three lines — nothing else:

CATEGORY: <exactly one of: landscape, portrait, street, architecture, nature, abstract, other>
TAGS: <up to 12 comma-separated descriptive keywords>
DESCRIPTION: <2-3 sentences describing what is in the scene>

{vision_section}

Rules:
- CATEGORY: portrait means the face of a person is clearly visible and is the primary subject — \
a figure seen from behind, at a distance, or without a visible face is NOT a portrait; \
landscape = outdoor scenery or countryside where no person dominates; \
street = candid scene in a public urban setting with people or activity; \
architecture = a building or structure is the main subject; \
nature = plants, animals, or natural setting without human structures; \
abstract = pattern or texture is the subject with no recognisable scene; \
other = anything not covered above
- TAGS must be extracted directly from the visual description — do not add any subject, \
person, animal, or object that is not explicitly mentioned in the visual description; \
if you are unsure whether something is present, omit it; \
list visible physical subjects first (people by generic type only: man, woman, child, group — \
never proper names; then other objects and setting); \
only then add lighting qualities — only if clearly visible, using these definitions: \
'natural light' (daylight is the apparent source), \
'window light' (a window is the light source), \
'golden hour' (warm orange or yellow low-angle sunlight is visible — not just any outdoor light), \
'bokeh' (background is visibly blurred), \
'high contrast' (extreme difference between light and shadow areas)
- DESCRIPTION: describe only subjects and details present in the visual description above — \
do not introduce people, animals, or objects not mentioned there; \
factual; no "The image shows" phrasing; \
do not mention film, grain, or equipment; \
refer to people generically (a man, a woman, two people) — do not use proper names; \
do not describe mood, atmosphere, or emotional tone — avoid words like peaceful, serene, \
calm, relaxed, cozy, warm, tranquil, joyful, melancholic, intimate"""

ROLL_SUMMARY_SYSTEM = "You are a photography archivist. Write concise, factual roll summaries."

ROLL_SUMMARY_PROMPT_TMPL = """\
Roll metadata:
  Location: {location}
  Subjects: {subjects}
  Date: {date}

Frame descriptions:
{descriptions}

Write 2-3 sentences summarising this roll as a whole. \
You may reference subject names from the roll metadata as general context for the roll \
(e.g. "a roll with Felix and Bea"), but do not attribute specific actions, poses, or \
positions to named individuals — you cannot identify who is in which frame; \
describe people in individual frames generically (a man, a woman, the group). \
Anchor the location to the roll metadata — do not infer or add location details not stated there. \
Describe only what is directly stated in the frame descriptions — do not speculate. \
Do not describe mood, atmosphere, or emotional qualities. \
Do not mention film, camera, equipment, or technical qualities."""

# Three escalating attempts: full prompt → short fallback → very short fallback
_VISION_ATTEMPTS = [
    (VISION_PROMPT,          {"num_predict": 300, "repeat_penalty": 1.3}),
    (VISION_PROMPT_FALLBACK, {"num_predict": 100, "repeat_penalty": 1.5}),
    (VISION_PROMPT_FALLBACK, {"num_predict":  60, "repeat_penalty": 1.8}),
]
_SYNTH_OPTS = {"num_predict": 200, "repeat_penalty": 1.1}

_PERSON_TERMS = {
    "man", "woman", "child", "boy", "girl", "person", "people",
    "couple", "group", "baby", "infant", "toddler", "teenager",
}

_PERSON_PLURALS = {
    "man": "men", "woman": "women", "child": "children", "person": "people",
}

_VISION_OPENER = re.compile(
    r"^(the (main subject|photograph|image|photo)( of this (photograph|image|photo))?"
    r"( (shows?|depicts?|captures?|is ))?"
    r"|this (image|photograph|photo) (shows?|depicts?|is ))",
    re.I,
)

# ── Ollama helpers ─────────────────────────────────────────────────────────────


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


def _call_vision(b64: str, model: str, prompt: str, system: str, options: dict | None = None) -> str:
    body: dict = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
    }
    if options:
        body["options"] = options
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["response"].strip()


def _call_text(model: str, prompt: str, system: str, options: dict | None = None) -> str:
    body: dict = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
    }
    if options:
        body["options"] = options
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["response"].strip()


# ── Repetition guard ──────────────────────────────────────────────────────────


def _is_repetitive(text: str) -> bool:
    # Degenerate symbol runs (soft hyphens, em dashes, ellipses)
    for sym, limit in [("—", 15), ("…", 8), (" .. ", 6), ("\xad", 10)]:
        if text.count(sym) > limit:
            return True

    # Sentence-level repetition: any sentence appearing 3+ times
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n', text) if len(s.strip()) > 20]
    if sentences:
        sc: dict[str, int] = {}
        for s in sentences:
            sc[s] = sc.get(s, 0) + 1
        if max(sc.values()) >= 3:
            return True

    # 4-gram repetition: repeated phrases
    words = text.split()
    if len(words) >= 12:
        ngrams = [" ".join(words[i:i+4]) for i in range(len(words) - 3)]
        nc: dict[str, int] = {}
        for ng in ngrams:
            nc[ng] = nc.get(ng, 0) + 1
        if max(nc.values()) >= 3:
            return True

    # Word-level frequency (original check)
    clean = [w.strip(",.;:!?\"'()[]") for w in words]
    clean = [w for w in clean if w]
    if len(clean) < 6:
        return False
    wc: dict[str, int] = {}
    for w in clean:
        wc[w] = wc.get(w, 0) + 1
    return max(wc.values()) / len(clean) >= 0.35


# ── Synthesis parser ──────────────────────────────────────────────────────────


def parse_synthesis(text: str) -> dict:
    result: dict = {}
    for line in text.strip().splitlines():
        key, sep, value = line.partition(":")
        k = key.strip().upper()
        if sep and k in SYNTHESIS_KEYS:
            result[k.lower()] = value.strip()

    tags_raw = result.get("tags", "")
    seen: set = set()
    tags: list = []
    for t in tags_raw.split(","):
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t)
            tags.append(t)
    result["tags"] = tags

    if result.get("category", "") not in VALID_CATEGORIES:
        result["category"] = "other"

    return result


def _person_forms(term: str) -> set:
    return {term, term + "s", _PERSON_PLURALS.get(term, term + "s")}


def _has_person(text: str) -> bool:
    t = text.lower()
    return any(
        re.search(r"\b" + re.escape(f) + r"\b", t)
        for term in _PERSON_TERMS
        for f in _person_forms(term)
    )


def _drop_phantom_people(tags: list, vision: str) -> list:
    """Remove person-type tags not supported by a word-boundary match in the vision text."""
    vision_lower = vision.lower()
    result = []
    for tag in tags:
        if tag not in _PERSON_TERMS:
            result.append(tag)
            continue
        if any(re.search(r"\b" + re.escape(f) + r"\b", vision_lower) for f in _person_forms(tag)):
            result.append(tag)
    return result


def _vision_as_desc(vision: str) -> str:
    """Strip common opener phrases from a vision description for use as a fallback."""
    text = _VISION_OPENER.sub("", vision).strip()
    return text[0].upper() + text[1:] if text else vision


def _fix_phantom_desc(description: str, vision: str) -> str:
    """Remove sentences that introduce person terms absent from the vision description.

    If vision already mentions any person, the synthesis description is trusted as-is.
    If vision has no people, any sentence mentioning a person is a phantom and is dropped.
    Falls back to a cleaned vision description if all sentences were phantom.
    """
    if not description or _has_person(vision):
        return description
    sentences = re.split(r"(?<=[.!?])\s+", description.strip())
    clean = [s for s in sentences if not _has_person(s)]
    return " ".join(clean) if clean else _vision_as_desc(vision)


# ── Main pipeline ─────────────────────────────────────────────────────────────


def analyze_image(
    path: Path,
    vision_model: str,
    text_model: str,
    roll: dict,
    verbose: bool,
) -> dict:
    b64 = _load_image_b64(path)

    visual_desc = None
    for attempt, (v_prompt, v_opts) in enumerate(_VISION_ATTEMPTS, 1):
        try:
            result = _call_vision(b64, vision_model, v_prompt, VISION_SYSTEM, v_opts)
        except Exception as e:
            raise RuntimeError(f"vision stage failed (attempt {attempt}): {e}") from e
        if not _is_repetitive(result):
            if attempt > 1:
                print(f"    [vision] succeeded on attempt {attempt}")
            visual_desc = result
            break
        if attempt < len(_VISION_ATTEMPTS):
            print(f"    [vision] loop on attempt {attempt} — retrying")

    if visual_desc is None:
        print("    [vision] all attempts looped — skipping")
        return {
            "category": "other",
            "tags": [],
            "description": "",
            "vision_raw": "(vision model produced repetitive output — skipped)",
        }

    if verbose:
        print(f"    [vision] {visual_desc}")

    synthesis_prompt = SYNTHESIS_PROMPT_TMPL.format(
        vision_section=f"Visual description: {visual_desc}",
    )

    try:
        raw_synthesis = _call_text(text_model, synthesis_prompt, SYNTHESIS_SYSTEM, _SYNTH_OPTS)
    except Exception as e:
        raise RuntimeError(f"synthesis stage failed: {e}") from e

    meta = parse_synthesis(raw_synthesis)
    meta["tags"]        = _drop_phantom_people(meta.get("tags", []), visual_desc)
    meta["description"] = _fix_phantom_desc(meta.get("description", ""), visual_desc)

    if verbose:
        print(f"    [category]    {meta.get('category', '?')}")
        print(f"    [tags]        {', '.join(meta.get('tags', []))}")
        print(f"    [description] {meta.get('description', '')}")

    return {
        "category": meta.get("category", "other"),
        "tags": meta.get("tags", []),
        "description": meta.get("description", ""),
        "vision_raw": visual_desc,
    }


# ── Roll summary ──────────────────────────────────────────────────────────────


def _generate_roll_prose(all_meta: list, roll: dict, text_model: str) -> str:
    descs = [
        m["description"] for m in all_meta
        if m.get("description") and not m.get("vision_raw", "").startswith("(vision")
    ]
    if not descs:
        return ""
    prompt = ROLL_SUMMARY_PROMPT_TMPL.format(
        location=", ".join(_split_list_field(roll.get("location", ""))) or "not specified",
        subjects=", ".join(_split_list_field(roll.get("subjects", ""))) or "not specified",
        date=roll.get("date", "not specified"),
        descriptions="\n".join(f"- {d}" for d in descs[:20]),
    )
    try:
        return _call_text(text_model, prompt, ROLL_SUMMARY_SYSTEM, {"num_predict": 150, "repeat_penalty": 1.1})
    except Exception:
        return ""


def write_roll_summary(
    folder: Path, all_meta: list, roll: dict, vision_model: str, text_model: str
) -> None:
    cat_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    for m in all_meta:
        cat = m.get("category", "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for t in m.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1

    categories_str = ", ".join(
        f"{cat}: {n}" for cat, n in sorted(cat_counts.items(), key=lambda x: -x[1])
    )
    top_tags_str = ", ".join(
        t for t, _ in sorted(tag_counts.items(), key=lambda x: -x[1])[:12]
    )

    print("Generating roll summary…")
    prose = _generate_roll_prose(all_meta, roll, text_model)

    path = folder / "roll.yaml"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    idx = content.find(GENERATED_MARKER)
    base = content[:idx].rstrip() + "\n" if idx != -1 else content

    model_line = (
        f'model:      "{vision_model}"\n' if vision_model == text_model
        else f'vision_model: "{vision_model}"\ntext_model:   "{text_model}"\n'
    )
    generated = (
        f"\n{GENERATED_MARKER} ─────────────────────────────────────────────────\n"
        f'processed:  "{datetime.now().strftime("%Y-%m-%d")}"\n'
        + model_line
        + f'frames:     "{len(all_meta)}"\n'
        f'categories: "{categories_str}"\n'
        f'top_tags:   "{top_tags_str}"\n'
    )
    if prose:
        generated += f'summary:    "{prose.replace(chr(34), chr(39))}"\n'

    path.write_text(base + generated, encoding="utf-8")
    print(f"  → roll.yaml updated\n")
