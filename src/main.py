"""Canli Toplanti Cevirmeni - orkestrasyon.

Zincir:  WASAPI loopback -> VAD segmenter -> Whisper (EN) -> opus-mt (TR)
                                         -> overlay + logs/<oturum>/transcript.*

Kullanim:
  .venv\\Scripts\\python -m src.main                 # overlay ile
  .venv\\Scripts\\python -m src.main --console       # arayuzsuz, konsola yaz
  .venv\\Scripts\\python -m src.main --model small.en
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

import numpy as np

from .asr import Transcriber, configure_threads
from .config import load_config, resolve_path
from .session_log import SessionLog, fmt_clock
from .translate import BaseEngine, NullEngine, TranslationError, build_engine

# Windows konsolu varsayilan cp1252; Turkce karakterler UnicodeEncodeError verir.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GREEN = "#3ddc84"
YELLOW = "#f2c744"
RED = "#ff6b6b"
GREY = "#5c6773"

AUDIO_QUEUE_BLOCKS = 200   # ~20 sn tampon
UTT_QUEUE_SIZE = 4         # dolarsa en eski cumle dusurulur (lag birikmesin)


def set_low_priority() -> None:
    """Teams/Zoom sesi kesilmesin: bu surec CPU'da geri planda kalir."""
    try:
        import psutil

        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception as exc:
        print(f"[uyari] surec onceligi ayarlanamadi: {exc}")


class Pipeline:
    def __init__(self, cfg: dict, console: bool) -> None:
        self.cfg = cfg
        self.console = console
        self.stop_event = threading.Event()
        self.session_start = time.monotonic()

        self.audio_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=AUDIO_QUEUE_BLOCKS)
        self.utt_q: "queue.Queue" = queue.Queue(maxsize=UTT_QUEUE_SIZE)
        # Ara altyazilarda sadece en yenisi anlamli: kuyruk 1, eskisi dusurulur.
        self.partial_q: "queue.Queue" = queue.Queue(maxsize=1)
        self.ui_q: "queue.Queue" = queue.Queue()

        self.log = SessionLog(resolve_path(cfg["log"]["dir"]))
        self.transcriber: Transcriber | None = None
        self.partial_transcriber: Transcriber | None = None
        self.engine: BaseEngine = NullEngine()
        self.capture = None
        self.segmenter = None
        self.is_paused = lambda: False
        self.partial_logprob = float(cfg["asr"].get("partial_min_avg_logprob", -0.6))
        self._last_line_ts = 0.0

    # ------------------------------------------------------------------ setup
    def load_models(self) -> None:
        print(f"[1/2] Whisper yukleniyor: {self.cfg['asr']['model']} (int8, "
              f"{self.cfg['asr']['cpu_threads']} thread)")
        t0 = time.monotonic()
        models_dir = str(resolve_path("models"))
        self.transcriber = Transcriber(self.cfg["asr"], download_root=models_dir)
        print(f"      tamam ({time.monotonic() - t0:.1f} sn)")

        # Ara altyazi icin daha kucuk model: cagri basina sabit ASR maliyeti
        # olculdu -> tiny.en ~0,6 sn, base.en ~1,1 sn. Ara altyazida gecikme
        # kaliteden onemli oldugu icin orada tiny.en kullanilir; kesin altyazi
        # ve log her zaman ana modelden gelir.
        partial_model = (self.cfg["asr"].get("partial_model") or "").strip()
        if (
            partial_model
            and partial_model != self.cfg["asr"]["model"]
            and self.cfg["ui"].get("show_partial", True)
        ):
            print(f"      ara altyazi modeli: {partial_model}")
            partial_cfg = dict(self.cfg["asr"])
            partial_cfg["model"] = partial_model
            try:
                self.partial_transcriber = Transcriber(partial_cfg, download_root=models_dir)
            except Exception as exc:
                print(f"[uyari] ara altyazi modeli yuklenemedi, ana model kullanilacak: {exc}")

        engine_name = self.cfg["translate"]["engine"]
        print(f"[2/2] Ceviri motoru: {engine_name}")
        try:
            self.engine = build_engine(self.cfg["translate"],
                                       cpu_threads=max(1, int(self.cfg["asr"]["cpu_threads"]) - 1))
        except TranslationError as exc:
            print(f"[uyari] Ceviri devre disi: {exc}")
            self.engine = NullEngine()
        except MemoryError:
            self._translate_oom()
        except RuntimeError as exc:
            # CTranslate2 bellek yetersizliginde mkl_malloc hatasi firlatiyor.
            if "malloc" in str(exc).lower() or "memory" in str(exc).lower():
                self._translate_oom()
            else:
                raise

    def _translate_oom(self) -> None:
        print("[uyari] Ceviri modeli bellege sigmadi -> sadece Ingilizce transkript.")
        print("        Muhtemel sebep: uygulamanin baska bir kopyasi zaten acik.")
        print("        Cozum: diger pencereyi kapat, ya da hafif modeli kur:")
        print("        .venv\\Scripts\\python tools\\convert_mt_model.py --light --force")
        self.engine = NullEngine()

    def start(self) -> None:
        from .audio_capture import AudioCapture
        from .segmenter import Segmenter

        self.capture = AudioCapture(self.audio_q, self.cfg["audio"]["device"])
        self.segmenter = Segmenter(
            self.audio_q, self.utt_q, self.cfg["segmenter"], self.session_start,
            partial_queue=self.partial_q if self.cfg["ui"].get("show_partial", True) else None,
        )
        self.capture.start()
        self.segmenter.start()
        threading.Thread(target=self._worker, name="asr-translate", daemon=True).start()
        threading.Thread(target=self._status_loop, name="status", daemon=True).start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.capture:
            self.capture.stop()
        if self.segmenter:
            self.segmenter.stop()

    # --------------------------------------------------------------- workers
    def _worker(self) -> None:
        assert self.transcriber is not None
        while not self.stop_event.is_set():
            # Tamamlanmis cumleler her zaman ara altyazidan onceliklidir.
            utt = None
            try:
                utt = self.utt_q.get_nowait()
            except queue.Empty:
                try:
                    utt = self.partial_q.get(timeout=0.2)
                except queue.Empty:
                    continue
            if self.is_paused():
                continue

            try:
                # Ara altyazilar kesik kelimeyle bittigi icin daha siki filtrelenir;
                # atlanan bir ara satirin maliyeti yok, saçma satirin maliyeti var.
                asr = self.transcriber
                if utt.partial and self.partial_transcriber is not None:
                    asr = self.partial_transcriber
                text = asr.transcribe(
                    utt.audio,
                    min_avg_logprob=self.partial_logprob if utt.partial else None,
                )
            except Exception as exc:
                print(f"[hata] transkripsiyon: {exc}")
                continue
            if not text:
                continue

            try:
                translated = self.engine.translate(text)
            except Exception as exc:
                print(f"[hata] ceviri: {exc}")
                translated = ""

            latency = time.monotonic() - utt.captured_at
            clock = fmt_clock(utt.start_s)

            if utt.partial:
                # Ara altyazi: loga yazilmaz, ekranda soluk gosterilir ve
                # cumle bitince nihai metinle degistirilir.
                if self.console:
                    print(f"  ~ {translated or text}")
                else:
                    self.ui_q.put(("partial", clock, text, translated))
                continue

            self.log.add(utt.start_s, text, translated, utt.duration_s, latency)
            self._last_line_ts = time.monotonic()

            if self.console:
                print(f"\n[{clock}] EN: {text}")
                if translated:
                    print(f"          TR: {translated}   ({latency:.1f} sn)")
            else:
                self.ui_q.put(("line", clock, text, translated))

    def _status_loop(self) -> None:
        while not self.stop_event.is_set():
            time.sleep(1.0)
            if self.console:
                continue
            now = time.monotonic()
            cap = self.capture
            if cap and cap.last_error:
                self.ui_q.put(("status", RED, f"ses hatasi: {cap.last_error[:40]}"))
            elif cap and now - cap.last_block_ts > 3.0:
                self.ui_q.put(("status", RED, "ses gelmiyor (cikis cihazini kontrol et)"))
            elif self.utt_q.qsize() >= UTT_QUEUE_SIZE - 1:
                self.ui_q.put(("status", YELLOW, "gecikme var - daha kucuk model dene"))
            else:
                waiting = self.utt_q.qsize()
                label = "dinleniyor" if waiting == 0 else f"isleniyor ({waiting})"
                self.ui_q.put(("status", GREEN, label))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Canli Toplanti Cevirmeni (EN->TR)")
    ap.add_argument("--config", help="alternatif config.yaml yolu")
    ap.add_argument("--console", action="store_true", help="overlay yerine konsola yaz")
    ap.add_argument("--model", help="asr.model ayarini gecici olarak degistir")
    ap.add_argument("--engine", choices=["local", "deepl", "none"], help="ceviri motoru")
    ap.add_argument("--duration", type=float,
                    help="belirtilen saniye sonunda kendiliginden kapan (test icin)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.model:
        cfg["asr"]["model"] = args.model
    if args.engine:
        cfg["translate"]["engine"] = args.engine

    configure_threads(int(cfg["asr"]["cpu_threads"]))
    set_low_priority()

    pipe = Pipeline(cfg, console=args.console)
    pipe.load_models()
    pipe.start()
    print(f"\nKayit klasoru: {pipe.log.session_dir}")

    if args.console:
        print("Dinleniyor... (Ctrl+C ile bitir)\n")
        deadline = time.monotonic() + args.duration if args.duration else None
        try:
            while deadline is None or time.monotonic() < deadline:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nKapatiliyor...")
    else:
        from .overlay import Overlay

        overlay = Overlay(cfg["ui"], pipe.ui_q, on_quit=pipe.stop)
        pipe.is_paused = lambda: overlay.paused
        if args.duration:
            overlay.root.after(int(args.duration * 1000), overlay._quit)
        if pipe.capture and pipe.capture.device_name:
            print(f"Ses cihazi: {pipe.capture.device_name}")
        overlay.run()

    pipe.stop()
    time.sleep(0.4)  # segmenter yarim cumleyi bosaltsin
    md = pipe.log.close()
    if md:
        print(f"\nTranskript hazir: {md}")
    else:
        print("\nHic konusma yakalanmadi, transkript olusturulmadi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
