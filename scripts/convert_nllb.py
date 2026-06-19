"""One-off: convert facebook/nllb-200-distilled-600M to CTranslate2 int8.

Why this exists: ctranslate2 4.7.2's TransformersConverter passes a `dtype` kwarg
to `from_pretrained`, which transformers 4.44.2 (pinned for the STT stack) forwards
into the model constructor and rejects. We can't bump transformers without breaking
faster-whisper/PhoWhisper, so we monkeypatch the converter's load step to drop the
unsupported kwarg for this single conversion. The model weights are read from the
HF cache (already downloaded), so this does not re-download 2.4GB.

Run once from repo root:
    python -m scripts.convert_nllb
Produces: models/nllb-200-distilled-600M-ct2/  (what NLLBEngine loads)
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import ctranslate2
import ctranslate2.converters.transformers as ct2t

_OUT = Path(__file__).resolve().parent.parent / "models" / "nllb-200-distilled-600M-ct2"

# Drop the `dtype` kwarg that transformers 4.44.2 can't accept; load float32 then
# quantize to int8 (quantization happens in spec building, independent of load dtype).
_orig_load_model = ct2t.TransformersConverter.load_model


def _patched_load_model(self, model_class, model_name_or_path, **kwargs):
    kwargs.pop("dtype", None)
    return model_class.from_pretrained(model_name_or_path, **kwargs)


ct2t.TransformersConverter.load_model = _patched_load_model


def main() -> None:
    if _OUT.exists():
        print(f"[convert] already exists: {_OUT}")
        return
    print("[convert] converting facebook/nllb-200-distilled-600M → CT2 int8 ...")
    converter = ctranslate2.converters.TransformersConverter("facebook/nllb-200-distilled-600M")
    converter.convert(str(_OUT), quantization="int8")
    print(f"[convert] done → {_OUT}")


if __name__ == "__main__":
    main()
