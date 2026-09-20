"""Calisan ornegin izi ve "geri getir" haberlesmesi.

Overlay modunda uygulama PID dosyasi birakir. `--show` ile baslatilan ikinci
kopya bu dosyaya bakar:
  - ornek calisiyorsa  -> bayrak dosyasi yazar (overlay dongusu gorup pencereyi
    gosterir ve ortalar), bayragin tuketildigini dogrular
  - calismiyorsa       -> uygulamayi bastan baslatir
Boylece "Altyazi-Geri-Getir" her iki durumda da dogru seyi yapar.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.gettempdir())
PID_FILE = TMP / "meeting-translator.pid"
SHOW_FLAG = TMP / "meeting-translator-show.flag"

DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


def write_pid() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def clear_pid() -> None:
    try:
        if PID_FILE.is_file() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass


def running_pid() -> int | None:
    """Calisan ornegin PID'i (yoksa None)."""
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        import psutil

        if not psutil.pid_exists(pid):
            return None
        # PID geri donusturulmus olabilir: surecin gercekten bizim oldugunu dogrula.
        proc = psutil.Process(pid)
        if "python" not in proc.name().lower():
            return None
        return pid
    except Exception:
        return None


def request_show(timeout: float = 4.0) -> bool:
    """Calisan ornekten pencereyi gostermesini ister; tuketildiyse True."""
    SHOW_FLAG.write_text("show", encoding="utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not SHOW_FLAG.exists():
            return True
        time.sleep(0.2)
    return False


def launch_detached(project_root: Path) -> None:
    """Uygulamayi ayri bir surec olarak baslatir (konsol penceresi acmaz)."""
    python = project_root / ".venv" / "Scripts" / "pythonw.exe"
    if not python.is_file():
        python = Path(sys.executable)
    subprocess.Popen(
        [str(python), "-m", "src.main"],
        cwd=str(project_root),
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        # Kopuk surec ebeveynin boru hattini devralirsa, ebeveyn kapaninca
        # ilk print cagrisinda kilitleniyor; std akislar acikca kapatilmali.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
