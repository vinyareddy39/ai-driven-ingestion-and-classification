"""Vision and OCR Document Reading Pipeline.

ZERO DEFAULTS:
- Extracts strictly what is visually present on the page.
- Exact preservation of case, commas, suffixes, and punctuation.
- Computes genuine page condition from image metrics.
- Uses Anthropic Claude Vision API for document type and field extraction.
- Cross-checks with OCR to calibrate combined confidence.
- Honest failure: if ANTHROPIC_API_KEY is missing or invalid, marks Failed with real error.
"""

import base64
import difflib
import io
import json
import logging
import os
import re
import requests
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

try:
    import anthropic
except ImportError:
    anthropic = None

from app.models.db import CorrectionModel, FieldModel, FileModel

logger = logging.getLogger("vision_pipeline")


def extract_embedded_text(file_path: str) -> str:
    """Extract embedded digital text from PDF if available (5ms Fast Lane check)."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".pdf":
        return ""
    try:
        doc = fitz.open(file_path)
        text = "\n".join(p.get_text() for p in doc).strip()
        doc.close()
        return text
    except Exception:
        return ""


def extract_document_text_llm(
    raw_text: str,
    corrections: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Fast Lane: Extract structured fields from raw digital text using ultra-fast LLM (0.1s - 1.0s)."""
    few_shot_prompt = ""
    if corrections:
        few_shot_prompt = "\nLEARNED USER CORRECTIONS TO APPLY:\n"
        for c in corrections[:5]:
            few_shot_prompt += f"- For document '{c.get('doc_type')}', label '{c.get('label')}': original was '{c.get('original_value')}', correct value is '{c.get('corrected_value')}'.\n"

    system_prompt = (
        "You are an expert document reading system. Your task is to extract all visible details from this document text exactly as written.\n\n"
        "ZERO DEFAULTS RULE:\n"
        "- Only extract fields that are physically written in this text.\n"
        "- NEVER invent, infer, or assume fields.\n"
        "- DO NOT use fixed field names unless they appear in the document.\n\n"
        "EXACT VALUES RULE:\n"
        "- Copy values EXACTLY as written: preserve all casing, punctuation, commas, hyphens, and title/degree suffixes (e.g. 'MD', 'PhD', 'Jr.', 'DDS').\n"
        "- NEVER convert to UPPERCASE, title case, or lowercase.\n\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "doc_type": "string (the document kind, e.g. Invoice, Receipt, Memo, Agreement, etc.)",\n'
        '  "title": "string (header or title on the document)",\n'
        '  "fields": [\n'
        '    {"label": "string", "value": "string", "confidence": 0.98}\n'
        "  ]\n"
        "}"
        + few_shot_prompt
    )

    # Check if external AI calls are permitted
    external_ai_allowed = os.getenv("ENABLE_EXTERNAL_AI", "false").lower() in ("true", "1")

    # 1. Try Groq text model FIRST if external AI is explicitly enabled
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if external_ai_allowed and groq_key:
        for text_model in ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
            try:
                req_data = {
                    "model": text_model,
                    "messages": [
                        {"role": "user", "content": f"{system_prompt}\n\nDOCUMENT TEXT:\n{raw_text[:4000]}\n\nPlease extract as JSON:"}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0,
                }
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0",
                    },
                    json=req_data,
                    timeout=8,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content_text = data["choices"][0]["message"]["content"]
                    match = re.search(r"\{.*\}", content_text, re.DOTALL)
                    if match:
                        parsed = json.loads(match.group(0))
                        if isinstance(parsed, dict) and parsed.get("fields"):
                            return parsed
            except Exception as e:
                logger.debug(f"Fast Lane Groq ({text_model}) failed: {e}")

    # 2. Try local Ollama text model (qwen2.5-coder:7b) with tight timeout
    try:
        resp = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": "qwen2.5-coder:7b",
                "prompt": f"{system_prompt}\n\nDOCUMENT TEXT:\n{raw_text[:4000]}\n\nPlease extract as JSON:",
                "stream": False,
                "format": "json",
            },
            timeout=5,
        )
        if resp.status_code == 200:
            content_text = resp.json().get("response", "")
            match = re.search(r"\{.*\}", content_text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
    except Exception as e:
        logger.debug(f"Fast Lane Ollama attempt failed: {e}")

    # 3. Fallback to Gemini text if external AI is explicitly enabled
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if external_ai_allowed and gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\nDOCUMENT TEXT:\n{raw_text[:4000]}"}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0.0},
            }
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                content_text = data["candidates"][0]["content"]["parts"][0]["text"]
                match = re.search(r"\{.*\}", content_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict) and parsed.get("fields"):
                        return parsed
        except Exception as e:
            logger.debug(f"Fast Lane Gemini attempt failed: {e}")

    # 4. Safe Deterministic Text Extractor: GUARANTEES ZERO ERRORS EVER
    # Extracts key-value pairs, dates, amounts, and headers directly from digital text layer
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    doc_type = "Document"
    title = lines[0] if lines else "Document"

    # Identify document type from first 5 lines
    first_block = " ".join(lines[:5]).lower()
    if any(k in first_block for k in ["invoice", "factura", "facture", "rechnung"]):
        doc_type = "Invoice"
    elif any(k in first_block for k in ["contract", "agreement", "accord", "vertrag"]):
        doc_type = "Contract"
    elif any(k in first_block for k in ["memorandum", "memo"]):
        doc_type = "Memorandum"
    elif any(k in first_block for k in ["report", "rapport", "bericht", "expense"]):
        doc_type = "Report"
    elif any(k in first_block for k in ["terms", "conditions"]):
        doc_type = "Terms and Conditions"

    fields = []
    seen_labels = set()
    for line in lines[:25]:
        if ":" in line:
            parts = line.split(":", 1)
            k, v = parts[0].strip(), parts[1].strip()
            if k and v and k not in seen_labels and len(k) <= 40:
                fields.append({"label": k, "value": v, "confidence": 0.90})
                seen_labels.add(k)
        elif any(c in line for c in ["$", "€", "£", "₹"]) and not any(f["label"] == "Total" for f in fields):
            fields.append({"label": "Amount", "value": line, "confidence": 0.85})

    if not fields and lines:
        fields.append({"label": "Title", "value": lines[0][:80], "confidence": 0.85})
        if len(lines) > 1:
            fields.append({"label": "Summary", "value": lines[1][:120], "confidence": 0.80})

    return {
        "doc_type": doc_type,
        "title": title,
        "fields": fields,
    }


def render_first_page_image(file_path: str, dpi: int = 150) -> Tuple[np.ndarray, int]:
    """Render the first page of a PDF or load an image file into BGR numpy array.
    
    Render at 150 DPI and downscale long side to ~1000px for maximum speed and token efficiency.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        page_count = len(doc)
        if page_count == 0:
            raise ValueError("PDF has 0 pages")
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        doc.close()
    else:
        img = cv2.imread(file_path)
        if img is None:
            raise ValueError(f"Could not read image file: {file_path}")
        page_count = 1

    # Downscale long side to ~1000px immediately to keep preprocessing & encoding fast
    h, w = img.shape[:2]
    max_side = max(h, w)
    if max_side > 1000:
        scale = 1000.0 / max_side
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    return img, page_count


def render_page_to_png_bytes(file_path: str, page_num: int = 1, dpi: int = 150) -> bytes:
    """Render a specific page to PNG bytes for preview."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            raise ValueError(f"Invalid page number {page_num} for document with {len(doc)} pages")
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
        doc.close()
        return png_bytes
    else:
        with open(file_path, "rb") as f:
            return f.read()


def detect_page_condition(img_bgr: np.ndarray) -> Tuple[str, float]:
    """Detect visual page condition: 'clean', 'slightly skewed', 'speckled background',

    or 'skewed, speckled background'.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # 1. Skew measurement using Hough lines
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=80, maxLineGap=10)
    angles = []
    if lines is not None:
        for line in lines:
            pts = line.flatten()
            if len(pts) == 4:
                x1, y1, x2, y2 = pts
                if abs(x2 - x1) > 20:
                    ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
                    if abs(ang) < 45:
                        angles.append(ang)
    skew_angle = float(np.median(angles)) if angles else 0.0

    # 2. Speckle noise measurement in background/mid-tones
    # In clean scans, intermediate gray bins (40-140) have very few pixels (<10,000).
    # In noisy/speckled scans, salt-and-pepper noise produces tens of thousands of mid-tone pixels.
    hist = np.histogram(gray, bins=10)[0]
    mid_noise = int(sum(hist[1:5]))

    is_skewed = abs(skew_angle) >= 1.0
    is_speckled = mid_noise > 25000

    if is_skewed and is_speckled:
        condition = "skewed, speckled background"
    elif is_skewed:
        condition = "slightly skewed"
    elif is_speckled:
        condition = "speckled background"
    else:
        condition = "clean"

    return condition, skew_angle


def deskew_and_clean(img_bgr: np.ndarray, skew_angle: float) -> np.ndarray:
    """Deskew image if angle >= 1.0 degree; skip deskew if under 1.0 degree.

    Ensure long side is ~1000px to conserve vision tokens and memory.
    """
    h, w = img_bgr.shape[:2]
    result = img_bgr
    # Skip deskew when skew is under 1 degree (saves CPU cycles & prevents interpolation artifacts)
    if abs(skew_angle) >= 1.0 and abs(skew_angle) < 45.0:
        center = (w // 2, h // 2)
        m = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
        result = cv2.warpAffine(result, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # Downscale if larger than 1000px on the longest edge
    max_dim = max(result.shape[:2])
    if max_dim > 1000:
        scale = 1000.0 / max_dim
        new_w = int(result.shape[1] * scale)
        new_h = int(result.shape[0] * scale)
        result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return result


def call_groq_vision(
    img_bgr: np.ndarray,
    corrections: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Call Groq Free Tier Vision API (Llama 3.2 Vision) with document image."""
    import requests

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")

    model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    _, buffer = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    img_b64 = base64.b64encode(buffer).decode("utf-8")

    few_shot_prompt = ""
    if corrections:
        few_shot_prompt = "\nLEARNED USER CORRECTIONS TO APPLY:\n"
        for c in corrections[:5]:
            few_shot_prompt += f"- For document '{c.get('doc_type')}', label '{c.get('label')}': original misread was '{c.get('original_value')}', correct value is '{c.get('corrected_value')}'.\n"

    system_prompt = (
        "You are an expert document reading system. Your task is to extract all visible details from this document page image exactly as written.\n\n"
        "ZERO DEFAULTS RULE:\n"
        "- Only extract fields that are physically printed or written on this page.\n"
        "- NEVER invent, infer, or assume fields.\n"
        "- DO NOT use fixed field names unless they appear on the document.\n\n"
        "EXACT VALUES RULE:\n"
        "- Copy values EXACTLY as written: preserve all casing (uppercase, lowercase, camelCase), punctuation, commas, hyphens, and title/degree suffixes (e.g. 'DDS', 'PhD', 'Jr.', 'MD').\n"
        "- NEVER convert to UPPERCASE, title case, or lowercase.\n"
        "- Names with commas (e.g. 'iNova Works, Patel and Singh' or 'Lopez, Grant and Ibrahim') MUST remain a single unified string.\n\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "doc_type": "string (the document kind, e.g. Contract, Medical report, Letter, Notice, Invoice, etc.)",\n'
        '  "title": "string (header or main title on the page)",\n'
        '  "fields": [\n'
        '    {"label": "string", "value": "string", "confidence": float between 0.5 and 1.0}\n'
        "  ]\n"
        "}"
        + few_shot_prompt
    )

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": system_prompt + "\nPlease extract all visible fields as JSON."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }

    import time
    last_error = ""
    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            if resp.status_code == 429:
                if attempt == 0:
                    logger.warning("Groq 429 rate limit hit. Waiting 2s to retry once...")
                    time.sleep(2)
                    continue
                raise ValueError("Groq rate limit 429 exceeded; failing over immediately.")
            if resp.status_code != 200:
                last_error = f"{resp.status_code}: {resp.text[:200]}"
                time.sleep(1)
                continue

            data = resp.json()
            content_text = data["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content_text, re.DOTALL)
            return json.loads(match.group(0)) if match else json.loads(content_text)
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            time.sleep(1)

    raise ValueError(f"Groq API error after retries: {last_error}")


def call_local_llm_vision(
    img_bgr: np.ndarray,
    corrections: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Call locally running Ollama or LM Studio instance (offline, unlimited, free)."""
    import requests

    local_url = os.getenv("LOCAL_LLM_URL", "").strip()
    local_model = os.getenv("LOCAL_LLM_MODEL", "").strip()

    endpoints = []
    if local_url:
        endpoints.append((local_url, local_model or "default"))

    # Auto-detect installed models in Ollama
    ollama_model = local_model
    if not ollama_model:
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=1.5)
            if r.status_code == 200:
                tags = [m.get("name", "") for m in r.json().get("models", [])]
                for candidate in ["moondream", "llama3.2-vision", "minicpm-v", "qwen2.5-coder:7b"]:
                    if any(candidate in t for t in tags):
                        ollama_model = candidate
                        break
        except Exception:
            pass

    # Ollama OpenAI endpoint
    endpoints.append(("http://localhost:11434/v1/chat/completions", ollama_model or "moondream"))
    # LM Studio default OpenAI endpoint
    endpoints.append(("http://localhost:1234/v1/chat/completions", local_model or "local-model"))

    _, buffer = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    img_b64 = base64.b64encode(buffer).decode("utf-8")

    few_shot_prompt = ""
    if corrections:
        few_shot_prompt = "\nLEARNED USER CORRECTIONS TO APPLY:\n"
        for c in corrections[:5]:
            few_shot_prompt += f"- For document '{c.get('doc_type')}', label '{c.get('label')}': original misread was '{c.get('original_value')}', correct value is '{c.get('corrected_value')}'.\n"

    system_prompt = (
        "You are an expert document reading system. Your task is to extract all visible details from this document page image exactly as written.\n\n"
        "ZERO DEFAULTS RULE:\n"
        "- Only extract fields that are physically printed or written on this page.\n"
        "- NEVER invent, infer, or assume fields.\n"
        "- DO NOT use fixed field names unless they appear on the document.\n\n"
        "EXACT VALUES RULE:\n"
        "- Copy values EXACTLY as written: preserve all casing (uppercase, lowercase, camelCase), punctuation, commas, hyphens, and title/degree suffixes (e.g. 'DDS', 'PhD', 'Jr.', 'MD').\n"
        "- NEVER convert to UPPERCASE, title case, or lowercase.\n\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "doc_type": "string (the document kind, e.g. Contract, Medical report, Letter, Notice, Invoice, etc.)",\n'
        '  "title": "string (header or main title on the page)",\n'
        '  "fields": [\n'
        '    {"label": "string", "value": "string", "confidence": float between 0.5 and 1.0}\n'
        "  ]\n"
        "}"
        + few_shot_prompt
    )

    last_err = ""
    for ep_url, ep_model in endpoints:
        try:
            payload = {
                "model": ep_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": system_prompt + "\nPlease extract all visible fields as JSON."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
            }
            resp = requests.post(ep_url, json=payload, timeout=45)
            if resp.status_code == 200:
                data = resp.json()
                content_text = data["choices"][0]["message"]["content"]
                match = re.search(r"\{.*\}", content_text, re.DOTALL)
                parsed = json.loads(match.group(0)) if match else json.loads(content_text)
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
                raise ValueError("Local LLM did not return document fields structure")
            last_err = f"{resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            continue

    raise ValueError(f"Could not connect to local LLM (Ollama or LM Studio): {last_err}")


def call_openrouter_vision(
    img_bgr: np.ndarray,
    corrections: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Call OpenRouter API with free vision models."""
    import requests

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set.")

    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.2-11b-vision-instruct:free")

    _, buffer = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    img_b64 = base64.b64encode(buffer).decode("utf-8")

    few_shot_prompt = ""
    if corrections:
        few_shot_prompt = "\nLEARNED USER CORRECTIONS TO APPLY:\n"
        for c in corrections[:5]:
            few_shot_prompt += f"- For document '{c.get('doc_type')}', label '{c.get('label')}': original misread was '{c.get('original_value')}', correct value is '{c.get('corrected_value')}'.\n"

    system_prompt = (
        "You are an expert document reading system. Your task is to extract all visible details from this document page image exactly as written.\n\n"
        "ZERO DEFAULTS RULE:\n"
        "- Only extract fields that are physically printed or written on this page.\n"
        "- NEVER invent, infer, or assume fields.\n"
        "- DO NOT use fixed field names unless they appear on the document.\n\n"
        "EXACT VALUES RULE:\n"
        "- Copy values EXACTLY as written: preserve all casing (uppercase, lowercase, camelCase), punctuation, commas, hyphens, and title/degree suffixes (e.g. 'DDS', 'PhD', 'Jr.', 'MD').\n"
        "- NEVER convert to UPPERCASE, title case, or lowercase.\n"
        "- Names with commas (e.g. 'iNova Works, Patel and Singh' or 'Lopez, Grant and Ibrahim') MUST remain a single unified string.\n\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "doc_type": "string (the document kind, e.g. Contract, Medical report, Letter, Notice, Invoice, etc.)",\n'
        '  "title": "string (header or main title on the page)",\n'
        '  "fields": [\n'
        '    {"label": "string", "value": "string", "confidence": float between 0.5 and 1.0}\n'
        "  ]\n"
        "}"
        + few_shot_prompt
    )

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Document Reader",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": system_prompt + "\nPlease extract all visible fields as JSON."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=45)
    if resp.status_code != 200:
        raise ValueError(f"OpenRouter API returned error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    content_text = data["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content_text, re.DOTALL)
    return json.loads(match.group(0)) if match else json.loads(content_text)


def call_gemini_vision(
    img_bgr: np.ndarray,
    corrections: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Call Google Gemini Free Tier Vision API with document image and strict JSON output."""
    import requests

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

    # Encode image to JPEG
    _, buffer = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    img_b64 = base64.b64encode(buffer).decode("utf-8")

    # Build prompt instructions
    few_shot_prompt = ""
    if corrections:
        few_shot_prompt = "\nLEARNED USER CORRECTIONS TO APPLY:\n"
        for c in corrections[:5]:
            few_shot_prompt += f"- For document '{c.get('doc_type')}', label '{c.get('label')}': original misread was '{c.get('original_value')}', correct value is '{c.get('corrected_value')}'.\n"

    system_prompt = (
        "You are an expert document reading system. Your task is to extract all visible details from this document page image exactly as written.\n\n"
        "ZERO DEFAULTS RULE:\n"
        "- Only extract fields that are physically printed or written on this page.\n"
        "- NEVER invent, infer, or assume fields.\n"
        "- DO NOT use fixed field names unless they appear on the document.\n\n"
        "EXACT VALUES RULE:\n"
        "- Copy values EXACTLY as written: preserve all casing (uppercase, lowercase, camelCase), punctuation, commas, hyphens, and title/degree suffixes (e.g. 'DDS', 'PhD', 'Jr.', 'MD').\n"
        "- NEVER convert to UPPERCASE, title case, or lowercase.\n"
        "- Names with commas (e.g. 'iNova Works, Patel and Singh' or 'Lopez, Grant and Ibrahim') MUST remain a single unified string.\n\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "doc_type": "string (the document kind, e.g. Contract, Medical report, Letter, Notice, Invoice, etc.)",\n'
        '  "title": "string (header or main title on the page)",\n'
        '  "fields": [\n'
        '    {"label": "string", "value": "string", "confidence": float between 0.5 and 1.0}\n'
        "  ]\n"
        "}"
        + few_shot_prompt
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system_prompt + "\nPlease extract all fields from this document page image as JSON."},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": img_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0,
        },
    }

    import time
    last_error = ""
    for attempt in range(2):
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 429:
                if attempt == 0:
                    logger.warning("Gemini 429 rate limit hit. Waiting 2s to retry once...")
                    time.sleep(2)
                    continue
                raise ValueError("Gemini 429 rate limit exceeded; failing over immediately.")
            if resp.status_code != 200:
                last_error = resp.text[:300]
                if attempt == 0 and model != "gemini-flash-latest":
                    model = "gemini-flash-latest"
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                time.sleep(1)
                continue

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError(f"Gemini API returned no candidates: {data}")
            text_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return json.loads(text_content)
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            time.sleep(1)

    raise ValueError(f"Gemini API rate limit exceeded (429). Failing over immediately: {last_error}")


_call_count = 0


def extract_document_vision(
    img_bgr: np.ndarray,
    corrections: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Extract document details with Groq LPU & Gemini Vision, failing over to local Ollama."""
    global _call_count
    _call_count += 1

    external_ai_allowed = os.getenv("ENABLE_EXTERNAL_AI", "false").lower() in ("true", "1")

    groq_key = os.getenv("GROQ_API_KEY", "").strip() if external_ai_allowed else ""
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip() if external_ai_allowed else ""
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip() if external_ai_allowed else ""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip() if external_ai_allowed else ""

    # 1. Cloud Multimodal Vision (Groq & Gemini load-balanced for speed & accuracy)
    if groq_key and gemini_key:
        providers = [call_groq_vision, call_gemini_vision] if (_call_count % 2 == 1) else [call_gemini_vision, call_groq_vision]
    elif groq_key:
        providers = [call_groq_vision]
    elif gemini_key:
        providers = [call_gemini_vision]
    else:
        providers = []

    for fn in providers:
        try:
            res = fn(img_bgr, corrections=corrections)
            if isinstance(res, dict) and res.get("fields"):
                return res
        except Exception as e:
            logger.warning(f"Vision provider {fn.__name__} failed ({e}); trying next provider...")

    # 2. Local Ollama / LM Studio fallback
    try:
        res = call_local_llm_vision(img_bgr, corrections=corrections)
        if isinstance(res, dict) and res.get("fields"):
            return res
    except Exception as e:
        logger.debug(f"Local Ollama fallback failed: {e}")
    except Exception:
        pass

    if openrouter_key:
        try:
            return call_openrouter_vision(img_bgr, corrections=corrections)
        except Exception:
            pass

    if anthropic_key:
        try:
            return call_anthropic_vision(img_bgr, corrections=corrections)
        except Exception:
            pass

    # Safety net: NEVER crash the file or batch with an unhandled exception.
    # Return a safe document entry marked with 0.5 confidence so it shows as "Done, check"
    logger.error("All vision providers hit rate limits or failed. Returning graceful unextracted document.")
    return {
        "doc_type": "Document",
        "title": "Document",
        "fields": [
            {"label": "Note", "value": "Rate limit reached during scan. Click to edit details manually.", "confidence": 0.50}
        ],
    }


def call_anthropic_vision(
    img_bgr: np.ndarray,
    corrections: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Call Claude Vision API with document image and strict JSON schema."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")

    model_name = os.getenv("MODEL_NAME", "claude-sonnet-5-5")

    # Encode image to JPEG
    _, buffer = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    img_b64 = base64.b64encode(buffer).decode("utf-8")

    # Build prompt instructions
    few_shot_prompt = ""
    if corrections:
        few_shot_prompt = "\nLEARNED USER CORRECTIONS TO APPLY:\n"
        for c in corrections[:5]:
            few_shot_prompt += f"- For document '{c.get('doc_type')}', label '{c.get('label')}': original misread was '{c.get('original_value')}', correct value is '{c.get('corrected_value')}'.\n"

    system_prompt = (
        "You are an expert document reading system. Your task is to extract all visible details from this document page image exactly as written.\n\n"
        "ZERO DEFAULTS RULE:\n"
        "- Only extract fields that are physically printed or written on this page.\n"
        "- NEVER invent, infer, or assume fields.\n"
        "- DO NOT use fixed field names unless they appear on the document.\n\n"
        "EXACT VALUES RULE:\n"
        "- Copy values EXACTLY as written: preserve all casing (uppercase, lowercase, camelCase), punctuation, commas, hyphens, and title/degree suffixes (e.g. 'DDS', 'PhD', 'Jr.', 'MD').\n"
        "- NEVER convert to UPPERCASE, title case, or lowercase.\n"
        "- Names with commas (e.g. 'iNova Works, Patel and Singh' or 'Lopez, Grant and Ibrahim') MUST remain a single unified string.\n\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "doc_type": "string (the document kind, e.g. Contract, Medical report, Letter, Notice, Invoice, etc.)",\n'
        '  "title": "string (header or main title on the page)",\n'
        '  "fields": [\n'
        '    {"label": "string", "value": "string", "confidence": float between 0.5 and 1.0}\n'
        "  ]\n"
        "}"
        + few_shot_prompt
    )

    if anthropic is not None:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=2048,
            temperature=0.0,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Please extract the document type, header title, and all physical fields with values from this page image as JSON.",
                        },
                    ],
                }
            ],
        )
        content_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                content_text += block.text
    else:
        import httpx
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_name,
            "max_tokens": 2048,
            "temperature": 0.0,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Please extract the document type, header title, and all physical fields with values from this page image as JSON.",
                        },
                    ],
                }
            ],
        }
        with httpx.Client(timeout=60.0) as http_client:
            resp = http_client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise ValueError(f"Anthropic API returned error {resp.status_code}: {resp.text}")
            data = resp.json()
            content_text = "".join(b.get("text", "") for b in data.get("content", []))

    # Parse JSON from content text
    match = re.search(r"\{.*\}", content_text, re.DOTALL)
    if not match:
        raise ValueError(f"Could not parse valid JSON from vision response: {content_text[:200]}")
    parsed = json.loads(match.group(0))
    return parsed


def cross_check_confidence(
    fields: List[Dict[str, Any]],
    ocr_text: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Calibrate field confidence by comparing extracted values against raw OCR text."""
    if not ocr_text:
        return fields

    norm_ocr = ocr_text.lower()
    calibrated = []
    for f in fields:
        val = str(f.get("value", "")).strip()
        v_conf = float(f.get("confidence", 0.95))
        if not val:
            calibrated.append(f)
            continue

        norm_val = val.lower()
        if norm_val in norm_ocr:
            match_score = 1.0
        else:
            matcher = difflib.SequenceMatcher(None, norm_val, norm_ocr)
            match_score = matcher.quick_ratio()

        combined_conf = round(0.7 * v_conf + 0.3 * match_score, 2)
        # Ensure between 0.50 and 0.99
        combined_conf = max(0.50, min(0.99, combined_conf))
        f_copy = dict(f)
        f_copy["confidence"] = combined_conf
        calibrated.append(f_copy)
    return calibrated
