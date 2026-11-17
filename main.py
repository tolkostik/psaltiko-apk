"""
Ψαλτικό ημερολόγιο – ήχος της εβδομάδας, Εωθινό, εορτές, νηστεία, Τριώδιο/Πεντηκοστάριο.
Λειτουργεί χωρίς internet. Ανοίγει τον Ισοκράτη στον ήχο της ημέρας.
"""
import datetime
import os
import re
import threading
import time
import webbrowser

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import NoTransition, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.stacklayout import StackLayout
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

import church as CH
import fasting_cal as FC
import menaion as MN
import saints_gr as SG
import synaxari as SX
import updater as UP
import ui_widgets as UW

IS_ANDROID = platform == "android"
TABS = ("home", "cal", "feasts", "fasts", "tones")
TITLES = {"home": "Ψαλτικό ημερολόγιο", "cal": "Ημερολόγιο", "feasts": "Εορτές & ονόματα", "fasts": "Ημερολόγιο νηστειών",
          "tones": "Οι 8 ήχοι",
          "day": "Ημέρα"}
RED = (0.75, 0.1, 0.12, 1)
GOLD = (0.78, 0.55, 0.16, 1)
DATA_DIR = None

KV = """
#:import dp kivy.metrics.dp

<NavItem>:
    orientation: 'vertical'
    padding: 0, dp(6)
    spacing: dp(2)

<Root>:
    orientation: 'vertical'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        size_hint_y: None
        height: dp(58)
        padding: dp(8), dp(6)
        spacing: dp(6)
        canvas.before:
            Color:
                rgba: 1, 1, 1, 1
            Rectangle:
                pos: self.pos
                size: self.size
                texture: app.grad
        Button:
            text: '<'
            bold: True
            font_size: '24sp'
            size_hint_x: None
            width: dp(46) if app.can_back else 0
            opacity: 1 if app.can_back else 0
            disabled: not app.can_back
            background_normal: ''
            background_color: 1, 1, 1, 0.15
            on_release: app.back()
        Label:
            text: app.title_text
            bold: True
            font_size: '20sp'
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
    ScreenManager:
        id: sm
    BoxLayout:
        id: nav
        size_hint_y: None
        height: dp(64)
        canvas.before:
            Color:
                rgba: app.c_card
            Rectangle:
                pos: self.pos
                size: self.size
            Color:
                rgba: app.c_line
            Rectangle:
                pos: self.x, self.top - dp(1)
                size: self.width, dp(1)
"""


class NavItem(ButtonBehavior, BoxLayout):
    pass


class Root(BoxLayout):
    pass


class Tap(ButtonBehavior, BoxLayout):
    pass


# ------------------------------------------------------------------ προστασία από κλεισίματα
from kivy.base import ExceptionHandler, ExceptionManager  # noqa: E402


class _Guard(ExceptionHandler):
    def handle_exception(self, inst):
        try:
            import traceback
            if DATA_DIR:
                with open(os.path.join(DATA_DIR, "errors.log"), "a", encoding="utf-8") as fh:
                    fh.write(time.strftime("%d/%m %H:%M ") + "".join(
                        traceback.format_exception(type(inst), inst, inst.__traceback__))[-1500:] + "\n")
        except Exception:  # noqa: BLE001
            pass
        return ExceptionManager.PASS


ExceptionManager.add_handler(_Guard())


def esc(t):
    return str(t).replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")


def hx(rgba):
    return UW.hexc(rgba)


_GENERIC = {"αγιοσ", "αγια", "αγιοι", "αγιεσ", "οσιοσ", "οσια", "οσιοι", "αποστ", "προφη", "μαρτυ", "ιερομ",
            "επισκ", "αρχιε", "πατρι", "μεγαλ", "οσιομ", "συναξ", "ανακο", "μνημη", "των", "του", "της", "και"}


def _fold(t):
    import unicodedata
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn").replace("ς", "σ")


def _stems(t):
    return {w[:5] for w in re.findall(r"[α-ω]+", _fold(t)) if len(w) > 3 and w[:5] not in _GENERIC}


def day_saints(info):
    """[(όνομα, σημείωση, μεγάλη)]: οι μεγάλες εορτές του Μηναίου + όλες οι μνήμες του εορτολογίου, χωρίς διπλά."""
    d = info["date"]
    out = [x for x in info["fixed"] if x[2]]
    seen = [_stems(n) for n, _, _ in out] + [_stems(n) for n, _ in info["movable"]]

    def dup(name):
        st = _stems(name)
        return any(st & o for o in seen)
    for n in SG.saints(d.month, d.day):
        if not dup(n):
            out.append((n, "", False))
            seen.append(_stems(n))
    for n, s_, g in info["fixed"]:
        if not g and not dup(n):
            out.append((n, s_, False))
            seen.append(_stems(n))
    return out


def is_great(info):
    k = (info["date"] - CH.easter(info["date"].year)).days
    return k in CH.GREAT_FEASTS or any(g for _, _, g in info["fixed"])


class PsaltikoApp(App):
    title = "Psaltiko"
    c_bg = ListProperty([0.965, 0.945, 0.91, 1])
    c_card = ListProperty([1, 0.995, 0.985, 1])
    c_line = ListProperty([0.88, 0.9, 0.93, 1])
    grad = ObjectProperty(None, allownone=True)
    can_back = BooleanProperty(False)
    title_text = StringProperty("Ψαλτικό ημερολόγιο")

    # ================================================================== εκκίνηση
    def build(self):
        global DATA_DIR
        DATA_DIR = self.user_data_dir
        SX.set_dir(DATA_DIR)
        UP.set_dir(DATA_DIR)
        self.update_info = None
        self.cal_mode = "grid"
        self.fast_year = datetime.date.today().year
        self._sx_token = 0
        self.c_bg, self.c_card, self.c_line = list(UW.C["bg"]), list(UW.C["card"]), list(UW.C["line"])
        Window.clearcolor = UW.C["bg"]
        self.grad = UW.gradient(UW.PRIMARY, UW.PRIMARY2)
        Builder.load_string(KV)
        self.root_w = Root()
        self.sm = self.root_w.ids.sm
        self.sm.transition = NoTransition()
        self.pages = {}
        for name in TITLES:
            scr = Screen(name=name)
            sv = ScrollView(do_scroll_x=False, bar_width=dp(4))
            box = BoxLayout(orientation="vertical", size_hint_y=None, padding=(dp(12), dp(12)), spacing=dp(12))
            box.bind(minimum_height=box.setter("height"))
            sv.add_widget(box)
            scr.add_widget(sv)
            self.sm.add_widget(scr)
            self.pages[name] = (sv, box)
        self.nav_items = {}
        for key, icon, label in (("home", "cross", "Σήμερα"), ("cal", "calendar", "Ημερολόγιο"),
                                 ("feasts", "list", "Εορτές"), ("fasts", "fish", "Νηστείες"),
                                 ("tones", "music", "Ήχοι")):
            it = NavItem()
            ic = UW.Icon(kind=icon, size_hint_y=None, height=dp(26))
            lb = Label(text=label, font_size=sp(12), size_hint_y=None, height=dp(18))
            it.add_widget(ic)
            it.add_widget(lb)
            it.icon, it.lab = ic, lb
            it.bind(on_release=lambda w, k=key: self.tab(k))
            self.root_w.ids.nav.add_widget(it)
            self.nav_items[key] = it
        today = datetime.date.today()
        self.day = today
        self.month = (today.year, today.month)
        self.detail = today
        self.stack = []
        self.last_query = ""
        Window.bind(on_keyboard=self._key)
        self.tab("home")
        if UP.due():
            Clock.schedule_once(lambda dt: self.check_update(silent=True), 3)
        return self.root_w

    def on_pause(self):
        return True

    def on_resume(self):
        # αν άλλαξε η μέρα όσο ήταν στο παρασκήνιο
        if self.sm.current == "home":
            self.day = datetime.date.today()
            self.build_home()

    # ================================================================== πλοήγηση
    def page(self, name):
        sv, box = self.pages[name]
        box.clear_widgets()
        sv.scroll_y = 1
        return box

    def show(self, name, push=True):
        if push and self.sm.current != name:
            self.stack.append(self.sm.current)
        self.sm.current = name
        self.title_text = TITLES.get(name, "Ψαλτικό ημερολόγιο")
        self.can_back = name not in TABS
        tab = name if name in TABS else (self.stack[0] if self.stack and self.stack[0] in TABS else "home")
        for k, it in self.nav_items.items():
            on = k == tab
            col = UW.PRIMARY if on else UW.C["muted"]
            it.icon.rgba = list(col)
            it.lab.color = col
            it.lab.bold = on

    def tab(self, name):
        self.stack = []
        if name == "home":
            self.day = datetime.date.today()
        getattr(self, "build_" + name)()
        self.show(name, push=False)

    def back(self):
        if not self.stack:
            return False
        prev = self.stack.pop()
        if prev in TABS:
            getattr(self, "build_" + prev)()
        self.show(prev, push=False)
        return True

    def _key(self, win, key, *a):
        if key == 27:
            return self.back()
        return False

    def animate_in(self, box, limit=10):
        kids = list(reversed(box.children))[:limit]
        for i, w in enumerate(kids):
            w.opacity = 0
            Clock.schedule_once(lambda dt, ww=w: Animation(opacity=1, d=0.25, t="out_quad").start(ww), 0.03 + i * 0.04)

    # ================================================================== κοινά στοιχεία
    def card(self, box, pad=14):
        c = UW.CardBox(pad=pad)
        box.add_widget(c)
        return c

    def btn(self, parent, text, cb, color=None, fg=(1, 1, 1, 1), h=50):
        b = Button(text=text, bold=True, size_hint_y=None, height=dp(h), background_normal="",
                   background_color=color or UW.PRIMARY, color=fg, font_size=sp(15))
        b.bind(on_release=lambda *a: cb())
        parent.add_widget(b)
        return b

    def ghost(self, parent, text, cb, h=46):
        return self.btn(parent, text, cb, color=UW.C["line"], fg=UW.C["ink"], h=h)

    def head(self, parent, title, icon=None):
        row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
        if icon:
            row.add_widget(UW.Icon(kind=icon, rgba=list(UW.PRIMARY), size_hint=(None, None), size=(dp(22), dp(22)),
                                   pos_hint={"center_y": 0.5}))
        lb = Label(text=f"[b]{title}[/b]", markup=True, color=UW.PRIMARY, font_size=sp(16), halign="left",
                   valign="middle")
        lb.bind(size=lambda w, s: setattr(w, "text_size", s))
        row.add_widget(lb)
        parent.add_widget(row)

    def chips(self, parent, items):
        st = StackLayout(size_hint_y=None, spacing=dp(6))
        st.bind(minimum_height=st.setter("height"))
        for t, col in items:
            st.add_widget(UW.Chip(t, col))
        parent.add_widget(st)
        return st

    def hero(self, box):
        h = BoxLayout(orientation="vertical", size_hint_y=None, padding=(dp(16), dp(14)), spacing=dp(4))
        h.bind(minimum_height=h.setter("height"))

        def bg(*a):
            h.canvas.before.clear()
            with h.canvas.before:
                Color(1, 1, 1, 1)
                RoundedRectangle(pos=h.pos, size=h.size, radius=[dp(18)], texture=self.grad)
        h.bind(pos=bg, size=bg)
        box.add_widget(h)
        return h

    def message(self, box, text):
        c = self.card(box, 12)
        c.add_widget(UW.text(text, color=UW.C["muted"]))

    # ================================================================== Ισοκράτης
    def open_isokratis(self, tone):
        if not tone:
            return self.toast("Δεν υπάρχει ήχος εβδομάδας αυτή την ημέρα")
        if not IS_ANDROID:
            return self.toast(f"Θα άνοιγε ο Ισοκράτης: {CH.ISOKRATIS_MODE[tone]}")
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            i = Intent(Intent.ACTION_VIEW, Uri.parse(f"isokratis://mode?n={tone}"))
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            act.startActivity(i)
        except Exception:  # noqa: BLE001
            self.toast("Ο Ισοκράτης δεν είναι εγκατεστημένος (χρειάζεται έκδοση 2.1 ή νεότερη)")

    def toast(self, text):
        sv, box = self.pages[self.sm.current]
        c = BoxLayout(orientation="vertical", size_hint_y=None, padding=(dp(12), dp(10)))
        c.bind(minimum_height=c.setter("height"))
        c.add_widget(UW.text(f"[b]{esc(text)}[/b]", color=(1, 1, 1, 1)))

        def bg(*a):
            c.canvas.before.clear()
            with c.canvas.before:
                Color(0.2, 0.1, 0.08, 0.92)
                RoundedRectangle(pos=c.pos, size=c.size, radius=[dp(14)])
        c.bind(pos=bg, size=bg)
        box.add_widget(c, index=len(box.children))
        sv.scroll_y = 1
        Clock.schedule_once(lambda dt: c.parent and c.parent.remove_widget(c), 3.5)

    def share(self, text):
        if not IS_ANDROID:
            try:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(text)
                self.toast("Αντιγράφηκε")
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            String = autoclass("java.lang.String")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            i = Intent(Intent.ACTION_SEND)
            i.setType("text/plain")
            i.putExtra(Intent.EXTRA_TEXT, cast("java.lang.CharSequence", String(text)))
            act.startActivity(Intent.createChooser(i, cast("java.lang.CharSequence", String("Κοινοποίηση"))))
        except Exception:  # noqa: BLE001
            pass

    # ================================================================== ημέρα
    def build_home(self):
        box = self.page("home")
        self.update_card(box)
        self.day_view(box, self.day, nav=True)
        c = self.card(box, 10)
        c.add_widget(UW.text(esc(UP.version_text()), 12, UW.C["muted"], halign="center"))
        self.ghost(c, "Έλεγχος για ενημέρωση", self.check_update, h=40)
        self.animate_in(box)

    def build_day(self):
        box = self.page("day")
        self.day_view(box, self.detail, nav=True)

    def open_day(self, d):
        self.detail = d
        self.build_day()
        self.show("day")

    def move_day(self, delta, page):
        if page == "home":
            self.day += datetime.timedelta(days=delta)
            self.build_home()
        else:
            self.detail += datetime.timedelta(days=delta)
            self.build_day()

    def day_view(self, box, d, nav=True):
        info = CH.day_info(d)
        today = datetime.date.today()
        page = "home" if box is self.pages["home"][1] else "day"

        if nav:
            row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
            for txt, delta in (("< Χθες" if d == today else "< Προηγούμενη", -1), ("Σήμερα", 0),
                               ("Αύριο >" if d == today else "Επόμενη >", 1)):
                b = Button(text=txt, bold=True, background_normal="", font_size=sp(14),
                           background_color=UW.C["line"] if delta else (UW.PRIMARY if d != today else UW.C["line"]),
                           color=UW.C["ink"] if (delta or d == today) else (1, 1, 1, 1))
                if delta:
                    b.bind(on_release=lambda w, dl=delta: self.move_day(dl, page))
                else:
                    b.bind(on_release=lambda w: self.goto_today(page))
                row.add_widget(b)
            box.add_widget(row)

        # ---------------- κεφαλίδα
        h = self.hero(box)
        rel = {0: "Σήμερα", 1: "Αύριο", -1: "Χθες"}.get((d - today).days)
        h.add_widget(UW.text((f"[b]{rel}[/b] · " if rel else "") + CH.date_text(d), 15, (1, 1, 1, 0.92)))
        t = info["tone"]
        big = f"Ήχος {CH.TONES[t]}" if t else "Χωρίς ήχο εβδομάδας"
        h.add_widget(UW.text(f"[b]{big}[/b]", 30, (1, 1, 1, 1)))
        sub = []
        if info["eothinon"]:
            e = info["eothinon"]
            sub.append(f"Εωθινό {CH.GREEK_NUM[e]} ({CH.EOTHINA[e]})")
        if info["sunday_n"]:
            sub.append(f"{CH.GREEK_NUM.get(info['sunday_n'], info['sunday_n'])} Κυριακή από της Πεντηκοστής")
        if not t:
            k = (d - CH.easter(d.year)).days
            sub.append("Μεγάλη Εβδομάδα: ιδιόμελα της ημέρας" if -7 <= k < 0 else "")
        elif d.weekday() != 6:
            sub.append("Ήχος της εβδομάδας (από την προηγούμενη Κυριακή)")
        h.add_widget(UW.text("\n".join(s for s in sub if s), 14, (1, 1, 1, 0.95)))
        self.chips(h, [(info["period"], (1, 1, 1, 0.22))] +
                   ([("ΜΕΓΑΛΗ ΕΟΡΤΗ", RED)] if is_great(info) else []))
        if t:
            ob = Button(text=f"Άνοιγμα στον Ισοκράτη · {CH.ISOKRATIS_MODE[t]}", bold=True, size_hint_y=None,
                        height=dp(46), background_normal="", background_color=(1, 1, 1, 0.95), color=UW.PRIMARY,
                        font_size=sp(14))
            ob.bind(on_release=lambda *a, tt=t: self.open_isokratis(tt))
            h.add_widget(Widget(size_hint_y=None, height=dp(4)))
            h.add_widget(ob)

        # ---------------- εορτάζει
        c = self.card(box)
        self.head(c, "Εορτάζει", "cross")
        for n, s_ in info["movable"]:
            c.add_widget(UW.text(f"[b][color={hx(RED)}]{esc(n)}[/color][/b]" + (f"\n{esc(s_)}" if s_ else ""), 15))
        for n, s_, g in day_saints(info):
            col = hx(RED) if g else hx(UW.C["ink"])
            c.add_widget(UW.text(f"[color={col}]{'[b]' if g else ''}{esc(n)}{'[/b]' if g else ''}[/color]" +
                                 (f"\n[color={hx(UW.C['muted'])}]{esc(s_)}[/color]" if s_ else ""), 15))
        if info["names"]:
            c.add_widget(UW.text(f"[b]Γιορτάζουν:[/b] {esc(', '.join(info['names']))}", 14))
        self.synaxari_block(c, d)

        # ---------------- νηστεία
        title, level, expl = info["fast"]
        c = self.card(box)
        self.head(c, "Νηστεία")
        self.chips(c, [(FC.LEVELS[level], FC.LEVEL_COLORS[level])] + ([(esc(title), GOLD)] if title else []))
        if expl:
            c.add_widget(UW.text(esc(expl), 14, UW.C["muted"]))

        # ---------------- θεία λειτουργία και ακολουθίες
        c = self.card(box)
        self.head(c, "Θεία Λειτουργία & ακολουθίες", "music")
        c.add_widget(UW.text(f"[b]{esc(info['liturgy'])}[/b]", 15))
        for s in info["services"]:
            c.add_widget(UW.text(f"•  {esc(s)}", 14))

        # ---------------- την Κυριακή
        if d.weekday() != 6:
            sun = d + datetime.timedelta(days=6 - d.weekday())
            si = CH.day_info(sun)
            c = self.card(box)
            self.head(c, f"Την Κυριακή {sun.day} {CH.MONTHS[sun.month - 1]}", "calendar")
            parts = []
            if si["tone"]:
                parts.append(f"[b]Ήχος {CH.TONES[si['tone']]}[/b]")
            if si["eothinon"]:
                parts.append(f"Εωθινό {CH.GREEK_NUM[si['eothinon']]}")
            if si["sunday_n"]:
                parts.append(f"{CH.GREEK_NUM.get(si['sunday_n'], si['sunday_n'])} από της Πεντηκοστής")
            c.add_widget(UW.text(" · ".join(parts) or "—", 15))
            for n, _ in si["movable"]:
                c.add_widget(UW.text(f"[color={hx(RED)}]{esc(n)}[/color]", 14))
            for n, _, g in si["fixed"]:
                if g:
                    c.add_widget(UW.text(f"[color={hx(RED)}]{esc(n)}[/color]", 14))
            self.ghost(c, "Άνοιγμα της Κυριακής", lambda s=sun: self.open_day(s), h=42)

        self.ghost(box, "Κοινοποίηση της ημέρας", lambda: self.share(self.day_text(info)))

    # ================================================================== συναξάρι (internet, προαιρετικό)
    def synaxari_block(self, card, d):
        holder = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        holder.bind(minimum_height=holder.setter("height"))
        card.add_widget(holder)
        saved = SX.cached(d.month, d.day)
        if saved:
            self.show_synaxari(holder, d, saved)
            return
        self.btn(holder, "Περισσότεροι άγιοι από το internet", lambda: self.load_synaxari(holder, d),
                 color=UW.PRIMARY2, h=44)
        holder.add_widget(UW.text("Προαιρετικό. Οι παραπάνω μνήμες υπάρχουν πάντα, και χωρίς internet.", 12,
                                  UW.C["muted"]))

    def load_synaxari(self, holder, d, force=False):
        self._sx_token += 1
        tok = self._sx_token
        holder.clear_widgets()
        holder.add_widget(UW.text("Φόρτωση συναξαρίου…", 14, UW.C["muted"]))

        def work():
            try:
                res, err = SX.fetch(d.month, d.day, force=force), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e
            Clock.schedule_once(lambda dt: done(res, err), 0)

        def done(res, err):
            if tok != self._sx_token or holder.parent is None:
                return
            holder.clear_widgets()
            if res:
                self.show_synaxari(holder, d, res, opened=True)
                return
            msg = ("Δεν βρέθηκαν επιπλέον μνήμες για αυτή την ημέρα." if isinstance(err, LookupError) else
                   "Δεν ήταν δυνατή η φόρτωση. Έλεγξε τη σύνδεση στο internet.")
            holder.add_widget(UW.text(f"[color={hx(RED)}]{msg}[/color]", 14))
            self.btn(holder, "Δοκίμασε ξανά", lambda: self.load_synaxari(holder, d, force), color=UW.PRIMARY2,
                     h=42)
        threading.Thread(target=work, daemon=True).start()

    def show_synaxari(self, holder, d, res, opened=False):
        total = sum(len(i) for _, i in res["groups"])

        def fill(body):
            for title, items in res["groups"]:
                body.add_widget(UW.text(f"[b][color={hx(UW.PRIMARY)}]{esc(title)}[/color][/b]", 14))
                for it in items[:80]:
                    body.add_widget(UW.text(f"•  {esc(it)}", 13))
            row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
            b1 = Button(text="Πλήρης σελίδα", background_normal="", background_color=UW.C["line"],
                        color=UW.C["ink"], bold=True)
            b1.bind(on_release=lambda *a: webbrowser.open(res["url"]))
            b2 = Button(text="Ανανέωση", background_normal="", background_color=UW.C["line"], color=UW.C["ink"],
                        bold=True)
            b2.bind(on_release=lambda *a: self.load_synaxari(holder, d, True))
            row.add_widget(b1)
            row.add_widget(b2)
            body.add_widget(row)
            body.add_widget(UW.text("Πηγή: ελληνική Wikipedia. Αποθηκεύτηκε στο κινητό για χρήση χωρίς internet.",
                                    11, UW.C["muted"]))
        holder.add_widget(UW.Section(f"Συναξάρι {d.day} {CH.MONTHS[d.month - 1]} ({total} μνήμες)",
                                     opened=opened, builder=fill))

    def goto_today(self, page):
        if page == "home":
            self.day = datetime.date.today()
            self.build_home()
        else:
            self.detail = datetime.date.today()
            self.build_day()

    def day_text(self, info):
        lines = [CH.date_text(info["date"])]
        if info["tone"]:
            lines.append(f"Ήχος {CH.TONES[info['tone']]}")
        if info["eothinon"]:
            lines.append(f"Εωθινό {CH.GREEK_NUM[info['eothinon']]}")
        lines += [n for n, _ in info["movable"]] + [n for n, _, _ in day_saints(info)]
        if info["names"]:
            lines.append("Γιορτάζουν: " + ", ".join(info["names"]))
        lines.append("Νηστεία: " + FC.LEVELS[info["fast"][1]])
        lines.append(info["liturgy"])
        return "\n".join(lines) + "\n— Ψαλτικό ημερολόγιο"

    # ================================================================== μήνας
    def build_cal(self):
        box = self.page("cal")
        y, m = self.month
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        b1 = Button(text="<", bold=True, font_size=sp(22), size_hint_x=None, width=dp(56), background_normal="",
                    background_color=UW.C["line"], color=UW.C["ink"])
        b1.bind(on_release=lambda *a: self.move_month(-1))
        lb = Label(text=f"[b]{CH.MONTHS_NOM[m - 1]} {y}[/b]", markup=True, color=UW.PRIMARY, font_size=sp(19))
        b2 = Button(text=">", bold=True, font_size=sp(22), size_hint_x=None, width=dp(56), background_normal="",
                    background_color=UW.C["line"], color=UW.C["ink"])
        b2.bind(on_release=lambda *a: self.move_month(1))
        row.add_widget(b1)
        row.add_widget(lb)
        row.add_widget(b2)
        box.add_widget(row)

        mode = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        for key, label in (("grid", "Μήνας (πλέγμα)"), ("list", "Εορτολόγιο (λίστα)")):
            on = self.cal_mode == key
            b = Button(text=label, bold=on, background_normal="", font_size=sp(14),
                       background_color=UW.PRIMARY if on else UW.C["line"], color=(1, 1, 1, 1) if on else UW.C["ink"])
            b.bind(on_release=lambda w, k=key: self.set_cal_mode(k))
            mode.add_widget(b)
        box.add_widget(mode)
        if self.cal_mode == "list":
            self.month_list(box, y, m)
            return

        c = self.card(box, 8)
        grid = GridLayout(cols=7, size_hint_y=None, spacing=dp(3))
        grid.bind(minimum_height=grid.setter("height"))
        for i, wd in enumerate(("Δε", "Τρ", "Τε", "Πε", "Πα", "Σα", "Κυ")):
            grid.add_widget(Label(text=f"[b]{wd}[/b]", markup=True, size_hint_y=None, height=dp(24), font_size=sp(13),
                                  color=RED if i == 6 else UW.C["muted"]))
        first = datetime.date(y, m, 1)
        for _ in range(first.weekday()):
            grid.add_widget(Widget(size_hint_y=None, height=dp(58)))
        today = datetime.date.today()
        d = first
        while d.month == m:
            grid.add_widget(self.cell(d, d == today))
            d += datetime.timedelta(days=1)
        c.add_widget(grid)

        leg = self.card(box, 12)
        self.head(leg, "Υπόμνημα")
        self.chips(leg, [(FC.LEVELS[k], FC.LEVEL_COLORS[k]) for k in FC.LEVEL_ORDER])
        leg.add_widget(UW.text(f"Η λωρίδα κάτω από κάθε ημέρα δείχνει τη νηστεία. "
                               f"[color={hx(RED)}][b]Κόκκινο[/b][/color] νούμερο: Κυριακή ή μεγάλη εορτή. "
                               f"Ο μικρός αριθμός είναι ο ήχος της εβδομάδας. Πάτα μια ημέρα για λεπτομέρειες.",
                               13, UW.C["muted"]))

        # εορτές του μήνα
        c = self.card(box)
        self.head(c, f"Εορτές του {CH.MONTHS[m - 1]}", "cross")
        d = first
        n = 0
        while d.month == m:
            info = CH.day_info(d)
            names = [x for x, _ in info["movable"]] + [x for x, _, g in info["fixed"] if g]
            if names:
                n += 1
                self.feast_row(c, d, names)
            d += datetime.timedelta(days=1)
        if not n:
            c.add_widget(UW.text("Δεν υπάρχουν μεγάλες εορτές.", 14, UW.C["muted"]))

    def set_cal_mode(self, k):
        self.cal_mode = k
        self.build_cal()

    def month_list(self, box, y, m):
        """Εορτολόγιο του μήνα: κάθε ημέρα με τις μνήμες της, τον ήχο και τη νηστεία."""
        today = datetime.date.today()
        c = self.card(box, 10)
        self.chips(c, [(FC.LEVELS[k], FC.LEVEL_COLORS[k]) for k in FC.LEVEL_ORDER])
        d = datetime.date(y, m, 1)
        while d.month == m:
            info = CH.day_info(d)
            great = is_great(info) or d.weekday() == 6
            lvl = info["fast"][1]
            r = Tap(orientation="horizontal", size_hint_y=None, spacing=dp(10), padding=(dp(4), dp(6)))
            r.bind(minimum_height=r.setter("height"))
            col = RED if great else UW.C["ink"]
            dl = Label(text=f"[b]{d.day}[/b]\n[size={int(sp(11))}]{CH.WEEKDAYS[d.weekday()][:3]}[/size]",
                       markup=True, halign="center", color=col, size_hint=(None, None), size=(dp(44), dp(44)))
            r.add_widget(dl)
            names = [n for n, _ in info["movable"]] + [n for n, _, _ in day_saints(info)]
            main_txt = "; ".join(names[:3]) if names else "—"
            extra = [f"[color={hx(FC.LEVEL_COLORS[lvl])}][b]{FC.LEVELS[lvl]}[/b][/color]"]
            if info["tone"]:
                extra.append(f"Ήχος {CH.TONES[info['tone']]}")
            if info["names"]:
                extra.append("Γιορτάζουν: " + ", ".join(info["names"][:4]))
            t = UW.text(f"{'[b]' if great else ''}{esc(main_txt)}{'[/b]' if great else ''}\n"
                        f"[size={int(sp(12))}]{esc(' · '.join(extra)).replace('&bl;', '[').replace('&br;', ']')}[/size]",
                        14, col if great else UW.C["ink"])
            r.add_widget(t)
            t.bind(height=lambda w, h, rr=r: setattr(rr, "height", max(dp(52), h + dp(10))))
            r.height = dp(56)

            def bg(*a, rr=r, lv=lvl, td=(d == today)):
                rr.canvas.before.clear()
                with rr.canvas.before:
                    if td:
                        Color(UW.PRIMARY[0], UW.PRIMARY[1], UW.PRIMARY[2], 0.1)
                        RoundedRectangle(pos=rr.pos, size=rr.size, radius=[dp(8)])
                    Color(*FC.LEVEL_COLORS[lv])
                    RoundedRectangle(pos=(rr.x, rr.y + dp(6)), size=(dp(4), rr.height - dp(12)), radius=[dp(2)])
            r.bind(pos=bg, size=bg)
            r.bind(on_release=lambda *a, dd=d: self.open_day(dd))
            c.add_widget(r)
            d += datetime.timedelta(days=1)

    def cell(self, d, today):
        info = CH.day_info(d)
        great = is_great(info) or d.weekday() == 6
        lvl = info["fast"][1]
        cell = Tap(orientation="vertical", size_hint_y=None, height=dp(58), padding=(dp(2), dp(4)))
        num = Label(text=f"[b]{d.day}[/b]", markup=True, font_size=sp(17),
                    color=(1, 1, 1, 1) if today else (RED if great else UW.C["ink"]))
        tn = Label(text=CH.TONES[info["tone"]] if info["tone"] else "", font_size=sp(10), size_hint_y=None,
                   height=dp(14), color=(1, 1, 1, 0.9) if today else UW.C["muted"])
        cell.add_widget(num)
        cell.add_widget(tn)
        cell.add_widget(Widget(size_hint_y=None, height=dp(6)))

        def bg(*a):
            cell.canvas.before.clear()
            with cell.canvas.before:
                if today:
                    Color(*UW.PRIMARY)
                elif any(g for _, _, g in info["fixed"]) or info["movable"]:
                    Color(1, 0.93, 0.85, 1)
                else:
                    Color(*UW.C["bg"])
                RoundedRectangle(pos=cell.pos, size=cell.size, radius=[dp(9)])
                Color(*FC.LEVEL_COLORS[lvl])
                RoundedRectangle(pos=(cell.x + dp(6), cell.y + dp(4)), size=(cell.width - dp(12), dp(5)),
                                 radius=[dp(2)])
        cell.bind(pos=bg, size=bg)
        cell.bind(on_release=lambda *a: self.open_day(d))
        return cell

    def move_month(self, delta):
        y, m = self.month
        m += delta
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self.month = (y, m)
        self.build_cal()

    def feast_row(self, parent, d, names):
        r = Tap(orientation="horizontal", size_hint_y=None, spacing=dp(10), padding=(0, dp(4)))
        r.bind(minimum_height=r.setter("height"))
        dl = Label(text=f"[b]{d.day}[/b]\n[size={int(sp(11))}]{CH.WEEKDAYS[d.weekday()][:3]}[/size]", markup=True,
                   halign="center", color=RED, size_hint=(None, None), size=(dp(48), dp(44)))
        r.add_widget(dl)
        t = UW.text("\n".join(esc(n) for n in names), 14)
        r.add_widget(t)
        t.bind(height=lambda w, h: setattr(r, "height", max(dp(48), h + dp(8))))
        r.height = dp(48)
        r.bind(on_release=lambda *a: self.open_day(d))
        parent.add_widget(r)

    # ================================================================== εορτές
    def build_feasts(self):
        box = self.page("feasts")
        today = datetime.date.today()

        # ---- αναζήτηση ονόματος
        c = self.card(box)
        self.head(c, "Πότε γιορτάζει;", "search")
        ti = TextInput(text=self.last_query, hint_text="Γράψε ένα όνομα, π.χ. Γιώργος", multiline=False,
                       size_hint_y=None, height=dp(46), font_size=sp(16), padding=(dp(10), dp(12)))
        res = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        res.bind(minimum_height=res.setter("height"))

        def find(*a):
            self.last_query = ti.text
            res.clear_widgets()
            hits = MN.search_name(ti.text)
            if not ti.text.strip():
                return
            if not hits:
                res.add_widget(UW.text("Δεν βρέθηκε στο ημερολόγιο της εφαρμογής.", 14, UW.C["muted"]))
            for m, dd, n in hits[:20]:
                if m is None:
                    res.add_widget(UW.text(f"•  [b]{esc(n)}[/b]", 14))
                    continue
                nd = datetime.date(today.year, m, dd)
                if nd < today:
                    nd = datetime.date(today.year + 1, m, dd)
                days = (nd - today).days
                when = "σήμερα!" if days == 0 else ("αύριο" if days == 1 else f"σε {days} ημέρες")
                res.add_widget(UW.text(f"•  [b]{esc(n)}[/b]: {dd} {CH.MONTHS[m - 1]} "
                                       f"([color={hx(UW.PRIMARY)}]{when}[/color])", 14))
        ti.bind(on_text_validate=find, text=lambda *a: Clock.schedule_once(find, 0))
        c.add_widget(ti)
        c.add_widget(res)
        if self.last_query:
            find()

        # ---- επόμενες εορτές
        c = self.card(box)
        self.head(c, "Οι επόμενες εορτές (60 ημέρες)", "calendar")
        d = today
        for _ in range(60):
            info = CH.day_info(d)
            names = [x for x, _ in info["movable"]] + [x for x, _, g in info["fixed"] if g]
            if names:
                self.feast_row(c, d, [f"[color={hx(UW.C['muted'])}]{d.day} {CH.MONTHS[d.month - 1]}[/color]"] + names)
            d += datetime.timedelta(days=1)

        # ---- κινητές εορτές της χρονιάς
        y = today.year if today <= CH.easter(today.year) + datetime.timedelta(days=63) else today.year + 1
        E = CH.easter(y)
        c = self.card(box)
        self.head(c, f"Τριώδιο & Πεντηκοστάριο {y}", "cross")
        key = [(-70, "Αρχή Τριωδίου (Τελώνου και Φαρισαίου)"), (-56, "Απόκρεω"), (-49, "Τυρινής"),
               (-48, "Καθαρά Δευτέρα"), (-7, "Κυριακή των Βαΐων"), (-2, "Μεγάλη Παρασκευή"), (0, "ΠΑΣΧΑ"),
               (7, "Κυριακή του Θωμά"), (39, "Ανάληψη"), (49, "Πεντηκοστή"), (50, "Αγίου Πνεύματος"),
               (56, "Αγίων Πάντων")]
        for off, n in key:
            dd = E + datetime.timedelta(days=off)
            col = hx(RED) if off in CH.GREAT_FEASTS else hx(UW.C["ink"])
            c.add_widget(UW.text(f"[b]{dd.day:02d}/{dd.month:02d}[/b]  [color={col}]{n}[/color]", 14))
        sa = E + datetime.timedelta(days=56)
        ap = datetime.date(y, 6, 29)
        c.add_widget(UW.text(f"Νηστεία των Αγίων Αποστόλων: "
                             + (f"{(ap - sa).days - 1} ημέρες" if ap > sa + datetime.timedelta(days=1)
                                else "δεν υπάρχει φέτος"), 13, UW.C["muted"]))

        # ---- Πάσχα επόμενων ετών
        c = self.card(box)
        self.head(c, "Πάσχα των επόμενων ετών")
        for yy in range(today.year, today.year + 6):
            e = CH.easter(yy)
            c.add_widget(UW.text(f"[b]{yy}[/b]:  {e.day} {CH.MONTHS[e.month - 1]}", 14))
        c.add_widget(UW.text("Το ημερολόγιο αγίων περιέχει τις κυριότερες εορτές· δεν είναι πλήρες συναξάρι.",
                             12, UW.C["muted"]))

    # ================================================================== νηστείες
    def build_fasts(self):
        box = self.page("fasts")
        y = self.fast_year
        E = CH.easter(y)
        td = datetime.timedelta
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        for txt, dl in (("<", -1), (None, 0), (">", 1)):
            if txt is None:
                row.add_widget(Label(text=f"[b]Νηστείες {y}[/b]", markup=True, color=UW.PRIMARY, font_size=sp(19)))
                continue
            b = Button(text=txt, bold=True, font_size=sp(22), size_hint_x=None, width=dp(56), background_normal="",
                       background_color=UW.C["line"], color=UW.C["ink"])
            b.bind(on_release=lambda w, k=dl: self.move_fast_year(k))
            row.add_widget(b)
        box.add_widget(row)

        def rng(a, b):
            if a == b:
                return f"{a.day} {CH.MONTHS[a.month - 1]} ({CH.WEEKDAYS[a.weekday()]})"
            return f"{a.day} {CH.MONTHS[a.month - 1]} – {b.day} {CH.MONTHS[b.month - 1]} ({(b - a).days + 1} ημέρες)"

        def period_card(title, items, icon=None):
            c = self.card(box)
            self.head(c, title, icon)
            for name, a, b, lvl, note in items:
                line = BoxLayout(size_hint_y=None, spacing=dp(10))
                line.bind(minimum_height=line.setter("height"))
                t = UW.text(f"[b]{esc(name)}[/b]\n{rng(a, b) if a else ''}"
                            + (f"\n[color={hx(UW.C['muted'])}]{esc(note)}[/color]" if note else ""), 14)
                line.add_widget(t)
                t.bind(height=lambda w, h, ln=line: setattr(ln, "height", h))
                if lvl is not None:
                    line.add_widget(UW.Chip(FC.LEVELS[lvl].split(" ")[0], FC.LEVEL_COLORS[lvl],
                                            pos_hint={"top": 1}))
                c.add_widget(line)

        pent = E + td(days=49)
        ap_a, ap_b = pent + td(days=8), datetime.date(y, 6, 28)
        big = [("Μεγάλη Τεσσαρακοστή", E - td(days=48), E - td(days=8), 0,
                "Από την Καθαρά Δευτέρα. Καθημερινές ξηροφαγία, Σαββατοκύριακα λάδι. Ψάρι: Ευαγγελισμός και Βαΐων."),
               ("Μεγάλη Εβδομάδα", E - td(days=6), E - td(days=1), 0,
                "Μεγάλη Παρασκευή αυστηρή νηστεία· Μεγάλο Σάββατο λάδι.")]
        if ap_a <= ap_b:
            big.append(("Νηστεία των Αγίων Αποστόλων", ap_a, ap_b, 2,
                        "Ψάρι, εκτός Τετάρτης και Παρασκευής (λάδι)."))
        else:
            big.append(("Νηστεία των Αγίων Αποστόλων", None, None, None, "Φέτος δεν υπάρχει (Πάσχα πολύ αργά)."))
        big += [("Δεκαπενταύγουστος", datetime.date(y, 8, 1), datetime.date(y, 8, 14), 0,
                 "Ξηροφαγία· λάδι τα Σαββατοκύριακα· ψάρι στη Μεταμόρφωση (6/8)."),
                ("Σαρανταήμερο των Χριστουγέννων", datetime.date(y, 11, 15), datetime.date(y, 12, 24), 2,
                 "Ψάρι έως 17/12 (εκτός Τετάρτης και Παρασκευής)· από 18/12 μόνο λάδι.")]
        period_card("Μεγάλες νηστείες", big, "fish")

        single = [(n, dd, dd, 1, "") for n, dd in (("Παραμονή των Θεοφανείων", datetime.date(y, 1, 5)),
                                                 ("Αποτομή της Κεφαλής του Προδρόμου", datetime.date(y, 8, 29)),
                                                 ("Ύψωση του Τιμίου Σταυρού", datetime.date(y, 9, 14)))]
        single.append(("Κάθε Τετάρτη και Παρασκευή", None, None, 1,
                       "Εκτός από τις εβδομάδες χωρίς νηστεία και τις μεγάλες εορτές (τότε ψάρι ή κατάλυση)."))
        period_card("Ημέρες νηστείας", single)

        free = [("Δωδεκαήμερο", datetime.date(y - 1, 12, 25), datetime.date(y, 1, 4), 3, ""),
                ("Εβδομάδα του Τελώνου και Φαρισαίου", E - td(days=70), E - td(days=64), 3, ""),
                ("Εβδομάδα της Τυρινής (Τυροφάγος)", E - td(days=55), E - td(days=49), 4,
                 "Όχι κρέας· γαλακτοκομικά, αυγά και ψάρι επιτρέπονται."),
                ("Διακαινήσιμος εβδομάδα", E, E + td(days=6), 3, ""),
                ("Εβδομάδα μετά την Πεντηκοστή", pent, pent + td(days=6), 3, ""),
                ("Δωδεκαήμερο (τέλος χρονιάς)", datetime.date(y, 12, 25), datetime.date(y, 12, 31), 3, "")]
        period_card("Χωρίς νηστεία (κατάλυση)", free, "cross")

        # μέτρηση ημερών
        counts = {k: 0 for k in FC.LEVELS}
        d = datetime.date(y, 1, 1)
        while d.year == y:
            counts[FC.today_fast(d)[1]] += 1
            d += td(days=1)
        c = self.card(box)
        self.head(c, f"Το {y} σε αριθμούς")
        total = sum(counts.values())
        for k in FC.LEVEL_ORDER:
            ln = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))
            lb = Label(text=FC.LEVELS[k].split(" ")[0], color=UW.C["ink"], font_size=sp(13), size_hint_x=None,
                       width=dp(96), halign="left", valign="middle")
            lb.bind(size=lambda w, sz: setattr(w, "text_size", sz))
            bar = Widget()

            def draw(*a, w=bar, v=counts[k] / total, col=FC.LEVEL_COLORS[k]):
                w.canvas.before.clear()
                with w.canvas.before:
                    Color(*UW.C["line"])
                    RoundedRectangle(pos=(w.x, w.y + dp(5)), size=(w.width, w.height - dp(10)), radius=[dp(6)])
                    Color(*col)
                    RoundedRectangle(pos=(w.x, w.y + dp(5)), size=(max(dp(4), w.width * v), w.height - dp(10)),
                                     radius=[dp(6)])
            bar.bind(pos=draw, size=draw)
            ln.add_widget(lb)
            ln.add_widget(bar)
            ln.add_widget(Label(text=str(counts[k]), color=UW.C["ink"], bold=True, font_size=sp(13),
                                size_hint_x=None, width=dp(40)))
            c.add_widget(ln)
        c.add_widget(UW.text("Ημέρες του έτους ανά είδος τροφής, κατά την κοινή τυπική. Για προσωπικό κανόνα "
                             "νηστείας ακολουθούμε τον πνευματικό μας.", 12, UW.C["muted"]))
        self.ghost(box, "Λίστα όλων των ημερών (εορτολόγιο)", self.open_list_today)

    def move_fast_year(self, k):
        self.fast_year += k
        self.build_fasts()

    def open_list_today(self):
        t = datetime.date.today()
        self.month = (t.year, t.month)
        self.cal_mode = "list"
        self.tab("cal")

    # ================================================================== ενημέρωση
    def update_card(self, box):
        if self.update_info:
            u = self.update_info
            h = self.hero(box)
            h.add_widget(UW.text(f"[b]Νέα έκδοση διαθέσιμη{(' ' + u['version']) if u['version'] else ''} "
                                 f"(build {u['build']})[/b]", 16, (1, 1, 1, 1)))
            h.add_widget(UW.text("Κατέβασε το APK και εγκατάστησέ το πάνω από την τωρινή εφαρμογή.", 13,
                                 (1, 1, 1, 0.9)))
            b = Button(text="Λήψη ενημέρωσης", bold=True, size_hint_y=None, height=dp(44), background_normal="",
                       background_color=(1, 1, 1, 0.95), color=UW.PRIMARY)
            b.bind(on_release=lambda *a: webbrowser.open(u["apk"] or u["page"]))
            h.add_widget(b)

    def check_update(self, silent=False):
        def work():
            try:
                res, err = UP.check(), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e
            Clock.schedule_once(lambda dt: done(res, err), 0)

        def done(res, err):
            if res:
                self.update_info = res
                if self.sm.current == "home":
                    self.build_home()
                if not silent:
                    self.toast("Βρέθηκε νέα έκδοση!")
            elif not silent:
                self.toast("Έχεις την τελευταία έκδοση." if err is None else
                           f"Δεν έγινε έλεγχος: {err if isinstance(err, RuntimeError) else 'χωρίς σύνδεση ή repository'}")
        if not silent:
            self.toast("Έλεγχος για ενημέρωση…")
        threading.Thread(target=work, daemon=True).start()

    # ================================================================== ήχοι
    def build_tones(self):
        box = self.page("tones")
        cur = CH.tone(datetime.date.today())
        c = self.card(box, 12)
        c.add_widget(UW.text("Η Οκτώηχος αλλάζει ήχο κάθε Κυριακή, ξεκινώντας με τον Α΄ ήχο την Κυριακή του Θωμά. "
                             "Πάτα «Ισοκράτης» για να ακούσεις τον ήχο με ισοκράτημα.", 14, UW.C["muted"]))
        for n in range(1, 9):
            base, genus, char = CH.TONE_INFO[n]
            c = self.card(box)
            row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
            lb = Label(text=f"[b]Ήχος {CH.TONES[n]}[/b]", markup=True, font_size=sp(19), halign="left",
                       valign="middle", color=UW.PRIMARY)
            lb.bind(size=lambda w, s: setattr(w, "text_size", s))
            row.add_widget(lb)
            if n == cur:
                row.add_widget(UW.Chip("ΑΥΤΗ ΤΗΝ ΕΒΔΟΜΑΔΑ", GOLD, pos_hint={"center_y": 0.5}))
            c.add_widget(row)
            c.add_widget(UW.text(f"[b]Βάση:[/b] {esc(base)}   ·   [b]Γένος:[/b] {esc(genus)}", 14))
            c.add_widget(UW.text(esc(char), 14, UW.C["muted"]))
            nxt = self.next_sunday_of(n)
            if nxt:
                c.add_widget(UW.text(f"Επόμενη Κυριακή σε αυτόν τον ήχο: [b]{nxt.day} {CH.MONTHS[nxt.month - 1]}[/b]",
                                     13, UW.C["muted"]))
            self.btn(c, f"Ισοκράτης · {CH.ISOKRATIS_MODE[n]}", lambda t=n: self.open_isokratis(t), h=44,
                     color=UW.PRIMARY if n == cur else UW.PRIMARY2)

    def next_sunday_of(self, n):
        d = datetime.date.today()
        d += datetime.timedelta(days=(6 - d.weekday()) or 7)
        for _ in range(60):
            if CH.tone(d) == n:
                return d
            d += datetime.timedelta(days=7)
        return None


if __name__ == "__main__":
    PsaltikoApp().run()
