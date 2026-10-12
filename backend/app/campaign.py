"""Règles de cohorte pour les publications collectives du concours."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Candidature


STATUTS_COHORTE_CONCOURS = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "VALIDATED",
    "RETAINED",
    "COMPOSITION_SCHEDULED",
    "ADMITTED",
    "REJECTED",
)


def requete_cohorte(db: Session):
    """Tous les dossiers transmis qui relèvent de la campagne commune."""
    return db.query(Candidature).filter(Candidature.statut.in_(STATUTS_COHORTE_CONCOURS))


def etat_deliberation(db: Session) -> tuple[int, int]:
    """Retourne (dossiers de la cohorte, dossiers sans décision du jury)."""
    total = (
        requete_cohorte(db)
        .with_entities(func.count(Candidature.numero_dossier))
        .scalar()
        or 0
    )
    en_attente = (
        requete_cohorte(db)
        .filter(Candidature.admis_concours.is_(None))
        .with_entities(func.count(Candidature.numero_dossier))
        .scalar()
        or 0
    )
    return total, en_attente


def deliberation_complete(db: Session) -> tuple[bool, int, int]:
    total, en_attente = etat_deliberation(db)
    return total > 0 and en_attente == 0, total, en_attente


def candidature_dans_cohorte(candidature: Candidature | None) -> bool:
    return bool(candidature and candidature.statut in STATUTS_COHORTE_CONCOURS)
