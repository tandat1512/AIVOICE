"""OCR service abstraction for image translation.

PaddleOCR is the preferred backend when installed. Tesseract remains a lightweight
fallback so image/travel features degrade gracefully on machines without Paddle.
"""

from __future__ import annotations

import os
import io
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class OcrResult:
    text: str
    blocks: list[dict]
    status: str = "ok"
    engine: str = ""
    lang: str = ""
    error: str | None = None


_PADDLE_LANG = {
    "vie_Latn": "vi",
    "vi": "vi",
    "eng_Latn": "en",
    "en": "en",
    "jpn_Jpan": "japan",
    "ja": "japan",
    "kor_Hang": "korean",
    "ko": "korean",
    "zho_Hans": "ch",
    "zh": "ch",
    "fra_Latn": "fr",
    "fr": "fr",
    "deu_Latn": "german",
    "de": "german",
    "spa_Latn": "es",
    "es": "es",
    "tha_Thai": "th",
    "th": "th",
}

_TESSERACT_LANG = {
    "vie_Latn": "vie",
    "vi": "vie",
    "eng_Latn": "eng",
    "en": "eng",
    "jpn_Jpan": "jpn",
    "ja": "jpn",
    "kor_Hang": "kor",
    "ko": "kor",
    "zho_Hans": "chi_sim",
    "zh": "chi_sim",
    "fra_Latn": "fra",
    "fr": "fra",
    "deu_Latn": "deu",
    "de": "deu",
    "spa_Latn": "spa",
    "es": "spa",
    "tha_Thai": "tha",
    "th": "tha",
}

_GOOGLE_LANG = {
    "vie_Latn": "vi",
    "vi": "vi",
    "eng_Latn": "en",
    "en": "en",
    "jpn_Jpan": "ja",
    "ja": "ja",
    "kor_Hang": "ko",
    "ko": "ko",
    "zho_Hans": "zh",
    "zh": "zh",
    "fra_Latn": "fr",
    "fr": "fr",
    "deu_Latn": "de",
    "de": "de",
    "spa_Latn": "es",
    "es": "es",
    "tha_Thai": "th",
    "th": "th",
}

_PADDLE_SUPPORTED_SUFFIXES = {
    ".bmp", ".dib", ".jpeg", ".jpg", ".png", ".webp", ".pbm", ".pgm", ".ppm",
    ".pnm", ".sr", ".ras", ".tiff", ".tif", ".pdf",
}

_VI_OCR_REPLACEMENTS = (
    ("DIÉM", "ĐIỂM"),
    ("Bài tp", "Bài tập"),
    ("bài tp", "bài tập"),
    ("luyn tp", "luyện tập"),
    ("k năng", "kỹ năng"),
    ("ly d liu", "lấy dữ liệu"),
    ("t ngưi", "từ người"),
    ("thc hin", "thực hiện"),
    ("ép kiu", "ép kiểu"),
    ("đ tính toán", "để tính toán"),
    ("Nhim v", "Nhiệm vụ"),
    ("nhim v", "nhiệm vụ"),
    ("Vit mt", "Viết một"),
    ("vit mt", "viết một"),
    ("chưong trình", "chương trình"),
    ("ngui dùng", "người dùng"),
    ("nhp vào mt s", "nhập vào một số"),
    ("tin USD", "tiền USD"),
    ("chuyn đồi", "chuyển đổi"),
    ("chuyn đổi", "chuyển đổi"),
    ("mt t giá", "một tỷ giá"),
    ("cho truóc", "cho trước"),
    ("cho truoc", "cho trước"),
    ("inputO", "input()"),
)


class OcrService:
    def __init__(self, default_engine: str | None = None) -> None:
        self._default_engine = (default_engine or os.environ.get("OCR_ENGINE", "auto")).strip().lower()
        self._paddle_cache: dict[str, Any] = {}
        self._google_client: Any | None = None

    def warmup(self, *, engine: str | None = None, lang: str | None = None) -> None:
        selected = (engine or self._default_engine or "auto").strip().lower()
        if selected in {"auto", "paddle"}:
            paddle_lang = _PADDLE_LANG.get((lang or "vie_Latn").strip(), "vi")
            try:
                from paddleocr import PaddleOCR

                cache_key = self._paddle_cache_key(paddle_lang)
                if cache_key not in self._paddle_cache:
                    self._paddle_cache[cache_key] = self._create_paddle_ocr(PaddleOCR, paddle_lang)
            except Exception as exc:
                print(f"[OCR] Paddle warmup skipped: {exc}", flush=True)

    def extract_text(
        self,
        image_bytes: bytes,
        filename: str = "",
        *,
        engine: str | None = None,
        lang: str | None = None,
    ) -> OcrResult:
        if not image_bytes:
            raise ValueError("image file is empty")

        selected = (engine or self._default_engine or "auto").strip().lower()
        if selected == "none":
            return OcrResult(text="", blocks=[], status="unavailable", engine="none", lang=lang or "", error="OCR is disabled.")

        errors: list[str] = []
        if selected in {"auto", "google", "google_vision"} and (selected != "auto" or self._should_try_google()):
            result = self._extract_with_google_vision(image_bytes, filename, lang or "")
            if result.status == "ok" or selected in {"google", "google_vision"}:
                return result
            if result.error:
                errors.append(result.error)

        if selected in {"auto", "paddle"}:
            result = self._extract_with_paddle(image_bytes, filename, lang or "")
            if result.status == "ok" or selected == "paddle":
                return result
            if result.error:
                errors.append(result.error)

        if selected in {"auto", "tesseract"}:
            result = self._extract_with_tesseract(image_bytes, filename, lang or "")
            if result.status == "ok" or selected == "tesseract":
                return result
            if result.error:
                errors.append(result.error)

        return OcrResult(
            text="",
            blocks=[],
            status="unavailable",
            engine=selected,
            lang=lang or "",
            error="; ".join(errors) or "No OCR backend is available.",
        )

    @staticmethod
    def _should_try_google() -> bool:
        if os.environ.get("OCR_AUTO_TRY_GOOGLE", "").strip().lower() in {"1", "true", "yes"}:
            return True
        return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))

    def _extract_with_google_vision(self, image_bytes: bytes, filename: str, lang: str) -> OcrResult:
        google_lang = _GOOGLE_LANG.get((lang or "").strip(), "en")
        try:
            from google.cloud import vision
        except Exception as exc:
            return OcrResult(
                text="",
                blocks=[],
                status="unavailable",
                engine="google",
                lang=google_lang,
                error=f"Google Vision dependency missing: {exc}. Install google-cloud-vision.",
            )

        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
            return OcrResult(
                text="",
                blocks=[],
                status="unavailable",
                engine="google",
                lang=google_lang,
                error="Google Vision credentials missing. Set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file.",
            )

        try:
            if self._google_client is None:
                self._google_client = vision.ImageAnnotatorClient()

            image = vision.Image(content=image_bytes)
            context = vision.ImageContext(language_hints=[google_lang])
            response = self._google_client.document_text_detection(image=image, image_context=context)
            if response.error.message:
                raise RuntimeError(response.error.message)

            blocks = self._postprocess_blocks(self._normalize_google_result(response), google_lang)
            text = ""
            if getattr(response, "full_text_annotation", None):
                text = (response.full_text_annotation.text or "").strip()
            if not text and getattr(response, "text_annotations", None):
                text = (response.text_annotations[0].description or "").strip()
            text = self._postprocess_text(text, google_lang)
            if not text:
                return OcrResult(
                    text="",
                    blocks=[],
                    status="no_text",
                    engine="google",
                    lang=google_lang,
                    error="No text detected in image.",
                )
            return OcrResult(text=text, blocks=blocks, status="ok", engine="google", lang=google_lang)
        except Exception as exc:
            return OcrResult(
                text="",
                blocks=[],
                status="error",
                engine="google",
                lang=google_lang,
                error=f"Google Vision OCR failed: {exc}",
            )

    def _extract_with_paddle(self, image_bytes: bytes, filename: str, lang: str) -> OcrResult:
        paddle_lang = _PADDLE_LANG.get((lang or "").strip(), "en")
        image_bytes, suffix = self._prepare_image_bytes(image_bytes, filename, for_paddle=True)
        tmp_path = ""
        try:
            from paddleocr import PaddleOCR

            cache_key = self._paddle_cache_key(paddle_lang)
            ocr = self._paddle_cache.get(cache_key)
            if ocr is None:
                ocr = self._create_paddle_ocr(PaddleOCR, paddle_lang)
                self._paddle_cache[cache_key] = ocr

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            raw = self._run_paddle_ocr(ocr, tmp_path)

            blocks = self._postprocess_blocks(self._normalize_paddle_result(raw), paddle_lang)
            text = "\n".join(block["text"] for block in blocks if block.get("text")).strip()
            text = self._postprocess_text(text, paddle_lang)
            if not text:
                return OcrResult(
                    text="",
                    blocks=[],
                    status="no_text",
                    engine="paddle",
                    lang=paddle_lang,
                    error="No text detected in image.",
                )
            return OcrResult(text=text, blocks=blocks, status="ok", engine="paddle", lang=paddle_lang)
        except Exception as exc:
            return OcrResult(
                text="",
                blocks=[],
                status="unavailable",
                engine="paddle",
                lang=paddle_lang,
                error=f"PaddleOCR unavailable: {exc}",
            )
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    @staticmethod
    def _paddle_cache_key(paddle_lang: str) -> str:
        profile = os.environ.get("OCR_PADDLE_PROFILE", "fast").strip().lower()
        version = os.environ.get("OCR_PADDLE_VERSION", "").strip()
        return f"{paddle_lang}:{profile}:{version}"

    @staticmethod
    def _paddle_ocr_version() -> str:
        explicit = os.environ.get("OCR_PADDLE_VERSION", "").strip()
        if explicit:
            return explicit
        profile = os.environ.get("OCR_PADDLE_PROFILE", "fast").strip().lower()
        if profile == "accurate":
            return "PP-OCRv6"
        if profile == "balanced":
            return "PP-OCRv5"
        return "PP-OCRv3"

    @staticmethod
    def _create_paddle_ocr(PaddleOCR, paddle_lang: str):
        ocr_version = OcrService._paddle_ocr_version()
        attempts = [
            {
                "lang": paddle_lang,
                "ocr_version": ocr_version,
                "device": os.environ.get("OCR_DEVICE", "cpu"),
                "enable_mkldnn": False,
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
            },
            {
                "lang": paddle_lang,
                "ocr_version": ocr_version,
                "device": os.environ.get("OCR_DEVICE", "cpu"),
                "enable_mkldnn": False,
            },
            {"lang": paddle_lang, "ocr_version": ocr_version},
            {"lang": paddle_lang},
        ]
        last_error: Exception | None = None
        for kwargs in attempts:
            try:
                return PaddleOCR(**kwargs)
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return PaddleOCR(lang=paddle_lang)

    @staticmethod
    def _run_paddle_ocr(ocr, image_path: str):
        if hasattr(ocr, "predict"):
            return ocr.predict(image_path)
        try:
            return ocr.ocr(image_path)
        except Exception:
            raise

    def _extract_with_tesseract(self, image_bytes: bytes, filename: str, lang: str) -> OcrResult:
        try:
            from PIL import Image
            import pytesseract
        except Exception as exc:
            return OcrResult(
                text="",
                blocks=[],
                status="unavailable",
                engine="tesseract",
                lang=lang or "",
                error=f"Tesseract dependency missing: {exc}. Install Pillow, pytesseract, and Tesseract OCR.",
            )

        tess_lang = _TESSERACT_LANG.get((lang or "").strip(), "eng")
        image_bytes, suffix = self._prepare_image_bytes(image_bytes, filename, for_paddle=False)
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            image = Image.open(tmp_path)
            text = self._postprocess_text((pytesseract.image_to_string(image, lang=tess_lang) or "").strip(), tess_lang)
            blocks = self._postprocess_blocks(self._extract_tesseract_blocks(pytesseract, image, tess_lang), tess_lang)
            if not text:
                return OcrResult(
                    text="",
                    blocks=[],
                    status="no_text",
                    engine="tesseract",
                    lang=tess_lang,
                    error="No text detected in image.",
                )
            return OcrResult(text=text, blocks=blocks, status="ok", engine="tesseract", lang=tess_lang)
        except Exception as exc:
            return OcrResult(
                text="",
                blocks=[],
                status="error",
                engine="tesseract",
                lang=tess_lang,
                error=f"Tesseract OCR failed: {exc}",
            )
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    @staticmethod
    def _safe_image_suffix(filename: str, *, for_paddle: bool) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix == ".jfif":
            return ".jpg"
        if not suffix:
            return ".png"
        if for_paddle and suffix not in _PADDLE_SUPPORTED_SUFFIXES:
            return ".png"
        return suffix

    @staticmethod
    def _prepare_image_bytes(image_bytes: bytes, filename: str, *, for_paddle: bool) -> tuple[bytes, str]:
        suffix = OcrService._safe_image_suffix(filename, for_paddle=for_paddle)
        if suffix == ".pdf" or os.environ.get("OCR_PREPROCESS", "1").strip().lower() in {"0", "false", "no"}:
            return image_bytes, suffix

        try:
            from PIL import Image, ImageEnhance, ImageOps
        except Exception:
            return image_bytes, suffix

        try:
            image = Image.open(io.BytesIO(image_bytes))
            image = ImageOps.exif_transpose(image).convert("RGB")
            width, height = image.size
            max_side = max(1000, int(os.environ.get("OCR_MAX_SIDE", "2800")))
            min_side = max(800, int(os.environ.get("OCR_MIN_SIDE", "1600")))
            scale = max(1.0, float(os.environ.get("OCR_SCALE", "2")))

            longest = max(width, height)
            factor = 1.0
            if longest < min_side:
                factor = min(scale, max_side / longest)
            elif min(width, height) < 900 and longest < max_side:
                factor = min(1.5, max_side / longest)

            if factor > 1.01:
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                image = image.resize((int(width * factor), int(height * factor)), resampling)

            image = ImageOps.autocontrast(image)
            image = ImageEnhance.Contrast(image).enhance(1.25)
            image = ImageEnhance.Sharpness(image).enhance(1.35)

            out = io.BytesIO()
            image.save(out, format="PNG", optimize=True)
            return out.getvalue(), ".png"
        except Exception:
            return image_bytes, suffix

    @staticmethod
    def _postprocess_blocks(blocks: list[dict], lang: str) -> list[dict]:
        processed: list[dict] = []
        for block in blocks:
            item = dict(block)
            if item.get("text"):
                item["text"] = OcrService._postprocess_text(str(item["text"]), lang)
            processed.append(item)
        return processed

    @staticmethod
    def _postprocess_text(text: str, lang: str) -> str:
        clean = unicodedata.normalize("NFC", text or "")
        if lang in {"vi", "vie", "vie_Latn"}:
            for source, target in _VI_OCR_REPLACEMENTS:
                clean = clean.replace(source, target)
        clean = re.sub(r"[^\S\r\n]+", " ", clean)
        return clean.strip()

    @staticmethod
    def _extract_tesseract_blocks(pytesseract, image, lang: str) -> list[dict]:
        try:
            data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
        except Exception:
            return []

        blocks: list[dict] = []
        for i, text in enumerate(data.get("text", [])):
            clean = (text or "").strip()
            if not clean:
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
            try:
                confidence = float(data.get("conf", ["-1"])[i])
            except (TypeError, ValueError):
                confidence = -1.0
            blocks.append({"text": clean, "bbox": [x, y, x + w, y + h], "confidence": confidence})
        return blocks

    @staticmethod
    def _normalize_google_result(response: Any) -> list[dict]:
        blocks: list[dict] = []
        annotation = getattr(response, "full_text_annotation", None)
        if annotation:
            for page in getattr(annotation, "pages", []) or []:
                for block in getattr(page, "blocks", []) or []:
                    for paragraph in getattr(block, "paragraphs", []) or []:
                        words = []
                        for word in getattr(paragraph, "words", []) or []:
                            value = "".join(symbol.text for symbol in getattr(word, "symbols", []) or [])
                            if value:
                                words.append(value)
                        text = " ".join(words).strip()
                        if not text:
                            continue
                        item = {"text": text}
                        bbox = OcrService._google_vertices_to_bbox(getattr(paragraph, "bounding_box", None))
                        if bbox:
                            item["bbox"] = bbox
                        confidence = getattr(paragraph, "confidence", None)
                        if confidence is not None:
                            item["confidence"] = float(confidence)
                        blocks.append(item)

        if blocks:
            return blocks

        for item in getattr(response, "text_annotations", []) or []:
            text = (getattr(item, "description", "") or "").strip()
            if not text or "\n" in text:
                continue
            block = {"text": text}
            bbox = OcrService._google_vertices_to_bbox(getattr(item, "bounding_poly", None))
            if bbox:
                block["bbox"] = bbox
            blocks.append(block)
        return blocks

    @staticmethod
    def _google_vertices_to_bbox(poly: Any) -> list[int] | None:
        vertices = getattr(poly, "vertices", None)
        if not vertices:
            return None
        xs = [int(getattr(vertex, "x", 0) or 0) for vertex in vertices]
        ys = [int(getattr(vertex, "y", 0) or 0) for vertex in vertices]
        if not xs or not ys:
            return None
        return [min(xs), min(ys), max(xs), max(ys)]

    @staticmethod
    def _normalize_paddle_result(raw: Any) -> list[dict]:
        lines: list[Any] = []
        dict_blocks: list[dict] = []

        def collect(node: Any) -> None:
            if isinstance(node, dict):
                OcrService._collect_paddle_dict(node, dict_blocks)
                for value in node.values():
                    collect(value)
                return
            if not isinstance(node, list):
                return
            if len(node) >= 2 and OcrService._looks_like_box(node[0]) and isinstance(node[1], (tuple, list)):
                lines.append(node)
                return
            for child in node:
                collect(child)

        collect(raw)

        blocks: list[dict] = dict_blocks
        for line in lines:
            box = line[0]
            rec = line[1]
            text = str(rec[0]).strip() if rec else ""
            if not text:
                continue
            confidence = None
            if len(rec) > 1:
                try:
                    confidence = float(rec[1])
                except (TypeError, ValueError):
                    confidence = None
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            blocks.append({
                "text": text,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "confidence": confidence,
            })
        return blocks

    @staticmethod
    def _collect_paddle_dict(node: dict, out: list[dict]) -> None:
        texts = OcrService._first_present(node, ("rec_texts", "texts", "text"))
        scores = OcrService._first_present(node, ("rec_scores", "scores", "confidence"))
        boxes = OcrService._first_present(node, ("rec_boxes", "dt_polys", "boxes"))

        if hasattr(texts, "tolist"):
            texts = texts.tolist()
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if hasattr(boxes, "tolist"):
            boxes = boxes.tolist()
        if isinstance(texts, str):
            texts = [texts]
        if texts is None:
            return
        if not isinstance(texts, list):
            return

        for i, text in enumerate(texts):
            clean = str(text or "").strip()
            if not clean:
                continue
            confidence = None
            if isinstance(scores, list) and i < len(scores):
                try:
                    confidence = float(scores[i])
                except (TypeError, ValueError):
                    confidence = None
            elif isinstance(scores, (int, float)):
                confidence = float(scores)

            bbox = None
            if boxes is not None:
                try:
                    box = boxes[i] if isinstance(boxes, list) else boxes
                    bbox = OcrService._box_to_bbox(box)
                except Exception:
                    bbox = None

            item = {"text": clean, "confidence": confidence}
            if bbox:
                item["bbox"] = bbox
            if item not in out:
                out.append(item)

    @staticmethod
    def _first_present(node: dict, keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in node and node[key] is not None:
                return node[key]
        return None

    @staticmethod
    def _box_to_bbox(box: Any) -> list[int] | None:
        if box is None:
            return None
        if hasattr(box, "tolist"):
            box = box.tolist()
        if not isinstance(box, list):
            return None
        if len(box) == 4 and all(isinstance(x, (int, float)) for x in box):
            x1, y1, x2, y2 = [int(x) for x in box]
            return [x1, y1, x2, y2]
        if len(box) >= 4 and all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in box[:4]):
            xs = [int(point[0]) for point in box[:4]]
            ys = [int(point[1]) for point in box[:4]]
            return [min(xs), min(ys), max(xs), max(ys)]
        return None

    @staticmethod
    def _looks_like_box(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) >= 4
            and all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in value[:4])
        )
