"""
Ενημέρωση της εφαρμογής από το GitHub.

Το GitHub Actions γράφει το build_info.py (repository, αριθμός build, έκδοση) και ανεβάζει κάθε νέο APK
ως «Release» με ετικέτα build-N. Η εφαρμογή ρωτά το δημόσιο API του GitHub αν υπάρχει νεότερο build.
Χρειάζεται δημόσιο repository (στα ιδιωτικά το GitHub δεν απαντά χωρίς λογαριασμό).
"""
import datetime
import json
import os
import re
import urllib.request

try:
    import build_info as _BI
except ImportError:                      # τοπική εκτέλεση, χωρίς GitHub Actions
    _BI = None

REPO = getattr(_BI, "REPO", "")
BUILD = int(getattr(_BI, "BUILD", 0) or 0)
VERSION = getattr(_BI, "VERSION", "")
STATE = None


def set_dir(path):
    global STATE
    STATE = os.path.join(path, "update.json")


def _load():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def _save(d):
    try:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    except Exception:  # noqa: BLE001
        pass


def version_text():
    if not REPO:
        return f"Έκδοση {VERSION or 'δοκιμαστική'} (χωρίς σύνδεση με GitHub)"
    return f"Έκδοση {VERSION} · build {BUILD}"


def due():
    """Αυτόματος έλεγχος το πολύ μία φορά την ημέρα."""
    return bool(REPO) and _load().get("last") != datetime.date.today().isoformat()


def _ctx():
    try:
        import ssl
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return None


def check(timeout=12):
    """None αν δεν υπάρχει νεότερη έκδοση, αλλιώς {'build','version','apk','page','notes'}.
    Σηκώνει εξαίρεση αν δεν υπάρχει σύνδεση ή repository."""
    if not REPO:
        raise RuntimeError("Η εφαρμογή δεν φτιάχτηκε από το GitHub Actions, οπότε δεν ξέρει πού να ψάξει.")
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"User-Agent": "app-updater", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        rel = json.loads(r.read().decode("utf-8"))
    st = _load()
    st["last"] = datetime.date.today().isoformat()
    _save(st)
    m = re.search(r"(\d+)$", rel.get("tag_name", ""))
    n = int(m.group(1)) if m else 0
    if n <= BUILD:
        return None
    apk = next((a.get("browser_download_url") for a in rel.get("assets", [])
                if a.get("name", "").endswith(".apk")), None)
    vm = re.search(r"v([\d.]+)", rel.get("name", "") or "")
    return {"build": n, "version": vm.group(1) if vm else "", "apk": apk, "page": rel.get("html_url"),
            "notes": (rel.get("body") or "")[:600]}
