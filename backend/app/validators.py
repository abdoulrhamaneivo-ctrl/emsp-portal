"""Fonctions de validation pures et réutilisables pour les candidatures.

Ces fonctions ne dépendent ni de FastAPI, ni de SQLAlchemy, ni de Pydantic.
Elles sont utilisées par ``app/schemas.py`` (validators Pydantic) et peuvent
être réutilisées dans ``app/routes_candidature.py`` pour valider les payloads
PATCH partiels.
"""

from __future__ import annotations

import re
from datetime import datetime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TELEPHONE_RE = re.compile(r"^\+?[0-9\s\-]{8,15}$")

ANNEE_BAC_MIN = 1980
ANNEE_BAC_MAX = datetime.now().year

NOTE_MIN = 0.0
NOTE_MAX = 20.0


def validate_email(value: str) -> str:
    """Valide un email (format EmailStr-like). Retourne la valeur nettoyée.

    Raises:
        ValueError: si le format est invalide.
    """
    if value is None:
        raise ValueError("L'adresse email est requise.")
    v = str(value).strip()
    if not v:
        raise ValueError("L'adresse email est requise.")
    if not EMAIL_RE.match(v):
        raise ValueError("L'adresse email est invalide.")
    return v


def validate_telephone(value: str) -> str:
    """Valide un numéro de téléphone selon ^\\+?[0-9\\s\\-]{8,15}$.

    Raises:
        ValueError: si le format est invalide.
    """
    if value is None:
        raise ValueError("Le numéro de téléphone est requis.")
    v = str(value).strip()
    if not v:
        raise ValueError("Le numéro de téléphone est requis.")
    if not TELEPHONE_RE.match(v):
        raise ValueError(
            "Le numéro de téléphone est invalide "
            "(8 à 15 chiffres, espaces et tirets autorisés, + optionnel)."
        )
    return v


def validate_note(value: float | int | None, field_name: str = "note") -> float | None:
    """Valide une note entre 0 et 20. Retourne la note en float.

    ``None`` est retourné tel quel (champ optionnel).
    Raises:
        ValueError: si hors borne ou non numérique.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Le champ {field_name} doit être un nombre entre 0 et 20.")
    if not (NOTE_MIN <= f <= NOTE_MAX):
        raise ValueError(f"Le champ {field_name} doit être compris entre 0 et 20.")
    return f


def validate_annee_bac(value: int) -> int:
    """Valide l'année du bac entre 1980 et l'année courante.

    Raises:
        ValueError: si hors borne ou non entier.
    """
    if value is None:
        raise ValueError("L'année du bac est requise.")
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"L'année du bac doit être un entier entre {ANNEE_BAC_MIN} et {ANNEE_BAC_MAX}.")
    # Garde-fou : rejette les booléens / flottants déguisés
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"L'année du bac doit être un entier entre {ANNEE_BAC_MIN} et {ANNEE_BAC_MAX}.")
    if not (ANNEE_BAC_MIN <= iv <= ANNEE_BAC_MAX):
        raise ValueError(
            f"L'année du bac doit être comprise entre {ANNEE_BAC_MIN} et {ANNEE_BAC_MAX}."
        )
    return iv
