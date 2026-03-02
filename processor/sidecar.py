"""
processor/sidecar.py
────────────────────
XMP sidecar read/write and image loading helpers.
No internal imports — stdlib only.
"""

import base64
import json
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _load_image_b64(path: Path, max_pixels: int = 1500) -> str:
    """Return base64-encoded image, downscaled via macOS sips to speed up inference."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        result = subprocess.run(
            ["sips", "-Z", str(max_pixels), "-s", "format", "jpeg", str(path), "--out", str(tmp_path)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and tmp_path.stat().st_size > 0:
            data = tmp_path.read_bytes()
            tmp_path.unlink(missing_ok=True)
            return base64.b64encode(data).decode()
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _xe(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _xe_decode(s: str) -> str:
    return (
        s.replace("&quot;", '"')
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
    )


def write_xmp(image_path: Path, meta: dict, roll: dict) -> Path:
    tags_xml = "\n".join(
        f"      <rdf:li>{_xe(t)}</rdf:li>" for t in meta.get("tags", [])
    )

    def field(tag: str, value: str) -> str:
        return f"      <{tag}>{_xe(value)}</{tag}>\n" if value else ""

    xmp = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description rdf:about=""\n'
        '      xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '      xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '      xmlns:Iptc4xmpCore="http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/"\n'
        '      xmlns:film="http://ns.contact.local/1.0/">\n'
        + field("dc:description", meta.get("description", ""))
        + "      <dc:subject>\n"
        + "        <rdf:Bag>\n"
        + tags_xml + "\n"
        + "        </rdf:Bag>\n"
        + "      </dc:subject>\n"
        + field("xmp:CreateDate", roll.get("date", ""))
        + field("Iptc4xmpCore:Location", roll.get("location", ""))
        + field("film:stock", roll.get("film", ""))
        + field("film:camera", roll.get("camera", ""))
        + field("film:lens", roll.get("lens", ""))
        + field("film:notes", roll.get("notes", ""))
        + field("film:category", meta.get("category", "other"))
        + field("film:visionRaw", meta.get("vision_raw", ""))
        + field("film:processedAt", datetime.now(timezone.utc).isoformat())
        + '    </rdf:Description>\n'
        + '  </rdf:RDF>\n'
        + '</x:xmpmeta>\n'
        + '<?xpacket end="w"?>'
    )

    xmp_path = image_path.with_suffix(".xmp")
    xmp_path.write_text(xmp, encoding="utf-8")
    return xmp_path


def _read_xmp_meta(xmp_path: Path) -> dict:
    """Extract description, tags, and category from an XMP sidecar we wrote."""
    try:
        content = xmp_path.read_text(encoding="utf-8")
    except Exception:
        return {"description": "", "category": "other", "tags": []}
    desc_m = re.search(r"<dc:description>(.*?)</dc:description>", content, re.DOTALL)
    cat_m  = re.search(r"<film:category>([^<]*)</film:category>", content)
    tags   = re.findall(r"<rdf:li>([^<]+)</rdf:li>", content)
    return {
        "description": _xe_decode(desc_m.group(1).strip()) if desc_m else "",
        "category":    cat_m.group(1).strip() if cat_m else "other",
        "tags":        [_xe_decode(t) for t in tags],
    }
