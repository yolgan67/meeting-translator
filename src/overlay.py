"""Her zaman ustte duran, yari saydam altyazi penceresi (Tkinter).

Electron/Qt yerine stdlib Tkinter kullanilir: ek RAM ve disk maliyeti ~0.
Gorunum ayarlari sag ustteki dis simgesinden canli degistirilebilir
(bkz. settings_panel.py).
"""
from __future__ import annotations

import queue
import tempfile
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

# "Geri getir" bayragi: calisan ornek bu dosyayi gozler, ikinci kez baslatilan
# uygulama (--show) dosyayi yazip cikar. Global kisayol kaydolmazsa gizlenen
# pencerenin geri getirilmesinin tek yolu bu; gizli pencere odak alamiyor.
SHOW_FLAG = Path(tempfile.gettempdir()) / "meeting-translator-show.flag"

BAR_BG = "#171c22"
FG_DIM = "#5c6773"

BAR_H = 26          # baslik cubugu
TEXT_PADY = 8       # Text widget'inin ust/alt boslugu
ENTRY_GAP = 10      # replikler arasi bosluk (bos satir yerine paragraf araligi)

MODES = ("bilingual", "tr_only", "en_only")
MODE_LABELS = {"bilingual": "iki dilli", "tr_only": "sadece TR", "en_only": "sadece EN"}

HOTKEY_HINT = "Ctrl+Shift+L mod  |  H gizle  |  P duraklat  |  Q cikis"


@dataclass
class Line:
    clock: str
    en: str
    tr: str


def _mix(color: str, other: str, ratio: float) -> str:
    """Iki rengi karistirir; ara altyazinin soluk tonunu uretmek icin."""
    try:
        c1 = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
        c2 = [int(other[i : i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, IndexError):
        return color
    mixed = [round(a * (1 - ratio) + b * ratio) for a, b in zip(c1, c2)]
    return "#{:02x}{:02x}{:02x}".format(*mixed)


class Overlay:
    def __init__(self, cfg: dict, ui_queue: "queue.Queue", on_quit=None,
                 on_mode_change=None) -> None:
        self.cfg = dict(cfg)
        self.ui_queue = ui_queue
        self.on_quit = on_quit
        # Pipeline mod degisikligini bilmek ister: "en_only" iken ceviri yapilmaz
        # ve ceviri modeli bellekten bosaltilir.
        self.on_mode_change = on_mode_change
        self.mode = self.cfg.get("mode", "bilingual")
        self.max_lines = int(self.cfg.get("max_lines", 4))
        self.paused = False
        self.hidden = False
        self.global_hotkeys = False
        self.settings_panel = None
        self.height_capped = False
        self._lines: list[Line] = []
        self._partial: Line | None = None
        self._commands: "queue.Queue[str]" = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Toplanti Cevirmeni")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", float(self.cfg.get("opacity", 0.85)))
        self.root.configure(bg=self._bg())

        self.auto_height = bool(self.cfg.get("auto_height", True))
        w = int(self.cfg.get("width", 900))
        h = int(self.cfg.get("height", 260))
        x = (self.root.winfo_screenwidth() - w) // 2
        y = self.root.winfo_screenheight() - h - int(self.cfg.get("margin_bottom", 80))
        self.root.geometry(f"{w}x{h}+{x}+{max(0, y)}")

        self._build_widgets()
        self._apply_styles()
        self._fit_height()
        self._bind_keys()
        self._register_global_hotkeys()
        self.set_status(FG_DIM, "hazirlaniyor")

    # ------------------------------------------------------------------ renkler
    def _bg(self) -> str:
        return self.cfg.get("color_bg", "#0f1216")

    def _fg_tr(self) -> str:
        return self.cfg.get("color_tr", "#ffffff")

    def _fg_en(self) -> str:
        return self.cfg.get("color_en", "#8b98a5")

    # ---------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        bar = tk.Frame(self.root, bg=BAR_BG, height=26)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)

        self.status_dot = tk.Label(bar, text="●", bg=BAR_BG, fg=FG_DIM,
                                   font=("Segoe UI", 11))
        self.status_dot.pack(side="left", padx=(8, 4))
        self.status_label = tk.Label(bar, text="", bg=BAR_BG, fg=FG_DIM,
                                     font=("Segoe UI", 8))
        self.status_label.pack(side="left")

        hint = tk.Label(bar, text=HOTKEY_HINT, bg=BAR_BG, fg=FG_DIM, font=("Segoe UI", 8))
        hint.pack(side="left", padx=12)

        tk.Button(
            bar, text="×", command=self._quit, bg=BAR_BG, fg=self._fg_en(),
            relief="flat", bd=0, font=("Segoe UI", 11), activebackground=BAR_BG,
            activeforeground="#ff6b6b", cursor="hand2",
        ).pack(side="right", padx=(2, 6))

        self.gear = tk.Button(
            bar, text="⚙", command=self.open_settings, bg=BAR_BG, fg=self._fg_en(),
            relief="flat", bd=0, font=("Segoe UI", 11), activebackground=BAR_BG,
            activeforeground="#ffffff", cursor="hand2",
        )
        self.gear.pack(side="right", padx=2)

        self.mode_label = tk.Label(bar, text="", bg=BAR_BG, fg=FG_DIM,
                                   font=("Segoe UI", 8))
        self.mode_label.pack(side="right", padx=6)

        # Baslik cubugundan pencereyi surukle
        for widget in (bar, self.status_label, hint, self.mode_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        self.text = tk.Text(
            self.root, bg=self._bg(), wrap="word", relief="flat", bd=0,
            highlightthickness=0, padx=14, pady=8, cursor="arrow",
            insertwidth=0, spacing1=1, spacing3=0,
        )
        self.text.pack(side="top", fill="both", expand=True)
        self.text.configure(state="disabled")

    def _apply_styles(self) -> None:
        """Renk/font ayarlarini widget'lara yazar (canli degisiklikte de cagrilir)."""
        bg, fg_tr, fg_en = self._bg(), self._fg_tr(), self._fg_en()
        size_tr = int(self.cfg.get("font_size_tr", 22))
        size_en = int(self.cfg.get("font_size_en", 12))

        self.root.configure(bg=bg)
        self.text.configure(bg=bg, fg=fg_tr)
        self.text.tag_configure("en", foreground=fg_en, font=("Segoe UI", size_en))
        self.text.tag_configure("tr", foreground=fg_tr,
                                font=("Segoe UI Semibold", size_tr),
                                spacing3=ENTRY_GAP)
        # Sadece Ingilizce modunda Ingilizce satir ana satir olur: buyuk ve parlak.
        self.text.tag_configure("en_big", foreground=fg_tr,
                                font=("Segoe UI Semibold", size_tr),
                                spacing3=ENTRY_GAP)
        self.text.tag_configure("clock", foreground=_mix(fg_en, bg, 0.35),
                                font=("Consolas", 8))
        self.text.tag_configure("en_partial", foreground=_mix(fg_en, bg, 0.45),
                                font=("Segoe UI", size_en))
        self.text.tag_configure("tr_partial", foreground=_mix(fg_tr, bg, 0.4),
                                font=("Segoe UI", size_tr))
        self.mode_label.configure(text=MODE_LABELS.get(self.mode, self.mode))

    def _fit_height(self) -> None:
        """Pencere yuksekligini max_lines ve yazi boyutuna gore ayarlar.

        Yuksekligi sabit birakinca "ekrandaki satir" ayarinin gorunur bir etkisi
        olmuyordu: 8 replik tutulsa da pencereye 2-3 tanesi siginiyordu. Alt kenar
        sabit kalir, pencere yukari dogru buyur.
        """
        if not self.auto_height:
            return
        # Pencere yuksekligi degisince Tk metni yeniden yerlestirir ve icerik
        # yuksekligi de degisebilir; olcum-boyutlandirma bir kez yapilinca bir
        # adim geride kaliyordu. Bir kac tur donerek oturmasini bekliyoruz.
        for _ in range(3):
            if not self._fit_height_once():
                break

    def _fonts(self) -> dict:
        import tkinter.font as tkfont

        size_tr = int(self.cfg.get("font_size_tr", 22))
        size_en = int(self.cfg.get("font_size_en", 12))
        big = tkfont.Font(font=("Segoe UI Semibold", size_tr))
        return {
            "tr": big, "en_big": big,
            "tr_partial": tkfont.Font(font=("Segoe UI", size_tr)),
            "en": tkfont.Font(font=("Segoe UI", size_en)),
            "en_partial": tkfont.Font(font=("Segoe UI", size_en)),
        }

    def _content_height(self) -> int:
        """Icerigin kaplayacagi pikseli yazi tipi olcusunden hesaplar.

        Tk'nin 'count -ypixels' sayaci ekranda gorunmeyen satirlari eksik
        olctugu icin (pencere sona kaydirildiginda ustteki replikler
        yerlestirilmiyor) pencere surekli kisa kaliyordu; bu yuzden genislige
        gore satir kaydirmasi burada kendimiz hesaplaniyor.
        """
        fonts = self._fonts()
        usable = max(120, self.root.winfo_width() - 2 * 14 - 6)
        total = 0
        last = int(self.text.index("end-1c").split(".")[0])
        for i in range(1, last + 1):
            start = f"{i}.0"
            text = self.text.get(start, f"{i}.end")
            tags = [t for t in self.text.tag_names(start) if t in fonts]
            font = fonts[tags[-1]] if tags else fonts["tr"]
            wraps = max(1, -(-font.measure(text) // usable)) if text else 1
            total += wraps * font.metrics("linespace")
            if any(t in ("tr", "en_big") for t in self.text.tag_names(start)):
                total += ENTRY_GAP
        return total

    def _fit_height_once(self) -> bool:
        """Bir olcum-boyutlandirma turu; boyut degistiyse True doner."""
        self.root.update_idletasks()
        content = self._content_height()

        # Icerik henuz azken pencere tamamen buzusmesin.
        tr_h = self._fonts()["tr"].metrics("linespace")
        floor = BAR_H + 2 * TEXT_PADY + int(tr_h * 1.6)
        need = max(floor, BAR_H + 2 * TEXT_PADY + content + 6)

        screen_h = self.root.winfo_screenheight()
        limit = int(screen_h * 0.7)
        target = max(90, min(need, limit))
        # Ayar penceresi kullaniciya soyleyebilsin: istenen satir sayisi ekrana
        # sigmiyorsa yazi boyutunu kucultmek gerekir.
        self.height_capped = need > limit

        cur_h = self.root.winfo_height()
        # Kucuk dalgalanmalarda pencereyi oynatma (yazi akarken titremesin).
        if abs(target - cur_h) < 18:
            return False
        bottom = self.root.winfo_y() + cur_h
        y = max(0, bottom - target)
        self.root.geometry(f"{self.root.winfo_width()}x{target}+{self.root.winfo_x()}+{y}")
        return True

    def apply_settings(self, values: dict) -> None:
        """Ayar penceresinden gelen degerleri aninda uygular."""
        old_mode = self.mode
        self.cfg.update(values)
        self.mode = self.cfg.get("mode", "bilingual")
        self.max_lines = int(self.cfg.get("max_lines", 4))
        self.root.attributes("-alpha", float(self.cfg.get("opacity", 0.85)))
        self.auto_height = bool(self.cfg.get("auto_height", self.auto_height))
        self._apply_styles()
        del self._lines[: max(0, len(self._lines) - self.max_lines)]
        if not self.cfg.get("show_partial", True):
            self._partial = None
        self._render()
        self._fit_height()
        if self.mode != old_mode and self.on_mode_change:
            self.on_mode_change(self.mode)

    def open_settings(self) -> None:
        from .settings_panel import SettingsPanel

        if self.settings_panel is not None:
            try:
                self.settings_panel.win.lift()
                self.settings_panel.win.focus_force()
                return
            except tk.TclError:
                self.settings_panel = None
        self.settings_panel = SettingsPanel(self)

    # ------------------------------------------------------------------- keys
    def _bind_keys(self) -> None:
        for seq, cmd in (
            ("<Control-Shift-L>", "mode"), ("<Control-Shift-l>", "mode"),
            ("<Control-Shift-H>", "hide"), ("<Control-Shift-h>", "hide"),
            ("<Control-Shift-P>", "pause"), ("<Control-Shift-p>", "pause"),
            ("<Control-Shift-Q>", "quit"), ("<Control-Shift-q>", "quit"),
            ("<Control-Shift-S>", "settings"), ("<Control-Shift-s>", "settings"),
        ):
            self.root.bind(seq, lambda e, c=cmd: self._cmd(c))

    def _register_global_hotkeys(self) -> None:
        """Pencere odakta olmasa da (toplanti sirasinda oyle olacak) calissin."""
        try:
            import keyboard

            for combo, cmd in (("ctrl+shift+l", "mode"), ("ctrl+shift+h", "hide"),
                               ("ctrl+shift+p", "pause"), ("ctrl+shift+q", "quit"),
                               ("ctrl+shift+s", "settings")):
                keyboard.add_hotkey(combo, lambda c=cmd: self._cmd(c))
            self.global_hotkeys = True
        except Exception:
            # keyboard yoksa/izin yoksa pencere odaktayken kisayollar yine calisir.
            self.global_hotkeys = False

    def _cmd(self, name: str) -> None:
        """Baska thread'lerden de guvenli: komut kuyruga yazilir, _poll isler."""
        self._commands.put(name)

    # ------------------------------------------------------------------- drag
    def _drag_start(self, event) -> None:
        self._drag_origin = (event.x_root, event.y_root,
                             self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event) -> None:
        x0, y0, wx, wy = getattr(self, "_drag_origin", (0, 0, 0, 0))
        self.root.geometry(f"+{wx + event.x_root - x0}+{wy + event.y_root - y0}")

    # ------------------------------------------------------------------ state
    def set_status(self, color: str, text: str) -> None:
        self.status_dot.configure(fg=color)
        if self.paused:
            text = "durakladi - " + text
        if not self.global_hotkeys:
            text += "  (kisayollar sadece pencere odaktayken)"
        self.status_label.configure(text=text)

    def add_line(self, clock: str, en: str, tr: str) -> None:
        self._partial = None  # nihai metin ara altyazinin yerini alir
        self._lines.append(Line(clock, en, tr))
        del self._lines[: max(0, len(self._lines) - self.max_lines)]
        self._render()
        self._fit_height()

    def set_partial(self, clock: str, en: str, tr: str) -> None:
        if not self.cfg.get("show_partial", True):
            return
        self._partial = Line(clock, en, tr)
        self._render()
        self._fit_height()

    def _render(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in self._lines:
            if self.mode == "en_only":
                self.text.insert("end", f"[{line.clock}] ", "clock")
                self.text.insert("end", line.en + "\n\n", "en_big")
                continue
            if self.mode == "bilingual":
                self.text.insert("end", f"[{line.clock}] ", "clock")
                self.text.insert("end", line.en + "\n", "en")
            self.text.insert("end", (line.tr or line.en) + "\n\n", "tr")

        if self._partial:
            if self.mode == "en_only":
                self.text.insert("end", self._partial.en + "\n", "tr_partial")
            else:
                if self.mode == "bilingual":
                    self.text.insert("end", self._partial.en + "\n", "en_partial")
                self.text.insert("end", (self._partial.tr or self._partial.en) + "\n",
                                 "tr_partial")
        self.text.configure(state="disabled")
        self.text.see("end")

    def _cycle_mode(self) -> None:
        nxt = MODES[(MODES.index(self.mode) + 1) % len(MODES)] \
            if self.mode in MODES else MODES[0]
        self.apply_settings({"mode": nxt})

    def _toggle_hidden(self) -> None:
        self.hidden = not self.hidden
        if self.hidden:
            self.root.withdraw()
        else:
            self.show()

    def show(self) -> None:
        """Pencereyi gorunur yapar ve ekran disinda kaldiysa geri alir."""
        self.hidden = False
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self._ensure_on_screen()

    def center(self) -> None:
        """Pencereyi ekranin altina, ortaya yerlestirir."""
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max(0, self.root.winfo_screenheight() - h - int(self.cfg.get("margin_bottom", 80)))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _ensure_on_screen(self) -> None:
        """Pencere surukleyerek ekran disina tasindiysa geri ceker.

        Baslik cubugu olmadigi icin tamamen ekran disina cikan pencere fareyle
        yakalanamaz; en az bir kismi her zaman ekranda kalmali.
        """
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        # Baslik cubugundan tutup surukleyebilmek icin bu kadari ekranda kalsin.
        margin = 240
        nx = min(max(x, margin - w), sw - margin)
        ny = min(max(y, 0), sh - BAR_H - 4)
        if (nx, ny) != (x, y):
            self.root.geometry(f"{w}x{h}+{nx}+{ny}")

    def _quit(self) -> None:
        if self.on_quit:
            self.on_quit()
        self.root.quit()

    # ------------------------------------------------------------------- loop
    def _poll(self) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                break
            if cmd == "mode":
                self._cycle_mode()
            elif cmd == "hide":
                self._toggle_hidden()
            elif cmd == "settings":
                self.open_settings()
            elif cmd == "pause":
                self.paused = not self.paused
                self.set_status(FG_DIM if self.paused else "#3ddc84",
                                "duraklatildi" if self.paused else "dinleniyor")
            elif cmd == "quit":
                self._quit()
                return

        while True:
            try:
                item = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if item[0] == "line":
                _, clock, en, tr = item
                self.add_line(clock, en, tr)
            elif item[0] == "partial":
                _, clock, en, tr = item
                self.set_partial(clock, en, tr)
            elif item[0] == "status":
                _, color, text = item
                self.set_status(color, text)

        # Saniyede bir "geri getir" bayragina bak (maliyeti ihmal edilebilir).
        self._poll_count = getattr(self, "_poll_count", 0) + 1
        if self._poll_count % 10 == 0 and SHOW_FLAG.exists():
            try:
                SHOW_FLAG.unlink()
            except OSError:
                pass
            self.show()
            self.center()
            self.set_status("#3ddc84", "pencere geri getirildi")

        self.root.after(100, self._poll)

    def run(self) -> None:
        self.root.after(100, self._poll)
        self.root.mainloop()
