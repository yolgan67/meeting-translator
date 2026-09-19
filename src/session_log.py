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
        self.session_dir = Path(log_root) / self.started_at.strftime("%Y-%m-%d_%H%M")
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

    def close(self) -> Path | None:
        try:
            self._fh.close()
        except Exception:
            pass
        return self._write_markdown()

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
