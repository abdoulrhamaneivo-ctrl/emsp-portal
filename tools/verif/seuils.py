"""Seuils de l'agent de vérification.

Ce sont des *bornes*, pas des/goûts : chacune est une mesure objective
(contraste WCAG, taille en pixels, largeur de ligne) qu'on peut vérifier
sans demander l'avis de personne. Un retour en arrière doit se décider
sur ces nombres, pas sur une impression.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Seuils:
    # Lisibilité — seuils WCAG 2.1 AA.
    contraste_texte: float = 4.5
    contraste_grand_texte: float = 3.0
    taille_police_grand_texte: float = 24.0
    taille_police_grand_texte_gras: float = 18.66

    # Lisibilité — preferences de confort, plus stricts que le minimum.
    police_min_px: float = 11.0
    mesure_max_caracteres: int = 105
    ligne_haute_min_px: float = 1.28

    # Mobile — cibles tactiles. 24 px est le minimum de la norme
    # (WCAG 2.5.8, AA). Le seuil de confort était 36 px, valeur observée
    # sur les projets antérieurs ; il est relevé à 44 px parce que le
    # contrat du portail l'impose désormais : un candidat sur téléphone
    # saisit son identité, sa date de naissance et joint dix pièces.
    # 44 px n'est plus une préférence esthétique, c'est une exigence de
    # remplissage, et un vérificateur qui tolère 36 px ne vérifie plus
    # ce que le contrat promet. On garde les deux severités distinctes :
    # sous 44 on signale, sous 24 c'est un défaut de norme.
    largeur_mobile: int = 390
    cible_tactile_px: float = 44.0        # exigence du contrat
    cible_tactile_min_px: float = 24.0    # norme WCAG 2.5.8 AA
    entete_max_mobile_px: int = 150       # garde-fou anti-enchérissement
    debordement_tolere_px: float = 2.0

    # Fonctionnel — doit rester vrai quoi qu'il arrive.
    etapes_parcours: int = 7
    pieces_justificatives: int = 10


SEUILS = Seuils()

# Largeurs sur lesquelles on mesure. 390 = téléphone courant, 900 =
# tablette, 1440 = portable. Une page qui ne tient qu'à 1440 est fausse.
LARGEURS = (390, 900, 1440)


@dataclass
class Verdict:
    """Un écart mesuré, prêt à être rapporté ou réparé."""

    famille: str
    cle: str
    page: str
    message: str
    mesure: str
    seuil: str
    gravite: str = "mineur"          # mineur | majeur | bloquant
    reparable: bool = False
    detail: dict = field(default_factory=dict)

    @property
    def bloquant(self) -> bool:
        return self.gravite == "bloquant"

    def ligne(self) -> str:
        return (f"[{self.gravite:<9}] {self.famille:<12} {self.page:<18} "
                f"{self.message} ({self.mesure}, attendu {self.seuil})")
