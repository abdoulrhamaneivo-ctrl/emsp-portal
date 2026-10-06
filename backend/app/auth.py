"""Authentification : hachage bcrypt, sessions opaques via cookie, dépendances."""

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Candidature, Session as SessionModel, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIE_NAME = "emsp_session"

# Seuil de glissement : si la session expire dans moins de 30 minutes,
# elle est prolongée automatiquement (expiry glissante).
REFRESH_THRESHOLD_MINUTES = 30

# Compteur de dossiers : CDT_0001, CDT_0002, ...
_NUMERO_RE = re.compile(r"^CDT_(\d{4,})$")


# --- Mots de passe ---


def hash_password(password: str) -> str:
    """Hache un mot de passe en clair avec bcrypt."""
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Vérifie un mot de passe en clair contre son hash bcrypt."""
    return pwd_context.verify(password, password_hash)


# --- Numéros de dossier ---


def generate_numero_dossier(db: Session) -> str:
    """Génère le prochain numéro de dossier (CDT_%04d, max + 1).

    La sécurité transactionnelle repose sur la contrainte d'unicité
    (clé primaire) : en cas de conflit concurrent, l'appelant doit
    annuler (rollback) puis réessayer.
    """
    numeros = [row[0] for row in db.query(Candidature.numero_dossier).all()]
    best = 0
    for numero in numeros:
        match = _NUMERO_RE.match(numero or "")
        if match:
            try:
                best = max(best, int(match.group(1)))
            except ValueError:
                continue
    return f"CDT_{best + 1:04d}"


# --- Sessions ---


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_session(db: Session, user_id: int) -> str:
    """Crée une session opaque et retourne son token."""
    token = secrets.token_urlsafe(32)
    expires_at = _utcnow() + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
    db.add(SessionModel(id=token, user_id=user_id, expires_at=expires_at))
    db.commit()
    return token


def delete_session(db: Session, token: str) -> None:
    """Supprime une session (logout). Idempotent."""
    session = db.get(SessionModel, token)
    if session is not None:
        db.delete(session)
        db.commit()


def get_session_token(request: Request) -> str | None:
    """Lit le token de session depuis le cookie HttpOnly."""
    return request.cookies.get(COOKIE_NAME)


def _cookie_kwargs(expires_at: datetime | None = None) -> dict:
    """Attributs canoniques du cookie de session (émission / réémission)."""
    if expires_at is not None:
        remaining = (expires_at - _utcnow()).total_seconds()
        max_age = max(int(remaining), 1)
    else:
        max_age = settings.SESSION_EXPIRE_MINUTES * 60
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": settings.COOKIE_SECURE,
        "max_age": max_age,
    }


def refresh_session_cookie(
    response: Response, token: str, expires_at: datetime
) -> None:
    """Réémet le cookie `emsp_session` avec les mêmes attributs.

    Utilisé après un glissement d'expiry : `max_age` est recalculé
    à partir de `expires_at` pour rester cohérent avec la BDD.
    """
    response.set_cookie(value=token, **_cookie_kwargs(expires_at))


def est_admin(user) -> bool:
    """Vrai si le compte est un administrateur actif."""
    return bool(user) and (getattr(user, "role", "CANDIDAT") or "").upper() == "ADMIN" and getattr(
        user, "actif", True
    )


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Dépendance FastAPI : retourne l'utilisateur connecté ou 401.

    Lit le cookie `emsp_session`, vérifie l'existence et l'expiration
    de la session en BDD.
    """
    token = get_session_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié. Veuillez vous connecter.",
        )
    session = db.get(SessionModel, token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié. Veuillez vous connecter.",
        )
    if session.expires_at <= _utcnow():
        db.delete(session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expirée. Veuillez vous reconnecter.",
        )
    user = db.get(User, session.user_id)
    if user is None:
        db.delete(session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié. Veuillez vous connecter.",
        )
    # --- Expiry glissante : prolonge si < 30 min restantes ---
    now = _utcnow()
    remaining = (session.expires_at - now).total_seconds()
    if remaining < REFRESH_THRESHOLD_MINUTES * 60:
        new_expires = now + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
        session.expires_at = new_expires
        db.commit()
        db.refresh(session)
        request.state.refresh_session = True
        request.state.refresh_session_token = token
        request.state.refresh_session_expires_at = new_expires
    return user
