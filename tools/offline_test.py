"""Deterministik regresyon testi: WAV dosyasini gercek akisi taklit ederek
segmenter -> ASR -> ceviri zincirinden gecirir ve kelime kapsamasini olcer.

Hoparlorden calip mikrofonla/loopback'le olcmek volume ve zamanlamaya bagli
oldugu icin guvenilmez; bu test ayni zinciri tekrarlanabilir sekilde dogrular.

  .venv\\Scripts\\python tools\\offline_test.py --wav ornek.wav --ref "beklenen metin"
  .venv\\Scripts\\python tools\\offline_test.py --wav ornek.wav --gains 1.0 0.3 0.1
"""
from __future__ import annotations

import argparse
import queue
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.asr import Transcriber  # noqa: E402
from src.config import load_config, resolve_path  # noqa: E402
from src.segmenter import SAMPLE_RATE, Segmenter  # noqa: E402
from src.translate import TranslationError, build_engine  # noqa: E402

BLOCK = 1600  # 100 ms, audio_capture ile ayni blok boyu


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as wf:
        rate, channels = wf.getframerate(), wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * SAMPLE_RATE / rate), dtype=np.float32)
        audio = np.interp(idx, np.arange(len(audio), dtype=np.float32), audio).astype(np.float32)
    return audio


def words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def run_chain(audio: np.ndarray, cfg: dict, tr: Transcriber, engine) -> tuple[list[tuple], float]:
    """Segmenter'i gercek zamanli degil, blok blok besler (hizli ama ayni mantik)."""
    inq: "queue.Queue[np.ndarray]" = queue.Queue()
    outq: "queue.Queue" = queue.Queue()
    seg = Segmenter(inq, outq, cfg["segmenter"], time.monotonic())
    seg.start()

    pad = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    stream = np.concatenate([pad, audio, pad])
    for i in range(0, len(stream), BLOCK):
        inq.put(stream[i : i + BLOCK])
    while not inq.empty():
        time.sleep(0.02)
    time.sleep(0.4)
    seg.stop()
    time.sleep(0.2)

    results, captured = [], 0.0
    while not outq.empty():
        utt = outq.get()
        captured += utt.duration_s
        text = tr.transcribe(utt.audio)
        if not text:
            continue
        translated = engine.translate(text) if engine else ""
        results.append((utt.duration_s, text, translated))
    return results, captured


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True, help="16-bit PCM WAV (Ingilizce konusma)")
    ap.add_argument("--ref", help="beklenen Ingilizce metin (kapsamayi olcmek icin)")
    ap.add_argument("--gains", type=float, nargs="+", default=[1.0, 0.3, 0.1],
                    help="test edilecek ses seviyeleri (1.0 = orijinal)")
    ap.add_argument("--min-coverage", type=float, default=0.9)
    args = ap.parse_args()

    cfg = load_config()
    audio = load_wav(args.wav)
    print(f"Kaynak: {args.wav}  ({len(audio)/SAMPLE_RATE:.1f} sn)")

    tr = Transcriber(cfg["asr"], download_root=str(resolve_path("models")))
    try:
        engine = build_engine(cfg["translate"], cpu_threads=2)
        engine.translate("warm up")
    except TranslationError as exc:
        print(f"[uyari] ceviri yok: {exc}")
        engine = None

    ref_words = words(args.ref) if args.ref else []
    ok = True
    for gain in args.gains:
        scaled = (audio * gain).astype(np.float32)
        rms = float(np.sqrt(np.mean(scaled**2)))
        print(f"\n=== seviye x{gain:.2f} (rms {rms:.4f}) ===")
        t0 = time.monotonic()
        results, captured = run_chain(scaled, cfg, tr, engine)
        dt = time.monotonic() - t0

        for dur, en, tr_text in results:
            print(f"  {dur:4.1f} sn | EN: {en}")
            if tr_text:
                print(f"           | TR: {tr_text}")
        print(f"  yakalanan konusma: {captured:.1f} sn / {len(audio)/SAMPLE_RATE:.1f} sn"
              f"  |  islem: {dt:.1f} sn")

        if ref_words:
            got = set(words(" ".join(r[1] for r in results)))
            cov = sum(1 for w in ref_words if w in got) / len(ref_words)
            missing = [w for w in ref_words if w not in got]
            print(f"  kelime kapsamasi: %{cov*100:.0f}" +
                  (f"  (eksik: {' '.join(missing[:8])})" if missing else ""))
            if cov < args.min_coverage:
                ok = False
                print(f"  BASARISIZ: %{args.min_coverage*100:.0f} bekleniyordu")

    print("\nSONUC:", "OK" if ok else "BASARISIZ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
