# -*- coding: utf-8 -*-
"""
وقتي - برنامج تنظيم وقت اللعب على كمبيوتر البيت (ويندوز)

- كل واحد له وقت باليوم.
- إذا خلص الوقت: مهلة (افتراضياً 5 دقايق) وبعدها ينقفل الجهاز.
- وقت إضافي: إما بموافقة الكبير (رمز)، أو بخيار "ما أحد صاحي"
  وهذا ينكتب في السجل ويوصل رسالة للكل (تيليجرام).
- السجل ظاهر للكل على شاشة القفل.
"""
import copy
import datetime
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request

IS_WIN = sys.platform.startswith("win")

# ---- التحديث التلقائي: كل دقيقة يشيك على النسخة اللي في الرابط، وإذا أحدث يتحدث ويعيد تشغيل نفسه
VERSION = 2
UPDATE_URL = "https://raw.githubusercontent.com/nawafz2011-blip/huroof/ccr-8b9f1bcf-7vtkhv/waqti/waqti.pyw"
UPDATE_EVERY_SEC = 60

DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Waqti")
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
LOG_PATH = os.path.join(DATA_DIR, "log.jsonl")

FONT = "Tahoma" if IS_WIN else "DejaVu Sans"
BG = "#0f172a"
CARD = "#1e293b"
FG = "#f1f5f9"
MUTED = "#94a3b8"
ACCENT = "#2563eb"
GOOD = "#16a34a"
WARN = "#d97706"
BAD = "#dc2626"
DIM = "#475569"

KEEP = "(بدون تغيير)"


def hash_pin(pin):
    return hashlib.sha256(("waqti:" + pin.strip()).encode("utf-8")).hexdigest()


DEFAULT_CONFIG = {
    "admin_pin": hash_pin("1234"),
    "players": [
        {"name": "اللاعب 1", "daily_minutes": 120, "pin": ""},
        {"name": "اللاعب 2", "daily_minutes": 120, "pin": ""},
    ],
    "grace_minutes": 5,            # المهلة بعد ما يخلص الوقت
    "warn_minutes": 10,            # تنبيه قبل نهاية الوقت
    "nobody_awake_minutes": 30,    # كم دقيقة يعطي خيار "ما أحد صاحي"
    "nobody_awake_per_day": 1,     # كم مرة باليوم لكل لاعب
    "day_start_hour": 4,           # اليوم الجديد يبدأ الساعة 4 الفجر
    "telegram_token": "",
    "telegram_chat_id": "",
    "autostart": False,
}


# ---------------------------------------------------------------- storage

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(default)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config():
    cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, copy.deepcopy(v))
    save_json(CONFIG_PATH, cfg)
    return cfg


def read_log(limit=200):
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except Exception:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return list(reversed(out))  # newest first


def fmt(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def now_hm():
    return datetime.datetime.now().strftime("%H:%M")


def entry_time(e):
    try:
        return datetime.datetime.fromisoformat(e["t"]).strftime("%d/%m  %H:%M")
    except Exception:
        return ""


# ---------------------------------------------------------------- telegram

def telegram_send_sync(cfg, text):
    token = (cfg.get("telegram_token") or "").strip()
    chat = (cfg.get("telegram_chat_id") or "").strip()
    if not token or not chat:
        return False, "ما فيه إعدادات تيليجرام"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        with urllib.request.urlopen(url, data=data, timeout=10) as r:
            ok = json.loads(r.read().decode()).get("ok", False)
        return ok, "" if ok else "تيليجرام رفض الرسالة"
    except Exception as ex:
        return False, str(ex)


def telegram_send(cfg, text):
    threading.Thread(target=telegram_send_sync, args=(dict(cfg), text), daemon=True).start()


# ---------------------------------------------------------------- windows helpers

def screen_geom(root):
    if IS_WIN:
        try:
            import ctypes
            u = ctypes.windll.user32
            x, y, w, h = (u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
            if w > 0 and h > 0:
                return x, y, w, h
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def set_autostart(on):
    if not IS_WIN:
        return
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
    try:
        if on:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}"'
            else:
                pyw = sys.executable.replace("python.exe", "pythonw.exe")
                cmd = f'"{pyw}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(key, "Waqti", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "Waqti")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def beep():
    if IS_WIN:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


def btn(parent, text, cmd, bg=ACCENT, size=12, width=None, fg=FG):
    b = tk.Button(parent, text=text, command=cmd, font=(FONT, size, "bold"), bg=bg, fg=fg,
                  activebackground=bg, activeforeground=fg, relief="flat", bd=0,
                  padx=14, pady=8, cursor="hand2")
    if width:
        b.configure(width=width)
    return b


# ---------------------------------------------------------------- app

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("وقتي")
        self.cfg = load_config()
        self.state = load_json(STATE_PATH, {})
        self.dialogs = []
        self.active = None
        self.grace_left = None
        self.warned = False
        self.last = time.monotonic()
        self.save_tick = 0

        self.ensure_today()
        resume = self.state.pop("resume", None)
        if resume and self.state.get("active") == resume.get("name") and time.time() - resume.get("at", 0) < 120:
            self.log("updated", f"تحدّث البرنامج للنسخة {VERSION}")
        elif self.state.get("active"):
            name = self.state["active"]
            self.log("abnormal", f"⚠️ البرنامج أو الجهاز انطفى وجلسة {name} شغالة، بدون ما تنتهي بشكل طبيعي",
                     name, notify=True)
            self.state["active"] = None
            self.save_state()
        self.log("app_start", "تشغّل البرنامج")

        self.setup_lock_window()
        self.setup_timer_window()
        self.show_lock()
        if resume and self.state.get("active") == resume.get("name"):
            self.continue_session(resume)
        elif resume:
            self.log("updated", f"تحدّث البرنامج للنسخة {VERSION}")
        self.update_ready = None
        self.root.after(1000, self.tick)
        self.root.after(500, self.keep_on_top)
        self.root.after(5000, self.check_update)

    # ---------- auto update
    def check_update(self):
        if self.update_ready:
            self.apply_update()
        elif UPDATE_URL and not getattr(sys, "frozen", False):
            threading.Thread(target=self._fetch_update, daemon=True).start()
        self.root.after(UPDATE_EVERY_SEC * 1000, self.check_update)

    def _fetch_update(self):
        try:
            url = f"{UPDATE_URL}?t={int(time.time())}"
            req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=15) as r:
                code = r.read().decode("utf-8")
            m = re.search(r"^VERSION = (\d+)", code, re.M)
            if not m or int(m.group(1)) <= VERSION:
                return
            compile(code, "waqti", "exec")  # نتأكد إن الكود سليم قبل لا نبدل
            self.update_ready = (int(m.group(1)), code)
        except Exception:
            pass

    def apply_update(self):
        if self.dialogs:              # لا نعيد التشغيل والكبير فاتح الإعدادات
            return
        ver, code = self.update_ready
        path = os.path.abspath(__file__)
        try:
            tmp = path + ".new"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(code)
            os.replace(tmp, path)
        except Exception as ex:
            self.update_ready = None
            self.log("update_fail", f"فشل التحديث: {ex}")
            return
        self.state["resume"] = {"name": self.active, "grace_left": self.grace_left,
                                "warned": self.warned, "at": time.time()}
        self.save_state()
        global _instance_lock
        try:
            _instance_lock.close()
        except Exception:
            pass
        flags = 0x00000008 if IS_WIN else 0  # DETACHED_PROCESS
        subprocess.Popen([sys.executable, path], creationflags=flags, close_fds=True)
        self.root.destroy()

    def continue_session(self, resume):
        self.active = resume["name"]
        self.grace_left = resume.get("grace_left")
        self.warned = bool(resume.get("warned"))
        self.show_timer()

    # ---------- data
    def save_state(self):
        save_json(STATE_PATH, self.state)

    def save_cfg(self):
        save_json(CONFIG_PATH, self.cfg)

    def log(self, kind, text, player=None, notify=False):
        e = {"t": datetime.datetime.now().isoformat(timespec="seconds"),
             "kind": kind, "player": player, "text": text}
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if notify:
            telegram_send(self.cfg, f"⏱ وقتي\n{text}\nالساعة {now_hm()}")

    def today(self):
        h = int(self.cfg.get("day_start_hour", 4))
        return (datetime.datetime.now() - datetime.timedelta(hours=h)).date().isoformat()

    def ensure_today(self):
        t = self.today()
        if self.state.get("date") != t:
            active = self.state.get("active")
            self.state = {"date": t, "used": {}, "bonus": {}, "nobody": {}, "active": active}
            self.save_state()
            return True
        for k in ("used", "bonus", "nobody"):
            self.state.setdefault(k, {})
        return False

    def player(self, name):
        for p in self.cfg["players"]:
            if p["name"] == name:
                return p
        return None

    def remaining(self, name):
        p = self.player(name)
        base = int(p["daily_minutes"]) * 60 if p else 0
        return base + self.state["bonus"].get(name, 0) - self.state["used"].get(name, 0)

    # ---------- dialogs
    def ask(self, title, msg, buttons, fields=None):
        d = tk.Toplevel(self.root)
        d.title(title)
        d.configure(bg=CARD, padx=26, pady=22)
        d.attributes("-topmost", True)
        d.resizable(False, False)
        result = {"v": None, "vals": []}
        entries = []

        def close(v):
            result["v"] = v
            result["vals"] = [e.get() for e in entries]
            try:
                d.grab_release()
            except Exception:
                pass
            if d in self.dialogs:
                self.dialogs.remove(d)
            d.destroy()

        d.protocol("WM_DELETE_WINDOW", lambda: close(None))
        tk.Label(d, text=title, font=(FONT, 16, "bold"), bg=CARD, fg=FG).pack(anchor="e")
        if msg:
            tk.Label(d, text=msg, font=(FONT, 12), bg=CARD, fg=MUTED, justify="right",
                     wraplength=440).pack(anchor="e", pady=(6, 12))
        for label, default, secret in fields or []:
            row = tk.Frame(d, bg=CARD)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, font=(FONT, 12), bg=CARD, fg=FG).pack(side="right")
            e = tk.Entry(row, font=(FONT, 13), justify="right", width=22, show="•" if secret else "")
            e.insert(0, str(default))
            e.pack(side="left", padx=(0, 12))
            entries.append(e)
        bf = tk.Frame(d, bg=CARD)
        bf.pack(fill="x", pady=(16, 0))
        default_v = None
        for lbl, val in buttons:
            if val is not None and default_v is None:
                default_v = val
            btn(bf, lbl, lambda v=val: close(v), bg=DIM if val is None else ACCENT).pack(side="right", padx=4)
        d.bind("<Return>", lambda e: close(default_v))
        d.bind("<Escape>", lambda e: close(None))

        self.dialogs.append(d)
        d.update_idletasks()
        w, h = d.winfo_reqwidth(), d.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        d.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        d.lift()
        try:
            d.wait_visibility()
            d.grab_set()
        except Exception:
            pass
        d.focus_force()
        if entries:
            entries[0].focus_set()
            entries[0].select_range(0, "end")
        self.root.wait_window(d)
        return result["v"], result["vals"]

    def info(self, title, msg):
        self.ask(title, msg, [("حسناً", "ok")])

    def check_admin(self, reason="اكتب رمز الكبير"):
        v, vals = self.ask("رمز الكبير", reason, [("دخول", True), ("إلغاء", None)],
                           fields=[("الرمز", "", True)])
        if not v:
            return False
        if hash_pin(vals[0]) == self.cfg["admin_pin"]:
            return True
        self.log("wrong_admin_pin", "⚠️ أحد حاول يدخل برمز الكبير وكان الرمز غلط", self.active, notify=True)
        self.info("خطأ", "الرمز غلط. وانكتبت المحاولة في السجل.")
        return False

    # ---------- lock screen
    def setup_lock_window(self):
        r = self.root
        r.configure(bg=BG)
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.protocol("WM_DELETE_WINDOW", lambda: None)
        x, y, w, h = screen_geom(r)
        r.geometry(f"{w}x{h}+{x}+{y}")

        lf = tk.Frame(r, bg=BG)
        lf.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(lf, text="⏱  وقتي", font=(FONT, 42, "bold"), bg=BG, fg=FG).pack()
        self.clock_lbl = tk.Label(lf, text="", font=(FONT, 16), bg=BG, fg=MUTED)
        self.clock_lbl.pack(pady=(4, 0))
        tk.Label(lf, text="مين بيلعب الحين؟", font=(FONT, 22, "bold"), bg=BG, fg=FG).pack(pady=(34, 12))
        self.players_frame = tk.Frame(lf, bg=BG)
        self.players_frame.pack()

        bottom = tk.Frame(lf, bg=BG)
        bottom.pack(pady=(26, 0))
        btn(bottom, "السجل", self.open_log, bg=CARD).pack(side="right", padx=6)
        btn(bottom, "الإعدادات", self.open_settings, bg=CARD).pack(side="right", padx=6)
        btn(bottom, "إغلاق البرنامج", self.exit_app, bg=CARD).pack(side="right", padx=6)

        tk.Label(lf, text="آخر الأحداث (الكل يشوفها)", font=(FONT, 13, "bold"), bg=BG,
                 fg=MUTED).pack(pady=(30, 6))
        self.recent_lbl = tk.Label(lf, text="", font=(FONT, 12), bg=BG, fg=MUTED, justify="right")
        self.recent_lbl.pack()

    def refresh_lock(self):
        for w in self.players_frame.winfo_children():
            w.destroy()
        cols = 4
        for i, p in enumerate(self.cfg["players"]):
            rem = self.remaining(p["name"])
            if rem > 0:
                txt, color = f'{p["name"]}\nباقي {fmt(rem)}', ACCENT
            else:
                txt, color = f'{p["name"]}\nخلص وقته', DIM
            b = btn(self.players_frame, txt, lambda n=p["name"]: self.choose_player(n),
                    bg=color, size=16, width=12)
            b.grid(row=i // cols, column=cols - 1 - (i % cols), padx=10, pady=10)
        lines = [f"{e['text']}   {entry_time(e)}" for e in read_log(7) if e.get("kind") != "app_start"][:6]
        self.recent_lbl.configure(text="\n".join(lines) or "ما فيه أحداث")

    def show_lock(self):
        self.timer.withdraw()
        self.root.deiconify()
        x, y, w, h = screen_geom(self.root)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.attributes("-topmost", True)
        self.refresh_lock()
        self.root.lift()
        self.root.focus_force()

    def choose_player(self, name):
        p = self.player(name)
        if not p:
            return
        if p.get("pin"):
            v, vals = self.ask(f"رمز {name}", "اكتب رمزك", [("دخول", True), ("إلغاء", None)],
                               fields=[("الرمز", "", True)])
            if not v:
                return
            if hash_pin(vals[0]) != p["pin"]:
                self.log("wrong_pin", f"⚠️ محاولة دخول على حساب {name} برمز غلط", name, notify=True)
                self.info("خطأ", "الرمز غلط. وانكتبت المحاولة في السجل.")
                return
        if self.remaining(name) <= 0:
            self.extension_flow(name, from_lock=True)
            self.refresh_lock()
            return
        self.start_session(name)

    # ---------- sessions
    def start_session(self, name):
        rem = self.remaining(name)
        self.active = name
        self.state["active"] = name
        self.grace_left = None
        self.warned = rem <= int(self.cfg["warn_minutes"]) * 60
        self.save_state()
        self.log("start", f"{name} بدأ يلعب (باقي له {fmt(rem)})", name)
        self.show_timer()

    def end_session_ask(self):
        if not self.active:
            return
        v, _ = self.ask("إنهاء الجلسة", f"{self.active}، متأكد تبي تنهي جلستك؟\nالوقت الباقي يتحفظ لك.",
                        [("إيه، أنهِ", "yes"), ("لا", None)])
        if v and self.active:
            name = self.active
            self.log("end", f"{name} أنهى جلسته (باقي له {fmt(self.remaining(name))})", name)
            self.close_session()

    def close_session(self):
        self.active = None
        self.grace_left = None
        self.state["active"] = None
        self.save_state()
        self.show_lock()

    def lock_now(self):
        name = self.active
        self.log("lock", f"⛔ انقفل الجهاز على {name}: خلص وقته وخلصت المهلة", name, notify=True)
        beep()
        self.close_session()

    def extension_flow(self, name, from_lock=False):
        nb_used = self.state["nobody"].get(name, 0)
        nb_max = int(self.cfg["nobody_awake_per_day"])
        nb_min = int(self.cfg["nobody_awake_minutes"])
        left = nb_max - nb_used
        v, _ = self.ask("وقت إضافي", f"{name} يبي وقت إضافي. كيف؟",
                        [("موافقة الكبير (بالرمز)", "admin"),
                         (f"ما أحد صاحي ({nb_min} دقيقة)", "nobody"),
                         ("إلغاء", None)])
        if v == "admin":
            if not self.check_admin("الكبير يكتب رمزه عشان يوافق على الوقت الإضافي"):
                return
            m, _ = self.ask("كم دقيقة؟", f"كم دقيقة تعطي {name}؟",
                            [("10", "10"), ("15", "15"), ("30", "30"), ("60", "60"), ("إلغاء", None)])
            if not m:
                return
            self.grant(name, int(m), "admin")
        elif v == "nobody":
            if left <= 0:
                self.log("nobody_denied", f"⚠️ {name} حاول ياخذ وقت بخيار «ما أحد صاحي» بعد ما خلص الحد حقه اليوم",
                         name, notify=True)
                self.info("ما يصير", f"استخدمت خيار «ما أحد صاحي» {nb_used} مرة اليوم وهذا الحد.\n"
                                     "انتظر لين أحد يصحى. وانكتبت المحاولة في السجل.")
                return
            ok, _ = self.ask("متأكد؟",
                             f"بتاخذ {nb_min} دقيقة.\n"
                             "بتوصل رسالة للكل، وتنكتب في السجل باسمك والساعة.\n"
                             f"بعدها يبقى لك {left - 1} مرة اليوم.",
                             [("إيه، متأكد", "yes"), ("لا", None)])
            if not ok:
                return
            self.grant(name, nb_min, "nobody")
        else:
            return
        if from_lock and not self.active and self.remaining(name) > 0:
            self.start_session(name)

    def grant(self, name, minutes, by):
        self.state["bonus"][name] = self.state["bonus"].get(name, 0) + minutes * 60
        if by == "nobody":
            self.state["nobody"][name] = self.state["nobody"].get(name, 0) + 1
            text = f"⚠️ {name} أخذ {minutes} دقيقة إضافية بخيار «ما أحد صاحي»"
        elif by == "admin":
            text = f"✅ الكبير أعطى {name} {minutes} دقيقة إضافية"
        else:
            text = f"الكبير عدّل وقت {name}: {minutes:+d} دقيقة"
        self.save_state()
        self.log("extra_" + by, text, name, notify=True)
        if self.active == name and self.remaining(name) > 0:
            self.grace_left = None
            self.warned = self.remaining(name) <= int(self.cfg["warn_minutes"]) * 60
            self.update_timer_ui()

    # ---------- timer window
    def setup_timer_window(self):
        t = self.timer = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=CARD, highlightthickness=2, highlightbackground=ACCENT)
        t.protocol("WM_DELETE_WINDOW", lambda: None)
        self.t_name = tk.Label(t, text="", font=(FONT, 12, "bold"), bg=CARD, fg=FG)
        self.t_name.pack(pady=(8, 0), padx=16)
        self.t_status = tk.Label(t, text="", font=(FONT, 10), bg=CARD, fg=MUTED)
        self.t_status.pack()
        self.t_time = tk.Label(t, text="", font=(FONT, 28, "bold"), bg=CARD, fg=GOOD)
        self.t_time.pack(padx=16)
        row = tk.Frame(t, bg=CARD)
        row.pack(pady=(4, 10), padx=10)
        btn(row, "إنهاء", self.end_session_ask, bg=DIM, size=10).pack(side="right", padx=3)
        btn(row, "وقت إضافي", lambda: self.active and self.extension_flow(self.active),
            bg=ACCENT, size=10).pack(side="right", padx=3)
        for w in (t, self.t_name, self.t_status, self.t_time):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        t.withdraw()

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.timer.winfo_x(), e.y_root - self.timer.winfo_y()

    def _drag_move(self, e):
        self.timer.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def show_timer(self):
        self.root.withdraw()
        self.update_timer_ui()
        self.timer.deiconify()
        self.timer.update_idletasks()
        sw = self.root.winfo_screenwidth()
        self.timer.geometry(f"+{sw - self.timer.winfo_reqwidth() - 24}+24")
        self.timer.lift()

    def update_timer_ui(self):
        if not self.active:
            return
        self.t_name.configure(text=self.active)
        if self.grace_left is None:
            rem = self.remaining(self.active)
            warn = rem <= int(self.cfg["warn_minutes"]) * 60
            color = WARN if warn else GOOD
            self.t_status.configure(text="باقي من وقتك اليوم")
            self.t_time.configure(text=fmt(rem), fg=color)
        else:
            color = BAD
            self.t_status.configure(text="خلص وقتك! الجهاز بيتقفل بعد")
            self.t_time.configure(text=fmt(self.grace_left), fg=BAD)
        self.timer.configure(highlightbackground=color)

    def toast(self, title, msg, color=WARN):
        beep()
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=color, padx=22, pady=16)
        tk.Label(t, text=title, font=(FONT, 16, "bold"), bg=color, fg="white").pack(anchor="e")
        tk.Label(t, text=msg, font=(FONT, 12), bg=color, fg="white", justify="right",
                 wraplength=380).pack(anchor="e")
        t.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        t.geometry(f"+{(sw - t.winfo_reqwidth()) // 2}+{sh // 5}")
        t.bind("<Button-1>", lambda e: t.destroy())
        t.after(8000, lambda: t.winfo_exists() and t.destroy())

    # ---------- loops
    def tick(self):
        try:
            now = time.monotonic()
            dt = now - self.last
            self.last = now
            if dt < 0 or dt > 5:      # الجهاز كان نايم (Sleep) - ما نحسب
                dt = 0
            if self.ensure_today():
                self.warned = False
                self.grace_left = None
                if not self.active:
                    self.refresh_lock()
            name = self.active
            if name:
                if self.grace_left is None:
                    self.state["used"][name] = self.state["used"].get(name, 0) + dt
                    rem = self.remaining(name)
                    warn_s = int(self.cfg["warn_minutes"]) * 60
                    if not self.warned and 0 < rem <= warn_s:
                        self.warned = True
                        self.toast("تنبيه", f"{name}، باقي لك {fmt(rem)} بس.")
                    if rem <= 0:
                        g = int(self.cfg["grace_minutes"])
                        self.grace_left = g * 60
                        self.log("timeout", f"⏰ خلص وقت {name}. عنده {g} دقايق مهلة وبعدها ينقفل الجهاز",
                                 name, notify=True)
                        self.toast("خلص وقتك!", f"عندك {g} دقايق وبعدها ينقفل الجهاز.\n"
                                                "احفظ لعبتك، أو اطلب وقت إضافي.", BAD)
                else:
                    self.grace_left -= dt
                    if self.grace_left <= 0:
                        self.lock_now()
                self.update_timer_ui()
                self.save_tick += 1
                if self.save_tick >= 10:
                    self.save_tick = 0
                    self.save_state()
            else:
                self.clock_lbl.configure(text=datetime.datetime.now().strftime("%H:%M"))
        except Exception as ex:  # ما نبي البرنامج يطيح
            print("tick error:", ex)
        self.root.after(1000, self.tick)

    def keep_on_top(self):
        try:
            if self.dialogs:
                for d in list(self.dialogs):
                    if d.winfo_exists():
                        d.lift()
                        d.attributes("-topmost", True)
            elif not self.active:
                self.root.lift()
                self.root.attributes("-topmost", True)
            else:
                self.timer.lift()
                self.timer.attributes("-topmost", True)
        except Exception:
            pass
        self.root.after(500, self.keep_on_top)

    # ---------- log window
    def open_log(self):
        w = tk.Toplevel(self.root)
        w.title("السجل")
        w.configure(bg=CARD, padx=16, pady=16)
        w.attributes("-topmost", True)
        self.dialogs.append(w)

        def close():
            if w in self.dialogs:
                self.dialogs.remove(w)
            w.destroy()

        w.protocol("WM_DELETE_WINDOW", close)
        tk.Label(w, text="السجل (ما أحد يقدر يمسحه)", font=(FONT, 16, "bold"), bg=CARD, fg=FG).pack(anchor="e")
        frame = tk.Frame(w, bg=CARD)
        frame.pack(fill="both", expand=True, pady=10)
        sb = tk.Scrollbar(frame)
        sb.pack(side="left", fill="y")
        txt = tk.Text(frame, width=70, height=24, font=(FONT, 12), bg=BG, fg=FG, relief="flat",
                      yscrollcommand=sb.set, padx=10, pady=10)
        txt.pack(side="right", fill="both", expand=True)
        sb.configure(command=txt.yview)
        txt.tag_configure("r", justify="right")
        for e in read_log(500):
            txt.insert("end", f"{e['text']}    {entry_time(e)}\n", "r")
        txt.configure(state="disabled")
        btn(w, "إغلاق", close, bg=DIM).pack(anchor="e")
        w.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w.geometry(f"+{(sw - w.winfo_reqwidth()) // 2}+{max(0, (sh - w.winfo_reqheight()) // 3)}")
        w.lift()
        w.focus_force()

    # ---------- settings
    def open_settings(self):
        if not self.check_admin("الإعدادات للكبير بس"):
            return
        s = tk.Toplevel(self.root)
        s.title("الإعدادات")
        s.configure(bg=CARD, padx=20, pady=18)
        s.attributes("-topmost", True)
        self.dialogs.append(s)

        def close():
            if s in self.dialogs:
                self.dialogs.remove(s)
            s.destroy()
            if not self.active:
                self.refresh_lock()

        s.protocol("WM_DELETE_WINDOW", close)
        tk.Label(s, text="الإعدادات", font=(FONT, 18, "bold"), bg=CARD, fg=FG).pack(anchor="e")

        # players
        tk.Label(s, text="اللاعبين", font=(FONT, 13, "bold"), bg=CARD, fg=MUTED).pack(anchor="e", pady=(12, 4))
        pf = tk.Frame(s, bg=CARD)
        pf.pack(fill="x")
        lb = tk.Listbox(pf, font=(FONT, 12), width=38, height=6, justify="right", bg=BG, fg=FG,
                        selectbackground=ACCENT, relief="flat", exportselection=False)
        lb.pack(side="right")
        pbtns = tk.Frame(pf, bg=CARD)
        pbtns.pack(side="left", padx=(0, 10))

        def refresh_lb():
            lb.delete(0, "end")
            for p in self.cfg["players"]:
                lock = "  🔒" if p.get("pin") else ""
                lb.insert("end", f'{p["name"]} — {p["daily_minutes"]} دقيقة باليوم — باقي {fmt(self.remaining(p["name"]))}{lock}')

        def selected():
            sel = lb.curselection()
            if not sel:
                self.info("اختر لاعب", "اختر لاعب من القائمة أول.")
                return None
            return self.cfg["players"][sel[0]]

        def edit_player(p=None):
            v, vals = self.ask("لاعب جديد" if p is None else "تعديل لاعب",
                               "الرمز اختياري: لو حطيت رمز، ما أحد يقدر يلعب باسمه غيره.",
                               [("حفظ", True), ("إلغاء", None)],
                               fields=[("الاسم", p["name"] if p else "", False),
                                       ("الدقايق باليوم", p["daily_minutes"] if p else 120, False),
                                       ("رمز اللاعب", KEEP if p and p.get("pin") else "", False)])
            if not v:
                return
            name, mins, pin = vals[0].strip(), vals[1].strip(), vals[2].strip()
            if not name or not mins.isdigit():
                self.info("خطأ", "اكتب اسم، والدقايق لازم تكون رقم.")
                return
            if any(q["name"] == name and q is not p for q in self.cfg["players"]):
                self.info("خطأ", "فيه لاعب بنفس الاسم.")
                return
            if p is None:
                p = {"name": name, "daily_minutes": int(mins), "pin": ""}
                self.cfg["players"].append(p)
                self.log("settings", f"الكبير أضاف لاعب: {name} ({mins} دقيقة باليوم)", notify=True)
            else:
                old = p["name"]
                if old != name:
                    for k in ("used", "bonus", "nobody"):
                        if old in self.state[k]:
                            self.state[k][name] = self.state[k].pop(old)
                    if self.active == old:
                        self.active = name
                        self.state["active"] = name
                if int(mins) != int(p["daily_minutes"]) or old != name:
                    self.log("settings", f"الكبير عدّل {old}: صار {name}، {mins} دقيقة باليوم", notify=True)
                p["name"], p["daily_minutes"] = name, int(mins)
            if pin != KEEP:
                p["pin"] = hash_pin(pin) if pin else ""
            self.save_cfg()
            self.save_state()
            refresh_lb()

        def del_player():
            p = selected()
            if not p:
                return
            v, _ = self.ask("حذف", f"تحذف {p['name']}؟", [("احذف", "y"), ("لا", None)])
            if v:
                self.cfg["players"].remove(p)
                self.save_cfg()
                self.log("settings", f"الكبير حذف اللاعب {p['name']}", notify=True)
                refresh_lb()

        def add_time():
            p = selected()
            if not p:
                return
            v, vals = self.ask("تعديل وقت اليوم", f"كم دقيقة تضيف لـ {p['name']}؟ (حط سالب عشان تنقص، مثلاً -15)",
                               [("تم", True), ("إلغاء", None)], fields=[("الدقايق", "15", False)])
            if not v:
                return
            try:
                m = int(vals[0].strip())
            except ValueError:
                self.info("خطأ", "اكتب رقم.")
                return
            self.grant(p["name"], m, "admin" if m > 0 else "adjust")
            refresh_lb()

        def reset_day():
            p = selected()
            if not p:
                return
            v, _ = self.ask("تصفير", f"ترجع وقت {p['name']} لليوم من جديد؟", [("إيه", "y"), ("لا", None)])
            if v:
                for k in ("used", "bonus", "nobody"):
                    self.state[k].pop(p["name"], None)
                self.save_state()
                self.log("settings", f"الكبير صفّر وقت {p['name']} لليوم", notify=True)
                refresh_lb()

        for label, cmd in (("إضافة", lambda: edit_player()),
                           ("تعديل", lambda: (lambda p: p and edit_player(p))(selected())),
                           ("حذف", del_player), ("زيادة/نقص وقت", add_time), ("تصفير اليوم", reset_day)):
            btn(pbtns, label, cmd, bg=BG, size=10, width=12).pack(pady=2)
        refresh_lb()

        # general
        tk.Label(s, text="عام", font=(FONT, 13, "bold"), bg=CARD, fg=MUTED).pack(anchor="e", pady=(16, 4))
        gf = tk.Frame(s, bg=CARD)
        gf.pack(fill="x")
        fields = [("grace_minutes", "المهلة بعد ما يخلص الوقت (دقايق)"),
                  ("warn_minutes", "تنبيه قبل نهاية الوقت (دقايق)"),
                  ("nobody_awake_minutes", "وقت خيار «ما أحد صاحي» (دقايق)"),
                  ("nobody_awake_per_day", "كم مرة «ما أحد صاحي» باليوم لكل واحد"),
                  ("day_start_hour", "اليوم الجديد يبدأ الساعة (0-23)"),
                  ("telegram_token", "تيليجرام: توكن البوت"),
                  ("telegram_chat_id", "تيليجرام: رقم القروب (chat id)")]
        ents = {}
        for i, (key, label) in enumerate(fields):
            tk.Label(gf, text=label, font=(FONT, 11), bg=CARD, fg=FG).grid(row=i, column=1, sticky="e", pady=3)
            e = tk.Entry(gf, font=(FONT, 11), width=30 if key.startswith("telegram") else 8, justify="right")
            e.insert(0, str(self.cfg.get(key, "")))
            e.grid(row=i, column=0, sticky="w", padx=(0, 12), pady=3)
            ents[key] = e

        auto_var = tk.BooleanVar(value=bool(self.cfg.get("autostart")))
        if IS_WIN:
            tk.Checkbutton(s, text="يشتغل تلقائياً مع تشغيل ويندوز", variable=auto_var, font=(FONT, 11),
                           bg=CARD, fg=FG, selectcolor=BG, activebackground=CARD,
                           activeforeground=FG).pack(anchor="e", pady=(8, 0))

        def collect():
            new = {}
            for key, _ in fields:
                val = ents[key].get().strip()
                if key.startswith("telegram"):
                    new[key] = val
                else:
                    if not val.isdigit():
                        self.info("خطأ", "كل الخانات اللي فوق التيليجرام لازم تكون أرقام.")
                        return None
                    new[key] = int(val)
            if new["day_start_hour"] > 23:
                self.info("خطأ", "ساعة بداية اليوم لازم تكون بين 0 و 23.")
                return None
            return new

        def test_tg():
            new = collect()
            if new is None:
                return
            ok, err = telegram_send_sync(new, "⏱ وقتي: رسالة تجربة. إذا وصلتكم، التيليجرام شغال ✅")
            self.info("تجربة تيليجرام", "وصلت الرسالة ✅" if ok else f"ما وصلت ❌\n{err}")

        def change_admin_pin():
            v, vals = self.ask("رمز الكبير الجديد", "", [("حفظ", True), ("إلغاء", None)],
                               fields=[("الرمز الجديد", "", True), ("أعده مرة ثانية", "", True)])
            if not v:
                return
            if not vals[0].strip() or vals[0] != vals[1]:
                self.info("خطأ", "الرمزين مو نفس بعض، أو فاضي.")
                return
            self.cfg["admin_pin"] = hash_pin(vals[0])
            self.save_cfg()
            self.log("settings", "الكبير غيّر رمز الإدارة", notify=True)
            self.info("تم", "تغيّر الرمز.")

        def save():
            new = collect()
            if new is None:
                return
            changed = {k: v for k, v in new.items() if self.cfg.get(k) != v}
            self.cfg.update(new)
            if IS_WIN and bool(auto_var.get()) != bool(self.cfg.get("autostart")):
                try:
                    set_autostart(bool(auto_var.get()))
                    self.cfg["autostart"] = bool(auto_var.get())
                except Exception as ex:
                    self.info("خطأ", f"ما قدرت أضبط التشغيل التلقائي:\n{ex}")
            self.save_cfg()
            visible = [k for k in changed if not k.startswith("telegram")]
            if visible:
                self.log("settings", "الكبير غيّر الإعدادات: " + "، ".join(f"{k}={changed[k]}" for k in visible),
                         notify=True)
            close()

        bb = tk.Frame(s, bg=CARD)
        bb.pack(fill="x", pady=(16, 0))
        btn(bb, "حفظ وإغلاق", save, bg=GOOD).pack(side="right", padx=4)
        btn(bb, "تجربة تيليجرام", test_tg, bg=BG).pack(side="right", padx=4)
        btn(bb, "تغيير رمز الكبير", change_admin_pin, bg=BG).pack(side="right", padx=4)
        btn(bb, "إلغاء", close, bg=DIM).pack(side="left", padx=4)

        s.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        s.geometry(f"+{(sw - s.winfo_reqwidth()) // 2}+{max(0, (sh - s.winfo_reqheight()) // 4)}")
        s.lift()
        s.focus_force()

    # ---------- exit
    def exit_app(self):
        if not self.check_admin("إغلاق البرنامج للكبير بس"):
            return
        v, _ = self.ask("إغلاق", "إذا قفلت البرنامج الجهاز يصير مفتوح بدون حد للوقت. متأكد؟",
                        [("إيه، اقفله", "y"), ("لا", None)])
        if not v:
            return
        self.log("app_exit", "الكبير قفل البرنامج", notify=True)
        self.state["active"] = None
        self.save_state()
        self.root.after(800, self.root.destroy)  # نعطي التيليجرام فرصة

    def run(self):
        self.root.mainloop()


_instance_lock = None


def main():
    # نسخة وحدة بس من البرنامج
    global _instance_lock
    _instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for _ in range(20):  # بعد التحديث ننتظر النسخة القديمة تطلع
        try:
            _instance_lock.bind(("127.0.0.1", 47613))
            break
        except OSError:
            time.sleep(0.5)
    else:
        return
    App().run()


if __name__ == "__main__":
    main()
