"""Her zaman ustte duran, yari saydam altyazi penceresi (Tkinter).

Electron/Qt yerine stdlib Tkinter kullanilir: ek RAM ve disk maliyeti ~0.
"""
from __future__ import annotations

import queue
import tkinter as tk
from dataclasses import dataclass

BG = "#0f1216"
BAR_BG = "#171c22"
FG_TR = "#ffffff"
FG_EN = "#8b98a5"
FG_DIM = "#5c6773"
FG_PARTIAL = "#9fb0c0"   # kesinlesmemis (ara) altyazi

HOTKEY_HINT = "Ctrl+Shift+L mod  |  H gizle  |  P duraklat  |  Q cikis"


@dataclass
class Line:
    clock: str
    en: str
    tr: str


class Overlay:
    def __init__(self, cfg: dict, ui_queue: "queue.Queue", on_quit=None) -> None:
        self.cfg = cfg
        self.ui_queue = ui_queue
        self.on_quit = on_quit
        self.mode = cfg.get("mode", "bilingual")
        self.max_lines = int(cfg.get("max_lines", 4))
        self.paused = False
        self.hidden = False
        self.global_hotkeys = False
        self._lines: list[Line] = []
        self._partial: Line | None = None
        self._commands: "queue.Queue[str]" = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Toplanti Cevirmeni")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", float(cfg.get("opacity", 0.85)))
        self.root.configure(bg=BG)

        w = int(cfg.get("width", 900))
        h = int(cfg.get("height", 260))
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = sh - h - int(cfg.get("margin_bottom", 80))
        self.root.geometry(f"{w}x{h}+{x}+{max(0, y)}")

        self._build_widgets()
        self._bind_keys()
        self._register_global_hotkeys()
        self.set_status(FG_DIM, "hazirlaniyor")

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
            bar, text="×", command=self._quit, bg=BAR_BG, fg=FG_EN,
            relief="flat", bd=0, font=("Segoe UI", 11), activebackground=BAR_BG,
            activeforeground="#ff6b6b", cursor="hand2",
        ).pack(side="right", padx=6)

        # Baslik cubugundan pencereyi surukle
        for widget in (bar, self.status_label, hint):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        self.text = tk.Text(
            self.root, bg=BG, fg=FG_TR, wrap="word", relief="flat", bd=0,
            highlightthickness=0, padx=14, pady=8, cursor="arrow",
            insertwidth=0, spacing1=2, spacing3=6,
        )
        self.text.pack(side="top", fill="both", expand=True)
        self.text.tag_configure("en", foreground=FG_EN,
                                font=("Segoe UI", int(self.cfg.get("font_size_en", 12))))
        self.text.tag_configure("tr", foreground=FG_TR,
                                font=("Segoe UI Semibold", int(self.cfg.get("font_size_tr", 22))))
        self.text.tag_configure("clock", foreground=FG_DIM, font=("Consolas", 8))
        # Ara altyazi: henuz kesinlesmemis, daha soluk gosterilir.
        self.text.tag_configure("en_partial", foreground=FG_DIM,
                                font=("Segoe UI", int(self.cfg.get("font_size_en", 12))))
        self.text.tag_configure("tr_partial", foreground=FG_PARTIAL,
                                font=("Segoe UI", int(self.cfg.get("font_size_tr", 22))))
        self.text.configure(state="disabled")

    # ------------------------------------------------------------------- keys
    def _bind_keys(self) -> None:
        for seq, cmd in (
            ("<Control-Shift-L>", "mode"), ("<Control-Shift-l>", "mode"),
            ("<Control-Shift-H>", "hide"), ("<Control-Shift-h>", "hide"),
            ("<Control-Shift-P>", "pause"), ("<Control-Shift-p>", "pause"),
            ("<Control-Shift-Q>", "quit"), ("<Control-Shift-q>", "quit"),
        ):
            self.root.bind(seq, lambda e, c=cmd: self._cmd(c))

    def _register_global_hotkeys(self) -> None:
        """Pencere odakta olmasa da (toplanti sirasinda oyle olacak) calissin."""
        try:
            import keyboard

            keyboard.add_hotkey("ctrl+shift+l", lambda: self._cmd("mode"))
            keyboard.add_hotkey("ctrl+shift+h", lambda: self._cmd("hide"))
            keyboard.add_hotkey("ctrl+shift+p", lambda: self._cmd("pause"))
            keyboard.add_hotkey("ctrl+shift+q", lambda: self._cmd("quit"))
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

    def set_partial(self, clock: str, en: str, tr: str) -> None:
        self._partial = Line(clock, en, tr)
        self._render()

    def _render(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in self._lines:
            if self.mode == "bilingual":
                self.text.insert("end", f"[{line.clock}] ", "clock")
                self.text.insert("end", line.en + "\n", "en")
            self.text.insert("end", (line.tr or line.en) + "\n\n", "tr")
        if self._partial:
            if self.mode == "bilingual":
                self.text.insert("end", self._partial.en + "\n", "en_partial")
            self.text.insert("end", (self._partial.tr or self._partial.en) + "\n",
                             "tr_partial")
        self.text.configure(state="disabled")
        self.text.see("end")

    def _toggle_mode(self) -> None:
        self.mode = "tr_only" if self.mode == "bilingual" else "bilingual"
        self._render()

    def _toggle_hidden(self) -> None:
        self.hidden = not self.hidden
        if self.hidden:
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)

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
                self._toggle_mode()
            elif cmd == "hide":
                self._toggle_hidden()
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

        self.root.after(100, self._poll)

    def run(self) -> None:
        self.root.after(100, self._poll)
        self.root.mainloop()
