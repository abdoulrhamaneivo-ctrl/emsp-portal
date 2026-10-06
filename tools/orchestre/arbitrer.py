#!/usr/bin/env python3
"""Arbitre d'orchestration : qui a écrit quoi, et quoi annuler.

Un agent qui se souvient de ses limites n'est pas une limite. Ce module
enregistre l'état du dépôt avant une vague, le compare après, et **restaute
toute écriture faite hors du périmètre déclaré**.

Le raisonnement est volontairement naïf : comparer des empreintes de
fichiers suffit, et il ne dépend d'aucune cooperation de l'agent.

Usage :
    python3 tools/orchestre/arbitrer.py capturer            # avant la vague
    python3 tools/orchestre/arbitrer.py arbitrer --agent R2  # après la vague
    python3 tools/orchestre/arbitrer.py etat
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
MANIFESTE = Path(__file__).resolve().parent / "manifeste.json"
ETAT = Path(__file__).resolve().parent / ".etat.json"
RAPPORTS = Path(__file__).resolve().parent / "rapports"


def _manifeste() -> dict:
    return json.loads(MANIFESTE.read_text(encoding="utf-8"))


def _empreintes() -> dict[str, str]:
    """Empreinte de chaque fichier suivi du dépôt."""
    suivi: dict[str, str] = {}
    for motif in ("frontend/*.html", "frontend/css/*.css", "frontend/src/*.css",
                  "frontend/js/*.js", "backend/app/**/*.py"):
        for f in RACINE.glob(motif):
            if "__pycache__" in f.parts or f.name == ".DS_Store":
                continue
            suivi[str(f.relative_to(RACINE))] = hashlib.sha256(
                f.read_bytes()
            ).hexdigest()[:16]
    return suivi


def _modifies(avant: dict, apres: dict) -> set[str]:
    return {
        chemin
        for chemin, empreinte in apres.items()
        if avant.get(chemin) != empreinte
    } | {c for c in avant if c not in apres}


def capturer() -> None:
    reference = _reference()
    etat = {"empreintes": _empreintes(), "reference": reference}
    ETAT.write_text(json.dumps(etat), encoding="utf-8")
    print(f"[orchestre] {len(etat['empreintes'])} fichier(s) sous surveillance")


def _versionne() -> bool:
    return (RACINE / ".git").is_dir()


def _reference() -> str | None:
    """Commit de référence : celui de la capture, pas HEAD."""
    if not _versionne():
        return None
    res = subprocess.run(
        ["git", "-C", str(RACINE), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    return res.stdout.strip() or None


def _restaurer(chemin: str, reference: str | None) -> bool:
    """Restaure un fichier depuis le commit de référence.

    Un fichier créé pendant la vague n'existe pas à cette référence : git le
    supprime avec `checkout --`. C'est exactement le comportement voulu.
    """
    if reference:
        res = subprocess.run(
            ["git", "-C", str(RACINE), "checkout", reference, "--", chemin],
            capture_output=True, text=True,
        )
        return res.returncode == 0
    p = RACINE / chemin
    if p.exists():
        p.unlink()
        return True
    return False


def arbitrer(agent: str) -> int:
    if not ETAT.exists():
        print("[orchestre] aucune capture : lancez « capturer » d'abord")
        return 2
    capture = json.loads(ETAT.read_text(encoding="utf-8"))
    avant = capture["empreintes"]
    apres = _empreintes()
    modifies = _modifies(avant, apres)

    man = _manifeste()
    partages = set(man.get("partages", []))
    perimetre = set(man["agents"].get(agent, {}).get("ecrit", []))

    # Un vérificateur n'a aucun droit d'écriture, même sur son périmètre.
    reference = capture.get("reference")

    if agent.startswith("V"):
        if modifies:
            print(f"[orchestre] {agent} est vérificateur : "
                  f"{len(modifies)} écriture(s) — toutes annulées")
            annules = 0
            for c in sorted(modifies):
                if _restaurer(c, reference):
                    annules += 1
            print(f"[orchestre] {annules}/{len(modifies)} écriture(s) annulée(s)")
            return 1
        print(f"[orchestre] {agent} : aucune écriture, conforme")
        return 0

    hors = {c for c in modifies if c not in perimetre}
    dans = modifies - hors
    partages_touches = dans & partages

    for c in sorted(dans):
        print(f"[orchestre]   écrit  {c}")
    for c in sorted(hors):
        marque = " (FICHIER PARTAGÉ)" if c in partages else ""
        print(f"[orchestre]   HORS PÉRIMÈTRE{marque}  {c}")

    if hors or partages_touches:
        RAPPORTS.mkdir(exist_ok=True)
        (RAPPORTS / f"hors-perimetre-{agent}.txt").write_text(
            "\n".join(sorted(hors | partages_touches)), encoding="utf-8"
        )
        if not _versionne():
            print(f"[orchestre] {agent} : {len(hors)} écriture(s) hors "
                  f"périmètre. Dépôt non versionné : SIGNALÉES, non annulées.")
            return 1
        annules = [c for c in sorted(hors | partages_touches) if _restaurer(c, reference)]
        echecs = sorted((hors | partages_touches) - set(annules))
        print(f"[orchestre] {agent} : {len(hors)} écriture(s) hors périmètre — "
              f"{len(annules)} annulée(s) automatiquement.")
        for c in echecs:
            print(f"[orchestre]   NON ANNULÉE, à traiter à la main : {c}")
        return 1

    print(f"[orchestre] {agent} : {len(dans)} écriture(s), périmètre respecté")
    return 0


def etat() -> None:
    if not ETAT.exists():
        print("aucune capture en cours")
        return
    avant = json.loads(ETAT.read_text(encoding="utf-8"))["empreintes"]
    mods = sorted(_modifies(avant, _empreintes()))
    man = _manifeste()
    print(f"{len(mods)} fichier(s) modifié(s) depuis la capture :")
    for c in mods:
        proprietaire = next(
            (a for a, d in man["agents"].items() if c in d.get("ecrit", [])),
            "PARTAGÉ" if c in man.get("partages", []) else "HORS MANIFESTE",
        )
        print(f"  {c:58} {proprietaire}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Arbitre d'orchestration")
    sous = ap.add_subparsers(dest="commande", required=True)
    sous.add_parser("capturer")
    p = sous.add_parser("arbitrer")
    p.add_argument("--agent", required=True)
    sous.add_parser("etat")
    args = ap.parse_args()

    if args.commande == "capturer":
        capturer()
        raise SystemExit(0)
    if args.commande == "arbitrer":
        raise SystemExit(arbitrer(args.agent))
    etat()
