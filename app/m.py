from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pathlib import Path

# 👇 Database imports
from app.database import Base, engine, get_db
from app.models import User
from app.auth import hash_password, verify_password

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# 👇 Create DB tables automatically
Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------- SIGNUP ----------
@app.post("/signup")
def signup(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return RedirectResponse("/", status_code=303)

    new_user = User(
        name=name,
        email=email,
        hashed_password=hash_password(password),
    )
    db.add(new_user)
    db.commit()

    return RedirectResponse("/", status_code=303)





@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})





# this is only ccopy code of main 
