"""EN -> TR ceviri motorlari.

local  : CTranslate2 + SentencePiece ile opus-mt (tamamen offline, ucretsiz)
deepl  : DeepL Free API (opsiyonel, anahtar gerekir)
none   : ceviri yok, sadece Ingilizce transkript
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path


class TranslationError(RuntimeError):
    pass


# Cumle sonu: . ! ? ve ardindan bosluk + buyuk harf/rakam/tirnak. Whisper yeni
# cumleye buyuk harfle baslar; "15.000" veya "e.g. this" bolunmez.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip())]
    return [p for p in parts if p] or [text.strip()]


class _Cache:
    """Kucuk LRU: toplantida tekrar eden kisa kaliplari bedava cevirir."""

    def __init__(self, capacity: int = 512) -> None:
        self.capacity = capacity
        self._data: "OrderedDict[str, str]" = OrderedDict()

    def get(self, key: str) -> str | None:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key: str, value: str) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)


class BaseEngine:
    name = "base"

    def translate(self, text: str, beam_size: int | None = None) -> str:  # pragma: no cover
        raise NotImplementedError

    def unload(self) -> float:
        """Modeli bellekten bosaltir; serbest kalan tahmini MB doner."""
        return 0.0

    def ensure_loaded(self) -> None:
        """Bosaltilmis modeli geri yukler."""
        return None


class NullEngine(BaseEngine):
    name = "none"

    def translate(self, text: str, beam_size: int | None = None) -> str:
        return ""


class LocalCT2Engine(BaseEngine):
    """opus-mt modelinin CTranslate2'ye cevrilmis hali."""

    name = "local"

    def __init__(self, model_dir: str | Path, source_prefix: str = "", cpu_threads: int = 1,
                 beam_size: int = 4, phrase_map: dict | None = None,
                 use_phrases: bool = True, post_map: dict | None = None) -> None:
        import ctranslate2
        import sentencepiece as spm

        from .phrases import build_pattern

        model_dir = Path(model_dir)
        if not (model_dir / "model.bin").is_file():
            raise TranslationError(
                f"Ceviri modeli yok: {model_dir}\n"
                r"Kurmak icin: .venv\Scripts\python tools\convert_mt_model.py"
            )

        src_spm = self._find_spm(model_dir, ("source.spm", "spiece.model", "sentencepiece.bpe.model"))
        tgt_spm = self._find_spm(model_dir, ("target.spm", "source.spm", "spiece.model"))

        self.translator = ctranslate2.Translator(
            str(model_dir),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=max(1, cpu_threads),
        )
        self.sp_src = spm.SentencePieceProcessor(model_file=str(src_spm))
        self.sp_tgt = spm.SentencePieceProcessor(model_file=str(tgt_spm))
        self.source_prefix = source_prefix.strip()
        # Olculdu: beam_size 1 -> 4 gecisi gercek ceviri hatalarini duzeltiyor
        # ("scope" -> "durbun" yerine "kapsam") ve cumle basina sadece ~25 ms
        # ekliyor. beam 8'in 4'e belirgin ustunlugu gorulmedi.
        self.beam_size = max(1, int(beam_size))
        self._pattern, self._phrases = (
            build_pattern(phrase_map) if use_phrases else (None, {})
        )
        # Turkce ciktida tekrar eden rahatsiz edici kaliplari duzeltmek icin
        # (ornegin bir terimi Ingilizce birakmak): {"Dagitim": "Deployment"}
        self._post_map = {str(k): str(v) for k, v in (post_map or {}).items()}
        self._cache = _Cache()
        try:
            self._model_mb = (model_dir / "model.bin").stat().st_size / 1e6
        except OSError:
            self._model_mb = 0.0

    @staticmethod
    def _find_spm(model_dir: Path, candidates: tuple[str, ...]) -> Path:
        for name in candidates:
            p = model_dir / name
            if p.is_file():
                return p
        raise TranslationError(f"SentencePiece dosyasi bulunamadi: {model_dir} ({candidates})")

    def unload(self) -> float:
        """Sadece Ingilizce moduna gecildiginde ~490 MB'i geri verir."""
        try:
            if self.translator.model_is_loaded:
                self.translator.unload_model()
                return self._model_mb
        except Exception:
            pass
        return 0.0

    def ensure_loaded(self) -> None:
        try:
            if not self.translator.model_is_loaded:
                self.translator.load_model()
        except Exception:
            pass

    def translate(self, text: str, beam_size: int | None = None) -> str:
        beam = self.beam_size if beam_size is None else max(1, int(beam_size))
        key = f"{beam}|{text}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self.ensure_loaded()

        from .phrases import paraphrase

        # Deyimler once sade Ingilizce'ye cevrilir; ekranda gosterilen metin degismez.
        prepared = paraphrase(text, self._pattern, self._phrases)
        # Olculdu (24.09 toplantisi): cok cumleli replik tek parca verilince
        # model sondaki cumleleri sessizce atiyor ("They're just going for less.
        # All right, great." hic cevrilmedi, 154 replikten 20+'sinda). Her cumle
        # ayri cevrilir ama tek batch'te gider; ek maliyet replik basina ~100 ms.
        sentences = split_sentences(prepared)
        batch = []
        for sentence in sentences:
            source = f"{self.source_prefix} {sentence}" if self.source_prefix else sentence
            # Marian modelleri cumle sonunu </s> ile anlar; eklenmezse decoder
            # durmaz ve ayni ifadeyi tekrarlar.
            batch.append(self.sp_src.encode(source, out_type=str) + ["</s>"])
        results = self.translator.translate_batch(
            batch,
            beam_size=beam,
            max_decoding_length=256,
            repetition_penalty=1.1, # kalan tekrar egilimine karsi emniyet
            replace_unknowns=True,
        )
        out = " ".join(
            self.sp_tgt.decode(r.hypotheses[0]).strip() for r in results
        ).strip()
        for src, dst in self._post_map.items():
            out = out.replace(src, dst)
        self._cache.put(key, out)
        return out


class DeepLEngine(BaseEngine):
    name = "deepl"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise TranslationError("DeepL secildi ama config.yaml icinde deepl_api_key bos")
        self.api_key = api_key
        self.url = (
            "https://api-free.deepl.com/v2/translate"
            if api_key.endswith(":fx")
            else "https://api.deepl.com/v2/translate"
        )
        self._cache = _Cache()

    def translate(self, text: str, beam_size: int | None = None) -> str:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        data = urllib.parse.urlencode(
            {"text": text, "source_lang": "EN", "target_lang": "TR"}
        ).encode()
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out = payload["translations"][0]["text"].strip()
        self._cache.put(text, out)
        return out


def as_str_map(value, name: str) -> dict[str, str]:
    """config.yaml'daki sozluk ayarlarini guvene alir.

    Kullanici yanlis bicim yazarsa (ornegin liste) uygulama acilista
    AttributeError ile coker; pythonw ile calistigi icin bu sessiz bir cokme
    olur. Bu yuzden gecersiz deger yok sayilip uyari basilir.
    """
    if not value:
        return {}
    if not isinstance(value, dict):
        print(f"[uyari] config.yaml -> translate.{name} sozluk olmali, "
              f"su an {type(value).__name__}; yok sayiliyor. "
              f'Dogru bicim: {name}: {{"kalip": "karsilik"}}')
        return {}
    out = {}
    for key, val in value.items():
        if isinstance(val, str):
            out[str(key)] = val
        else:
            print(f"[uyari] config.yaml -> translate.{name}: '{key}' degeri metin "
                  f"degil ({type(val).__name__}), yok sayiliyor")
    return out


def build_engine(cfg: dict, cpu_threads: int = 1) -> BaseEngine:
    from .config import resolve_path

    engine = (cfg.get("engine") or "local").lower()
    if engine == "none":
        return NullEngine()
    if engine == "deepl":
        return DeepLEngine(cfg.get("deepl_api_key", ""))
    return LocalCT2Engine(
        resolve_path(cfg["model_dir"]),
        source_prefix=cfg.get("source_prefix", ""),
        cpu_threads=cpu_threads,
        beam_size=int(cfg.get("beam_size", 4)),
        phrase_map=as_str_map(cfg.get("phrase_map"), "phrase_map"),
        use_phrases=bool(cfg.get("simplify_idioms", True)),
        post_map=as_str_map(cfg.get("post_map"), "post_map"),
    )
