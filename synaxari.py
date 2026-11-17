"""
Συναξάρι της ημέρας από το internet (προαιρετικό).

Πηγή 1: ελληνική Wikipedia, σελίδα της ημέρας (π.χ. «17 Νοεμβρίου»), ενότητα εορτών.
Μόνο ελληνικές πηγές. Χωρίς internet η εφαρμογή χρησιμοποιεί το ενσωματωμένο εορτολόγιο (saints_gr.py).
Χρησιμοποιείται το δημόσιο API της Wikipedia (δωρεάν, χωρίς λογαριασμό). Τα αποτελέσματα κρατιούνται στο κινητό,
οπότε μια ημέρα που φορτώθηκε μία φορά ανοίγει και χωρίς internet.
"""
import json
import os
import re
import urllib.parse
import urllib.request

MONTHS_GEN = ["Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου", "Ιουλίου", "Αυγούστου",
              "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου"]
UA = "Psaltiko/1.2 (Android; Orthodox calendar app)"
CACHE_DIR = None


def set_dir(path):
    global CACHE_DIR
    CACHE_DIR = os.path.join(path, "synaxari")
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except OSError:
        CACHE_DIR = None


def _ctx():
    try:
        import ssl
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return None


def _get_wikitext(host, title, timeout=12):
    q = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "format": "json",
                                "redirects": 1, "formatversion": 2})
    req = urllib.request.Request(f"https://{host}/w/api.php?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("parse") or {}).get("wikitext") or ""


# ------------------------------------------------------------------ καθάρισμα wikitext
def clean(t):
    t = re.sub(r"<ref[^>]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    for _ in range(3):                                         # εμφωλευμένα πρότυπα {{...}}
        t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:Αρχείο|Εικόνα|File|Image):[^\]]*\]\]", "", t, flags=re.I)
    t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\]", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("'''", "").replace("''", "").replace("&nbsp;", " ")
    t = re.sub(r"\s+", " ", t).strip(" *:#;-–")
    return t.strip()


def sections(wikitext):
    """[(τίτλος, επίπεδο, [γραμμές λίστας])]"""
    out = []
    cur = ("", 1, [])
    for line in wikitext.splitlines():
        m = re.match(r"^(=+)\s*(.*?)\s*\1\s*$", line)
        if m:
            out.append(cur)
            cur = (clean(m.group(2)), len(m.group(1)), [])
            continue
        if line.startswith("*") or line.startswith("#"):
            c = clean(line.lstrip("*#: "))
            if len(c) > 2:
                cur[2].append(c)
    out.append(cur)
    return out


def parse_el(wikitext):
    """Από την ελληνική σελίδα της ημέρας: η ενότητα «Εορτές» (και υποενότητές της)."""
    groups = []
    inside = 0
    for title, lvl, items in sections(wikitext):
        low = title.lower()
        if re.search(r"εορτ|άγι|αγι|μνήμ|εκκλησ", low):
            inside = lvl
            if items:
                groups.append(("Εορτές και μνήμες" if lvl == inside else title, items))
        elif inside and lvl > inside:
            if items:
                groups.append((title, items))
        else:
            inside = 0
    return groups


def page_url(m, d, lang="el"):
    return "https://el.wikipedia.org/wiki/" + urllib.parse.quote(f"{d} {MONTHS_GEN[m - 1]}".replace(" ", "_"))


def _cache_path(m, d):
    return os.path.join(CACHE_DIR, f"{m:02d}-{d:02d}.json") if CACHE_DIR else None


def cached(m, d):
    p = _cache_path(m, d)
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                c = json.load(fh)
            return c if c.get("lang") == "el" else None          # παλιά αγγλικά αποτελέσματα αγνοούνται
        except Exception:  # noqa: BLE001
            return None
    return None


def fetch(m, d, force=False):
    """{'groups': [(τίτλος, [άγιοι])], 'lang': 'el'|'en', 'url': ...} ή σηκώνει εξαίρεση αν δεν υπάρχει σύνδεση."""
    if not force:
        c = cached(m, d)
        if c:
            return c
    res = None
    err = None
    try:
        g = parse_el(_get_wikitext("el.wikipedia.org", f"{d} {MONTHS_GEN[m - 1]}"))
        if sum(len(i) for _, i in g) >= 1:
            res = {"groups": g, "lang": "el", "url": page_url(m, d, "el")}
    except Exception as e:  # noqa: BLE001
        err = e
    if res is None:
        raise err or LookupError("Δεν βρέθηκαν στοιχεία")
    p = _cache_path(m, d)
    if p:
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False)
        except OSError:
            pass
    return res
