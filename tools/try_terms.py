r"""config.yaml'a girdigin terimleri dener ve ise yarayip yaramadigini gosterir.

Uc ayri yer var, uc ayri ise yarar:

  asr.initial_prompt      -> Whisper'in jargonu DOGRU YAZMASI icin (transkript)
  translate.phrase_map    -> Ingilizce kalibi cevirmeden ONCE sadelestirmek icin
  translate.post_map      -> Turkce CIKTIDA kelime degistirmek icin

Kullanim:
  .venv\Scripts\python tools\try_terms.py                       # ayarlari dogrula + ornekler
  .venv\Scripts\python tools\try_terms.py --text "We deployed to prod."
  .venv\Scripts\python tools\try_terms.py --text "..." --text "..."
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import load_config  # noqa: E402
from src.phrases import DEFAULT_PHRASES, build_pattern, paraphrase  # noqa: E402
from src.translate import as_str_map, build_engine  # noqa: E402


def dogrula(cfg: dict) -> bool:
    """Ayarlarin bicimini kontrol eder; yaygin YAML hatalarini yakalar."""
    ok = True
    tr_cfg = cfg["translate"]
    asr_cfg = cfg["asr"]

    for ad in ("phrase_map", "post_map"):
        deger = tr_cfg.get(ad)
        if deger is None or deger == {}:
            print(f"  {ad:14s}: bos")
            continue
        if not isinstance(deger, dict):
            print(f"  {ad:14s}: HATA - sozluk olmali, su an {type(deger).__name__}.")
            print(f"                  Dogru bicim: {ad}: {{\"kalip\": \"karsilik\"}}")
            ok = False
            continue
        bozuk = [k for k, v in deger.items() if not isinstance(v, str)]
        print(f"  {ad:14s}: {len(deger)} kayit" + (f"  (metin olmayan deger: {bozuk})" if bozuk else ""))
        if bozuk:
            ok = False

    prompt = (asr_cfg.get("initial_prompt") or "").strip()
    kelime = len(prompt.split())
    if not prompt:
        print("  initial_prompt: bos")
    else:
        print(f"  initial_prompt: {kelime} kelime")
        if kelime > 50:
            print("                  UYARI: 50 kelimeyi gecmesi onerilmez; Whisper"
                  " uzun ipuclarini kirpar ve bazen listedeki kelimeleri uydurur.")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="append", default=[],
                    help="denenecek Ingilizce cumle (birkac kez verilebilir)")
    ap.add_argument("--config", default=None, help="alternatif config.yaml yolu")
    args = ap.parse_args()

    cfg = load_config(args.config)
    print("--- config.yaml kontrolu ---")
    saglam = dogrula(cfg)

    tr_cfg = cfg["translate"]
    kendi = {k.lower(): v for k, v in as_str_map(tr_cfg.get("phrase_map"), "phrase_map").items()}
    pattern, table = build_pattern(kendi)
    post = as_str_map(tr_cfg.get("post_map"), "post_map")

    cumleler = args.text or [
        "We deployed to prod and the smoke test passed.",
        "Let's circle back on the blocker tomorrow.",
    ]

    engine = build_engine(tr_cfg, cpu_threads=3)
    ham_engine = build_engine({**tr_cfg, "simplify_idioms": False, "post_map": {}},
                              cpu_threads=3)
    engine.translate("warm up")
    ham_engine.translate("warm up")

    print("\n--- denemeler ---")
    for text in cumleler:
        sade = paraphrase(text, pattern, table)
        kendi_eslesme = [k for k in kendi if k in text.lower()]
        hazir_eslesme = [k for k in DEFAULT_PHRASES if k in text.lower()]
        print(f"\nEN                : {text}")
        if sade != text:
            print(f"sadelestirilmis   : {sade}")
        else:
            print("sadelestirilmis   : (degisiklik yok)")
        print(f"eslesen kendi      : {kendi_eslesme or '-'}")
        print(f"eslesen hazir liste: {hazir_eslesme or '-'}")
        print(f"TR (ayarsiz)       : {ham_engine.translate(text)}")
        print(f"TR (ayarlarinla)   : {engine.translate(text)}")

    if post:
        print(f"\npost_map uygulanan kelimeler: {list(post)}")
        print("  (Turkce cikti bu kelimeleri iceriyorsa degistirilir; buyuk/kucuk"
              " harf AYNEN eslesmeli)")

    print("\nhazir listede toplam kalip:", len(DEFAULT_PHRASES))
    return 0 if saglam else 1


if __name__ == "__main__":
    raise SystemExit(main())
