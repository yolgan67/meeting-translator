r"""EN->TR ceviri kalitesini STANDART bir test setiyle olcer.

"Hangi model daha iyi?" sorusu goz karariyla degil, referans cevirileri olan bir
test seti ve otomatik puanlarla cevaplanir. Burada kullanilanlar:

  - Test seti: FLORES-200 dev (Meta). 997 cumle, 200 dilde insan cevirisi var;
    makine cevirisi karsilastirmalarinin fiili standardi.
  - Puanlar: chrF2 ve BLEU (sacrebleu ile). chrF2 karakter n-gram tabanli oldugu
    icin Turkce gibi eklemeli dillerde BLEU'dan daha guvenilirdir; ikisi de
    yuksek = iyi.

Sinir: FLORES cumleleri Wikipedia uslubunda. Toplanti jargonu (deyimler) icin
ayri bir alan testi gerekir; bu yuzden --domain ile kendi toplanti cumleleri
listesi de calistirilabilir (referanssiz, sadece goz kontrolu icin).

Kullanim:
  .venv\Scripts\python tools\bench_mt.py                    # varsayilan ayar
  .venv\Scripts\python tools\bench_mt.py --compare          # beam ve deyim etkisi
  .venv\Scripts\python tools\bench_mt.py --n 400
"""
from __future__ import annotations

import argparse
import io
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import load_config  # noqa: E402
from src.translate import build_engine  # noqa: E402

FLORES_URL = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"
CACHE = Path(tempfile.gettempdir()) / "flores200"


def ensure_flores() -> tuple[list[str], list[str]]:
    """FLORES-200 dev bolumunu indirir (bir kez) ve EN/TR cumlelerini dondurur."""
    en_path = CACHE / "dev" / "eng_Latn.dev"
    tr_path = CACHE / "dev" / "tur_Latn.dev"
    if not (en_path.is_file() and tr_path.is_file()):
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"FLORES-200 indiriliyor (~25 MB): {FLORES_URL}")
        with urllib.request.urlopen(FLORES_URL, timeout=180) as resp:
            blob = resp.read()
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for member in tar.getmembers():
                name = Path(member.name).name
                if name in ("eng_Latn.dev", "tur_Latn.dev"):
                    target = CACHE / "dev" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = tar.extractfile(member)
                    if extracted:
                        target.write_bytes(extracted.read())
        print(f"  -> {CACHE / 'dev'}")
    en = en_path.read_text(encoding="utf-8").splitlines()
    tr = tr_path.read_text(encoding="utf-8").splitlines()
    return en, tr


def score(hyps: list[str], refs: list[str]) -> tuple[float, float]:
    import sacrebleu

    chrf = sacrebleu.CHRF(word_order=2).corpus_score(hyps, [refs]).score
    bleu = sacrebleu.BLEU().corpus_score(hyps, [refs]).score
    return chrf, bleu


def run(engine, sentences: list[str], beam: int | None = None) -> tuple[list[str], float]:
    out, t0 = [], time.monotonic()
    for s in sentences:
        out.append(engine.translate(s, beam_size=beam))
    return out, time.monotonic() - t0


DOMAIN_SENTENCES = [
    "Let's take this offline and circle back tomorrow.",
    "We need to align on the scope before we commit to a delivery date.",
    "I'd push back on that estimate; it doesn't account for regression testing.",
    "Do you have bandwidth to review this by end of day?",
    "That's a blocker; let's find a quick win instead.",
    "We found a workaround for that edge case.",
    "It works on the happy path but fails in production.",
    "Let's nail down the scope to avoid scope creep.",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="FLORES'ten kac cumle (max 997)")
    ap.add_argument("--compare", action="store_true",
                    help="beam ve deyim katmani varyantlarini karsilastir")
    ap.add_argument("--domain", action="store_true",
                    help="toplanti cumlelerini de cevir (referanssiz, goz kontrolu)")
    args = ap.parse_args()

    cfg = load_config()["translate"]
    en, tr = ensure_flores()
    n = max(1, min(args.n, len(en)))
    src, ref = en[:n], tr[:n]
    print(f"\nTest seti: FLORES-200 dev, ilk {n} cumle (EN -> TR)")
    print("Puanlar: chrF2 ve BLEU (yuksek = iyi). chrF2 Turkce icin daha guvenilir.\n")

    variants = [("mevcut ayar", dict(cfg), None)]
    if args.compare:
        variants = [
            ("beam 1, deyim yok", {**cfg, "simplify_idioms": False}, 1),
            ("beam 4, deyim yok", {**cfg, "simplify_idioms": False}, 4),
            ("beam 1, deyim var", dict(cfg), 1),
            ("beam 4, deyim var (mevcut)", dict(cfg), 4),
        ]

    print(f"{'ayar':28s} {'chrF2':>7s} {'BLEU':>7s} {'ms/cumle':>10s}")
    print("-" * 56)
    for label, vcfg, beam in variants:
        engine = build_engine(vcfg, cpu_threads=3)
        engine.translate("warm up")
        hyps, dt = run(engine, src, beam)
        chrf, bleu = score(hyps, ref)
        print(f"{label:28s} {chrf:7.2f} {bleu:7.2f} {dt / n * 1000:10.0f}")

    if args.domain:
        print("\nToplanti cumleleri (referans yok, goz kontrolu):")
        engine = build_engine(cfg, cpu_threads=3)
        engine.translate("warm up")
        for s in DOMAIN_SENTENCES:
            print(f"  EN: {s}")
            print(f"  TR: {engine.translate(s)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
