"""EN -> TR ceviri motorlari.

local  : CTranslate2 + SentencePiece ile opus-mt (tamamen offline, ucretsiz)
deepl  : DeepL Free API (opsiyonel, anahtar gerekir)
none   : ceviri yok, sadece Ingilizce transkript
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path


class TranslationError(RuntimeError):
    pass


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

    def translate(self, text: str) -> str:  # pragma: no cover - arayuz
        raise NotImplementedError


class NullEngine(BaseEngine):
    name = "none"

    def translate(self, text: str) -> str:
        return ""


class LocalCT2Engine(BaseEngine):
    """opus-mt modelinin CTranslate2'ye cevrilmis hali."""

    name = "local"

    def __init__(self, model_dir: str | Path, source_prefix: str = "", cpu_threads: int = 1) -> None:
        import ctranslate2
        import sentencepiece as spm

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
        self._cache = _Cache()

    @staticmethod
    def _find_spm(model_dir: Path, candidates: tuple[str, ...]) -> Path:
        for name in candidates:
            p = model_dir / name
            if p.is_file():
                return p
        raise TranslationError(f"SentencePiece dosyasi bulunamadi: {model_dir} ({candidates})")

    def translate(self, text: str) -> str:
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        source = f"{self.source_prefix} {text}".strip() if self.source_prefix else text
        # Marian modelleri cumle sonunu </s> ile anlar; eklenmezse decoder
        # durmaz ve ayni ifadeyi tekrarlar.
        tokens = self.sp_src.encode(source, out_type=str) + ["</s>"]
        results = self.translator.translate_batch(
            [tokens],
            beam_size=1,            # hiz icin greedy
            max_decoding_length=256,
            repetition_penalty=1.1, # kalan tekrar egilimine karsi emniyet
            replace_unknowns=True,
        )
        out = self.sp_tgt.decode(results[0].hypotheses[0]).strip()
        self._cache.put(text, out)
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

    def translate(self, text: str) -> str:
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
    )
