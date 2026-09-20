"""Oturum transkriptini diske yazar (ses kaydi YOK, sadece metin)."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


def fmt_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


class SessionLog:
    def __init__(self, log_root: Path) -> None:
        self.started_at = datetime.now()
        # Klasor adi SANIYE icerir. Dakika cozunurlugu kullanildiginda ayni
        # dakika icinde ikinci kez baslatmak iki oturumu ayni klasore yaziyor,
        # jsonl satirlari karisiyor ve ilk oturumun transcript.md'si ezilerek
        # kayboluyordu (olculdu).
        base = Path(log_root) / self.started_at.strftime("%Y-%m-%d_%H%M%S")
        candidate, n = base, 2
        while candidate.exists():
            candidate = base.with_name(f"{base.name}-{n}")
            n += 1
        self.session_dir = candidate
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.session_dir / "transcript.jsonl"
        self.md_path = self.session_dir / "transcript.md"
        self._entries: list[dict] = []
        self._t0 = time.monotonic()
        # Akis halinde acik tutulur: uygulama cokse bile o ana kadarki log durur.
        self._fh = self.jsonl_path.open("a", encoding="utf-8")

    def add(self, offset_s: float, en: str, tr: str, duration_s: float, latency_s: float) -> None:
        entry = {
            "t": fmt_clock(offset_s),
            "offset_s": round(offset_s, 2),
            "en": en,
            "tr": tr,
            "dur": round(duration_s, 2),
            "latency_s": round(latency_s, 2),
        }
        self._entries.append(entry)
        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()
        # Okunur transkript her replikte yeniden yazilir. Onceden yalnizca
        # kapanista yaziliyordu; uygulama temiz kapanmazsa (gorev yoneticisinden
        # sonlandirma, elektrik kesintisi) transcript.md hic olusmuyordu -
        # 44 replikli gercek bir oturumda yasandi, jsonl'den kurtarildi.
        self._write_markdown()

    def close(self) -> Path | None:
        try:
            self._fh.close()
        except Exception:
            pass
        if not self._entries:
            # Hic konusma yakalanmadi: bos klasor birakmayalim.
            self._discard()
            return None
        return self._write_markdown()

    def _discard(self) -> None:
        try:
            if self.jsonl_path.is_file() and self.jsonl_path.stat().st_size == 0:
                self.jsonl_path.unlink()
            if not any(self.session_dir.iterdir()):
                self.session_dir.rmdir()
        except OSError:
            pass


    def _write_markdown(self) -> Path | None:
        if not self._entries:
            return None
        total = time.monotonic() - self._t0
        avg_lat = sum(e["latency_s"] for e in self._entries) / len(self._entries)
        lines = [
            "# Toplanti Transkripti",
            "",
            f"- **Tarih:** {self.started_at.strftime('%d.%m.%Y %H:%M')}",
            f"- **Sure:** {fmt_clock(total)}",
            f"- **Replik sayisi:** {len(self._entries)}",
            f"- **Ortalama gecikme:** {avg_lat:.1f} sn",
            "",
            "---",
            "",
        ]
        for e in self._entries:
            lines.append(f"**[{e['t']}]**")
            lines.append("")
            lines.append(f"> {e['en']}")
            lines.append("")
            if e["tr"]:
                lines.append(e["tr"])
                lines.append("")
        self.md_path.write_text("\n".join(lines), encoding="utf-8")
        return self.md_path



def cleanup_old_sessions(log_root: Path, keep_days: int) -> int:
    """keep_days > 0 ise eski oturum klasorlerini siler; silinen sayisini doner.

    Toplanti transkriptleri hassas olabilir; bu yuzden varsayilan 0 (kapali).
    """
    if keep_days <= 0:
        return 0
    import shutil

    cutoff = time.time() - keep_days * 86400
    removed = 0
    for path in Path(log_root).glob("*"):
        if not path.is_dir():
            continue
        # Sadece oturum klasorleri silinir (app.log gibi dosyalara dokunulmaz).
        if not ((path / "transcript.jsonl").exists() or (path / "transcript.md").exists()):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
                removed += 1
        except OSError:
            pass
    return removed
