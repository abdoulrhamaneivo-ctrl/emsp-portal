"""Schémas Pydantic pour la candidature multi-étapes."""

from __future__ import annotations

from datetime import date
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.validators import (
    validate_annee_bac,
    validate_email,
    validate_note,
    validate_telephone,
)

# Les cinq spécialités du FS MENUM (session 2026). Les six intitulés
# qui figuraient auparavant — Prépa Scientifique, Informatique, Génie
# logiciel, Infographie, Création digitale, Prépa Économique — ne
# correspondent à aucune formation de l'EMSP : l'institution est
# l'École Multinationale Supérieure des Postes, pas une école de santé.
SPECIALITES = [
    "LNUM — Logistique et Numérique",
    "FDIG — Finance Digitale",
    "MDIG — Marketing Digital",
    "DSER — Digitalisation des Services",
    "GARE — Gestion des Activités Régulées de l'Économie",
]

# Alias conservé : plusieurs modules importent encore le nom `FILIERES`,
# qui désigne aujourd'hui les spécialités du concours, pas des filières
# d'établissement. Deux mots pour une seule liste, c'est un piège ; on garde
# l'ancien nom pour ne pas casser ces imports, et `SPECIALITES` est la
# dénomination à employer dans le nouveau code.
FILIERES = SPECIALITES

# Séries admises au concours d'entrée en Licence 1. « E » et « Autre »
# n'existent pas dans ce concours ; « F » et « G » remplacent les
# sous-séries F1/F2 et G2 réellement attendues.
SERIES_ADMISES = ["A", "B", "C", "D", "F1", "F2", "G2"]

Filiere = Literal[
    "LNUM — Logistique et Numérique",
    "FDIG — Finance Digitale",
    "MDIG — Marketing Digital",
    "DSER — Digitalisation des Services",
    "GARE — Gestion des Activités Régulées de l'Économie",
]

Sexe = Literal["Masculin", "Féminin"]

NaturePiece = Literal[
    "CNI",
    "Attestation d'identité",
    "Passeport",
    "Carte consulaire",
]

Mention = Literal[
    "Passable",
    "Assez Bien",
    "Bien",
    "Très Bien",
    "Excellent",
]

SerieBac = Literal["A", "B", "C", "D", "F1", "F2", "G2"]

LienTuteur = Literal["Père", "Mère", "Tuteur", "Autre"]


# ---------------------------------------------------------------------------
# Étape 1 — État civil
# ---------------------------------------------------------------------------
class CandidatureStep1(BaseModel):
    code_tresor_pay: Optional[str] = None
    nom: str
    prenoms: str
    sexe: Sexe
    date_naissance: date
    lieu_naissance: str
    nationalite: str
    nature_piece: NaturePiece
    numero_piece: str
    email: str
    telephone: str
    commune: str
    ville: str
    adresse: str

    @field_validator("nom", "prenoms", "lieu_naissance", "nationalite", mode="before")
    @classmethod
    def _strip_non_empty(cls, v, info):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"Le champ {info.field_name} est requis.")
        return v.strip() if isinstance(v, str) else v

    @field_validator("numero_piece", "commune", "ville", "adresse", mode="before")
    @classmethod
    def _strip_non_empty_2(cls, v, info):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"Le champ {info.field_name} est requis.")
        return v.strip() if isinstance(v, str) else v

    @field_validator("code_tresor_pay", mode="before")
    @classmethod
    def _strip_optional(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("email", mode="before")
    @classmethod
    def _check_email(cls, v):
        return validate_email(v)

    @field_validator("telephone", mode="before")
    @classmethod
    def _check_tel(cls, v):
        return validate_telephone(v)

    @field_validator("date_naissance", mode="before")
    @classmethod
    def _check_date_naissance(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Le champ date_naissance est requis.")
        if not v:
            raise ValueError("Le champ date_naissance est requis.")
        return v

    @field_validator("date_naissance")
    @classmethod
    def _date_passee(cls, v: date):
        if v and v > date.today():
            raise ValueError("La date de naissance ne peut pas être dans le futur.")
        return v


# ---------------------------------------------------------------------------
# Étape 2 — Parcours scolaire
# ---------------------------------------------------------------------------
class Step2(BaseModel):
    annee_bac: int
    serie_bac: SerieBac
    numero_bac: str
    numero_table: str
    mention: Mention
    moyenne_bac: float
    # Notes par matière (colonnes modèle : note_*_bac). Le champ générique
    # `notes` reste accepté à l'API et est traduit vers ces colonnes.
    note_math_bac: Optional[float] = None
    note_physique_bac: Optional[float] = None
    note_francais_bac: Optional[float] = None
    note_anglais_bac: Optional[float] = None
    notes: Optional[Dict[str, float]] = None
    choix_1_filiere: Filiere
    choix_2_filiere: Optional[Filiere] = None

    @field_validator("annee_bac", mode="before")
    @classmethod
    def _check_annee(cls, v):
        return validate_annee_bac(v)

    @field_validator("numero_bac", "numero_table", mode="before")
    @classmethod
    def _strip_required(cls, v, info):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"Le champ {info.field_name} est requis.")
        return v.strip() if isinstance(v, str) else v

    @field_validator("moyenne_bac", mode="before")
    @classmethod
    def _check_moyenne(cls, v):
        if v is None or (isinstance(v, str) and not str(v).strip()):
            raise ValueError("Le champ moyenne_bac est requis.")
        return validate_note(v, "moyenne_bac")

    @field_validator(
        "note_math_bac",
        "note_physique_bac",
        "note_francais_bac",
        "note_anglais_bac",
        mode="before",
    )
    @classmethod
    def _check_note_matiere(cls, v, info):
        return validate_note(v, info.field_name)

    @field_validator("notes", mode="before")
    @classmethod
    def _check_notes(cls, v):
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("Le champ notes doit être un objet {matière: note}.")
        cleaned: Dict[str, float] = {}
        for matiere, note in v.items():
            cleaned[str(matiere)] = validate_note(note, f"notes.{matiere}")
        return cleaned

    @model_validator(mode="after")
    def _choix_differents(self):
        if (
            self.choix_2_filiere is not None
            and self.choix_1_filiere is not None
            and self.choix_2_filiere == self.choix_1_filiere
        ):
            raise ValueError("Les deux choix ne peuvent pas être identiques.")
        return self


# ---------------------------------------------------------------------------
# Étape 3 — Tuteurs
# ---------------------------------------------------------------------------
class Step3(BaseModel):
    tuteur1_nom: str
    tuteur1_contact: str
    tuteur1_lien: LienTuteur
    tuteur1_residence: str
    tuteur2_nom: Optional[str] = None
    tuteur2_contact: Optional[str] = None
    tuteur2_lien: Optional[LienTuteur] = None
    tuteur2_residence: Optional[str] = None

    @field_validator("tuteur1_nom", "tuteur1_residence", mode="before")
    @classmethod
    def _t1_required(cls, v, info):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"Le champ {info.field_name} est requis.")
        return v.strip() if isinstance(v, str) else v

    @field_validator("tuteur1_contact", mode="before")
    @classmethod
    def _t1_contact(cls, v):
        return validate_telephone(v)

    @field_validator(
        "tuteur2_nom", "tuteur2_contact", "tuteur2_residence", mode="before"
    )
    @classmethod
    def _t2_optional_strip(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("tuteur2_contact")
    @classmethod
    def _t2_contact_valid(cls, v):
        if v is None:
            return None
        return validate_telephone(v)


# ---------------------------------------------------------------------------
# Lecture complète + soumission
# ---------------------------------------------------------------------------
class CandidatureOut(BaseModel):
    """Représentation complète d'une candidature.

    Les champs métiers sont optionnels pour permettre la sérialisation
    d'un dossier DRAFT incomplet (multi-étapes). Les étapes Step1/Step2/Step3
    restent strictes à l'écriture.
    """

    model_config = ConfigDict(from_attributes=True)

    numero_dossier: str
    statut: str
    etape_courante: int = 1

    code_tresor_pay: Optional[str] = None
    nom: Optional[str] = None
    prenoms: Optional[str] = None
    sexe: Optional[str] = None
    date_naissance: Optional[date] = None
    lieu_naissance: Optional[str] = None
    nationalite: Optional[str] = None
    nature_piece: Optional[str] = None
    numero_piece: Optional[str] = None
    email: Optional[str] = None
    telephone: Optional[str] = None
    commune: Optional[str] = None
    ville: Optional[str] = None
    adresse: Optional[str] = None

    annee_bac: Optional[int] = None
    serie_bac: Optional[str] = None
    numero_bac: Optional[str] = None
    numero_table: Optional[str] = None
    mention: Optional[str] = None
    moyenne_bac: Optional[float] = None
    note_math_bac: Optional[float] = None
    note_physique_bac: Optional[float] = None
    note_francais_bac: Optional[float] = None
    note_anglais_bac: Optional[float] = None
    notes: Optional[Dict[str, float]] = None
    choix_1_filiere: Optional[str] = None
    choix_2_filiere: Optional[str] = None

    tuteur1_nom: Optional[str] = None
    tuteur1_contact: Optional[str] = None
    tuteur1_lien: Optional[str] = None
    tuteur1_residence: Optional[str] = None
    tuteur2_nom: Optional[str] = None
    tuteur2_contact: Optional[str] = None
    tuteur2_lien: Optional[str] = None
    tuteur2_residence: Optional[str] = None


class SubmitIn(BaseModel):
    confirmation: bool
    # Facultatif : refuser l'analyse automatisée des pièces ne doit
    # jamais empêcher un candidat de déposer son dossier.
    consentement_tiers: bool = False

    @field_validator("confirmation")
    @classmethod
    def _must_confirm(cls, v: bool):
        if v is not True:
            raise ValueError(
                "Veuillez certifier l'exactitude des informations avant de soumettre."
            )
        return v
