r"""transcript.jsonl dosyalarindan transcript.md'yi yeniden uretir.

Uygulama temiz kapanmazsa (gorev yoneticisinden sonlandirma, elektrik kesintisi)
eski surumlerde okunur transkript olusmuyordu; jsonl ise her replikte diske
yazildigi icin duruyor. Bu arac onlari kurtarir.

  .venv\Scripts\python tools\rebuild_md.py              # logs/ altindaki eksikleri tamamla
  .venv\Scripts\python tools\rebuild_md.py --all        # var olanlari da yenile
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import resolve_path  # noqa: E402
from src.session_log import fmt_clock  # noqa: E402


def rebuild(session_dir: Path) -> int:
    jsonl = session_dir / "transcript.jsonl"
    entries = []
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # yarim yazilmis son satir
    if not entries:
        return 0

    son = max(float(e.get("offset_s", 0)) + float(e.get("dur", 0)) for e in entries)
    lat = [float(e.get("latency_s", 0)) for e in entries if e.get("latency_s") is not None]
    lines = [
        "# Toplanti Transkripti",
        "",
        f"- **Klasor:** {session_dir.name}",
        f"- **Sure:** {fmt_clock(son)}",
        f"- **Replik sayisi:** {len(entries)}",
    ]
    if lat:
        lines.append(f"- **Ortalama gecikme:** {sum(lat)/len(lat):.1f} sn")
    lines += ["", "---", ""]
    for e in entries:
        lines.append(f"**[{e.get('t', '')}]**")
        lines.append("")
        lines.append(f"> {e.get('en', '')}")
        lines.append("")
        if e.get("tr"):
            lines.append(e["tr"])
            lines.append("")
    (session_dir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")
    return len(entries)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="var olan transcript.md'leri de yenile")
    ap.add_argument("--logs", default=None, help="logs klasoru (varsayilan: proje/logs)")
    args = ap.parse_args()

    root = Path(args.logs) if args.logs else resolve_path("logs")
    if not root.is_dir():
        print(f"logs klasoru yok: {root}")
        return 1

    toplam = 0
    for session in sorted(root.iterdir()):
        if not session.is_dir() or not (session / "transcript.jsonl").is_file():
            continue
        md = session / "transcript.md"
        if md.exists() and not args.all:
            continue
        n = rebuild(session)
        if n:
            toplam += 1
            print(f"  {session.name}: {n} replik -> transcript.md")
    print(f"\n{toplam} transkript yazildi." if toplam else "\nEksik transkript bulunamadi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
