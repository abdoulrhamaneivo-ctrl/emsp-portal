"""Limitation de débit en mémoire (style slowapi, sans dépendance externe).

Usage :
    if not check_rate_limit(f"login:{ip}", limit=5, window_sec=60):
        raise HTTPException(429, "Trop de tentatives...")
"""

import threading
import time

_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


def check_rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """Enregistre une tentative et retourne True si elle est autorisée.

    Args:
        key: identifiant du compteur (ex. "login:1.2.3.4").
        limit: nombre maximal de tentatives par fenêtre. ``0`` ou moins
            désactive le limiteur pour cette clé : l'agent de vérification
            en dépend, puisqu'il ouvre des dizaines de sessions sur son
            propre serveur. Sans ce cas particulier, ``0`` bloquerait
            tout le monde, ce qui n'est manifestement pas l'intention.
        window_sec: durée de la fenêtre en secondes.

    Returns:
        True si la tentative est autorisée, False si le quota est dépassé.
    """
    if limit <= 0:
        return True

    now = time.monotonic()
    cutoff = now - window_sec
    with _lock:
        timestamps = [t for t in _hits.get(key, []) if t > cutoff]
        if len(timestamps) >= limit:
            _hits[key] = timestamps  # purge sans enregistrer
            return False
        timestamps.append(now)
        _hits[key] = timestamps
        return True


def reset_rate_limit(key: str) -> None:
    """Réinitialise le compteur (utile pour les tests)."""
    with _lock:
        _hits.pop(key, None)


def clear_rate_limits() -> None:
    """Vide tous les compteurs (utile pour les tests)."""
    with _lock:
        _hits.clear()
