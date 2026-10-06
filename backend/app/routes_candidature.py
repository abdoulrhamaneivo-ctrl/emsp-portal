"""Routes candidature multi-étapes.

Hypothèses d'interfaces (créées par un autre agent) :
- ``app.db.get_db`` : dependency FastAPI qui fournit une ``Session`` SQLAlchemy.
- ``app.auth.get_current_user`` : dependency FastAPI qui retourne l'utilisateur
  connecté (modèle ``User`` avec attribut ``numero_dossier``).
- ``app.models.Candidature`` : modèle SQLAlchemy avec au minimum les colonnes
  métier des schémas (étape 1/2/3) + ``numero_dossier`` (unique), ``statut``,
  ``etape_courante``. Colonnes optionnelles gérées en ``hasattr`` :
  ``dossier_valide``, ``submitted_at``, ``updated_at``, ``created_at``.

Anti-IDOR : le ``numero_dossier`` est toujours résolu depuis ``current_user``,
jamais depuis les query params ni le body.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Candidature, DocumentCandidature
from app.schemas import FILIERES, CandidatureOut, SubmitIn
from app.storage_service import TYPES_AUTORISES
from app.validators import (
    validate_annee_bac,
    validate_email,
    validate_note,
    validate_telephone,
)

router = APIRouter(prefix="/api/candidature", tags=["candidature"])

STATUT_LABELS: Dict[str, str] = {
    "DRAFT": "Brouillon",
    "SUBMITTED": "Dossier soumis",
    "UNDER_REVIEW": "Dossier en cours d'examen",
    "VALIDATED": "Dossier validé",
    "RETAINED": "Dossier retenu",
    "REJECTED": "Dossier non retenu",
    "COMPOSITION_SCHEDULED": "Composition programmée",
    "ADMITTED": "Admis",
}

# Champs modifiables via PATCH (jamais statut / numero_dossier / horodatages).
MODIFIABLE_FIELDS = {
    # Étape 1
    "code_tresor_pay",
    "nom",
    "prenoms",
    "sexe",
    "date_naissance",
    "lieu_naissance",
    "nationalite",
    "nature_piece",
    "numero_piece",
    "email",
    "telephone",
    "commune",
    "ville",
    "adresse",
    # Étape 2
    "annee_bac",
    "serie_bac",
    "numero_bac",
    "numero_table",
    "mention",
    "moyenne_bac",
    "notes",
    "note_math_bac",
    "note_physique_bac",
    "note_francais_bac",
    "note_anglais_bac",
    "choix_1_filiere",
    "choix_2_filiere",
    # Étape 3
    "tuteur1_nom",
    "tuteur1_contact",
    "tuteur1_lien",
    "tuteur1_residence",
    "tuteur2_nom",
    "tuteur2_contact",
    "tuteur2_lien",
    "tuteur2_residence",
    # Progression (prise en compte via max, jamais de régression)
    "etape_courante",
}

SEXES = {"Masculin", "Féminin"}
NATURES_PIECE = {"CNI", "Attestation d'identité", "Passeport", "Carte consulaire"}
# Séries réellement admises au concours FS MENUM.
SERIES_BAC = {"A", "B", "C", "D", "F1", "F2", "G2"}
MENTIONS = {"Passable", "Assez Bien", "Bien", "Très Bien", "Excellent"}
LIENS_TUTEUR = {"Père", "Mère", "Tuteur", "Autre"}

FIELD_TO_ETAPE: Dict[str, int] = {
    "code_tresor_pay": 1,
    "nom": 1,
    "prenoms": 1,
    "sexe": 1,
    "date_naissance": 1,
    "lieu_naissance": 1,
    "nationalite": 1,
    "nature_piece": 1,
    "numero_piece": 1,
    "email": 1,
    "telephone": 1,
    "commune": 1,
    "ville": 1,
    "adresse": 1,
    "annee_bac": 2,
    "serie_bac": 2,
    "numero_bac": 2,
    "numero_table": 2,
    "mention": 2,
    "moyenne_bac": 2,
    "notes": 2,
    "note_math_bac": 2,
    "note_physique_bac": 2,
    "note_francais_bac": 2,
    "note_anglais_bac": 2,
    "choix_1_filiere": 2,
    "choix_2_filiere": 2,
    "tuteur1_nom": 3,
    "tuteur1_contact": 3,
    "tuteur1_lien": 3,
    "tuteur1_residence": 3,
    "tuteur2_nom": 3,
    "tuteur2_contact": 3,
    "tuteur2_lien": 3,
    "tuteur2_residence": 3,
}

REQUIRED_STEP1 = [
    "nom",
    "prenoms",
    "sexe",
    "date_naissance",
    "lieu_naissance",
    "nationalite",
    "nature_piece",
    "numero_piece",
    "email",
    "telephone",
    "commune",
    "ville",
    "adresse",
]
REQUIRED_STEP2 = [
    "annee_bac",
    "serie_bac",
    "numero_bac",
    "numero_table",
    "mention",
    "moyenne_bac",
    "choix_1_filiere",
]
REQUIRED_STEP3 = [
    "tuteur1_nom",
    "tuteur1_contact",
    "tuteur1_lien",
    "tuteur1_residence",
]

# Les 10 pièces justificatives exigées pour soumettre le dossier.
# Doit rester aligné avec ``storage_service.TYPES_AUTORISES`` (types
# déposables par le candidat) : toute pièce hors de cette liste ne peut pas
# être téléversée, donc ne peut pas être exigée.
TYPES_DOCUMENTS_REQUIS = [
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now():
    # Naïf UTC, cohérent avec app/models._utcnow et app/auth._utcnow
    # (colonnes DateTime sans timezone, SQLite + Postgres).
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Correspondance clés `notes` (API, insensible casse/accents) -> colonnes modèle.
NOTES_KEY_TO_COLUMN: Dict[str, str] = {
    "math": "note_math_bac",
    "maths": "note_math_bac",
    "mathematiques": "note_math_bac",
    "mathématiques": "note_math_bac",
    "note_math_bac": "note_math_bac",
    "physique": "note_physique_bac",
    "physique-chimie": "note_physique_bac",
    "physique_chimie": "note_physique_bac",
    "note_physique_bac": "note_physique_bac",
    "francais": "note_francais_bac",
    "français": "note_francais_bac",
    "note_francais_bac": "note_francais_bac",
    "anglais": "note_anglais_bac",
    "note_anglais_bac": "note_anglais_bac",
}

NOTE_COLUMNS = (
    "note_math_bac",
    "note_physique_bac",
    "note_francais_bac",
    "note_anglais_bac",
)


def _resolve_numero_dossier(current_user: Any) -> Optional[str]:
    """Résout le numero_dossier depuis l'utilisateur connecté uniquement.

    Supporte ``current_user.numero_dossier`` (cas standard) et
    ``current_user.user.numero_dossier`` (wrapper), ainsi que les dicts.
    """
    if current_user is None:
        return None
    if isinstance(current_user, dict):
        nd = current_user.get("numero_dossier")
        if nd:
            return str(nd)
        nested = current_user.get("user")
        if isinstance(nested, dict) and nested.get("numero_dossier"):
            return str(nested["numero_dossier"])
        return None
    nd = getattr(current_user, "numero_dossier", None)
    if nd:
        return str(nd)
    nested = getattr(current_user, "user", None)
    if nested is not None:
        nd2 = getattr(nested, "numero_dossier", None)
        if nd2:
            return str(nd2)
        if isinstance(nested, dict) and nested.get("numero_dossier"):
            return str(nested["numero_dossier"])
    return None


def _get_candidature_or_404(db: Session, current_user: Any) -> Any:
    numero_dossier = _resolve_numero_dossier(current_user)
    if not numero_dossier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune candidature trouvée pour cet utilisateur.",
        )
    candidature = (
        db.query(Candidature)
        .filter(Candidature.numero_dossier == numero_dossier)
        .first()
    )
    if candidature is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune candidature trouvée pour cet utilisateur.",
        )
    return candidature


def _parse_date(value: Any) -> Any:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("Le champ date_naissance est requis.")
        try:
            return date.fromisoformat(s)
        except ValueError:
            raise ValueError(
                "Le champ date_naissance doit être une date ISO (AAAA-MM-JJ)."
            )
    raise ValueError("Le champ date_naissance doit être une date ISO (AAAA-MM-JJ).")


def _validate_patch_value(field: str, value: Any) -> Any:
    """Valide et normalise une valeur PATCH. Lève ValueError avec message FR."""
    # Optionnels : "" (ou blanc) → None, comme None (effacement).
    # Couvre choix_2_filiere, tuteur2_*, code_tresor_pay, notes_* / notes.
    if isinstance(value, str) and not value.strip():
        if (
            field == "choix_2_filiere"
            or field == "code_tresor_pay"
            or field == "notes"
            or field in NOTE_COLUMNS
            or field.startswith("tuteur2_")
        ):
            return None
    if field == "email":
        return validate_email(value)
    if field in ("telephone", "tuteur1_contact", "tuteur2_contact"):
        if value is None and field.startswith("tuteur2_"):
            return None
        return validate_telephone(value)
    if field == "annee_bac":
        return validate_annee_bac(value)
    if field == "moyenne_bac":
        return validate_note(value, "moyenne_bac")
    if field in NOTE_COLUMNS:
        return validate_note(value, field)
    if field == "notes":
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("Le champ notes doit être un objet {matière: note}.")
        cleaned_notes: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(v, str) and not v.strip():
                v = None
            cleaned_notes[str(k)] = validate_note(v, f"notes.{k}")
        return cleaned_notes
    if field in ("choix_1_filiere", "choix_2_filiere"):
        if value is None and field == "choix_2_filiere":
            return None
        if value not in FILIERES:
            raise ValueError(
                f"Le champ {field} doit être parmi : {', '.join(FILIERES)}."
            )
        return value
    if field == "sexe":
        if value not in SEXES:
            raise ValueError("Le champ sexe doit être Masculin ou Féminin.")
        return value
    if field == "nature_piece":
        if value not in NATURES_PIECE:
            raise ValueError(
                "Le champ nature_piece doit être CNI, Attestation d'identité, "
                "Passeport ou Carte consulaire."
            )
        return value
    if field == "serie_bac":
        if value not in SERIES_BAC:
            raise ValueError("Le champ serie_bac est invalide.")
        return value
    if field == "mention":
        if value not in MENTIONS:
            raise ValueError("Le champ mention est invalide.")
        return value
    if field in ("tuteur1_lien", "tuteur2_lien"):
        if value is None and field == "tuteur2_lien":
            return None
        if value not in LIENS_TUTEUR:
            raise ValueError("Le champ lien tuteur doit être Père, Mère, Tuteur ou Autre.")
        return value
    if field == "date_naissance":
        d = _parse_date(value)
        if d and d > date.today():
            raise ValueError("La date de naissance ne peut pas être dans le futur.")
        return d
    if field == "etape_courante":
        try:
            iv = int(value)
        except (TypeError, ValueError):
            raise ValueError("Le champ etape_courante doit être un entier entre 1 et 7.")
        if not 1 <= iv <= 7:
            raise ValueError("Le champ etape_courante doit être un entier entre 1 et 7.")
        return iv
    # Champs texte génériques : strip, None autorisé seulement pour tuteur2_*
    if value is None:
        if field.startswith("tuteur2_") or field == "code_tresor_pay":
            return None
        raise ValueError(f"Le champ {field} est requis.")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            if field.startswith("tuteur2_") or field == "code_tresor_pay":
                return None
            raise ValueError(f"Le champ {field} est requis.")
        return s
    return value


def _missing_fields(candidature: Any) -> List[str]:
    missing: List[str] = []
    for f in REQUIRED_STEP1 + REQUIRED_STEP2 + REQUIRED_STEP3:
        v = getattr(candidature, f, None)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(f)
    return missing


def _missing_document_types(db: Session, candidature: Any) -> List[str]:
    """Retourne les types de pièces requis encore absents du dossier.

    Interroge ``documents_candidature`` pour le dossier courant uniquement
    (ownership strict : le ``numero_dossier`` vient de la candidature déjà
    résolue via ``current_user``). L'ordre suit ``TYPES_DOCUMENTS_REQUIS``
    pour un message d'erreur stable.
    """
    numero_dossier = getattr(candidature, "numero_dossier", None)
    if not numero_dossier:
        return list(TYPES_DOCUMENTS_REQUIS)
    try:
        presents = {
            row[0]
            for row in db.query(DocumentCandidature.type_document)
            .filter(DocumentCandidature.numero_dossier == numero_dossier)
            .all()
            if row and row[0]
        }
    except Exception:
        # Ne jamais autoriser un submit si l'inventaire des pièces échoue.
        return list(TYPES_DOCUMENTS_REQUIS)
    return [t for t in TYPES_DOCUMENTS_REQUIS if t not in presents]


def _notes_dict_from_candidature(candidature: Any) -> Optional[Dict[str, float]]:
    """Reconstruit le dict `notes` API depuis les colonnes note_*_bac."""
    out: Dict[str, float] = {}
    for col in NOTE_COLUMNS:
        v = getattr(candidature, col, None)
        if v is not None:
            try:
                out[col] = float(v)
            except (TypeError, ValueError):
                continue
    return out or None


def _build_out(candidature: Any) -> CandidatureOut:
    """Sérialise en CandidatureOut en réconciliant notes dict <-> colonnes."""
    data = CandidatureOut.model_validate(candidature, from_attributes=True)
    # Le modèle n'a pas de colonne `notes` : on la reconstruit.
    try:
        data.notes = _notes_dict_from_candidature(candidature)
    except Exception:
        pass
    for col in NOTE_COLUMNS:
        try:
            setattr(data, col, getattr(candidature, col, None))
        except Exception:
            pass
    return data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=CandidatureOut)
@router.get("/", response_model=CandidatureOut, include_in_schema=False)
def get_ma_candidature(
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Retourne la candidature de l'utilisateur connecté."""
    candidature = _get_candidature_or_404(db, current_user)
    return _build_out(candidature)


@router.patch("", response_model=CandidatureOut)
@router.patch("/", response_model=CandidatureOut, include_in_schema=False)
def patch_ma_candidature(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Mise à jour partielle (whitelist). Etape_courante = max (jamais de régression)."""
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucune donnée modifiable fournie.",
        )
    unknown = [k for k in payload if k not in MODIFIABLE_FIELDS]
    data = {k: v for k, v in payload.items() if k in MODIFIABLE_FIELDS}
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Aucune donnée modifiable fournie."
                + (f" Champs non autorisés : {', '.join(unknown)}." if unknown else "")
            ),
        )

    candidature = _get_candidature_or_404(db, current_user)

    # Validation champ par champ (messages FR, 422)
    cleaned: Dict[str, Any] = {}
    for field, value in data.items():
        try:
            cleaned[field] = _validate_patch_value(field, value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )

    # Cohérence choix1 != choix2 (en tenant compte de l'état existant)
    choix1 = cleaned.get("choix_1_filiere", getattr(candidature, "choix_1_filiere", None))
    choix2 = cleaned.get("choix_2_filiere", getattr(candidature, "choix_2_filiere", None))
    if choix1 is not None and choix2 is not None and choix1 == choix2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Les deux choix ne peuvent pas être identiques.",
        )

    for field, value in cleaned.items():
        if field == "etape_courante":
            continue
        if field == "notes":
            # Traduit le dict `notes` vers les colonnes note_*_bac du modèle.
            if value is None:
                continue
            for matiere, note in value.items():
                col = NOTES_KEY_TO_COLUMN.get(str(matiere).strip().lower())
                if col is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"Note non reconnue : {matiere}. Matières acceptées : "
                            "math, physique, francais, anglais "
                            "(ou note_math_bac, note_physique_bac, "
                            "note_francais_bac, note_anglais_bac)."
                        ),
                    )
                setattr(candidature, col, note)
            continue
        setattr(candidature, field, value)

    # etape_courante = max(existante, fournie, inférée des champs)
    try:
        current_etape = int(getattr(candidature, "etape_courante", 1) or 1)
    except (TypeError, ValueError):
        current_etape = 1
    inferred = max(
        [FIELD_TO_ETAPE.get(f, current_etape) for f in cleaned if f != "etape_courante"],
        default=current_etape,
    )
    provided = cleaned.get("etape_courante", current_etape)
    try:
        provided = int(provided)
    except (TypeError, ValueError):
        provided = current_etape
    new_etape = max(current_etape, provided, inferred)
    # Borne haute = 7 (étape « dossier transmis » atteignable via submit).
    # Un clamp à 5 écraserait l'étape 7 posée par POST /submit.
    new_etape = max(1, min(7, new_etape))
    try:
        candidature.etape_courante = new_etape
    except Exception:
        pass
    if hasattr(candidature, "updated_at"):
        try:
            candidature.updated_at = _now()
        except Exception:
            pass

    db.add(candidature)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit de données : email ou code TrésorPay déjà utilisé.",
        )
    db.refresh(candidature)
    return _build_out(candidature)


@router.post("/submit")
def submit_ma_candidature(
    body: SubmitIn,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Soumet définitivement le dossier (DRAFT -> SUBMITTED)."""
    if body.confirmation is not True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Veuillez certifier l'exactitude des informations avant de soumettre.",
        )

    candidature = _get_candidature_or_404(db, current_user)

    # Le consentement est horodaté : un accord sans date n'est pas un
    # accord. Il est facultatif, mais s'il est donné il doit être daté.
    if body.consentement_tiers:
        candidature.consentement_tiers = True
        candidature.consentement_le = _now()

    statut = getattr(candidature, "statut", "DRAFT")
    if statut != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dossier déjà soumis.",
        )

    missing = _missing_fields(candidature)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Dossier incomplet, veuillez compléter les étapes 1 à 3. "
                f"Champs manquants : {', '.join(missing)}."
            ),
        )

    missing_docs = _missing_document_types(db, candidature)
    if missing_docs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Pièces justificatives manquantes : "
                f"{', '.join(missing_docs)}. "
                "Veuillez déposer les 10 documents requis."
            ),
        )

    choix1 = getattr(candidature, "choix_1_filiere", None)
    choix2 = getattr(candidature, "choix_2_filiere", None)
    if not choix1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dossier incomplet, veuillez renseigner au moins le premier choix de filière.",
        )
    if choix2 is not None and choix1 == choix2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Les deux choix ne peuvent pas être identiques.",
        )

    candidature.statut = "SUBMITTED"
    if hasattr(candidature, "dossier_valide"):
        try:
            candidature.dossier_valide = True
        except Exception:
            pass
    if hasattr(candidature, "submitted_at"):
        try:
            candidature.submitted_at = _now()
        except Exception:
            pass
    try:
        # Étape 7 = dossier transmis : toutes les étapes 1 à 6 sont bouclées
        # (identité, scolarité, tuteurs, choix + dépôt des 10 pièces).
        candidature.etape_courante = 7
    except Exception:
        pass
    if hasattr(candidature, "updated_at"):
        try:
            candidature.updated_at = _now()
        except Exception:
            pass

    db.add(candidature)
    db.commit()
    db.refresh(candidature)

    return {
        "message": "Votre candidature a été enregistrée avec succès.",
        "numero_dossier": getattr(candidature, "numero_dossier", None),
    }


@router.get("/status")
def get_mon_statut(
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Retourne le statut du dossier de l'utilisateur connecté."""
    candidature = _get_candidature_or_404(db, current_user)
    statut = getattr(candidature, "statut", "DRAFT")
    return {
        "numero_dossier": getattr(candidature, "numero_dossier", None),
        "statut": statut,
        "statut_label": STATUT_LABELS.get(statut, statut),
        "etape_courante": getattr(candidature, "etape_courante", 1),
    }
