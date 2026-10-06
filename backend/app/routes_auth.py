"""Routes d'authentification : inscription, connexion, déconnexion, profil."""

import re
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    create_session,
    delete_session,
    generate_numero_dossier,
    get_current_user,
    get_session_token,
    hash_password,
    verify_password,
)
from app.config import settings
from app.db import get_db
from app.email_service import (
    brevo_is_configured,
    send_password_changed_email,
    send_password_reset_email,
    send_registration_email,
)
from app.models import Candidature, PasswordResetToken, Session as SessionModel, User
from app.rate_limit import check_rate_limit

router = APIRouter()

IDENTIFIANTS_INCORRECTS = "Identifiants incorrects."
TROP_DE_TENTATIVES = "Trop de tentatives. Veuillez réessayer dans une minute."
MESSAGE_REINITIALISATION = (
    "Si un compte EMSP correspond à cette adresse et que la messagerie est activée, "
    "un lien de réinitialisation va être envoyé."
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _cookie_kwargs() -> dict:
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": settings.COOKIE_SECURE,
        "max_age": settings.SESSION_EXPIRE_MINUTES * 60,
    }


def _delete_cookie_kwargs() -> dict:
    """Attributs complets pour l'effacement du cookie (symétriques à l'émission)."""
    return {
        "key": COOKIE_NAME,
        "path": "/",
        "secure": settings.COOKIE_SECURE,
        "httponly": True,
        "samesite": "lax",
    }


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "inconnu"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Schémas ---


class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    confirmation: str = Field(..., min_length=8, max_length=128)
    nom: str = Field(..., min_length=1, max_length=120)
    prenoms: str = Field(..., min_length=1, max_length=255)

    @field_validator("email")
    @classmethod
    def _email_valide(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("Adresse e-mail invalide.")
        return value

    @field_validator("nom", "prenoms")
    @classmethod
    def _non_vide(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Ce champ est obligatoire.")
        return value

    @field_validator("password")
    @classmethod
    def _password_bcrypt_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Le mot de passe ne peut pas dépasser 72 octets.")
        return value

    @model_validator(mode="after")
    def _confirmation_identique(self):
        if self.password != self.confirmation:
            raise ValueError("La confirmation du mot de passe ne correspond pas.")
        return self


class LoginRequest(BaseModel):
    identifiant: str | None = Field(None, min_length=1, max_length=255)
    # Alias de compatibilité pour les clients qui envoient encore « email ».
    email: str | None = Field(None, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)

    @model_validator(mode="after")
    def _normaliser_identifiant(self):
        value = (self.identifiant or self.email or "").strip()
        if not value:
            raise ValueError("Saisissez votre e-mail ou votre numéro de dossier.")
        self.identifiant = value.lower() if "@" in value else value.upper()
        return self


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=255)

    @field_validator("email")
    @classmethod
    def _email_normalise(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("Adresse e-mail invalide.")
        return value


class PasswordPairRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)
    confirmation: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_bcrypt_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Le mot de passe ne peut pas dépasser 72 octets.")
        return value

    @model_validator(mode="after")
    def _confirmation_identique(self):
        if self.new_password != self.confirmation:
            raise ValueError("La confirmation du mot de passe ne correspond pas.")
        return self


class ChangePasswordRequest(PasswordPairRequest):
    current_password: str = Field(..., min_length=1, max_length=128)

    @model_validator(mode="after")
    def _mot_de_passe_different(self):
        if self.new_password == self.current_password:
            raise ValueError("Choisissez un mot de passe différent de l’actuel.")
        return self


class ResetPasswordRequest(PasswordPairRequest):
    token: str = Field(..., min_length=32, max_length=200)


class AuthResponse(BaseModel):
    message: str
    email: str
    numero_dossier: str | None = None
    statut: str | None = None
    role: str = "CANDIDAT"


class MeResponse(BaseModel):
    email: str
    numero_dossier: str | None = None
    role: str = "CANDIDAT"
    nom_affiche: str | None = None
    statut: str | None = None
    etape_courante: int = 1


# --- Routes ---


@router.post(
    "/api/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Crée un dossier DRAFT + un compte, puis ouvre une session (cookie)."""
    if not check_rate_limit(f"register:{_client_ip(request)}",
                            limit=settings.RATE_LIMIT_INSCRIPTION, window_sec=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TROP_DE_TENTATIVES
        )

    if db.query(User).filter(User.email == data.email).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un compte existe déjà avec cette adresse e-mail.",
        )

    numero_dossier = generate_numero_dossier(db)
    candidature = Candidature(
        numero_dossier=numero_dossier,
        email=data.email,
        nom=data.nom,
        prenoms=data.prenoms,
        statut="DRAFT",
        etape_courante=1,
        dossier_valide=False,
    )
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        numero_dossier=numero_dossier,
    )
    db.add(candidature)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un compte existe déjà avec cette adresse e-mail.",
        )
    db.refresh(user)

    token = create_session(db, user.id)
    response.set_cookie(value=token, **_cookie_kwargs())
    if brevo_is_configured():
        background_tasks.add_task(
            send_registration_email, user.email, data.prenoms, numero_dossier
        )

    return AuthResponse(
        message="Votre dossier est créé. Un courriel de bienvenue vous sera envoyé si la messagerie EMSP est activée.",
        email=user.email,
        numero_dossier=numero_dossier,
        statut="DRAFT",
        role=user.role,
    )


@router.post("/api/auth/login", response_model=AuthResponse)
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Vérifie les identifiants puis ouvre une session (cookie).

    Message volontairement générique (anti-énumération) en cas d'échec.
    """
    if not check_rate_limit(f"login:{_client_ip(request)}",
                            limit=settings.RATE_LIMIT_CONNEXION, window_sec=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TROP_DE_TENTATIVES
        )
    identifiant = data.identifiant or ""
    if not check_rate_limit(f"login:identifier:{identifiant}",
                            limit=settings.RATE_LIMIT_CONNEXION, window_sec=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TROP_DE_TENTATIVES
        )

    if "@" in identifiant:
        user = db.query(User).filter(User.email == identifiant).first()
    else:
        user = db.query(User).filter(User.numero_dossier == identifiant).first()
    if user is None or not user.actif or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=IDENTIFIANTS_INCORRECTS
        )

    candidature = (
        db.query(Candidature).filter(Candidature.numero_dossier == user.numero_dossier).first()
    )
    statut = candidature.statut if candidature else "DRAFT"

    user.derniere_connexion = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    token = create_session(db, user.id)
    response.set_cookie(value=token, **_cookie_kwargs())

    return AuthResponse(
        message="Connexion réussie.",
        email=user.email,
        numero_dossier=user.numero_dossier,
        statut=statut,
        role=user.role,
    )


@router.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Ferme la session et efface le cookie."""
    # Annule une éventuelle réémission glissante (la session est supprimée).
    request.state.refresh_session = False
    token = get_session_token(request)
    if token:
        delete_session(db, token)
    response.delete_cookie(**_delete_cookie_kwargs())
    return {"message": "Déconnexion réussie."}


@router.post("/api/auth/logout-all")
def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ferme TOUTES les sessions de l'utilisateur et efface le cookie."""
    # Annule une éventuelle réémission glissante (sessions supprimées).
    request.state.refresh_session = False
    db.query(SessionModel).filter(SessionModel.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.commit()
    response.delete_cookie(**_delete_cookie_kwargs())
    return {"message": "Toutes les sessions ont été fermées."}


@router.get("/api/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Profil connecté : jamais de hash, et le rôle pour l'interface."""
    candidature = None
    if current_user.numero_dossier:
        candidature = (
            db.query(Candidature)
            .filter(Candidature.numero_dossier == current_user.numero_dossier)
            .first()
        )
    if candidature is None and (current_user.role or "").upper() != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier de candidature introuvable.",
        )
    return MeResponse(
        email=current_user.email,
        numero_dossier=current_user.numero_dossier,
        role=current_user.role or "CANDIDAT",
        nom_affiche=current_user.nom_affiche,
        statut=candidature.statut if candidature else None,
        etape_courante=candidature.etape_courante if candidature else 1,
    )


@router.post("/api/auth/password/change")
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change le mot de passe après vérification du mot de passe actuel."""
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe actuel est incorrect.",
        )

    current_token = get_session_token(request)
    current_user.password_hash = hash_password(data.new_password)
    other_sessions = db.query(SessionModel).filter(SessionModel.user_id == current_user.id)
    if current_token:
        other_sessions = other_sessions.filter(SessionModel.id != current_token)
    other_sessions.delete(synchronize_session=False)
    db.commit()

    if brevo_is_configured():
        background_tasks.add_task(
            send_password_changed_email, current_user.email, current_user.nom_affiche
        )
    return {"message": "Votre mot de passe a été modifié."}


@router.post("/api/auth/password/forgot")
def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Envoie un lien de réinitialisation sans révéler si l'adresse existe."""
    if not check_rate_limit(
        f"password-reset:{_client_ip(request)}",
        limit=settings.RATE_LIMIT_PASSWORD_RESET,
        window_sec=60,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=TROP_DE_TENTATIVES,
        )

    user = db.query(User).filter(User.email == data.email).first()
    if user is not None and user.actif and brevo_is_configured():
        reset_token = secrets.token_urlsafe(32)
        now = _utcnow()
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).delete(synchronize_session=False)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hashlib.sha256(reset_token.encode("utf-8")).hexdigest(),
                expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES),
            )
        )
        db.commit()
        background_tasks.add_task(
            send_password_reset_email, user.email, user.nom_affiche, reset_token
        )
    return {"message": MESSAGE_REINITIALISATION}


@router.post("/api/auth/password/reset")
def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Consomme un jeton expirant à usage unique et ferme les sessions actives."""
    if not check_rate_limit(
        f"password-reset-confirm:{_client_ip(request)}",
        limit=settings.RATE_LIMIT_PASSWORD_RESET,
        window_sec=60,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=TROP_DE_TENTATIVES,
        )

    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > _utcnow(),
    ).with_for_update().first()
    if reset is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce lien est invalide ou a expiré. Demandez-en un nouveau.",
        )

    user = db.get(User, reset.user_id)
    if user is None or not user.actif:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce lien est invalide ou a expiré. Demandez-en un nouveau.",
        )

    reset.used_at = _utcnow()
    user.password_hash = hash_password(data.new_password)
    db.query(SessionModel).filter(SessionModel.user_id == user.id).delete(
        synchronize_session=False
    )
    request.state.refresh_session = False
    db.commit()
    response.delete_cookie(**_delete_cookie_kwargs())

    if brevo_is_configured():
        background_tasks.add_task(
            send_password_changed_email, user.email, user.nom_affiche
        )
    return {"message": "Mot de passe réinitialisé. Vous pouvez vous connecter."}
