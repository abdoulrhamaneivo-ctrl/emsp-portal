"""Réparations automatiques, et leurs limites.

Trois règles, non négociables :

1. **CSS seulement.** Un défaut d'affichage se corrige en changeant
   l'affichage. Jamais de JavaScript, de balisage, de Python ni de base :
   une régression fonctionnelle n'est pas un problème d'apparence.
2. **Une famille de corrections par cause.** On ne touche que ce dont on
   connaît la cause exacte — un contraste insuffisant, une cible tactile
   trop petite. Un texte tronqué ou un chevauchement n'ont pas de
   correction universelle : ils sont constatés, pas devinés.
3. **Réversible.** Chaque modification est journalisée pour être
   annulée en un geste si la re-mesure ne confirme pas la correction.

Le choix de la couleur respecte le système du projet : on ne sort pas un
hex arbitraire, on réutilise un jeton existant quand la couleur réparée
s'en approche (le blanc du thème, le noir du texte), sinon on calcule la
teinte minimale qui atteint le seuil en gardant la teinte d'origine.
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass
from pathlib import Path

from .seuils import SEUILS, Verdict

FEUILLE = "css/verif-repares.css"
Racine_frontend = Path(__file__).resolve().parents[2] / "frontend"

# Jetons du projet, privilégiés quand ils atteignent le seuil : une
# réparation qui produit du blanc pur plutôt que du #F4F7F4 reste
# dans le langage du site.
JETONS = {
    "--blanc": (255, 255, 255),
    "--blanc-casse": (250, 249, 245),
    "--noir": (22, 25, 26),
    "--vert": (18, 122, 60),
    "--vert-sombre": (11, 90, 43),
    "--texte": (29, 35, 38),
    "--texte-2": (74, 85, 104),
    "--jaune": (245, 196, 0),
}


@dataclass
class Reparation:
    verdict: Verdict
    css: str
    famille: str
    description: str

    @property
    def signature(self) -> str:
        return f"{self.famille}:{self.verdict.detail.get('selecteur', '')}"


def _rgb(s: str) -> tuple[int, int, int] | None:
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)", s)
    return (int(float(m[1])), int(float(m[2])), int(float(m[3]))) if m else None


def _luminance(c: tuple[int, int, int]) -> float:
    def comp(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (comp(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    l1, l2 = _luminance(a), _luminance(b)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def couleur_reparante(couleur: str, fond: str, seuil: float,
                      tolere: float = 26) -> str | None:
    """Couleur atteignant le contraste demandé, au plus près de l'originale.

    Trois tentatives, dans l'ordre où elles respectent le mieux le site :
    un jeton existant, puis un ajustement de luminosité, puis l'autre
    direction. ``None`` si rien n'atteint le seuil — dans ce cas on ne
    répare pas, on constate.
    """
    base = _rgb(couleur)
    aplat = _rgb(fond)
    if not base or not aplat:
        return None

    # 1. Un jeton du projet qui passe et qui ressemble à la couleur d'origine.
    for nom, valeur in JETONS.items():
        if _contraste(valeur, aplat) >= seuil and \
           sum(abs(a - b) for a, b in zip(valeur, base)) < tolere:
            return f"var({nom})"

    # 2. Ajuster la luminosité en gardant la teinte, dans la direction
    #    qui s'éloigne du fond. On retient le PREMIER pas qui atteint le
    #    seuil : la correction reste minimale et la teinte d'origine.
    #    Le pas doit être fin (0,01) et la course complète : une échelle
    #    grossière s'arrête trop tôt et laisse un défaut qu'elle pouvait
    #    pourtant corriger.
    r, g, b = (c / 255 for c in base)
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    clair = _luminance(aplat) > 0.35          # fond clair → texte à assombrir
    for i in range(1, 101):
        pas = i / 100
        cible = max(0.0, l - pas) if clair else min(1.0, l + pas)
        rgb = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, cible, sat))
        if _contraste(rgb, aplat) >= seuil:
            return "#%02x%02x%02x" % rgb

    # 3. Rien à ajuster en gardant la teinte (couche saturée sur fond
    #    extrême) : on tente l'autre direction avant d'abandonner.
    for i in range(1, 101):
        pas = i / 100
        cible = min(1.0, l + pas) if clair else max(0.0, l - pas)
        rgb = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, cible, sat))
        if _contraste(rgb, aplat) >= seuil:
            return "#%02x%02x%02x" % rgb
    return None


def reparer(verdicts: list[Verdict]) -> tuple[list[Reparation], list[Verdict]]:
    """Transforme des verdicts en CSS. Ne répare que les deux familles
    dont la cause est certaine ; renvoie le reste inchangé."""
    reparations: list[Reparation] = []
    restants: list[Verdict] = []
    vus: set[str] = set()

    for v in verdicts:
        if not v.reparable:
            restants.append(v)
            continue
        selecteur = v.detail.get("selecteur")
        if not selecteur or selecteur.startswith("body"):
            restants.append(v)
            continue

        if v.famille == "contraste":
            seuil = v.detail.get("seuil_num")
            if not v.detail.get("couleur_texte") or not v.detail.get("couleur_fond") or not seuil:
                restants.append(v)
                continue
            couleur = couleur_reparante(
                v.detail["couleur_texte"], v.detail["couleur_fond"], seuil
            )
            if couleur is None:
                restants.append(v)
                continue
            cle = f"contraste::{selecteur}"
            if cle in vus:
                continue
            vus.add(cle)
            reparations.append(Reparation(
                verdict=v, famille="contraste", css=f"{selecteur} {{ color: {couleur} !important; }}",
                description=f"contraste {v.mesure} → ≥{v.seuil} ({couleur})",
            ))

        elif v.famille == "ergonomie":
            hauteur = v.detail.get("hauteur", 0)
            if not hauteur:
                restants.append(v)
                continue
            cle = f"cible::{selecteur}"
            if cle in vus:
                continue
            vus.add(cle)
            reparations.append(Reparation(
                verdict=v, famille="cible",
                css=f"{selecteur} {{ min-height: {int(SEUILS.cible_tactile_px)}px; "
                    f"display: inline-flex; align-items: center; justify-content: center; }}",
                description=f"cible tactile {hauteur}px → {int(SEUILS.cible_tactile_px)}px",
            ))
        else:
            restants.append(v)

    return reparations, restants


def ecrire_css(reparations: list[Reparation], racine: Path = Racine_frontend) -> Path:
    """Écrit (ou réécrit) la feuille des réparations, en tête de session."""
    chemin = racine / FEUILLE
    if not reparations:
        chemin.unlink(missing_ok=True)
        return chemin
    corps = [
        "/* Fichier généré par l'agent de vérification — ne pas éditer à la main.",
        "   Régénéré à chaque exécution : `python3 tools/verif.py`.",
        "   Ne contient que des corrections de contraste et de cible tactile,",
        "   dont la cause est mesurée. Pour des corrections manuelles, écrire",
        "   dans les feuilles existantes. */",
        "",
    ]
    for famille in ("contraste", "cible"):
        lot = [r for r in reparations if r.famille == famille]
        if not lot:
            continue
        corps.append(f"/* {'—' * 68}")
        corps.append(f"   {famille} : {len(lot)} correction(s)")
        corps.append(f"   {'—' * 68} */")
        corps += [r.css for r in lot]
        corps.append("")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(corps), encoding="utf-8")
    return chemin
