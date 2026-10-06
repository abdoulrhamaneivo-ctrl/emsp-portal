"""Modèles SQLAlchemy : candidatures, utilisateurs, documents, contact, sessions."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    """Horodatage UTC naïf (compatible SQLite et Postgres TIMESTAMP)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Candidature(Base):
    """Dossier de candidature au concours (clé = numero_dossier, ex. CDT_0001)."""

    __tablename__ = "candidatures"

    numero_dossier: Mapped[str] = mapped_column(String(16), primary_key=True)
    code_tresor_pay: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    statut: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    etape_courante: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dossier_valide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- État civil ---
    nom: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prenoms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sexe: Mapped[str | None] = mapped_column(String(16), nullable=True)
    date_naissance: Mapped[Date | None] = mapped_column(Date, nullable=True)
    lieu_naissance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nationalite: Mapped[str] = mapped_column(String(120), nullable=False, default="Ivoirienne")
    nature_piece: Mapped[str | None] = mapped_column(String(64), nullable=True)
    numero_piece: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Coordonnées ---
    telephone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    commune: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ville: Mapped[str | None] = mapped_column(String(120), nullable=True)
    adresse: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- BAC ---
    annee_bac: Mapped[int | None] = mapped_column(Integer, nullable=True)
    serie_bac: Mapped[str | None] = mapped_column(String(16), nullable=True)
    numero_bac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    numero_table: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mention: Mapped[str | None] = mapped_column(String(64), nullable=True)
    moyenne_bac: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_math_bac: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_physique_bac: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_francais_bac: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_anglais_bac: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Choix de filières ---
    choix_1_filiere: Mapped[str | None] = mapped_column(String(120), nullable=True)
    choix_2_filiere: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- Tuteurs ---
    tuteur1_nom: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tuteur1_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tuteur1_lien: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tuteur1_residence: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tuteur2_nom: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tuteur2_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tuteur2_lien: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tuteur2_residence: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Concours ---
    date_compo: Mapped[Date | None] = mapped_column(Date, nullable=True)
    heure_compo: Mapped[str | None] = mapped_column(String(5), nullable=True)
    centre_compo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note_francais_compo: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_math_compo: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_anglais_compo: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_psycho_compo: Mapped[float | None] = mapped_column(Float, nullable=True)
    admis_concours: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    filiere_formation: Mapped[str | None] = mapped_column(String(120), nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Suivi interne (visible uniquement par l'administration) ---
    note_interne: Mapped[str | None] = mapped_column(Text, nullable=True)
    motif_refus: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Consentement à la lecture automatisée des pièces par un modèle
    # extérieur. Obligatoire pour soumettre un dossier dès lors que
    # CONSENTEMENT_TIERS_REQUIS est actif.
    consentement_tiers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    consentement_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # Relations
    utilisateur: Mapped["User"] = relationship("User", back_populates="candidature", uselist=False)
    documents: Mapped[list["DocumentCandidature"]] = relationship(
        "DocumentCandidature", back_populates="candidature", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_candidatures_statut", "statut"),)


class User(Base):
    """Compte candidat : identifiants de connexion liés à un dossier."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # Hash bcrypt — ne jamais l'exposer dans une réponse API.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    numero_dossier: Mapped[str | None] = mapped_column(
        String(16),
        ForeignKey("candidatures.numero_dossier", ondelete="CASCADE"),
        unique=True,
        nullable=True,
        index=True,
    )
    # CANDIDAT : accès à son seul dossier. ADMIN : accès à toutes les soumissions.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="CANDIDAT", index=True)
    nom_affiche: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    derniere_connexion: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    candidature: Mapped[Candidature] = relationship("Candidature", back_populates="utilisateur")
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="utilisateur", cascade="all, delete-orphan"
    )


class DocumentCandidature(Base):
    """Pièce justificative téléversée pour un dossier."""

    __tablename__ = "documents_candidature"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    numero_dossier: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("candidatures.numero_dossier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type_document: Mapped[str] = mapped_column(String(64), nullable=False)
    nom_original: Mapped[str] = mapped_column(String(500), nullable=False)
    nom_stockage: Mapped[str] = mapped_column(String(500), nullable=False)
    chemin_relatif: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    taille: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    statut: Mapped[str] = mapped_column(String(32), nullable=False, default="UPLOADED")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    candidature: Mapped[Candidature] = relationship("Candidature", back_populates="documents")

    __table_args__ = (Index("ix_documents_dossier_type", "numero_dossier", "type_document"),)


class MessageContact(Base):
    """Message du formulaire de contact public."""

    __tablename__ = "messages_contact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    telephone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    objet: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    statut: Mapped[str] = mapped_column(String(32), nullable=False, default="NOUVEAU")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ActionAdmin(Base):
    """Trace des opérations d'administration (qui, quoi, sur quel dossier, quand).

    Une administration qui gère des données personnelles doit pouvoir prouver
    ce qu'elle a consulté et modifié : chaque lecture de pièce et chaque
    changement de statut est journalisé.
    """

    __tablename__ = "actions_admin"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    numero_dossier: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_actions_admin_dossier_date", "numero_dossier", "created_at"),)


class HistoriqueStatut(Base):
    """Historique des changements de statut d'un dossier (chronologie du jury)."""

    __tablename__ = "historique_statut"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    numero_dossier: Mapped[str] = mapped_column(
        String(16), ForeignKey("candidatures.numero_dossier", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ancien_statut: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nouveau_statut: Mapped[str] = mapped_column(String(32), nullable=False)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    par_admin: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class Session(Base):
    """Session opaque : le token (id) est stocké dans le cookie `emsp_session`."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    utilisateur: Mapped[User] = relationship("User", back_populates="sessions")


class PasswordResetToken(Base):
    """Jeton de réinitialisation à usage unique ; seul son hash est conservé."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

class Controle(Base):
    """Un constat de vérification sur un dossier ou sur une de ses pièces.

    Séparé de `candidatures` par construction : un contrôle est un
    **constat**, jamais une décision. Aucun code de vérification n'écrit
    dans `candidatures` — un test le vérifie. Le jury lit les constats et
    tranche ; la machine ne modifie jamais un statut.

    `source` distingue l'origine du constat : ``deterministe`` pour un
    contrôle local, le nom du fournisseur pour une lecture par modèle.
    C'est aussi ce qui permet de savoir, d'un coup d'œil, si un dossier a
    été analysé par un tiers ou seulement déduit des métadonnées.
    """

    __tablename__ = "controles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    numero_dossier: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("candidatures.numero_dossier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL pour un contrôle portant sur le dossier entier (notes, dates).
    document_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("documents_candidature.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    type_document: Mapped[str | None] = mapped_column(String(64), nullable=True)
    controle: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    statut: Mapped[str] = mapped_column(String(32), nullable=False)
    gravite: Mapped[str] = mapped_column(String(16), nullable=False, default="mineur")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="deterministe")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    __table_args__ = (
        Index("ix_controles_dossier_controle", "numero_dossier", "controle"),
    )
