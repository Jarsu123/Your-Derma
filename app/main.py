from fastapi import FastAPI, Request, Form, Depends, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import uuid
import os

# ✅ ADDED (speed debug + compress)
import time
import io
from PIL import Image

# 👇 Database imports
from app.database import Base, engine, get_db
from app.models import User

# 👇 Auth
from app.auth import hash_password, verify_password

# 👇 AI
from app.ai import analyze_image_bytes


# =========================
#   PATHS + ENV
# =========================
APP_DIR = Path(__file__).resolve().parent          # .../Your drma/app
ROOT_DIR = APP_DIR.parent                          # .../Your drma

# Load .env from project root: Your drma/.env
load_dotenv(dotenv_path=str(ROOT_DIR / ".env"))

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "CHANGE_THIS_TO_A_LONG_RANDOM_SECRET"),
    same_site="lax",
    https_only=False,  # production me True (HTTPS)
)

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# Ensure uploads folder exists
(APP_DIR / "static" / "uploads").mkdir(parents=True, exist_ok=True)

# Create tables
Base.metadata.create_all(bind=engine)


# =========================
#   ROUTES
# =========================
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.post("/signup")
def signup(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = (email or "").lower().strip()
    password = password or ""

    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return RedirectResponse("/signup?err=already_exists", status_code=303)

        new_user = User(
            name=name,
            email=email,
            hashed_password=hash_password(password),
        )

        db.add(new_user)
        db.commit()

        return RedirectResponse("/", status_code=303)

    except IntegrityError as e:
        db.rollback()
        print("❌ IntegrityError:", e)
        return RedirectResponse("/signup?err=email_taken", status_code=303)

    except Exception as e:
        db.rollback()
        print("❌ Signup failed:", repr(e))
        raise HTTPException(status_code=500, detail=f"Signup error: {repr(e)}")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, err: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "err": err})


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = (email or "").lower().strip()
    password = password or ""

    user = db.query(User).filter(User.email == email).first()
    if not user:
        return RedirectResponse("/login?err=invalid", status_code=303)

    if not verify_password(password, user.hashed_password):
        return RedirectResponse("/login?err=invalid", status_code=303)

    request.session["user_id"] = user.id
    request.session["user_email"] = user.email

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse("upload.html", {"request": request, "err": ""})


@app.post("/upload", response_class=HTMLResponse)
def upload_photo(request: Request, photo: UploadFile = File(...)):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)

    allowed = {"image/jpeg", "image/png", "image/webp"}
    if photo.content_type not in allowed:
        return templates.TemplateResponse(
            "upload.html",
            {"request": request, "err": "Only JPG/PNG/WEBP images allowed."},
            status_code=400,
        )

    # ✅ Read bytes ONCE
    img_bytes = photo.file.read()
    if not img_bytes:
        return templates.TemplateResponse(
            "upload.html",
            {"request": request, "err": "Empty image. Upload again."},
            status_code=400,
        )

    # ✅ SPEED BOOST (NEW): compress BEFORE sending to AI
    # (Gemini ko heavy image mat bhejo — yahi main delay fix hai)
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        im.thumbnail((800, 800))  # max 800px
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=65, optimize=True)
        img_bytes = buf.getvalue()
        print("✅ Compressed size:", round(len(img_bytes) / 1024), "KB")
    except Exception as _:
        # agar koi image issue ho to original bytes use rehne do
        pass

    # ✅ AI analyze with safe error handling + timing
    try:
        t0 = time.time()
        ai = analyze_image_bytes(img_bytes, mime_type=photo.content_type)
        print("✅ AI took:", round(time.time() - t0, 2), "sec")
        print("AI RESULT:", ai)
    except Exception as e:
        print("AI ERROR:", repr(e))
        return templates.TemplateResponse(
            "upload.html",
            {"request": request, "err": f"AI failed: {str(e)}"},
            status_code=500,
        )

    # ✅ STRICT CHECK: only accept acne or hair
    if ai.get("category") not in ["acne", "hair"]:
        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "err": "Please upload a clear FACE (acne) or SCALP/HAIR photo only.",
            },
            status_code=400,
        )

    # ✅ Keep your old reject logic (fixed indentation)
    if (not ai.get("relevant")) or (ai.get("category") == "other"):
        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "err": f"Upload a clear FACE (acne) or SCALP/HAIR photo only. Reason: {ai.get('reason', 'not_relevant')}",
            },
            status_code=400,
        )

    # ✅ Save file after AI passed
    ext = ".jpg"
    if photo.filename and "." in photo.filename:
        ext = "." + photo.filename.split(".")[-1].lower()

    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = APP_DIR / "static" / "uploads" / filename

    with open(save_path, "wb") as f:
        f.write(img_bytes)

    # ✅ Show result
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "image_url": f"/static/uploads/{filename}",
            "prescription": ai.get("routine", []),
            "findings": ai.get("findings", []),
            "note": ai.get("safety_note", ""),
            "category": ai.get("category", "other"),
            "confidence": ai.get("confidence", 0),
        },
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)