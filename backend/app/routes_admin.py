"""Administration : accès à l'ensemble des soumissions.

Sécurité — trois règles non négociables :
1. chaque route exige `require_admin` ou `require_super_admin` (rôle vérifié côté serveur) ;
2. la lecture d'une pièce belonging à un candidat est journalisée
   (`ActionAdmin`) : l'administration rend des comptes ;
3. un compte candidat ne peut jamais atteindre ce module, quel que soit le
   numéro de dossier transmis.

Le frontend n'a aucun pouvoir : il ne fait que proposer des routes que le
serveur filtre.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password
from app.campaign import deliberation_complete, requete_cohorte
from app.config import settings
from app.db import SessionLocal, get_db
from app.demo_downloads import read_or_rebuild_demo_document
from app.models import (
    ActionAdmin,
    Candidature,
    DocumentCandidature,
    HistoriqueStatut,
    MessageContact,
    ParametresConcours,
    PieceRequise,
    ProgrammeConcours,
    User,
)
from app.schemas import SPECIALITES as FILIERES
from app.email_service import (
    brevo_is_configured, send_convocation_notification, send_result_notification,
)
from app.pdf_documents import build_convocation_pdf, build_result_certificate_pdf
from app.rate_limit import check_rate_limit
from app.storage_service import DocumentStorageService

router = APIRouter(prefix="/api/admin", tags=["administration"])

# Statuts que l'administration peut poser, et transitions autorisées.
STATUTS_ADMIN = {
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "VALIDATED",
    "RETAINED",
    "REJECTED",
    "COMPOSITION_SCHEDULED",
    "ADMITTED",
}
STATUT_LABELS = {
    "DRAFT": "Brouillon",
    "SUBMITTED": "Dossier soumis",
    "UNDER_REVIEW": "Dossier en cours d'examen",
    "VALIDATED": "Dossier validé",
    "RETAINED": "Dossier retenu",
    "REJECTED": "Dossier non retenu",
    "COMPOSITION_SCHEDULED": "Composition programmée",
    "ADMITTED": "Admis",
}
TYPES_PIECES = [
    "attestation_bac",
    "releve_notes_bac",
    "piece_identite",
    "bulletins_seconde",
    "bulletins_premiere",
    "bulletins_terminale",
    "photo_identite",
    "lettre_motivation",
    "acte_naissance",
    "cv",
]
INTERDIT = "Vous n'êtes pas autorisé à accéder à cette ressource."
INTROUVABLE = "Dossier introuvable."


# ───────────────────────────── garde-fous ─────────────────────────────
def _service() -> DocumentStorageService:
    root = settings.DOCUMENT_STORAGE_ROOT
    if not os.path.isabs(root):
        root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), os.pardir, root)
        )
    return DocumentStorageService(root)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Exige un compte ADMIN ou SUPER_ADMIN actif. 403 sinon."""
    role = (getattr(current_user, "role", "CANDIDAT") or "CANDIDAT").upper()
    if role not in {"ADMIN", "SUPER_ADMIN"} or not getattr(current_user, "actif", True):
        raise HTTPException(status_code=403, detail=INTERDIT)
    return current_user


def require_super_admin(admin: User = Depends(require_admin)) -> User:
    """Réserve les réglages globaux et les comptes de privilège au super-admin."""
    if (admin.role or "").upper() != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Cette action est réservée au super-administrateur.")
    return admin


def journaliser(
    db: Session,
    admin: User,
    action: str,
    numero_dossier: str | None = None,
    detail: str | None = None,
    request: Request | None = None,
) -> None:
    """Écrit une ligne d'audit. Ne doit jamais faire échouer l'action métier."""
    ip = None
    if request is not None and request.client is not None:
        ip = request.client.host
    db.add(
        ActionAdmin(
            admin_id=admin.id,
            admin_email=admin.email,
            action=action,
            numero_dossier=numero_dossier,
            detail=(detail or "")[:500] or None,
            ip=ip,
        )
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _envoyer_convocations_en_arriere_plan(en_attente: list[tuple[str, str]]) -> None:
    """Envoie le lot hors requête HTTP et rend chaque échec retentable."""
    with SessionLocal() as db:
        calendrier = db.get(ParametresConcours, 1)
        for numero, jeton in en_attente:
            candidature = db.get(Candidature, numero)
            if candidature is None or candidature.convocation_email_started_at is None:
                continue
            if candidature.convocation_email_started_at.isoformat() != jeton:
                continue  # une nouvelle campagne a remplacé ce lot.
            succes = False
            try:
                if (
                    calendrier
                    and calendrier.convocations_publiees_le
                    and calendrier.date_composition
                    and calendrier.centre_composition
                ):
                    succes = send_convocation_notification(
                        candidature.email, candidature.prenoms or "", candidature.numero_dossier,
                        calendrier.date_composition.strftime("%d/%m/%Y"),
                        calendrier.heure_composition or "", calendrier.centre_composition,
                    )
            except Exception:
                succes = False
            finally:
                if succes:
                    candidature.convocation_email_sent_at = _utcnow()
                candidature.convocation_email_started_at = None
                db.commit()


def _envoyer_resultats_en_arriere_plan(en_attente: list[tuple[str, str]]) -> None:
    """Notifie les décisions du jury déjà publiables, sans bloquer l'admin."""
    with SessionLocal() as db:
        for numero, jeton in en_attente:
            candidature = db.get(Candidature, numero)
            if candidature is None or candidature.result_email_started_at is None:
                continue
            if candidature.result_email_started_at.isoformat() != jeton:
                continue
            succes = False
            try:
                calendrier = db.get(ParametresConcours, 1)
                complete, _, _ = deliberation_complete(db)
                if (
                    candidature.admis_concours is not None
                    and calendrier
                    and calendrier.resultats_publies_le
                    and complete
                    and (
                        not calendrier.publication_resultats
                        or date.today() >= calendrier.publication_resultats
                    )
                ):
                    succes = send_result_notification(
                        candidature.email, candidature.prenoms or "", candidature.numero_dossier,
                    )
            except Exception:
                succes = False
            finally:
                if succes:
                    candidature.result_email_sent_at = _utcnow()
                candidature.result_email_started_at = None
                db.commit()


def _dossier(db: Session, numero: str) -> Candidature:
    if not numero or not isinstance(numero, str) or len(numero) > 16:
        raise HTTPException(status_code=404, detail=INTROUVABLE)
    c = (
        db.query(Candidature)
        .filter(Candidature.numero_dossier == numero.strip().upper())
        .first()
    )
    if c is None:
        raise HTTPException(status_code=404, detail=INTROUVABLE)
    return c


# ───────────────────────────── schémas ─────────────────────────────
class StatutChange(BaseModel):
    statut: str = Field(..., description=" nouveau statut du dossier")
    commentaire: Optional[str] = Field(None, max_length=1000)
    motif_refus: Optional[str] = Field(None, max_length=1000)


class DossierPatch(BaseModel):
    filiere_formation: Optional[str] = None
    date_compo: Optional[date] = None
    heure_compo: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    centre_compo: Optional[str] = Field(None, max_length=255)
    note_interne: Optional[str] = Field(None, max_length=4000)
    note_francais_compo: Optional[float] = None
    note_math_compo: Optional[float] = None
    note_anglais_compo: Optional[float] = None
    note_psycho_compo: Optional[float] = None
    # L'admission se décide par la route de statut, jamais par un champ
    # libre : elle est acceptée ici pour rester explicite, mais
    # l'arrière refuse toute valeur et dit où agir.
    admis_concours: Optional[bool] = None


class MessageStatut(BaseModel):
    statut: str = Field(..., pattern="^(NOUVEAU|EN_COURS|TRAITE|ARCHIVE)$")


class ProgrammeCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=16, pattern=r"^[A-Z][A-Z0-9]{1,15}$")
    libelle: str = Field(..., min_length=3, max_length=160)
    description: Optional[str] = Field(None, max_length=2000)
    ordre: int = Field(0, ge=0, le=999)


class ProgrammePatch(BaseModel):
    libelle: Optional[str] = Field(None, min_length=3, max_length=160)
    description: Optional[str] = Field(None, max_length=2000)
    ordre: Optional[int] = Field(None, ge=0, le=999)
    actif: Optional[bool] = None


class PieceCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    libelle: str = Field(..., min_length=3, max_length=160)
    description: Optional[str] = Field(None, max_length=2000)
    obligatoire: bool = True
    ordre: int = Field(0, ge=0, le=999)


class PiecePatch(BaseModel):
    libelle: Optional[str] = Field(None, min_length=3, max_length=160)
    description: Optional[str] = Field(None, max_length=2000)
    obligatoire: Optional[bool] = None
    actif: Optional[bool] = None
    ordre: Optional[int] = Field(None, ge=0, le=999)


class ConcoursPatch(BaseModel):
    campagne: str = Field(..., min_length=3, max_length=160)
    ouverture_inscriptions: Optional[date] = None
    cloture_inscriptions: Optional[date] = None
    date_composition: Optional[date] = None
    heure_composition: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    centre_composition: Optional[str] = Field(None, max_length=255)
    publication_resultats: Optional[date] = None


class BulkConfirmation(BaseModel):
    confirmation: bool = False


# ───────────────────────────── tableau de bord ─────────────────────────────
@router.get("/overview")
def overview(
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    """Compteurs pour la page d'administration."""
    par_statut: dict[str, int] = {}
    for statut, nb in (
        db.query(Candidature.statut, func.count(Candidature.numero_dossier))
        .group_by(Candidature.statut)
        .all()
    ):
        par_statut[statut] = nb
        par_statut.setdefault(STATUT_LABELS.get(statut, statut), 0)

    total_docs = db.query(func.count(DocumentCandidature.id)).scalar() or 0
    messages_non_lus = (
        db.query(func.count(MessageContact.id))
        .filter(MessageContact.statut == "NOUVEAU")
        .scalar()
        or 0
    )
    dossiers_soumis = (
        db.query(func.count(Candidature.numero_dossier))
        .filter(Candidature.statut != "DRAFT")
        .scalar()
        or 0
    )
    return {
        "dossiers_total": db.query(func.count(Candidature.numero_dossier)).scalar() or 0,
        "dossiers_soumis": dossiers_soumis,
        "par_statut": par_statut,
        "documents": total_docs,
        "messages_non_lus": messages_non_lus,
        "dernieres_actions": [
            {
                "horodatage": a.created_at.isoformat() if a.created_at else None,
                "admin": a.admin_email,
                "action": a.action,
                "numero_dossier": a.numero_dossier,
            }
            for a in db.query(ActionAdmin)
            .order_by(ActionAdmin.created_at.desc())
            .limit(12)
            .all()
        ],
    }


# ─────────────────────── paramètres du super-admin ───────────────────────
def _date_iso(value):
    return value.isoformat() if value else None


def _configuration_dict(db: Session) -> dict:
    concours = db.get(ParametresConcours, 1)
    return {
        "concours": {
            "campagne": concours.campagne if concours else "Concours EMSP",
            "ouverture_inscriptions": _date_iso(concours.ouverture_inscriptions) if concours else None,
            "cloture_inscriptions": _date_iso(concours.cloture_inscriptions) if concours else None,
            "date_composition": _date_iso(concours.date_composition) if concours else None,
            "heure_composition": concours.heure_composition if concours else None,
            "centre_composition": concours.centre_composition if concours else None,
            "publication_resultats": _date_iso(concours.publication_resultats) if concours else None,
            "convocations_publiees_le": concours.convocations_publiees_le.isoformat() if concours and concours.convocations_publiees_le else None,
            "resultats_publies_le": concours.resultats_publies_le.isoformat() if concours and concours.resultats_publies_le else None,
        },
        "filieres": [
            {"code": p.code, "libelle": p.libelle, "description": p.description, "actif": p.actif, "ordre": p.ordre}
            for p in db.query(ProgrammeConcours).order_by(ProgrammeConcours.ordre, ProgrammeConcours.code).all()
        ],
        "pieces": [
            {"code": p.code, "libelle": p.libelle, "description": p.description,
             "obligatoire": p.obligatoire, "actif": p.actif, "ordre": p.ordre}
            for p in db.query(PieceRequise).order_by(PieceRequise.ordre, PieceRequise.code).all()
        ],
    }


@router.get("/configuration")
def lire_configuration(
    db: Session = Depends(get_db), admin: User = Depends(require_super_admin),
) -> dict:
    return _configuration_dict(db)


@router.put("/configuration/concours")
def modifier_configuration_concours(
    payload: ConcoursPatch,
    db: Session = Depends(get_db), admin: User = Depends(require_super_admin),
    request: Request = None,
) -> dict:
    if payload.ouverture_inscriptions and payload.cloture_inscriptions and payload.ouverture_inscriptions > payload.cloture_inscriptions:
        raise HTTPException(status_code=422, detail="La clôture doit être postérieure à l’ouverture des inscriptions.")
    if payload.date_composition and payload.publication_resultats and payload.publication_resultats < payload.date_composition:
        raise HTTPException(status_code=422, detail="La publication des résultats ne peut pas précéder le concours.")
    row = db.get(ParametresConcours, 1)
    if row is None:
        row = ParametresConcours(id=1, campagne=payload.campagne)
        db.add(row)
    ancien_calendrier = (
        row.date_composition,
        row.heure_composition,
        row.centre_composition,
        row.publication_resultats,
    )
    for key, value in payload.model_dump().items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    nouveau_calendrier = (
        row.date_composition,
        row.heure_composition,
        row.centre_composition,
        row.publication_resultats,
    )
    if ancien_calendrier[:3] != nouveau_calendrier[:3]:
        row.convocations_publiees_le = None
        for dossier in requete_cohorte(db).all():
            dossier.convocation_email_sent_at = None
            dossier.convocation_email_started_at = None
    if ancien_calendrier[3] != nouveau_calendrier[3]:
        row.resultats_publies_le = None
    row.updated_by = admin.email
    journaliser(db, admin, "MODIFIE_CALENDRIER_CONCOURS", detail=payload.campagne, request=request)
    db.commit()
    return {"message": "Calendrier du concours enregistré.", **_configuration_dict(db)["concours"]}


@router.post("/filieres")
def creer_filiere(
    payload: ProgrammeCreate, db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin), request: Request = None,
) -> dict:
    code = payload.code.upper()
    if db.get(ProgrammeConcours, code):
        raise HTTPException(status_code=409, detail="Ce code de formation existe déjà.")
    if db.query(ProgrammeConcours).filter(func.lower(ProgrammeConcours.libelle) == payload.libelle.strip().lower()).first():
        raise HTTPException(status_code=409, detail="Cette formation existe déjà.")
    row = ProgrammeConcours(code=code, libelle=payload.libelle.strip(), description=(payload.description or "").strip() or None, ordre=payload.ordre, actif=True)
    db.add(row)
    journaliser(db, admin, "AJOUTE_FILIERE", detail=code, request=request)
    db.commit()
    return {"message": "Formation ajoutée au catalogue.", "filiere": {"code": row.code, "libelle": row.libelle}}


@router.patch("/filieres/{code}")
def modifier_filiere(
    code: str, payload: ProgrammePatch, db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin), request: Request = None,
) -> dict:
    row = db.get(ProgrammeConcours, code.upper())
    if row is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    data = payload.model_dump(exclude_unset=True)
    if data.get("libelle") and db.query(ProgrammeConcours).filter(
        func.lower(ProgrammeConcours.libelle) == data["libelle"].strip().lower(),
        ProgrammeConcours.code != row.code,
    ).first():
        raise HTTPException(status_code=409, detail="Cette formation existe déjà.")
    nouveau_libelle = data.get("libelle", row.libelle).strip()
    if nouveau_libelle != row.libelle:
        for dossier in db.query(Candidature).filter(or_(
            Candidature.choix_1_filiere == row.libelle,
            Candidature.choix_2_filiere == row.libelle,
            Candidature.filiere_formation == row.libelle,
        )).all():
            for champ in ("choix_1_filiere", "choix_2_filiere", "filiere_formation"):
                if getattr(dossier, champ) == row.libelle:
                    setattr(dossier, champ, nouveau_libelle)
    for key, value in data.items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    journaliser(db, admin, "MODIFIE_FILIERE", detail=row.code, request=request)
    db.commit()
    return {"message": "Formation mise à jour."}


@router.delete("/filieres/{code}")
def supprimer_filiere(
    code: str, db: Session = Depends(get_db), admin: User = Depends(require_super_admin),
    request: Request = None,
) -> dict:
    row = db.get(ProgrammeConcours, code.upper())
    if row is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    utilisee = db.query(Candidature.numero_dossier).filter(or_(
        Candidature.choix_1_filiere == row.libelle,
        Candidature.choix_2_filiere == row.libelle,
        Candidature.filiere_formation == row.libelle,
    )).first()
    row.actif = False  # archivage logique : conserve les références et l'historique.
    journaliser(db, admin, "RETIRE_FILIERE", detail=f"{row.code} ({'utilisée' if utilisee else 'non référencée'})", request=request)
    db.commit()
    return {"message": "Formation archivée. Les dossiers existants conservent leur libellé historique ; elle peut être réactivée."}


@router.post("/pieces")
def creer_piece_requise(
    payload: PieceCreate, db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin), request: Request = None,
) -> dict:
    if payload.code == "convocation":
        raise HTTPException(status_code=422, detail="Le type « convocation » est réservé aux documents officiels générés par l’administration.")
    if db.get(PieceRequise, payload.code):
        raise HTTPException(status_code=409, detail="Ce type de pièce existe déjà.")
    row = PieceRequise(
        code=payload.code, libelle=payload.libelle.strip(),
        description=(payload.description or "").strip() or None,
        obligatoire=payload.obligatoire, actif=True, ordre=payload.ordre,
    )
    db.add(row)
    journaliser(db, admin, "AJOUTE_PIECE_REQUISE", detail=payload.code, request=request)
    db.commit()
    return {"message": "Pièce ajoutée aux pièces à fournir."}


@router.patch("/pieces/{code}")
def modifier_piece_requise(
    code: str, payload: PiecePatch, db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin), request: Request = None,
) -> dict:
    row = db.get(PieceRequise, code)
    if row is None:
        raise HTTPException(status_code=404, detail="Pièce introuvable.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    journaliser(db, admin, "MODIFIE_PIECE_REQUISE", detail=code, request=request)
    db.commit()
    return {"message": "Règle de dépôt mise à jour."}


@router.delete("/pieces/{code}")
def supprimer_piece_requise(
    code: str, db: Session = Depends(get_db), admin: User = Depends(require_super_admin),
    request: Request = None,
) -> dict:
    row = db.get(PieceRequise, code)
    if row is None:
        raise HTTPException(status_code=404, detail="Pièce introuvable.")
    # Archivage doux : la pièce ne sera plus demandée, mais son historique reste lisible.
    row.actif = False
    journaliser(db, admin, "ARCHIVE_PIECE_REQUISE", detail=code, request=request)
    db.commit()
    return {"message": "Pièce archivée. Les documents déjà déposés restent conservés."}


@router.get("/campagne/apercu")
def apercu_campagne(
    db: Session = Depends(get_db), admin: User = Depends(require_super_admin),
) -> dict:
    concours = db.get(ParametresConcours, 1)
    calendrier_complet = bool(concours and concours.date_composition and concours.centre_composition)
    cohorte_convocations = requete_cohorte(db).with_entities(func.count(Candidature.numero_dossier)).scalar() or 0
    if concours and concours.convocations_publiees_le:
        convocations = (
            requete_cohorte(db)
            .filter(Candidature.convocation_email_sent_at.is_(None))
            .with_entities(func.count(Candidature.numero_dossier))
            .scalar() or 0
        ) if brevo_is_configured() else 0
    else:
        convocations = cohorte_convocations
    complete, total_resultats, en_attente = deliberation_complete(db)
    resultats = db.query(func.count(Candidature.numero_dossier)).filter(
        Candidature.admis_concours.is_not(None), Candidature.result_email_sent_at.is_(None),
    ).scalar() or 0
    publication_prete = bool(
        complete
        and concours
        and concours.publication_resultats
        and date.today() >= concours.publication_resultats
    )
    return {
        "convocations_a_programmer": convocations,
        "convocations_publiees": bool(concours and concours.convocations_publiees_le),
        "candidats_convoques": cohorte_convocations,
        "resultats_a_notifier": resultats,
        "resultats_publies": bool(concours and concours.resultats_publies_le),
        "resultats_prets_publication": publication_prete,
        "dossiers_sans_decision": en_attente,
        "dossiers_a_deliberer": total_resultats,
        "calendrier_complet": calendrier_complet,
        "brevo_configure": brevo_is_configured(),
    }


@router.post("/campagne/convocations")
def programmer_convocations(
    background_tasks: BackgroundTasks, payload: BulkConfirmation, db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin), request: Request = None,
) -> dict:
    if not payload.confirmation:
        raise HTTPException(status_code=422, detail="Confirmez explicitement l’envoi groupé.")
    concours = db.get(ParametresConcours, 1)
    if not concours or not concours.date_composition or not concours.centre_composition:
        raise HTTPException(status_code=409, detail="Enregistrez d’abord la date et le centre du concours.")
    candidates = requete_cohorte(db).order_by(Candidature.numero_dossier).all()
    if not candidates:
        raise HTTPException(status_code=409, detail="Aucun dossier soumis ne fait partie de cette campagne.")
    premiere_publication = concours.convocations_publiees_le is None
    concours.convocations_publiees_le = concours.convocations_publiees_le or _utcnow()
    if premiere_publication:
        for c in candidates:
            c.convocation_email_sent_at = None
            c.convocation_email_started_at = None
    changed = 0
    for c in candidates:
        c.date_compo = concours.date_composition
        c.heure_compo = concours.heure_composition
        c.centre_compo = concours.centre_composition
        if c.statut not in {"COMPOSITION_SCHEDULED", "ADMITTED", "REJECTED"}:
            ancien = c.statut
            c.statut = "COMPOSITION_SCHEDULED"
            c.reviewed_at = _utcnow()
            db.add(HistoriqueStatut(
                numero_dossier=c.numero_dossier, ancien_statut=ancien,
                nouveau_statut=c.statut, commentaire="Convocation publiée pour toute la campagne",
                par_admin=admin.email,
            ))
        changed += 1
    db.flush()
    en_attente: list[tuple[str, str]] = []
    if brevo_is_configured():
        maintenant = _utcnow()
        seuil_reprise = maintenant - timedelta(minutes=30)
        for index, c in enumerate(candidates):
            if c.convocation_email_sent_at:
                continue
            if c.convocation_email_started_at and c.convocation_email_started_at >= seuil_reprise:
                continue
            jeton = maintenant + timedelta(microseconds=index + 1)
            c.convocation_email_started_at = jeton
            en_attente.append((c.numero_dossier, jeton.isoformat()))
    action = "PUBLIE_CONVOCATIONS_CAMPAGNE" if premiere_publication else "RENVOIE_NOTIFICATIONS_CONVOCATIONS"
    journaliser(db, admin, action, detail=f"{changed} dossier(s), {len(en_attente)} notification(s) en file", request=request)
    db.commit()
    if en_attente:
        background_tasks.add_task(_envoyer_convocations_en_arriere_plan, en_attente)
    return {
        "message": (
            f"Les convocations communes sont publiées pour les {changed} dossiers de la campagne."
            if premiere_publication else f"Les informations communes sont confirmées pour {changed} dossiers."
        ),
        "programmes": changed,
        "emails_queued": len(en_attente),
        "brevo_configure": brevo_is_configured(),
        "convocations_publiees": True,
        "publication_le": concours.convocations_publiees_le.isoformat(),
    }


@router.post("/campagne/resultats/publier")
def publier_resultats_campagne(
    payload: BulkConfirmation, db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin), request: Request = None,
) -> dict:
    """Rend visibles les décisions uniquement après délibération complète."""
    if not payload.confirmation:
        raise HTTPException(status_code=422, detail="Confirmez explicitement la publication collective.")
    concours = db.get(ParametresConcours, 1)
    if not concours or not concours.publication_resultats:
        raise HTTPException(status_code=409, detail="Enregistrez d’abord la date commune de publication des résultats.")
    if date.today() < concours.publication_resultats:
        raise HTTPException(
            status_code=409,
            detail=f"La publication collective est prévue le {concours.publication_resultats.strftime('%d/%m/%Y')}.",
        )
    complete, total, en_attente = deliberation_complete(db)
    if not complete:
        raise HTTPException(
            status_code=409,
            detail=f"Publication bloquée : {en_attente} dossier(s) de la cohorte n’ont pas encore de décision du jury.",
        )
    if concours.resultats_publies_le:
        return {
            "message": f"Les résultats des {total} dossiers sont déjà publiés collectivement.",
            "resultats_publies": True,
            "publication_le": concours.resultats_publies_le.isoformat(),
        }
    concours.resultats_publies_le = _utcnow()
    journaliser(db, admin, "PUBLIE_RESULTATS_CAMPAGNE", detail=f"{total} décision(s)", request=request)
    db.commit()
    return {
        "message": f"Les résultats des {total} dossiers sont maintenant publiés ensemble.",
        "resultats_publies": True,
        "publication_le": concours.resultats_publies_le.isoformat(),
    }


@router.post("/campagne/resultats/notifier")
def notifier_resultats_publies(
    background_tasks: BackgroundTasks, payload: BulkConfirmation, db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin), request: Request = None,
) -> dict:
    if not payload.confirmation:
        raise HTTPException(status_code=422, detail="Confirmez explicitement l’envoi groupé.")
    calendrier = db.get(ParametresConcours, 1)
    complete, _, _ = deliberation_complete(db)
    if not calendrier or not calendrier.resultats_publies_le or not complete:
        raise HTTPException(status_code=409, detail="Publiez d’abord les résultats pour toute la cohorte.")
    if calendrier and calendrier.publication_resultats and date.today() < calendrier.publication_resultats:
        raise HTTPException(status_code=409, detail=f"La publication est prévue le {calendrier.publication_resultats.strftime('%d/%m/%Y')}.")
    if not brevo_is_configured():
        raise HTTPException(status_code=503, detail="Brevo n’est pas configuré : les résultats restent consultables dans l’espace candidat, aucun e-mail n’a été envoyé.")
    # Seules les décisions humaines déjà écrites par le jury peuvent être notifiées.
    candidates = db.query(Candidature).filter(
        Candidature.admis_concours.is_not(None), Candidature.result_email_sent_at.is_(None),
    ).order_by(Candidature.numero_dossier).all()
    maintenant = _utcnow()
    seuil_reprise = maintenant - timedelta(minutes=30)
    en_attente: list[tuple[str, str]] = []
    for index, c in enumerate(candidates):
        if c.result_email_started_at and c.result_email_started_at >= seuil_reprise:
            continue
        jeton = maintenant + timedelta(microseconds=index + 1)
        c.result_email_started_at = jeton
        en_attente.append((c.numero_dossier, jeton.isoformat()))
    journaliser(db, admin, "NOTIFIE_RESULTATS", detail=f"{len(en_attente)} notification(s) mise(s) en file", request=request)
    db.commit()
    if en_attente:
        background_tasks.add_task(_envoyer_resultats_en_arriere_plan, en_attente)
    return {"message": f"{len(en_attente)} notification(s) de résultat mise(s) en file d’envoi.", "emails_queued": len(en_attente)}


# ───────────────────────────── liste des dossiers ─────────────────────────────
@router.get("/candidatures")
def lister_candidatures(
    statut: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=120),
    limite: int = Query(50, ge=1, le=200),
    decalage: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Liste filtrable de toutes les soumissions."""
    query = db.query(Candidature)
    if statut:
        query = query.filter(Candidature.statut == statut)
    if q:
        motif = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Candidature.numero_dossier.ilike(motif),
                Candidature.nom.ilike(motif),
                Candidature.prenoms.ilike(motif),
                Candidature.email.ilike(motif),
            )
        )
    total = query.count()
    rows = (
        query.order_by(Candidature.updated_at.desc())
        .limit(limite)
        .offset(decalage)
        .all()
    )

    resultats = []
    for c in rows:
        exigences = db.query(PieceRequise).filter(
            PieceRequise.actif.is_(True), PieceRequise.obligatoire.is_(True),
        ).all()
        required_codes = [p.code for p in exigences]
        pieces = {
            d.type_document for d in db.query(DocumentCandidature)
            .filter(DocumentCandidature.numero_dossier == c.numero_dossier).all()
        }
        manquantes = [t for t in required_codes if t not in pieces]
        resultats.append(
            {
                "numero_dossier": c.numero_dossier,
                "nom": c.nom,
                "prenoms": c.prenoms,
                "email": c.email,
                "telephone": c.telephone,
                "statut": c.statut,
                "statut_label": STATUT_LABELS.get(c.statut, c.statut),
                "choix_1_filiere": c.choix_1_filiere,
                "choix_2_filiere": c.choix_2_filiere,
                "moyenne_bac": c.moyenne_bac,
                "annee_bac": c.annee_bac,
                "pieces_deposees": len(required_codes) - len(manquantes),
                "pieces_total": len(required_codes),
                "pieces_manquantes": manquantes,
                "soumis_le": c.submitted_at.isoformat() if c.submitted_at else None,
                "mis_a_jour_le": c.updated_at.isoformat() if c.updated_at else None,
            }
        )
    return {
        "total": total,
        "limite": limite,
        "decalage": decalage,
        "resultats": resultats,
        "filieres": [p.libelle for p in db.query(ProgrammeConcours).filter(
            ProgrammeConcours.actif.is_(True)).order_by(ProgrammeConcours.ordre).all()],
        "statuts": [{"code": k, "label": v} for k, v in STATUT_LABELS.items()],
    }


# ───────────────────────────── détail d'un dossier ─────────────────────────────
@router.get("/candidatures/{numero_dossier}")
def detail_candidature(
    numero_dossier: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    c = _dossier(db, numero_dossier)
    calendrier = db.get(ParametresConcours, 1)
    journaliser(db, admin, "CONSULTE_DOSSIER", c.numero_dossier, request=request)
    db.commit()

    storage = _service()
    documents = []
    for d in db.query(DocumentCandidature).filter(
        DocumentCandidature.numero_dossier == c.numero_dossier
    ).order_by(DocumentCandidature.type_document).all():
        try:
            storage_available = storage.file_exists(d.chemin_relatif)
        except (FileNotFoundError, ValueError):
            storage_available = False
        except Exception:
            storage_available = None
        if storage_available is False:
            d.statut = "MISSING"
        documents.append({
            "id": d.id,
            "type_document": d.type_document,
            "nom_original": d.nom_original,
            "mime_type": d.mime_type,
            "taille": d.taille,
            "statut": d.statut,
            "stockage_disponible": storage_available,
            "reparation": "Le candidat peut déposer une nouvelle version depuis son espace." if storage_available is False else None,
            "depose_le": d.created_at.isoformat() if d.created_at else None,
            "url": f"/api/admin/documents/{d.id}/download",
        })
    if any(d["stockage_disponible"] is False for d in documents):
        db.commit()
    pieces_requises = db.query(PieceRequise).filter(PieceRequise.actif.is_(True)).order_by(
        PieceRequise.ordre, PieceRequise.code,
    ).all()
    required_codes = [p.code for p in pieces_requises if p.obligatoire]
    types_deposes = {
        d["type_document"] for d in documents if d["stockage_disponible"] is not False
    }
    historique = [
        {
            "ancien_statut": h.ancien_statut,
            "nouveau_statut": h.nouveau_statut,
            "libelle": STATUT_LABELS.get(h.nouveau_statut, h.nouveau_statut),
            "commentaire": h.commentaire,
            "par": h.par_admin,
            "le": h.created_at.isoformat() if h.created_at else None,
        }
        for h in db.query(HistoriqueStatut)
        .filter(HistoriqueStatut.numero_dossier == c.numero_dossier)
        .order_by(HistoriqueStatut.created_at.desc())
        .all()
    ]
    from app.verif import rapport as rapport_verif

    return {
        "dossier": {
            "numero_dossier": c.numero_dossier,
            "nom": c.nom,
            "prenoms": c.prenoms,
            "email": c.email,
            "statut": c.statut,
            "statut_label": STATUT_LABELS.get(c.statut, c.statut),
            "note_interne": c.note_interne,
            "motif_refus": c.motif_refus,
            "date_naissance": c.date_naissance.isoformat() if c.date_naissance else None,
            "lieu_naissance": c.lieu_naissance,
            "sexe": c.sexe,
            "nationalite": c.nationalite,
            "nature_piece": c.nature_piece,
            "numero_piece": c.numero_piece,
            "code_tresor_pay": c.code_tresor_pay,
            "telephone": c.telephone,
            "commune": c.commune,
            "ville": c.ville,
            "adresse": c.adresse,
            "annee_bac": c.annee_bac,
            "serie_bac": c.serie_bac,
            "numero_bac": c.numero_bac,
            "numero_table": c.numero_table,
            "mention": c.mention,
            "moyenne_bac": c.moyenne_bac,
            "notes": {
                "math": c.note_math_bac,
                "physique": c.note_physique_bac,
                "francais": c.note_francais_bac,
                "anglais": c.note_anglais_bac,
            },
            "choix_1_filiere": c.choix_1_filiere,
            "choix_2_filiere": c.choix_2_filiere,
            "tuteur1": {
                "nom": c.tuteur1_nom,
                "contact": c.tuteur1_contact,
                "lien": c.tuteur1_lien,
                "residence": c.tuteur1_residence,
            },
            "tuteur2": {
                "nom": c.tuteur2_nom,
                "contact": c.tuteur2_contact,
                "lien": c.tuteur2_lien,
                "residence": c.tuteur2_residence,
            },
            "date_compo": calendrier.date_composition.isoformat() if calendrier and calendrier.date_composition else None,
            "heure_compo": calendrier.heure_composition if calendrier else None,
            "centre_compo": calendrier.centre_composition if calendrier else None,
            "notes_compo": {
                "francais": c.note_francais_compo,
                "math": c.note_math_compo,
                "anglais": c.note_anglais_compo,
                "psycho": c.note_psycho_compo,
            },
            "admis_concours": c.admis_concours,
            "filiere_formation": c.filiere_formation,
            "soumis_le": c.submitted_at.isoformat() if c.submitted_at else None,
        },
        "documents": documents,
        "pieces_manquantes": [t for t in required_codes if t not in types_deposes],
        "pieces_requises": [
            {"code": p.code, "libelle": p.libelle, "obligatoire": p.obligatoire}
            for p in pieces_requises
        ],
        "verification": rapport_verif.resume(db, c),
        "historique": historique,
        "filieres": [p.libelle for p in db.query(ProgrammeConcours).filter(
            ProgrammeConcours.actif.is_(True)).order_by(ProgrammeConcours.ordre).all()],
        "statuts": [{"code": k, "label": v} for k, v in STATUT_LABELS.items()],
    }


@router.patch("/candidatures/{numero_dossier}")
def modifier_candidature(
    numero_dossier: str,
    payload: DossierPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Décision du jury : convocation, filière, notes, note interne."""
    c = _dossier(db, numero_dossier)
    data = payload.model_dump(exclude_unset=True)

    # L'admission passe par la route de statut, qui journalise et verrouille.
    # Le champ est déclaré pour que le client sache qu'il existe, mais on
    # refuse explicitement : sans cela, une valeur envoyée serait ignorée
    # en silence et l'écran afficherait « enregistré » à tort.
    if "admis_concours" in data:
        raise HTTPException(
            status_code=422,
            detail=(
                "L'admission se décide par l'action de statut, qui est "
                "journalisée. Utilisez le bouton « Admis » ou « Non retenu »."
            ),
        )

    if {"date_compo", "heure_compo", "centre_compo"}.intersection(data):
        raise HTTPException(
            status_code=422,
            detail="La date, l’heure et le centre sont communs à toute la campagne. Modifiez-les dans le calendrier du concours.",
        )

    if "filiere_formation" in data and data["filiere_formation"] is not None:
        active_programs = {p.libelle for p in db.query(ProgrammeConcours).filter(ProgrammeConcours.actif.is_(True)).all()}
        if data["filiere_formation"] not in active_programs:
            raise HTTPException(status_code=422, detail="Filière inconnue ou inactive.")
    for champ in (
        "filiere_formation",
        "note_interne",
        "note_francais_compo",
        "note_math_compo",
        "note_anglais_compo",
        "note_psycho_compo",
    ):
        if champ in data:
            setattr(c, champ, data[champ])

    if any(key in data for key in (
        "filiere_formation", "note_francais_compo", "note_math_compo",
        "note_anglais_compo", "note_psycho_compo",
    )):
        calendrier = db.get(ParametresConcours, 1)
        if calendrier and calendrier.resultats_publies_le:
            calendrier.resultats_publies_le = None

    journaliser(
        db,
        admin,
        "MODIFIE_DOSSIER",
        c.numero_dossier,
        ",".join(sorted(data.keys())) or "—",
        request,
    )
    db.commit()
    return {"message": "Dossier mis à jour.", "numero_dossier": c.numero_dossier,
            "statut": c.statut, "statut_label": STATUT_LABELS.get(c.statut, c.statut)}


@router.post("/candidatures/{numero_dossier}/statut")
def changer_statut(
    numero_dossier: str,
    payload: StatutChange,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Change le statut du dossier (décision du jury) et journalise."""
    c = _dossier(db, numero_dossier)
    nouveau = payload.statut.strip().upper()
    if nouveau not in STATUTS_ADMIN:
        raise HTTPException(status_code=422, detail="Statut inconnu.")
    if nouveau == "COMPOSITION_SCHEDULED" and c.statut != "COMPOSITION_SCHEDULED":
        raise HTTPException(
            status_code=422,
            detail="La composition se programme collectivement depuis les actions de campagne.",
        )
    if c.statut == nouveau:
        return {"message": "Statut inchangé.", "statut": c.statut,
                "statut_label": STATUT_LABELS[nouveau]}

    ancien = c.statut
    c.statut = nouveau
    c.reviewed_at = _utcnow()
    if nouveau == "REJECTED":
        c.motif_refus = payload.motif_refus or payload.commentaire
    if nouveau == "ADMITTED":
        c.admis_concours = True
    elif nouveau in ("REJECTED",):
        c.admis_concours = False
    else:
        c.admis_concours = None
        c.result_email_sent_at = None
        c.result_email_started_at = None
    if nouveau in {"ADMITTED", "REJECTED"}:
        # Si le jury corrige ensuite sa décision, la nouvelle notification
        # doit pouvoir être envoyée explicitement depuis la campagne.
        c.result_email_sent_at = None
        c.result_email_started_at = None
    if (ancien in {"ADMITTED", "REJECTED"}) != (nouveau in {"ADMITTED", "REJECTED"}) or (
        ancien in {"ADMITTED", "REJECTED"} and nouveau != ancien
    ):
        calendrier = db.get(ParametresConcours, 1)
        if calendrier:
            calendrier.resultats_publies_le = None

    db.add(
        HistoriqueStatut(
            numero_dossier=c.numero_dossier,
            ancien_statut=ancien,
            nouveau_statut=nouveau,
            commentaire=payload.commentaire,
            par_admin=admin.email,
        )
    )
    journaliser(
        db, admin, "CHANGE_STATUT", c.numero_dossier, f"{ancien} -> {nouveau}", request
    )
    db.commit()
    return {
        "message": "Statut mis à jour.",
        "numero_dossier": c.numero_dossier,
        "statut": nouveau,
        "statut_label": STATUT_LABELS[nouveau],
    }


# ───────────────────────────── pièces justificatives ─────────────────────────────
@router.get("/documents/{document_id}/download")
def telecharger_document_admin(
    document_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> Response:
    """Téléchargement d'une pièce par l'administration — toujours journalisé."""
    doc = db.get(DocumentCandidature, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    service = _service()
    try:
        content = read_or_rebuild_demo_document(db, doc, service)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le serveur.")

    journaliser(
        db,
        admin,
        "TELECHARGE_PIECE",
        doc.numero_dossier,
        f"{doc.type_document} / {doc.nom_original}",
        request,
    )
    db.commit()
    return Response(
        content=content,
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc.nom_original, safe='')}"
        },
    )


@router.get("/candidatures/{numero_dossier}/document/{type_document}")
def piece_par_type(
    numero_dossier: str,
    type_document: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
):
    """Téléchargement direct par type (pratique pour l'affichage en liste)."""
    if not check_rate_limit(f"admin-doc:{admin.id}", limit=120, window_sec=60):
        raise HTTPException(status_code=429, detail="Trop de téléchargements. Patientez une minute.")
    doc = (
        db.query(DocumentCandidature)
        .filter(
            DocumentCandidature.numero_dossier == _dossier(db, numero_dossier).numero_dossier,
            DocumentCandidature.type_document == type_document,
        )
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Pièce non déposée.")
    return telecharger_document_admin(doc.id, db=db, admin=admin, request=request)


@router.get("/candidatures/{numero_dossier}/convocation.pdf")
def telecharger_convocation_generee(
    numero_dossier: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
):
    """Génère un exemplaire nominatif avec le calendrier commun de campagne."""
    dossier = _dossier(db, numero_dossier)
    calendrier = db.get(ParametresConcours, 1)
    if not calendrier or not calendrier.date_composition or not calendrier.centre_composition:
        raise HTTPException(status_code=409, detail="Enregistrez d’abord la date et le centre de composition.")
    pdf = build_convocation_pdf(
        dossier,
        date_compo=calendrier.date_composition,
        heure_compo=calendrier.heure_composition,
        centre_compo=calendrier.centre_composition,
    )
    journaliser(db, admin, "GENERE_CONVOCATION_PDF", dossier.numero_dossier, request=request)
    db.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="convocation-{dossier.numero_dossier}.pdf"'},
    )


@router.get("/candidatures/{numero_dossier}/resultat.pdf")
def telecharger_resultat_genere(
    numero_dossier: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
):
    """Génère l’attestation EMSP uniquement après la décision du jury."""
    dossier = _dossier(db, numero_dossier)
    if dossier.admis_concours is None:
        raise HTTPException(status_code=409, detail="Publiez d’abord la décision officielle du jury.")
    calendrier = db.get(ParametresConcours, 1)
    pdf = build_result_certificate_pdf(
        dossier,
        date_publication=calendrier.publication_resultats if calendrier else None,
    )
    journaliser(db, admin, "GENERE_RESULTAT_PDF", dossier.numero_dossier, request=request)
    db.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="attestation-resultat-{dossier.numero_dossier}.pdf"'},
    )


# ───────────────────────────── convocation ─────────────────────────────
@router.post("/candidatures/{numero_dossier}/convocation")
async def deposer_convocation(
    numero_dossier: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """L'ancienne publication individuelle est bloquée au niveau serveur."""
    _dossier(db, numero_dossier)
    raise HTTPException(
        status_code=409,
        detail="Les convocations sont générées depuis le calendrier commun puis publiées pour toute la campagne.",
    )


# ───────────────────────────── messages de contact ─────────────────────────────
@router.get("/messages")
def lister_messages(
    statut: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    query = db.query(MessageContact)
    if statut:
        query = query.filter(MessageContact.statut == statut)
    rows = query.order_by(MessageContact.created_at.desc()).limit(200).all()
    return {
        "messages": [
            {
                "id": m.id,
                "nom": m.nom,
                "email": m.email,
                "telephone": m.telephone,
                "objet": m.objet,
                "message": m.message,
                "statut": m.statut,
                "cree_le": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]
    }


@router.patch("/messages/{message_id}")
def maj_message(
    message_id: int,
    payload: MessageStatut,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    m = db.get(MessageContact, message_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Message introuvable.")
    m.statut = payload.statut
    journaliser(db, admin, "MESSAGE", None, f"#{m.id} -> {payload.statut}", request)
    db.commit()
    return {"message": "Message mis à jour."}


# ───────────────────────────── gestion des comptes ─────────────────────────────
@router.get("/comptes")
def lister_comptes(
    db: Session = Depends(get_db), admin: User = Depends(require_super_admin)
) -> dict:
    rows = db.query(User).order_by(User.created_at.desc()).limit(500).all()
    return {
        "comptes": [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "actif": u.actif,
                "numero_dossier": u.numero_dossier,
                "nom_affiche": u.nom_affiche,
                "cree_le": u.created_at.isoformat() if u.created_at else None,
            }
            for u in rows
        ]
    }


@router.post("/comptes/admin")
def creer_admin(
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin),
) -> dict:
    """Crée un compte administrateur (usage interne, protégé par le rôle)."""
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    nom = str(payload.get("nom_affiche") or "Administration").strip()[:255]
    if "@" not in email or len(password) < 8:
        raise HTTPException(status_code=422, detail="E-mail valide et mot de passe de 8 caractères minimum.")
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet e-mail.")
    user = User(
        email=email,
        password_hash=hash_password(password),
        role="ADMIN",
        nom_affiche=nom,
        numero_dossier=None,
    )
    db.add(user)
    db.commit()
    return {"message": "Compte administrateur créé.", "email": email}
