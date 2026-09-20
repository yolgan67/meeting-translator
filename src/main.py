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
from .session_log import SessionLog, cleanup_old_sessions, fmt_clock
from .stability import StableText
from .translate import BaseEngine, NullEngine, TranslationError, build_engine

# pythonw ile (konsolsuz) baslatildiginda stdout/stderr None veya gecersiz olur;
# her print cagrisi uygulamayi cokertir ya da kilitler. Bu durumda mesajlar
# logs/app.log dosyasina yazilir, boylece konsol penceresi acik tutmak gerekmez.
def _redirect_output_to_file() -> None:
    import os
    from pathlib import Path

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "app.log"
        # Her oturum ekleniyor; sinirsiz buyumesin.
        if path.is_file() and path.stat().st_size > 1_000_000:
            path.replace(log_dir / "app.log.1")
        stream = open(path, "a", encoding="utf-8", buffering=1)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        stream.write(f"{chr(10)}===== {stamp} ====={chr(10)}")
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = stream
    sys.stderr = stream


if sys.stdout is None or sys.stderr is None or "pythonw" in sys.executable.lower():
    _redirect_output_to_file()

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
        self.partial_beam = int(cfg["translate"].get("partial_beam_size", 1))
        # Ara altyazi: metin yalnizca uzar (kararli onek) ve varsayilan olarak
        # cevrilmez. Her hipotezde Turkce'yi bastan kurmak ekrani okunamaz
        # hale getiriyordu (olculdu: 7 guncellemede 7 kez tamamen degisti).
        self.partial_translate = bool(cfg["ui"].get("partial_translate", False))
        self.stable_partial = StableText()
        # "Sadece Ingilizce" modunda ceviri hem gereksiz hem pahali.
        self.translate_enabled = cfg["ui"].get("mode", "bilingual") != "en_only"
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

        # Baslangictan beri "sadece Ingilizce" modundaysak modeli hemen bosalt.
        if not self.translate_enabled:
            freed = self.engine.unload()
            if freed:
                print(f"      sadece Ingilizce modu -> ceviri modeli bosaltildi")

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

    def on_mode_change(self, mode: str) -> None:
        """Overlay'den mod degisikligi: ceviri gerekmiyorsa modeli bellekten bosalt."""
        self.translate_enabled = mode != "en_only"
        if self.translate_enabled:
            self.engine.ensure_loaded()
        else:
            freed = self.engine.unload()
            if freed:
                print(f"[bilgi] ceviri modeli bosaltildi, ~{freed:.0f} MB serbest")

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

            if utt.partial:
                # Kararli onek: sadece son iki hipotezin ortak kismi gosterilir.
                text = self.stable_partial.update(text)
                if not text:
                    continue
            else:
                self.stable_partial.reset()

            translated = ""
            if self.translate_enabled and (not utt.partial or self.partial_translate):
                try:
                    # Ara altyazi hizli (greedy), kesin altyazi kaliteli (beam):
                    # beam=4 cumle basina ~25 ms ekliyor ama gercek ceviri
                    # hatalarini duzeltiyor.
                    translated = self.engine.translate(
                        text, beam_size=self.partial_beam if utt.partial else None
                    )
                except Exception as exc:
                    print(f"[hata] ceviri: {exc}")

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
    ap.add_argument("--show", action="store_true",
                    help="calisan ornegin altyazi penceresini geri getir ve cik")
    args = ap.parse_args(argv)

    if args.show:
        from .config import PROJECT_ROOT
        from .instance import launch_detached, request_show, running_pid

        pid = running_pid()
        if pid is None:
            print("Calisan uygulama yok -> baslatiliyor...")
            launch_detached(PROJECT_ROOT)
            print("Altyazi penceresi birkac saniye icinde acilacak.")
            return 0
        print(f"Calisan uygulama bulundu (PID {pid}), pencere isteniyor...")
        if request_show():
            print("Altyazi penceresi geri getirildi ve ekranin altina ortalandi.")
            return 0
        print("Uygulama yanit vermedi. Muhtemelen eski surumu calisiyor;")
        print("pencereyi Ctrl+Shift+H ile dene, olmazsa uygulamayi yeniden baslat.")
        return 1

    cfg = load_config(args.config)
    if args.model:
        cfg["asr"]["model"] = args.model
    if args.engine:
        cfg["translate"]["engine"] = args.engine

    configure_threads(int(cfg["asr"]["cpu_threads"]))
    set_low_priority()

    if not args.console:
        from .instance import SHOW_FLAG, request_show, running_pid, write_pid

        # Ikinci kez cift tiklandiginda yeni ornek acmak yerine mevcut pencereyi
        # one getir. Bu kontrol model yuklemeden ONCE yapilmali: aksi halde
        # ikinci kopya ~570 MB'i bosa yukluyor (ve ceviri modeli bellege
        # sigmayabiliyor), sonra cikiyordu.
        other = running_pid()
        if other:
            print(f"Uygulama zaten calisiyor (PID {other}); pencere one getiriliyor.")
            request_show()
            return 0

        SHOW_FLAG.unlink(missing_ok=True)  # onceki oturumdan kalan bayrak
        write_pid()

    silinen = cleanup_old_sessions(resolve_path(cfg["log"]["dir"]),
                                   int(cfg["log"].get("keep_days", 0)))
    if silinen:
        print(f"[bilgi] {silinen} eski oturum klasoru silindi (log.keep_days)")

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

        overlay = Overlay(cfg["ui"], pipe.ui_q, on_quit=pipe.stop,
                          on_mode_change=pipe.on_mode_change)
        pipe.is_paused = lambda: overlay.paused
        if args.duration:
            overlay.root.after(int(args.duration * 1000), overlay._quit)
        if pipe.capture and pipe.capture.device_name:
            print(f"Ses cihazi: {pipe.capture.device_name}")
        overlay.run()

    pipe.stop()
    if not args.console:
        from .instance import clear_pid

        clear_pid()
    time.sleep(0.4)  # segmenter yarim cumleyi bosaltsin
    md = pipe.log.close()
    if md:
        print(f"\nTranskript hazir: {md}")
    else:
        print("\nHic konusma yakalanmadi, transkript olusturulmadi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
