import os
import json
import io
from dotenv import load_dotenv
from PIL import Image
import google.generativeai as genai
from pathlib import Path

# =========================
#   LOAD .ENV (ROOT)
# =========================
APP_DIR = Path(__file__).resolve().parent          # .../Your drma/app
ROOT_DIR = APP_DIR.parent                          # .../Your drma
load_dotenv(dotenv_path=str(ROOT_DIR / ".env"))

API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY missing in .env (Your drma/.env)")

genai.configure(api_key=API_KEY)

# ✅ Use a valid, supported model name
MODEL_NAME = (os.getenv("GEMINI_MODEL") or "gemini-flash-latest").strip()


def analyze_image_bytes(img_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Returns a dict like:
    {
      "relevant": true/false,
      "category": "acne" | "hair" | "other",
      "confidence": 0-100,
      "findings": [...],
      "routine": [...],
      "safety_note": "..."
    }
    """

    # --- Convert bytes -> PIL Image
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        return {
            "relevant": False,
            "category": "other",
            "confidence": 0,
            "findings": [],
            "routine": [],
            "safety_note": "",
            "reason": "invalid_image",
        }

    # --- Model
    model = genai.GenerativeModel(MODEL_NAME)

    # --- Force JSON output
    prompt = """
You are an expert dermatologist AI.

STEP 1: Identify image type strictly:
- If FACE visible → category = "acne"
- If SCALP/HAIR visible → category = "hair"
- Else → category = "other"

STEP 2:
- If category = acne → give acne routine
- If category = hair → give hair fall routine
- If category = other → return relevant=false

IMPORTANT:
- Never give acne routine for hair image
- Never give hair routine for face image

Return ONLY JSON:
{
  "relevant": true/false,
  "category": "acne" | "hair" | "other",
  "confidence": 0-100,
  "findings": [],
  "routine": [],
  "safety_note": "",
  "reason": ""
}
"""

    try:
        # ✅ more consistent output
        resp = model.generate_content(
            [prompt, img],
            generation_config={"temperature": 0.0},
            request_options={"timeout": 10},
        )
        text = (resp.text or "").strip()

        # Extract JSON
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON found in model response")

        data = json.loads(text[start:end + 1])

        # Basic normalization/safety
        if "relevant" not in data:
            data["relevant"] = False
        if "category" not in data:
            data["category"] = "other"

        data.setdefault("confidence", 0)
        data.setdefault("findings", [])
        data.setdefault("routine", [])
        data.setdefault("safety_note", "")
        data.setdefault("reason", "ok")

        return data

    except Exception as e:
        return {
            "relevant": False,
            "category": "other",
            "confidence": 0,
            "findings": [],
            "routine": [],
            "safety_note": "",
            "reason": f"gemini_error: {str(e)}",
        }