"""Adaptation entre l'agent (Python) et le navigateur (Node).

Le paquet Playwright Python installé ici (1.55) et les pilotes Node
disponibles (1.62, 1.63) ne parlent pas le même protocole : la connexion
meurt au lancement. Plutôt que de batailler avec des versions, le
moteur de mesure est le paquet Node — celui qui fonctionne déjà — et
Python lui passe une job JSON. La frontière est nette : le navigateur
renvoie des chiffres bruts, Python en tire des verdicts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .seuils import LARGEURS, SEUILS, Verdict

RACINE = Path(__file__).resolve().parents[2]
BACKEND = RACINE / "backend"
NAVIGATEUR = Path(__file__).resolve().parent / "navigateur.mjs"

# Modules Node dont le paquet Playwright fonctionne réellement ici.
MODULES_NODE = [
    p / "node_modules/playwright"
    for p in (RACINE, *RACINE.parents, Path.home() / "Bureau")
    if (p / "node_modules/playwright/package.json").is_file()
]
MODULES_NODE += sorted(Path.home().glob("Bureau/*/node_modules/playwright"))


CACHE_NAVIGATEURS = Path.home() / ".cache/ms-playwright"


def _revision_attendue(module: Path) -> str | None:
    """Numéro de build de Chromium qu'attend ce paquet Playwright."""
    # La table des navigateurs vit dans playwright-core, pas dans playwright.
    for nom in ("browsers.json", "../playwright-core/browsers.json"):
        try:
            donnees = json.loads((module / nom).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for nav in donnees.get("browsers", []):
            if nav.get("name") in ("chromium", "chromium-headless-shell"):
                return str(nav.get("revision", ""))
    return None


def _revision_installee() -> set[str]:
    if not CACHE_NAVIGATEURS.is_dir():
        return set()
    return {d.name.rsplit("-", 1)[-1]
            for d in CACHE_NAVIGATEURS.iterdir()
            if d.is_dir() and not d.name.startswith(".")}


def module_playwright() -> str:
    """Paquet Playwright Node dont le navigateur est réellement installé.

    Plusieurs versions de Playwright coexistent sur cette machine et
    chacune attend un build de Chromium différent. Choisir au hasard
    produit une erreur « executable doesn't exist » ; on vérifie donc
    que le build attendu est bien dans le cache avant de trancher.
    """
    installees = _revision_installee()
    for m in MODULES_NODE:
        if not (m / "package.json").is_file():
            continue
        revision = _revision_attendue(m)
        if revision and revision in installees:
            return str(m)
    for m in MODULES_NODE:
        if (m / "package.json").is_file():
            return str(m)
    raise RuntimeError(
        "aucun paquet Playwright Node utilisable — attendu : "
        "node_modules/playwright dans un projet voisin, avec son Chromium "
        f"installé dans {CACHE_NAVIGATEURS}"
    )


PAGES_ANONYMES = [
    "/index.html",
    "/conditions.html",
    "/candidature.html",
    "/connexion.html",
    "/contacts.html",
]
PAGES_PROTEGEES = [
    # Le formulaire connecté est la surface la plus utilisée du site : il
    # était absent de la liste, donc jamais mesuré. On le prend avec un
    # dossier en cours (« presque »), le cas le plus contraignant :
    # listes vides, compteurs à zéro, états d'erreur disponibles.
    ("/candidature.html", "formulaire"),
    ("/dashboard.html", "candidat"),
    ("/documents.html", "candidat"),
    ("/suivi.html", "candidat"),
    ("/convocation.html", "candidat"),
    ("/admis.html", "candidat"),
    ("/profil.html", "candidat"),
    ("/admin.html", "admin"),
]

COMPTES = {
    "admin": ["admin@emsp.ci", "AdminEmsp2026"],
    "soumis": ["soumis@demo.emsp.ci", "DemoEmsp2026"],
    "presque": ["presque@demo.emsp.ci", "DemoEmsp2026"],
    "brouillon": ["brouillon@demo.emsp.ci", "DemoEmsp2026"],
    "admis": ["admis@demo.emsp.ci", "DemoEmsp2026"],
    "refuse": ["refuse@demo.emsp.ci", "DemoEmsp2026"],
    "convoque": ["convoque@demo.emsp.ci", "DemoEmsp2026"],
    "admis": ["admis@demo.emsp.ci", "DemoEmsp2026"],
    "refuse": ["refuse@demo.emsp.ci", "DemoEmsp2026"],
}


class Mesures:
    """Un cycle complet : une job envoyée, des mesures revenues."""

    def __init__(self, base: str, seuils=SEUILS):
        self.base = base
        self.seuils = seuils
        self.brut: dict = {}

    # ── job ────────────────────────────────────────────────────────────
    def _pages(self):
        return (
            [{"chemin": p, "role": "anonyme"} for p in PAGES_ANONYMES]
            + [{"chemin": c, "role": r} for c, r in PAGES_PROTEGEES]
        )

    def _job(self) -> dict:
        s = self.seuils
        return {
            "base": self.base,
            "seuils": {
                "contrasteTexte": s.contraste_texte,
                "contrasteGrandTexte": s.contraste_grand_texte,
                "taillePoliceGrandTexte": s.taille_police_grand_texte,
                "taillePoliceGrandTexteGras": s.taille_police_grand_texte_gras,
                "policeMinPx": s.police_min_px,
                "mesureMaxCaracteres": s.mesure_max_caracteres,
                "largeurMobile": s.largeur_mobile,
                "cibleTactilePx": s.cible_tactile_px,
                "cibleTactileMinPx": s.cible_tactile_min_px,
                "enteteMaxMobilePx": s.entete_max_mobile_px,
                "debordementTolerePx": s.debordement_tolere_px,
            },
            "pages": [{**p, "largeurs": list(LARGEURS)} for p in self._pages()],
            "comptes": COMPTES,
            "etapesAttendues": s.etapes_parcours,
            "piecesAttendees": s.pieces_justificatives,
            "motifInterne": self._motif_interne(),
        }

    def _motif_interne(self) -> str | None:
        """Le motif qu'on interdit au candidat, lu à la source."""
        import sqlite3
        db = BACKEND / "emsp.db"
        if not db.exists():
            return None
        try:
            with sqlite3.connect(db) as con:
                ligne = con.execute(
                    "select motif_refus from candidatures "
                    "where motif_refus is not null and motif_refus <> '' limit 1"
                ).fetchone()
            return ligne[0] if ligne else None
        except sqlite3.Error:
            return None

    # ── exécution ──────────────────────────────────────────────────────
    def lancer(self, delai: int = 900) -> None:
        env = {**os.environ, "PW_MODULE": module_playwright()}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self._job(), f, ensure_ascii=False)
            job = f.name
        try:
            res = subprocess.run(
                ["node", str(NAVIGATEUR), job],
                capture_output=True, text=True, timeout=delai, env=env,
            )
            if res.returncode != 0 or not res.stdout.strip():
                raise RuntimeError(
                    "le moteur de mesure a échoué :\n"
                    + (res.stderr or res.stdout)[-1200:]
                )
            self.brut = json.loads(res.stdout)
        finally:
            Path(job).unlink(missing_ok=True)

    # ── traduction en verdicts ─────────────────────────────────────────
    def verdicts_affichage(self) -> list[Verdict]:
        v: list[Verdict] = []
        for entree in self.brut.get("pages", []):
            ou = f"{entree['page']} @{entree['largeur']}"
            if "erreur" in entree:
                v.append(Verdict(
                    famille="chargement", cle="erreur", page=ou,
                    message=f"page illisible : {entree['erreur']}",
                    mesure="erreur", seuil="page rendue", gravite="bloquant",
                ))
                continue
            b = entree["brut"]
            for c in b["contraste"]:
                v.append(Verdict(
                    famille="contraste", cle="contraste", page=ou,
                    message=f"« {c['texte']} » illisible ({c['couleur']} sur {c['fond']})",
                    mesure=f"{c['ratio']}:1", seuil=f"{c['seuil']}:1",
                    gravite="majeur", reparable=True,
                    detail={"selecteur": c["selecteur"], "couleur_texte": c["couleur"],
                            "couleur_fond": c["fond"], "seuil_num": c["seuil"]},
                ))
            for c in b["police"]:
                v.append(Verdict(
                    famille="typographie", cle="police", page=ou,
                    message=f"« {c['texte']} » en {c['taille']}px",
                    mesure=f"{c['taille']}px", seuil=f"{self.seuils.police_min_px}px",
                    gravite="majeur",
                    detail={"selecteur": c["selecteur"]},
                ))
            for m in b["mise_en_page"]:
                if m["type"] == "cible":
                    # Sous la norme : défaut. Entre la norme et le confort :
                    # préférence — à signaler, mais pas à corriger d'urgence.
                    sous_norme = m.get("hauteur", 0) < m.get("norme", 0)
                    v.append(Verdict(
                        famille="ergonomie", cle="cible", page=ou,
                        message=f"cible tactile « {m['texte']} » trop petite",
                        mesure=f"{m['hauteur']}px", seuil=f"{m['seuil']}px",
                        gravite="majeur" if sous_norme else "mineur",
                        reparable=sous_norme,
                        detail={"selecteur": m["selecteur"], "hauteur": m["hauteur"]},
                    ))
                elif m["type"] == "tronque":
                    v.append(Verdict(
                        famille="mise en page", cle="tronque", page=ou,
                        message=f"texte tronqué « {m['texte']} »",
                        mesure=f"-{m['lost']}px", seuil="0px", gravite="majeur",
                        detail={"selecteur": m["selecteur"]},
                    ))
                elif m["type"] == "debordement":
                    v.append(Verdict(
                        famille="mise en page", cle="debordement", page=ou,
                        message=f"débordement hors écran « {m['texte']} »",
                        mesure=f"+{m['excess']}px", seuil="0px", gravite="majeur",
                        detail={"selecteur": m["selecteur"]},
                    ))
                elif m["type"] == "entete":
                    v.append(Verdict(
                        famille="mise en page", cle="entete", page=ou,
                        message="l'en-tête s'est épaissi (garde-fou anti-régression)",
                        mesure=f"{m['hauteur']}px", seuil=f"{m['seuil']}px",
                        gravite="majeur",
                        detail={"selecteur": m["selecteur"]},
                    ))
                elif m["type"] == "mesure":
                    v.append(Verdict(
                        famille="typographie", cle="mesure", page=ou,
                        message=f"ligne trop longue « {m['texte']} »",
                        mesure=f"{m['caracteres']} car.", seuil=f"{m['seuil']} car.",
                        gravite="mineur",
                        detail={"selecteur": m["selecteur"]},
                    ))
            # ── Contrat de design (DESIGN.md) ──────────────────────────
            # Ces contrôles manquaient, et leur absence a laissé la dérive
            # passer : rien ne regardait la profondeur ni les familles.
            c = b.get("contrat")
            if c:
                surplus = [f for f in c.get("familles", []) if f not in c.get("polices", [])]
                # `polices` liste ce que le navigateur a réellement chargé ;
                # une famille rendue mais absente de cette liste est un repli
                # qui s'est échappé, et c'est exactement ce qu'on veut voir.
                if surplus:
                    v.append(Verdict(
                        famille="contrat", cle="familles", page=ou,
                        message=f"famille de caractères hors contrat : {', '.join(surplus)}",
                        mesure=f"{len(surplus)} famille(s)",
                        seuil="0 hors contrat",
                        gravite="majeur",
                        detail={"attendu": c.get("polices")},
                    ))
                nb_cartes = c.get("cartes", 0)
                if nb_cartes and c.get("sansRayon"):
                    v.append(Verdict(
                        famille="contrat", cle="rayon", page=ou,
                        message=f"carte sans rayon ({c['sansRayon']}/{nb_cartes}) — "
                                f"le contrat impose {c.get('rayons') or '3px'}",
                        mesure=f"{c['sansRayon']}/{nb_cartes} sans rayon",
                        seuil=c.get("rayons") or "3px",
                        gravite="majeur",
                    ))
                if nb_cartes and c.get("sansOmbre"):
                    v.append(Verdict(
                        famille="contrat", cle="ombre", page=ou,
                        message=f"carte sans ombre ({c['sansOmbre']}/{nb_cartes}) — "
                                f"le contrat en impose une",
                        mesure=f"{c['sansOmbre']}/{nb_cartes} sans ombre",
                        seuil="1 ombre, 1 couche",
                        gravite="majeur",
                    ))
                if c.get("blocsMasques"):
                    v.append(Verdict(
                        famille="contrat", cle="contenu_masque", page=ou,
                        message=f"{c['blocsMasques']} bloc(s) masqué(s) par l'entrée "
                                f"en scène alors qu'ils sont à l'écran",
                        mesure=f"{c['blocsMasques']} bloc(s)", seuil="0",
                        gravite="bloquant",
                    ))
        return v

    def verdicts_fonctionnels(self) -> list[Verdict]:
        v: list[Verdict] = []
        for p in self.brut.get("parcours", []):
            if p["etat"] == "ok":
                continue
            if p["etat"] == "limite":
                v.append(Verdict(
                    famille="parcours", cle="limite", page=f"login:{p['role']}",
                    message=p["message"], mesure="429", seuil="200", gravite="mineur",
                ))
                continue
            v.append(Verdict(
                famille="parcours", cle=p["role"], page=f"parcours:{p['role']}",
                message=p["message"],
                mesure=p.get("mesure", "absent"), seuil=p.get("seuil", "conforme"),
                gravite="bloquant",
            ))
        for s in self.brut.get("securite", []):
            if s["etat"] == "ok":
                continue
            v.append(Verdict(
                famille="securite", cle=s["page"], page=s["page"],
                message=s["message"],
                mesure=s.get("mesure", "divulgué"), seuil=s.get("seuil", "absent"),
                gravite="bloquant",
            ))
        return v
