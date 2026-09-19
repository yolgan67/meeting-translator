"""Kurulum ve performans dogrulamasi.

  .venv\\Scripts\\python tools\\selftest.py --all
  .venv\\Scripts\\python tools\\selftest.py --audio
  .venv\\Scripts\\python tools\\selftest.py --asr
  .venv\\Scripts\\python tools\\selftest.py --translate
"""
from __future__ import annotations

import argparse
import queue
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import load_config, resolve_path  # noqa: E402

SAMPLES = [
    "Good morning everyone, thanks for joining the call.",
    "Can you share your screen so we can look at the dashboard?",
    "We need to close the remaining issues before the release on Friday.",
    "I think the root cause is in the integration layer, not the database.",
    "Let's park that item and follow up in a separate meeting.",
    "Could you repeat the last part? The connection dropped for a second.",
    "The client asked for a status update by the end of the week.",
    "We are still waiting for the approval from the security team.",
    "That change will require a regression test on the whole flow.",
    "Any objections if we move the deadline by two days?",
]


def test_audio(seconds: float = 5.0) -> bool:
    from src.audio_capture import AudioCapture

    print(f"--- SES TESTI ({seconds:.0f} sn) ---")
    print("Simdi bilgisayarda Ingilizce bir video/ses cal (YouTube yeterli).")
    q: "queue.Queue[np.ndarray]" = queue.Queue()
    cap = AudioCapture(q, "auto")
    cap.start()
    time.sleep(1.0)
    print(f"Cihaz: {cap.device_name or '(bulunamadi)'}")
    if cap.last_error:
        print(f"HATA: {cap.last_error}")
        cap.stop()
        return False

    blocks: list[np.ndarray] = []
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        try:
            blocks.append(q.get(timeout=0.5))
        except queue.Empty:
            pass
    cap.stop()

    if not blocks:
        print("HATA: hic ses blogu gelmedi.")
        return False
    audio = np.concatenate(blocks)
    rms = float(np.sqrt(np.mean(audio**2)))
    peak = float(np.max(np.abs(audio)))
    print(f"Sure: {len(audio)/16000:.1f} sn  |  RMS: {rms:.4f}  |  Tepe: {peak:.3f}")
    if rms < 0.001:
        print("UYARI: seviye cok dusuk - ses caliyor muydu? Cikis cihazi dogru mu?")
        return False
    print("SONUC: ses yakalama OK")
    return True


def test_asr(cfg: dict) -> bool:
    from src.asr import Transcriber

    print("\n--- ASR TESTI ---")
    t0 = time.monotonic()
    tr = Transcriber(cfg["asr"], download_root=str(resolve_path("models")))
    print(f"Model yuklendi: {cfg['asr']['model']} ({time.monotonic() - t0:.1f} sn)")

    # 3 saniyelik sessizlik: halusinasyon filtresi bos donmeli
    silence = np.zeros(16000 * 3, dtype=np.float32)
    t0 = time.monotonic()
    out = tr.transcribe(silence)
    dt = time.monotonic() - t0
    print(f"Sessizlik testi -> '{out}'  ({dt:.2f} sn)  "
          f"{'OK' if out == '' else 'UYARI: bos donmeliydi'}")

    # Gurultu uzerinde hiz olcumu (gercek ses degil, sadece CPU kiyasi)
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(16000 * 5) * 0.02).astype(np.float32)
    t0 = time.monotonic()
    tr.transcribe(noise)
    dt = time.monotonic() - t0
    print(f"5 sn'lik ses icin islem suresi: {dt:.2f} sn  (RTF {dt/5:.2f})")
    if dt / 5 > 0.9:
        print("UYARI: gercek zamanli takip zor olabilir; tiny.en dene.")
    print("SONUC: ASR OK")
    return True


def test_translate(cfg: dict) -> bool:
    from src.translate import TranslationError, build_engine

    print("\n--- CEVIRI TESTI ---")
    try:
        engine = build_engine(cfg["translate"], cpu_threads=2)
    except TranslationError as exc:
        print(f"HATA: {exc}")
        return False
    print(f"Motor: {engine.name}")

    engine.translate("warm up")  # ilk cagri model isitma
    times = []
    for text in SAMPLES:
        t0 = time.monotonic()
        out = engine.translate(text)
        times.append(time.monotonic() - t0)
        print(f"  EN: {text}\n  TR: {out}\n")
    avg_ms = sum(times) / len(times) * 1000
    print(f"Cumle basina ortalama: {avg_ms:.0f} ms")
    if avg_ms > 400:
        print("UYARI: yavas. models/ icindeki modeli daha kucugune degistirmeyi dusun.")
    print("SONUC: ceviri OK")
    return True


def test_file(cfg: dict, wav_path: str) -> bool:
    """Gercek konusma iceren bir WAV ile uctan uca olcum (16-bit PCM)."""
    import wave

    from src.asr import Transcriber
    from src.segmenter import FRAME_LEN, SAMPLE_RATE
    from src.translate import TranslationError, build_engine

    print(f"\n--- UCTAN UCA TESTI ({wav_path}) ---")
    with wave.open(wav_path, "rb") as wf:
        rate, channels = wf.getframerate(), wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * SAMPLE_RATE / rate), dtype=np.float32)
        audio = np.interp(idx, np.arange(len(audio), dtype=np.float32), audio).astype(np.float32)
    dur = len(audio) / SAMPLE_RATE
    print(f"Ses: {dur:.1f} sn, {SAMPLE_RATE} Hz mono")

    tr = Transcriber(cfg["asr"], download_root=str(resolve_path("models")))
    t0 = time.monotonic()
    text = tr.transcribe(audio)
    asr_dt = time.monotonic() - t0
    print(f"\nASR ({cfg['asr']['model']}): {asr_dt:.2f} sn  -> RTF {asr_dt/dur:.2f}")
    print(f"  EN: {text}")
    if not text:
        print("HATA: transkript bos")
        return False

    try:
        engine = build_engine(cfg["translate"], cpu_threads=2)
    except TranslationError as exc:
        print(f"UYARI: ceviri yok ({exc})")
        return True
    engine.translate("warm up")
    t0 = time.monotonic()
    out = engine.translate(text)
    mt_dt = time.monotonic() - t0
    print(f"\nCeviri: {mt_dt:.2f} sn")
    print(f"  TR: {out}")

    # Gercek gecikme = cumle bittikten sonra gecen sure (ses zaten dinlenmis oldu)
    print(f"\nTahmini ekrana yansima gecikmesi: {asr_dt + mt_dt:.1f} sn "
          f"(+ VAD sessizlik esigi {cfg['segmenter']['silence_ms']/1000:.1f} sn)")
    if (asr_dt + mt_dt) / dur > 0.8:
        print("UYARI: uzun konusmalarda geri kalabilir; tiny.en dene.")
    print("SONUC: uctan uca OK")
    return bool(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="16-bit PCM WAV ile uctan uca test")
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--asr", action="store_true")
    ap.add_argument("--translate", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    if not any((args.audio, args.asr, args.translate, args.all, args.file)):
        args.all = True

    cfg = load_config()
    results: dict[str, bool] = {}
    if args.file:
        results["uctan uca"] = test_file(cfg, args.file)
    if args.all or args.audio:
        results["ses"] = test_audio(args.seconds)
    if args.all or args.asr:
        results["asr"] = test_asr(cfg)
    if args.all or args.translate:
        results["ceviri"] = test_translate(cfg)

    print("\n=== OZET ===")
    for name, ok in results.items():
        print(f"  {name}: {'OK' if ok else 'BASARISIZ'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
