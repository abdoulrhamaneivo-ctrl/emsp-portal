"""Point d'entrée FastAPI du portail EMSP Candidature.

Montage :
- CORS restrictif (localhost uniquement),
- SecurityHeaders (nosniff / DENY / same-origin),
- 4 routers (auth, candidature, documents, misc),
- statique frontend en `/` si le dossier existe,
- `GET /health`, `GET /` (index.html ou JSON),
- handler 500 générique FR sans stacktrace.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import get_db, init_db
from app.auth import COOKIE_NAME, refresh_session_cookie
from app.config import settings
from app.routes_admin import router as admin_router
from app.routes_auth import router as auth_router
from app.routes_candidature import router as candidature_router
from app.routes_documents import router as documents_router
from app.routes_misc import router as misc_router
from app.routes_verif import router as verif_router
from app.ui import (
    get_optional_user,
    render_admin,
    render_candidature,
    render_conditions,
    render_contact,
    render_convocation,
    render_dashboard,
    render_login,
    render_pieces,
    render_password_forgot,
    render_password_reset,
    render_profils,
    render_public_home,
    render_resultat,
    render_suivi,
)

logger = logging.getLogger("emsp")

# --- CORS restrictif : localhost uniquement ---
ALLOW_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def find_frontend_dir() -> str | None:
    """Localise le dossier frontend (dev repo, cwd, ou image Docker)."""
    here = os.path.abspath(os.path.dirname(__file__))
    candidats = [
        # backend/app/main.py -> <repo>/frontend (canonique)
        os.path.abspath(os.path.join(here, os.pardir, os.pardir, "frontend")),
        # backend/ comme cwd
        os.path.abspath(os.path.join(os.getcwd(), "frontend")),
        os.path.abspath(os.path.join(os.getcwd(), "..", "frontend")),
        # Image Docker éventuelle
        "/app/frontend",
        "/frontend",
        "/app",
    ]
    for candidat in candidats:
        index = os.path.join(candidat, "index.html")
        if os.path.isdir(candidat) and os.path.isfile(index):
            return candidat
    return None


FRONTEND_DIR = find_frontend_dir()
ASSETS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "frontend")
)
PHOTOS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "Photos")
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _amorcer_admin()
    yield


def _amorcer_admin() -> None:
    """Crée le compte « super admin » si ADMIN_EMAIL/ADMIN_PASSWORD sont définis.

    Sans ces variables, aucun administrateur n'est créé : c'est volontaire,
    on ne fabrique pas d'accès privilégié par défaut.
    """
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return
    try:
        from app.admin_cli import creer_admin

        ok, message = creer_admin(
            settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD, settings.ADMIN_NOM
        )
        if ok:
            print(f"[admin] {message}")
    except Exception as exc:  # pragma: no cover - démarrage ne doit jamais échouer
        print(f"[admin] création impossible : {type(exc).__name__}")


app = FastAPI(title="EMSP Portail Candidature", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.middleware("http")
async def session_refresh_middleware(request: Request, call_next):
    """Réémet le cookie `emsp_session` après glissement d'expiry.

    `get_current_user` prolonge `expires_at` en BDD et pose
    `request.state.refresh_session=True` (+ token et nouvel expires).
    Ce middleware traduit ce flag en `Set-Cookie` avec `max_age` recalculé,
    en conservant les attributs canoniques (httponly / samesite / secure / path).
    """
    response = await call_next(request)
    if getattr(request.state, "refresh_session", False):
        token = getattr(
            request.state, "refresh_session_token", None
        ) or request.cookies.get(COOKIE_NAME)
        expires_at = getattr(request.state, "refresh_session_expires_at", None)
        if token:
            if expires_at is not None:
                refresh_session_cookie(response, token, expires_at)
            else:
                # Repli : réémet avec la durée de vie standard.
                from datetime import datetime, timedelta, timezone

                fallback_expires = datetime.now(timezone.utc).replace(
                    tzinfo=None
                ) + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
                refresh_session_cookie(response, token, fallback_expires)
    return response


# --- Routers métier (ne pas recréer : simple montage) ---
app.include_router(auth_router)
app.include_router(candidature_router)
app.include_router(documents_router)
app.include_router(misc_router)
app.include_router(admin_router)  # accès à toutes les soumissions (rôle ADMIN)
app.include_router(verif_router)  # contrôles de vérification (rôle ADMIN)


@app.get("/health", tags=["meta"])
def health():
    # Vérification de vie uniquement : ne pas garder Neon actif via les pings
    # fréquents de Render, afin de rester dans le quota gratuit.
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
def ready(db: Session = Depends(get_db)):
    # Contrôle DB explicite, destiné aux opérations et vérifications manuelles.
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}


@app.get("/", tags=["meta"])
def root(request: Request, user=Depends(get_optional_user)):
    """Page d'accueil côté backend, avec nav/footer dépendants de la session."""
    return render_public_home(user)


@app.get("/index.html", tags=["meta"])
def index_html(request: Request, user=Depends(get_optional_user)):
    return render_public_home(user)


@app.get("/connexion.html", tags=["meta"])
def connexion_html(request: Request, user=Depends(get_optional_user)):
    if user is not None:
        destination = (
            "/admin.html"
            if (user.role or "CANDIDAT").upper() == "ADMIN"
            else "/espace-candidat.html"
        )
        return RedirectResponse(url=destination, status_code=302)
    return render_login(user)


@app.get("/mot-de-passe-oublie.html", tags=["meta"])
def mot_de_passe_oublie_html(request: Request, user=Depends(get_optional_user)):
    return render_password_forgot(user)


@app.get("/reinitialiser-mot-de-passe.html", tags=["meta"])
def reinitialiser_mot_de_passe_html(
    request: Request, token: str = "", user=Depends(get_optional_user)
):
    return render_password_reset(user, token)


@app.get("/candidature.html", tags=["meta"])
def candidature_html(request: Request, user=Depends(get_optional_user)):
    return render_candidature(user)


@app.get("/espace-candidat.html", tags=["meta"])
def espace_candidat_html(request: Request, user=Depends(get_optional_user)):
    return render_dashboard(user)


@app.get("/admin.html", tags=["meta"])
def admin_html(request: Request, user=Depends(get_optional_user)):
    return render_admin(user)


@app.get("/conditions.html", tags=["meta"])
def conditions_html(request: Request, user=Depends(get_optional_user)):
    return render_conditions(user)


@app.get("/contact.html", tags=["meta"])
def contact_html(request: Request, user=Depends(get_optional_user)):
    return render_contact(user)


@app.get("/profil.html", tags=["meta"])
def profil_html(request: Request, user=Depends(get_optional_user)):
    return render_profils(user)


@app.get("/pieces.html", tags=["meta"])
def pieces_html(request: Request, user=Depends(get_optional_user)):
    return render_pieces(user)


@app.get("/suivi.html", tags=["meta"])
def suivi_html(request: Request, user=Depends(get_optional_user)):
    return render_suivi(user)


@app.get("/convocation.html", tags=["meta"])
def convocation_html(request: Request, user=Depends(get_optional_user)):
    return render_convocation(user)


@app.get("/resultat.html", tags=["meta"])
def resultat_html(request: Request, user=Depends(get_optional_user)):
    return render_resultat(user)


@app.exception_handler(Exception)
async def erreur_interne_generique(request: Request, exc: Exception):
    # Laisse passer les erreurs HTTP volontaires (401/403/404/422/429...).
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        status = getattr(exc, "status_code", 500)
        detail = getattr(exc, "detail", None) or "Une erreur est survenue."
        return JSONResponse(status_code=status, content={"detail": detail})
    logger.exception("Erreur interne non gérée sur %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Une erreur est survenue. Veuillez réessayer."},
    )


# --- Statique frontend en dernier (ne doit pas écraser les routes /api) ---
if os.path.isdir(PHOTOS_DIR):
    app.mount("/media", StaticFiles(directory=PHOTOS_DIR), name="media")

if os.path.isdir(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

if FRONTEND_DIR:
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
