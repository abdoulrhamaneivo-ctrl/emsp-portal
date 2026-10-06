#!/usr/bin/env python3
"""Agent de vérification du portail EMSP.

    python3 tools/verif.py            # vérifie, répare, rend compte
    python3 tools/verif.py --check    # vérifie seulement, ne touche à rien
    python3 tools/verif.py --json     # sortie machine

Déroulé d'une exécution qui répare :

    1. instantané des fichiers susceptibles d'être modifiés ;
    2. tests backend (pytest) — la fonctionnalité,:intouchable ;
    3. audit du rendu : contraste, typographie, mise en page, cibles ;
    4. contrôle fonctionnel : les six états du parcours et la sécurité ;
    5. réparation des deux familles de cause certaine ;
    6. re-mesure : chaque correction est confirmée par la mesure ;
    7. re-contrôle fonctionnel — si quelque chose a bougé, on annule tout ;
    8. diff et rapport.

L'agent n'invente pas : une correction qu'il ne sait pas mesurer n'est
pas appliquée, elle est rapportée.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verif import mesures, repares  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
FRONTEND = RACINE / "frontend"
BALISE_LIEN = '<link rel="stylesheet" href="/css/verif-repares.css">'


# ── instantané ───────────────────────────────────────────────────────────
@contextlib.contextmanager
def serveur(port: int):
    """Démarre l'API, attend qu'elle réponde, puis l'arrête proprement."""
    import os
    import sys as _sys

    with socket.socket() as s:
        s.settimeout(0.2)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"le port {port} est déjà occupé — choisir un autre --port")

    # L'agent ouvre une trentaine de sessions ; le limiteur de connexion
    # (5/min/IP) rejetterait ses propres mesures. On ne le désactive que
    # sur CE serveur de test, et on le dit dans le rapport — la valeur
    # par défaut du site, 5, reste vérifiée par les tests.
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{RACINE / 'backend' / 'emsp.db'}",
        "RATE_LIMIT_CONNEXION": "0",
    }
    proc = subprocess.Popen(
        [_sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=RACINE / "backend", env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        fin = time.monotonic() + 60
        while time.monotonic() < fin:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.4)
        else:
            raise RuntimeError("l'API n'a pas démarré")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)


def fichiers_surveilles() -> list[Path]:
    css = sorted(FRONTEND.glob("css/*.css"))
    html = sorted(FRONTEND.glob("*.html"))
    return css + html


def instantaner(cibles: list[Path]) -> dict[Path, str]:
    etat = {}
    for f in cibles:
        etat[f] = f.read_text(encoding="utf-8") if f.exists() else ""
    return etat


def restaurer(etat: dict[Path, str]) -> None:
    for f, contenu in etat.items():
        if f.exists():
            if f.read_text(encoding="utf-8") == contenu:
                continue
            f.write_text(contenu, encoding="utf-8")
        elif contenu == "":
            f.unlink(missing_ok=True)


def diff(avant: dict[Path, str], apres: dict[Path, str]) -> str:
    morceaux = []
    for f in sorted(set(avant) | set(apres), key=lambda p: str(p)):
        a, b = avant.get(f, ""), apres.get(f, "")
        if a == b:
            continue
        nom = f.relative_to(RACINE) if f.is_relative_to(RACINE) else f
        if not a and b:
            morceaux.append(f"--- /dev/null\n+++ {nom}\n@@ nouveau @@\n"
                            + "".join(f"+{l}\n" for l in b.splitlines()))
            continue
        morceaux.append("".join(difflib.unified_diff(
            a.splitlines(keepends=True), b.splitlines(keepends=True),
            fromfile=f"a/{nom}", tofile=f"b/{nom}", n=3,
        )))
    return "".join(morceaux)


# ── feuille de réparations ───────────────────────────────────────────────
LIAISON = "<link rel=\"stylesheet\" href=\"/css/verif-repares.css\">"


def ligner_feuille() -> list[Path]:
    """ rend la feuille générée effective dans toutes les pages.

    Exception explicite à la règle « CSS seulement » : sans cette ligne,
    les corrections seraient écrites mais jamais appliquées. C'est un
    ajout idempotent, sans effet sur le comportement, et il apparaît dans
    le diff comme tout le reste.
    """
    modifies = []
    for page in sorted(FRONTEND.glob("*.html")):
        txt = page.read_text(encoding="utf-8")
        if BALISE_LIEN in txt:
            continue
        if "</head>" not in txt:
            continue
        # avant la fermeture du head, à côté des autres feuilles
        avant_dernier = txt.rsplit("\n", 1)
        if len(avant_dernier) == 2 and avant_dernier[1].startswith("</head>"):
            txt = f"{avant_dernier[0]}\n{BALISE_LIEN}\n{avant_dernier[1]}"
        else:
            txt = txt.replace("</head>", f"{BALISE_LIEN}\n</head>", 1)
        page.write_text(txt, encoding="utf-8")
        modifies.append(page)
    return modifies


# ── tests backend ────────────────────────────────────────────────────────
def tests_backend() -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests/", "-q"],
        cwd=RACINE, capture_output=True, text=True, timeout=900,
    )
    sortie = (res.stdout or "") + (res.stderr or "")
    ligne = [l for l in sortie.splitlines() if " passed" in l or " failed" in l]
    return res.returncode, (ligne[-1] if ligne else sortie.strip()[-200:])


# ── rapport ──────────────────────────────────────────────────────────────
def fmt(verdicts, titre: str) -> str:
    if not verdicts:
        return f"  {titre} : rien à signaler"
    lignes = [f"  {titre} : {len(verdicts)} écart(s)"]
    for v in sorted(verdicts, key=lambda x: ("bloquant majeur mineur".find(x.gravite[:3]), x.page)):
        lignes.append("    " + v.ligne())
    return "\n".join(lignes)


def main() -> int:
    ap = argparse.ArgumentParser(description="Vérification et réparation du portail EMSP")
    ap.add_argument("--check", action="store_true",
                    help="ne rien réparer, seulement rapporter")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--port", type=int, default=8223)
    args = ap.parse_args()

    t0 = time.monotonic()
    sortie: list[str] = []
    journal: list[dict] = []

    def dire(s=""):
        if not args.json:
            print(s, flush=True)
        sortie.append(s)

    surveilles = fichiers_surveilles()
    avant = instantaner(surveilles)
    dire("=" * 78)
    dire("AGENT DE VÉRIFICATION — portail EMSP")
    dire("=" * 78)

    # 1. fonctionnalité d'abord : c'est elle qu'on ne peut pas casser
    dire("\n[1/6] tests backend — la fonctionnalité, intouchable")
    code, resume = tests_backend()
    dire(f"  {resume}")
    if code != 0:
        dire("  tests en échec : vérification interrompue, rien n'a été touché")
        return 2

    dire("  note : limiteur de connexion désactivé sur le serveur de test "
         "(valeur du site inchangée : 5/min/IP, vérifiée par les tests)")

    with serveur(args.port) as base:
        # 2 + 3. audit du rendu et contrôle fonctionnel
        m = mesures.Mesures(base)
        dire("\n[2/6] audit du rendu (contraste, typographie, mise en page)")
        dire("\n[3/6] contrôle fonctionnel (parcours et sécurité)")
        t = time.monotonic()
        m.lancer()
        ecarts = m.verdicts_affichage()
        fonctionnel = m.verdicts_fonctionnels()
        dire(f"  {len(m.brut.get('pages', []))} rendus mesurés en {time.monotonic() - t:.0f}s")

        bloquants = [v for v in ecarts + fonctionnel if v.bloquant]
        if bloquants:
            dire(fmt(bloquants, "bloquant — pas de réparation automatique"))
            for v in bloquants:
                journal.append(v.__dict__ | {"etat": "constate"})
            if args.check:
                return 1
            dire("\n  un défaut fonctionnel bloque la réparation : on ne corrige pas à l'aveugle")
            return 1

        if args.check:
            dire("\n" + fmt([v for v in ecarts if v.gravite == "majeur"], "majeur"))
            dire(fmt([v for v in ecarts if v.gravite == "mineur"], "mineur"))
            dire(fmt(fonctionnel, "fonctionnel"))
            dire(f"\n{len(ecarts)} écart(s) d'affichage, {len(fonctionnel)} écart(s) fonctionnel(s)")
            return 1 if (ecarts or fonctionnel) else 0

        # 4. réparation
        dire("\n[4/6] réparation")
        a_faire, non_repares = repares.reparer(ecarts)
        if not a_faire:
            dire("  aucune correction de cause certaine — rien n'a été écrit")
        else:
            chemin = repares.ecrire_css(a_faire)
            lies = ligner_feuille()
            for r in a_faire:
                dire(f"  · {r.description}")
            dire(f"  → {chemin.relative_to(RACINE)} ({len(a_faire)} règles, "
                 f"{len(lies)} page(s) liée(s))")
            dire("  non réparés (cause inconnue) : " + (", ".join(
                sorted({v.famille for v in non_repares if v.gravite == "majeur"})) or "aucun"))

        # 5. re-mesure : une correction non confirmée n'est pas une correction
        dire("\n[5/6] re-mesure après réparation")
        m2 = mesures.Mesures(base)
        m2.lancer()
        apres_ecarts = m2.verdicts_affichage()
        reparables_avant = {(v.famille, v.page, v.mesure) for v in ecarts if v.reparable}
        reparables_apres = {(v.famille, v.page, v.mesure) for v in apres_ecarts if v.reparable}
        corriges = len(reparables_avant - reparables_apres)
        apparus = reparables_apres - reparables_avant
        dire(f"  {corriges} écart(s) corrigé(s) et confirmé(s) par la mesure")
        if apparus:
            dire(f"  ⚠ {len(apparus)} écart(s) réparable(s) nouveau(s) : "
                 + ", ".join(sorted({f"{a} {b}" for a, b, _ in apparus})[:4]))
        restants = [v for v in apres_ecarts if v.gravite in ("majeur", "bloquant")]

        # 6. re-contrôle fonctionnel : garde-fou
        dire("\n[6/6] re-contrôle fonctionnel")
        fonctionnel_apres = m2.verdicts_fonctionnels()
        regression = [v for v in fonctionnel_apres if v.bloquant]
        if regression:
            dire("  régression fonctionnelle détectée :")
            for v in regression:
                dire("    " + v.ligne())
            dire("\n  toutes les modifications sont annulées")
            restaurer(avant)
            for v in ecarts:
                journal.append(v.__dict__ | {"etat": "constate"})
            return 3
        dire("  aucune régression : parcours et sécurité intacts")

    # ── bilan ───────────────────────────────────────────────────────────
    d = diff(avant, instantaner(surveilles))
    dire("\n" + "=" * 78)
    dire("BILAN")
    dire("=" * 78)
    dire(fmt(restants, "écarts d'affichage restants"))
    for v in restants:
        journal.append(v.__dict__ | {"etat": "restant"})
    dire("")
    dire(f"  {corriges} correction(s) confirmée(s) · {len(restants)} écart(s) restant(s) · "
         f"{len(fonctionnel_apres)} écart(s) fonctionnel(s) · "
         f"{'tests OK' if code == 0 else 'TESTS KO'}")
    dire(f"  durée {time.monotonic() - t0:.1f}s")

    if d:
        dire("\n" + "=" * 78)
        dire("DIFF")
        dire("=" * 78)
        morceaux = d.split("--- a/")
        for i, m in enumerate(morceaux):
            if not m.strip():
                continue
            if i == 0:
                dire(m.rstrip())
                continue
            if LIAISON in m and m.count("@@") == 1 and "\n+" in m:
                page = m.split("\n", 1)[0].replace("a/", "")
                dire(f"--- a/{page}")
                dire("+++ b/" + page)
                dire(f"@@ {LIAISON} @@")
                dire(f"+{LIAISON}   (ajout mécanique, sans effet sur le comportement)")
            else:
                dire("--- a/" + m.rstrip())
    else:
        dire("\n  aucun fichier modifié")

    if args.json:
        print(json.dumps({
            "corriges": corriges,
            "restants": [v.__dict__ for v in restants],
            "fonctionnel": [v.__dict__ for v in fonctionnel_apres],
            "diff": d,
        }, ensure_ascii=False, indent=2))
    return 0 if not restants else 1


if __name__ == "__main__":
    raise SystemExit(main())
