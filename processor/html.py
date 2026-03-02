"""
processor/html.py
─────────────────
HTML contact sheet generation.
"""

from pathlib import Path

from .roll import load_roll_yaml, _split_list_field
from .sidecar import _xe


def write_roll_html(folder: Path, pairs: list, roll: dict) -> None:
    """pairs: [(image_path, meta), ...]. Reloads roll.yaml to pick up generated summary."""
    full_roll = load_roll_yaml(folder)

    _LIST_FM_FIELDS = {"location", "lens", "subjects"}

    roll_label = full_roll.get("label", "")
    location = full_roll.get("location", "")
    locs = _split_list_field(location)
    first_loc = locs[0] if locs else ""
    if roll_label:
        title = roll_label
    else:
        title_parts = [p for p in [first_loc, full_roll.get("date", "")] if p]
        title = " — ".join(title_parts) if title_parts else folder.name

    # Frontmatter: terminal key/value block (Option B)
    _DOT = ' <span class="fm-sep">\u00b7</span> '

    def _fm_join(key):
        v = full_roll.get(key, "")
        if not v:
            return ""
        items = _split_list_field(v) if key in _LIST_FM_FIELDS else [v]
        return _DOT.join(_xe(i) for i in items)

    lab_parts = [p for p in [full_roll.get("lab", ""), full_roll.get("lab_notes", "")] if p]
    lab_val = _DOT.join(_xe(p) for p in lab_parts)

    fm_rows_data = [
        ("DATE",  _xe(full_roll.get("date",   ""))),
        ("FILM",  _xe(full_roll.get("film",   ""))),
        ("CAM",   _xe(full_roll.get("camera", ""))),
        ("LENS",  _fm_join("lens")),
        ("LOC",   _fm_join("location")),
        ("SUBJ",  _fm_join("subjects")),
        ("LAB",   lab_val),
        ("NOTES", _xe(full_roll.get("notes",  ""))),
    ]
    fm_rows_html = "".join(
        f'<div class="fm-row"><span class="fm-key">{k}</span>'
        f'<span class="fm-val">{v}</span></div>'
        for k, v in fm_rows_data if v
    )
    summary = full_roll.get("summary", "")
    if summary and fm_rows_html:
        fm_rows_html += (
            '<div class="fm-row fm-summ-row">'
            '<span class="fm-key fm-summ-key">+</span>'
            f'<span class="fm-summ-val" style="display:none">'
            f'<span class="fm-summ-label">AI summary</span>  {_xe(summary)}'
            '</span>'
            '</div>'
        )
    frontmatter_html = f'<div class="fm-strip">{fm_rows_html}</div>' if fm_rows_html else ""

    cards = []
    for img_path, meta in pairs:
        tags_str = ", ".join(meta.get("tags", []))
        search_data = " ".join([
            img_path.name,
            meta.get("description", ""),
            meta.get("category", ""),
            tags_str,
        ]).lower()
        cards.append(
            f'<div class="card" data-search="{_xe(search_data)}" data-img="{_xe(img_path.name)}"'
            f' data-category="{_xe(meta.get("category", ""))}"'
            f' data-description="{_xe(meta.get("description", ""))}"'
            f' data-tags="{_xe(tags_str)}">'
            f'<button class="star-btn" aria-label="Star">&#9734;</button>'
            f'<img src="{_xe(img_path.name)}" alt="" loading="lazy">'
            f'<div class="card-body">'
            f'<div class="fname">{_xe(img_path.name)}</div>'
            f'</div></div>'
        )

    css = """\
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; background: #f0f0f0; color: #1a1a1a; padding: 2rem 1.5rem; }
.header { margin-bottom: 1.5rem; }
.header-top { margin-bottom: .5rem; }
h1 { font-size: 1.4rem; font-weight: 600; }
.fm-strip { font-family: ui-monospace, 'SF Mono', monospace; font-size: .76rem; line-height: 1.8; margin-bottom: .6rem; }
.fm-row { display: flex; gap: 0; }
.fm-key { color: #bbb; min-width: 5ch; margin-right: 1.5ch; flex-shrink: 0; }
.fm-val { color: #444; }
.fm-sep { color: #ccc; margin: 0 .3em; }
#search { width: 100%; display: block; padding: .4rem .7rem; font-size: .85rem; border: 1px solid #ccc; border-radius: 4px; background: #fff; color: #1a1a1a; margin-bottom: .75rem; }
#search:focus { outline: none; border-color: #888; }
.fm-summ-key { cursor: pointer; }
.fm-summ-key:hover { color: #555; }
.fm-summ-val { color: #555; }
.fm-summ-label { color: #bbb; margin-right: .4em; }
.no-results { font-size: .85rem; color: #999; padding: .5rem 0 1rem; display: none; }
.starred-section { margin-bottom: .25rem; }
.starred-label { font-size: .68rem; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: #ccc; margin-bottom: .5rem; }
.section-rule { border: none; border-top: 1px solid #e4e4e4; margin: .25rem 0 1rem; }
.grid { columns: 300px; column-gap: 1rem; }
.card { background: #fff; border-radius: 6px; overflow: hidden; position: relative; break-inside: avoid; margin-bottom: 1rem; }
.card img { width: 100%; height: auto; display: block; background: #ddd; cursor: zoom-in; }
.card-body { padding: .5rem .75rem .6rem; }
.fname { font-family: monospace; font-size: .68rem; color: #bbb; }
.star-btn { position: absolute; top: .5rem; right: .5rem; background: rgba(0,0,0,.4); border: none; border-radius: 50%; width: 28px; height: 28px; font-size: .95rem; line-height: 28px; text-align: center; cursor: pointer; color: #fff; opacity: 0; transition: opacity .15s; z-index: 1; }
.card:hover .star-btn, .card.starred .star-btn { opacity: 1; }
.card.starred .star-btn { color: #f0b429; }
#lightbox { display: none; position: fixed; inset: 0; z-index: 1000; flex-direction: column; }
#lightbox.open { display: flex; }
#lb-bg { position: absolute; inset: 0; background: rgba(0,0,0,.92); }
#lb-close { position: absolute; top: 1rem; right: 1rem; background: rgba(255,255,255,.15); border: none; color: #fff; font-size: 1.4rem; width: 36px; height: 36px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 2; }
#lb-main { position: relative; flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 1rem 4rem; }
#lb-img { position: relative; max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 2px; z-index: 1; }
#lb-prev, #lb-next { position: fixed; top: 50%; transform: translateY(-50%); background: rgba(255,255,255,.12); border: none; color: #fff; font-size: 2.2rem; width: 52px; height: 72px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 2; }
#lb-prev { left: .5rem; }
#lb-next { right: .5rem; }
#lb-prev:hover, #lb-next:hover, #lb-close:hover { background: rgba(255,255,255,.25); }
#lb-info { position: relative; z-index: 1; background: rgba(0,0,0,.65); border-top: 1px solid rgba(255,255,255,.07); padding: .6rem 1.5rem; display: flex; flex-direction: column; gap: .35rem; }
.lb-top { display: flex; align-items: center; gap: .75rem; }
#lb-star { background: none; border: none; color: #666; font-size: 1rem; cursor: pointer; padding: 0; line-height: 1; }
#lb-star:hover { color: #f0b429; }
#lb-star.on { color: #f0b429; }
#lb-fname { font-family: monospace; font-size: .72rem; color: #666; }
#lb-cat { font-size: .63rem; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: #555; background: rgba(255,255,255,.08); padding: 1px 7px; border-radius: 99px; }
#lb-desc { font-size: .83rem; line-height: 1.5; color: #aaa; }
#lb-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.lb-tag { font-size: .67rem; background: rgba(255,255,255,.08); color: #888; padding: 2px 7px; border-radius: 3px; }
"""

    js = """\
<script>
(function(){
  // ── Search ──────────────────────────────────────────────────────────────────
  var searchEl = document.getElementById('search');
  searchEl.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { searchEl.value = ''; searchEl.dispatchEvent(new Event('input')); searchEl.blur(); }
  });
  var cards = Array.from(document.querySelectorAll('.card'));
  var starredGrid = document.getElementById('starred-grid');
  var mainGrid = document.getElementById('main-grid');
  var starredSection = document.getElementById('starred-section');
  var noRes = document.getElementById('no-results');
  searchEl.addEventListener('input', function(){
    var q = searchEl.value.toLowerCase();
    var visible = 0;
    cards.forEach(function(c){
      var show = !q || c.dataset.search.indexOf(q) !== -1;
      c.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    noRes.style.display = (q && visible === 0) ? 'block' : 'none';
  });

  // ── Stars / pinning ─────────────────────────────────────────────────────────
  var STAR_KEY = 'film-stars:' + window.location.pathname;
  var starred = JSON.parse(localStorage.getItem(STAR_KEY) || '[]');
  function applyStars() {
    cards.forEach(function(card) {
      var on = starred.indexOf(card.dataset.img) !== -1;
      card.classList.toggle('starred', on);
      card.querySelector('.star-btn').innerHTML = on ? '&#9733;' : '&#9734;';
      (on ? starredGrid : mainGrid).appendChild(card);
    });
    starredSection.style.display = starredGrid.children.length ? '' : 'none';
    // Sync lightbox star button
    var lbStarEl = document.getElementById('lb-star');
    if (lbStarEl && lbCard) {
      var on = starred.indexOf(lbCard.dataset.img) !== -1;
      lbStarEl.innerHTML = on ? '&#9733;' : '&#9734;';
      lbStarEl.classList.toggle('on', on);
    }
  }
  applyStars();
  document.querySelectorAll('.star-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      toggleStar(btn.closest('.card').dataset.img);
    });
  });
  function toggleStar(imgName) {
    var i = starred.indexOf(imgName);
    if (i === -1) starred.push(imgName); else starred.splice(i, 1);
    localStorage.setItem(STAR_KEY, JSON.stringify(starred));
    applyStars();
  }

  // ── Lightbox ─────────────────────────────────────────────────────────────────
  var lb = document.getElementById('lightbox');
  var lbImg = document.getElementById('lb-img');
  var lbCard = null;
  function showLbCard(card) {
    lbCard = card;
    lbImg.src = card.querySelector('img').src;
    var on = starred.indexOf(card.dataset.img) !== -1;
    var lbStarEl = document.getElementById('lb-star');
    lbStarEl.innerHTML = on ? '&#9733;' : '&#9734;';
    lbStarEl.classList.toggle('on', on);
    document.getElementById('lb-fname').textContent = card.dataset.img;
    document.getElementById('lb-cat').textContent = card.dataset.category;
    document.getElementById('lb-desc').textContent = card.dataset.description;
    var tagsEl = document.getElementById('lb-tags');
    tagsEl.innerHTML = '';
    (card.dataset.tags || '').split(',').forEach(function(t) {
      t = t.trim();
      if (!t) return;
      var s = document.createElement('span');
      s.className = 'lb-tag';
      s.textContent = t;
      tagsEl.appendChild(s);
    });
  }
  function openLb(card) {
    showLbCard(card);
    lb.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function closeLb() { lb.classList.remove('open'); lbImg.src = ''; document.body.style.overflow = ''; }
  function navLb(d) {
    var vc = cards.filter(function(c){ return c.style.display !== 'none'; });
    var idx = vc.indexOf(lbCard);
    if (idx === -1) idx = 0;
    showLbCard(vc[(idx + d + vc.length) % vc.length]);
  }
  cards.forEach(function(card) {
    card.querySelector('img').addEventListener('click', function() { openLb(card); });
  });
  document.getElementById('lb-bg').addEventListener('click', closeLb);
  document.getElementById('lb-close').addEventListener('click', closeLb);
  document.getElementById('lb-prev').addEventListener('click', function(){ navLb(-1); });
  document.getElementById('lb-next').addEventListener('click', function(){ navLb(1); });
  document.getElementById('lb-star').addEventListener('click', function(){ if (lbCard) toggleStar(lbCard.dataset.img); });

  // ── Global keyboard ─────────────────────────────────────────────────────────
  document.addEventListener('keydown', function(e) {
    if (lb.classList.contains('open')) {
      if (e.key === 'ArrowLeft' || e.key === 'k') { e.preventDefault(); navLb(-1); }
      if (e.key === 'ArrowRight' || e.key === 'j') { e.preventDefault(); navLb(1); }
      if (e.key === 's' && lbCard) toggleStar(lbCard.dataset.img);
      if (e.key === 'Escape') closeLb();
      return;
    }
    if (e.key === 'Escape' && document.activeElement === searchEl) { searchEl.blur(); return; }
    if ((e.key === 'Enter' || e.key === '/') && document.activeElement !== searchEl) { e.preventDefault(); searchEl.focus(); }
  });

  // ── Summary toggle ───────────────────────────────────────────────────────────
  var summKey = document.querySelector('.fm-summ-key');
  if (summKey) {
    summKey.addEventListener('click', function() {
      var val = this.parentElement.querySelector('.fm-summ-val');
      var open = val.style.display !== 'none';
      val.style.display = open ? 'none' : '';
      this.textContent = open ? '+' : '-';
    });
  }
})();
</script>"""

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_xe(title)}</title>\n"
        f"<style>\n{css}\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="header">\n'
        '<div class="header-top">\n'
        f'<h1>{_xe(title)}</h1>\n'
        '</div>\n'
        f"{frontmatter_html}\n"
        '<input type="search" id="search" placeholder="Search frames\u2026" autocomplete="off">\n'
        "</div>\n"
        '<div id="no-results" class="no-results">No frames match.</div>\n'
        '<div id="starred-section" class="starred-section" style="display:none">'
        '<div class="starred-label">Starred</div>'
        '<div id="starred-grid" class="grid"></div>'
        '<hr class="section-rule">'
        '</div>'
        '<div id="main-grid" class="grid">\n'
        + "".join(cards)
        + "\n</div>\n"
        '<div id="lightbox">'
        '<div id="lb-bg"></div>'
        '<button id="lb-close">&#215;</button>'
        '<div id="lb-main">'
        '<button id="lb-prev">&#8249;</button>'
        '<img id="lb-img" alt="">'
        '<button id="lb-next">&#8250;</button>'
        '</div>'
        '<div id="lb-info">'
        '<div class="lb-top"><button id="lb-star">&#9734;</button><span id="lb-fname"></span><span id="lb-cat"></span></div>'
        '<p id="lb-desc"></p>'
        '<div id="lb-tags"></div>'
        '</div>'
        '</div>\n'
        + js
        + "\n</body>\n</html>"
    )

    out = folder / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"  → index.html")
