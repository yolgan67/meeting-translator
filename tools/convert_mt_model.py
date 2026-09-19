r"""EN->TR ceviri modelini CTranslate2 formatinda models/ altina kurar.

Sira:
  1) Hazir CT2 modelini Hugging Face'ten indir (torch GEREKMEZ)
  2) Argos Translate en->tr paketi (zaten CT2, kucuk ve int8)
  3) Son care: %TEMP% icinde gecici bir venv kurup transformers+torch ile donustur,
     ardindan gecici venv'i sil (kalici disk maliyeti olmaz)

Kullanim:
  .venv\Scripts\python tools\convert_mt_model.py
  .venv\Scripts\python tools\convert_mt_model.py --force
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = PROJECT_ROOT / "models" / "opus-mt-en-tr-ct2"

HF_CT2_REPOS = [
    "ooeoeo/opus-mt-tc-big-en-tr-ct2-float16",
]
ARGOS_URL = "https://argos-net.com/v1/translate-en_tr-1_5.argosmodel"
FALLBACK_HF_MODEL = "Helsinki-NLP/opus-mt-tc-big-en-tr"


def is_valid(model_dir: Path) -> bool:
    if not (model_dir / "model.bin").is_file():
        return False
    return any((model_dir / n).is_file() for n in ("source.spm", "sentencepiece.model", "spiece.model"))


def try_hf_ct2(model_dir: Path) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("[hf] huggingface_hub yok, atlaniyor")
        return False

    for repo in HF_CT2_REPOS:
        print(f"[hf] indiriliyor: {repo}")
        try:
            path = snapshot_download(
                repo_id=repo,
                allow_patterns=["*.json", "*.spm", "model.bin", "*.txt"],
            )
        except Exception as exc:
            print(f"[hf] basarisiz ({repo}): {exc}")
            continue
        if model_dir.exists():
            shutil.rmtree(model_dir)
        shutil.copytree(path, model_dir, dirs_exist_ok=True)
        if is_valid(model_dir):
            print(f"[hf] tamam -> {model_dir}")
            return True
        print("[hf] indirilen klasor eksik, siliniyor")
        shutil.rmtree(model_dir, ignore_errors=True)
    return False


def try_argos(model_dir: Path) -> bool:
    """Argos .argosmodel = icinde CT2 modeli ve sentencepiece olan bir zip."""
    print(f"[argos] indiriliyor: {ARGOS_URL}")
    try:
        with urllib.request.urlopen(ARGOS_URL, timeout=120) as resp:
            blob = resp.read()
    except Exception as exc:
        print(f"[argos] basarisiz: {exc}")
        return False

    tmp = Path(tempfile.mkdtemp(prefix="argos-"))
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(tmp)
        ct2_dir = next((p.parent for p in tmp.rglob("model.bin")), None)
        spm = next(iter(tmp.rglob("sentencepiece.model")), None)
        if ct2_dir is None or spm is None:
            print("[argos] paket beklenen yapida degil")
            return False
        if model_dir.exists():
            shutil.rmtree(model_dir)
        shutil.copytree(ct2_dir, model_dir)
        shutil.copy2(spm, model_dir / "sentencepiece.model")
        print(f"[argos] tamam -> {model_dir}")
        return is_valid(model_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def try_temp_venv_conversion(model_dir: Path) -> bool:
    """transformers+torch'u SADECE gecici bir venv'de kurup donusturur."""
    tmp = Path(tempfile.mkdtemp(prefix="mtconv-"))
    venv = tmp / "venv"
    print(f"[convert] gecici venv: {venv} (islem sonunda silinecek, ~2.5 GB gecici disk)")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        py = venv / "Scripts" / "python.exe"
        if not py.is_file():
            py = venv / "bin" / "python"
        subprocess.run(
            [str(py), "-m", "pip", "install", "--quiet",
             "torch", "--index-url", "https://download.pytorch.org/whl/cpu"],
            check=True,
        )
        subprocess.run(
            [str(py), "-m", "pip", "install", "--quiet",
             "transformers[sentencepiece]", "ctranslate2"],
            check=True,
        )
        if model_dir.exists():
            shutil.rmtree(model_dir)
        subprocess.run(
            [str(venv / "Scripts" / "ct2-transformers-converter.exe"),
             "--model", FALLBACK_HF_MODEL,
             "--output_dir", str(model_dir),
             "--quantization", "int8",
             "--copy_files", "source.spm", "target.spm"],
            check=True,
        )
        return is_valid(model_dir)
    except subprocess.CalledProcessError as exc:
        print(f"[convert] basarisiz: {exc}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print("[convert] gecici venv silindi")


def write_meta(model_dir: Path, source: str) -> None:
    (model_dir / "_install_meta.json").write_text(
        json.dumps({"source": source}, indent=2), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="model varsa bile yeniden kur")
    ap.add_argument("--light", action="store_true",
                    help="hafif model (Argos, int8, ~100 MB): RAM'i yarilar, kalite biraz duser")
    args = ap.parse_args()

    if is_valid(TARGET_DIR) and not args.force:
        print(f"Model zaten kurulu: {TARGET_DIR}")
        return 0

    if args.light:
        # Argos paketi zaten int8: dosya ~100 MB, yuklerken ayrilan bellek de
        # fp16 opus-mt'nin (~490 MB) cok altinda kalir.
        order = (("argos", try_argos), ("hf-ct2", try_hf_ct2))
    else:
        order = (("hf-ct2", try_hf_ct2), ("argos", try_argos),
                 ("temp-venv", try_temp_venv_conversion))

    for name, fn in order:
        if fn(TARGET_DIR):
            write_meta(TARGET_DIR, name)
            size_mb = sum(f.stat().st_size for f in TARGET_DIR.rglob("*") if f.is_file()) / 1e6
            print(f"\nKurulum tamam ({name}), boyut: {size_mb:.0f} MB")
            return 0

    print("\nHicbir yontem basarili olmadi. config.yaml icinde translate.engine: none "
          "yapip sadece Ingilizce transkriptle devam edebilirsin.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
