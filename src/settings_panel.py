"""Dis simgesinden acilan ayar penceresi.

Ayni Tk dongusunde bir Toplevel olarak acilir; kapaliyken hicbir maliyeti yoktur,
acikken ~1-2 MB. Degisiklikler aninda uygulanir, "Kaydet" ile config.yaml'a yazilir.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, ttk

PANEL_BG = "#171c22"
PANEL_FG = "#e6edf3"
PANEL_DIM = "#8b98a5"

MODES = (
    ("bilingual", "Iki dilli  (Ingilizce + Turkce)"),
    ("tr_only", "Sadece Turkce"),
    ("en_only", "Sadece Ingilizce  (ceviri kapali, ~250 MB RAM serbest)"),
)


class SettingsPanel:
    """Overlay'in gorunum ayarlarini duzenler. Tek ornek olarak acilir."""

    def __init__(self, overlay) -> None:
        self.overlay = overlay
        self.win = tk.Toplevel(overlay.root)
        self.win.title("Ayarlar")
        self.win.configure(bg=PANEL_BG)
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        cfg = overlay.cfg
        self.mode = tk.StringVar(value=overlay.mode)
        self.font_tr = tk.IntVar(value=int(cfg.get("font_size_tr", 22)))
        self.font_en = tk.IntVar(value=int(cfg.get("font_size_en", 12)))
        self.opacity = tk.DoubleVar(value=float(cfg.get("opacity", 0.85)))
        self.max_lines = tk.IntVar(value=int(cfg.get("max_lines", 4)))
        self.show_partial = tk.BooleanVar(value=bool(cfg.get("show_partial", True)))
        self.color_tr = cfg.get("color_tr", "#ffffff")
        self.color_en = cfg.get("color_en", "#8b98a5")
        self.color_bg = cfg.get("color_bg", "#0f1216")

        self.status: tk.Label | None = None  # _build icinde olusturulur
        self._build()
        self._place_near_overlay()

    # ---------------------------------------------------------------- yerlesim
    def _build(self) -> None:
        pad = {"padx": 12, "pady": 4}
        row = 0

        self._header("Gorunum modu", row)
        row += 1
        for value, label in MODES:
            tk.Radiobutton(
                self.win, text=label, value=value, variable=self.mode,
                command=self._apply, bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
                activebackground=PANEL_BG, activeforeground=PANEL_FG,
                highlightthickness=0, anchor="w", font=("Segoe UI", 9),
            ).grid(row=row, column=0, columnspan=3, sticky="w", **pad)
            row += 1

        self._header("Yazi boyutu", row)
        row += 1
        row = self._spin_row("Turkce", self.font_tr, 10, 60, row)
        row = self._spin_row("Ingilizce", self.font_en, 8, 40, row)

        self._header("Renkler", row)
        row += 1
        row = self._color_row("Turkce yazi", "color_tr", row)
        row = self._color_row("Ingilizce yazi", "color_en", row)
        row = self._color_row("Arka plan", "color_bg", row)

        self._header("Pencere", row)
        row += 1
        tk.Label(self.win, text="Saydamlik", bg=PANEL_BG, fg=PANEL_FG,
                 font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", **pad)
        tk.Scale(
            self.win, from_=0.3, to=1.0, resolution=0.05, orient="horizontal",
            variable=self.opacity, command=lambda _=None: self._apply(),
            bg=PANEL_BG, fg=PANEL_FG, troughcolor="#0f1216", highlightthickness=0,
            length=170, showvalue=True, font=("Segoe UI", 8),
        ).grid(row=row, column=1, columnspan=2, sticky="w", padx=(0, 12))
        row += 1

        row = self._spin_row("Ekranda kac replik", self.max_lines, 1, 10, row)

        tk.Checkbutton(
            self.win, text="Ara altyazi (cumle bitmeden gosterilen soluk satir)",
            variable=self.show_partial, command=self._apply,
            bg=PANEL_BG, fg=PANEL_FG, selectcolor=PANEL_BG,
            activebackground=PANEL_BG, activeforeground=PANEL_FG,
            highlightthickness=0, anchor="w", font=("Segoe UI", 9),
        ).grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        self.status = tk.Label(self.win, text="", bg=PANEL_BG, fg=PANEL_DIM,
                               font=("Segoe UI", 8))
        self.status.grid(row=row, column=0, columnspan=3, sticky="w", padx=12)
        row += 1

        btns = tk.Frame(self.win, bg=PANEL_BG)
        btns.grid(row=row, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 12))
        tk.Button(btns, text="Kaydet", command=self._save, bg="#2d7ff9", fg="white",
                  relief="flat", font=("Segoe UI", 9), padx=14, cursor="hand2",
                  activebackground="#1f68d6", activeforeground="white").pack(side="left")
        tk.Button(btns, text="Pencereyi ortala", command=self._center, bg="#273039",
                  fg=PANEL_FG, relief="flat", font=("Segoe UI", 9), padx=10,
                  cursor="hand2", activebackground="#313c46",
                  activeforeground=PANEL_FG).pack(side="left", padx=6)
        tk.Button(btns, text="Varsayilana don", command=self._reset, bg="#273039",
                  fg=PANEL_FG, relief="flat", font=("Segoe UI", 9), padx=10,
                  cursor="hand2", activebackground="#313c46",
                  activeforeground=PANEL_FG).pack(side="left", padx=6)
        tk.Button(btns, text="Kapat", command=self.close, bg="#273039", fg=PANEL_FG,
                  relief="flat", font=("Segoe UI", 9), padx=14, cursor="hand2",
                  activebackground="#313c46", activeforeground=PANEL_FG).pack(side="right")

    def _header(self, text: str, row: int) -> None:
        tk.Label(self.win, text=text.upper(), bg=PANEL_BG, fg=PANEL_DIM,
                 font=("Segoe UI", 8, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 2))

    def _spin_row(self, label: str, var: tk.IntVar, lo: int, hi: int, row: int) -> int:
        tk.Label(self.win, text=label, bg=PANEL_BG, fg=PANEL_FG,
                 font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", padx=12, pady=4)
        ttk.Spinbox(self.win, from_=lo, to=hi, textvariable=var, width=6,
                    command=self._apply).grid(row=row, column=1, sticky="w")
        return row + 1

    def _color_row(self, label: str, attr: str, row: int) -> int:
        tk.Label(self.win, text=label, bg=PANEL_BG, fg=PANEL_FG,
                 font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", padx=12, pady=4)
        swatch = tk.Button(
            self.win, text="   ", bg=getattr(self, attr), relief="flat", width=4,
            cursor="hand2", command=lambda: self._pick_color(attr, swatch),
        )
        swatch.grid(row=row, column=1, sticky="w")
        tk.Label(self.win, text=getattr(self, attr), bg=PANEL_BG, fg=PANEL_DIM,
                 font=("Consolas", 8), name=f"lbl_{attr}").grid(
            row=row, column=2, sticky="w", padx=(6, 12))
        return row + 1

    def _place_near_overlay(self) -> None:
        self.win.update_idletasks()
        ox, oy = self.overlay.root.winfo_x(), self.overlay.root.winfo_y()
        w = self.win.winfo_width()
        x = max(0, ox + self.overlay.root.winfo_width() - w)
        y = max(0, oy - self.win.winfo_height() - 8)
        self.win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------ islem
    def _pick_color(self, attr: str, swatch: tk.Button) -> None:
        current = getattr(self, attr)
        _rgb, chosen = colorchooser.askcolor(color=current, parent=self.win,
                                             title="Renk sec")
        if not chosen:
            return
        setattr(self, attr, chosen)
        swatch.configure(bg=chosen)
        try:
            self.win.nametowidget(f"lbl_{attr}").configure(text=chosen)
        except Exception:
            pass
        self._apply()

    def _values(self) -> dict:
        return {
            "mode": self.mode.get(),
            "font_size_tr": int(self.font_tr.get()),
            "font_size_en": int(self.font_en.get()),
            "opacity": round(float(self.opacity.get()), 2),
            "max_lines": int(self.max_lines.get()),
            "show_partial": bool(self.show_partial.get()),
            "color_tr": self.color_tr,
            "color_en": self.color_en,
            "color_bg": self.color_bg,
        }

    def _apply(self) -> None:
        try:
            self.overlay.apply_settings(self._values())
            if getattr(self.overlay, "height_capped", False):
                self._say("bu kadar satir ekrana sigmiyor - yazi boyutunu kucult")
            else:
                self._say("uygulandi (kalici olmasi icin Kaydet)")
        except Exception as exc:
            self._say(f"hata: {exc}")

    def _save(self) -> None:
        from .config import save_ui_settings

        try:
            self.overlay.apply_settings(self._values())
            path = save_ui_settings(self._values())
            self._say(f"kaydedildi -> {path.name}")
        except Exception as exc:
            self._say(f"kaydedilemedi: {exc}")

    def _center(self) -> None:
        self.overlay.show()
        self.overlay.center()
        self._place_near_overlay()
        self._say("pencere ekranin altina ortalandi")

    def _reset(self) -> None:
        from .config import DEFAULTS

        d = DEFAULTS["ui"]
        self.mode.set(d["mode"])
        self.font_tr.set(d["font_size_tr"])
        self.font_en.set(d["font_size_en"])
        self.opacity.set(d["opacity"])
        self.max_lines.set(d["max_lines"])
        self.show_partial.set(d["show_partial"])
        self.color_tr, self.color_en, self.color_bg = (
            d["color_tr"], d["color_en"], d["color_bg"])
        self._apply()
        self._say("varsayilanlar uygulandi (Kaydet ile yaz)")

    def _say(self, text: str) -> None:
        if self.status is not None:
            self.status.configure(text=text)

    def close(self) -> None:
        self.overlay.settings_panel = None
        self.win.destroy()
