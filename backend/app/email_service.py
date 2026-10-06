"""E-mails transactionnels EMSP envoyés par l'API Brevo.

L'envoi est volontairement best-effort : une indisponibilité de Brevo ne
bloque ni l'inscription, ni le changement ou la réinitialisation du mot de passe.
"""

from __future__ import annotations

import json
import logging
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import settings

logger = logging.getLogger(__name__)
BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


def brevo_is_configured() -> bool:
    return bool(settings.BREVO_API_KEY.strip() and settings.BREVO_SENDER_EMAIL.strip())


def _send(to_email: str, to_name: str, subject: str, html_content: str) -> bool:
    if not brevo_is_configured():
        logger.info("E-mail transactionnel ignoré : Brevo n'est pas configuré.")
        return False

    payload = {
        "sender": {
            "name": settings.BREVO_SENDER_NAME,
            "email": settings.BREVO_SENDER_EMAIL,
        },
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    request = Request(
        BREVO_SEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": settings.BREVO_API_KEY,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            if 200 <= response.status < 300:
                return True
            logger.warning("Brevo a refusé un e-mail transactionnel (HTTP %s).", response.status)
    except HTTPError as exc:
        logger.warning("Brevo a refusé un e-mail transactionnel (HTTP %s).", exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning("Brevo est indisponible (%s).", type(exc).__name__)
    return False


def _email_shell(title: str, greeting: str, body: str, action: str | None = None, url: str | None = None) -> str:
    button = ""
    if action and url:
        button = (
            '<p style="margin:28px 0"><a href="'
            + escape(url, quote=True)
            + '" style="display:inline-block;padding:14px 20px;background:#ffdc00;color:#102b21;'
            'font-weight:700;text-decoration:none;border-radius:3px">'
            + escape(action)
            + "</a></p>"
        )
    return (
        '<!doctype html><html lang="fr"><body style="margin:0;background:#f3f4ee;'
        'font-family:Arial,sans-serif;color:#17251c"><div style="max-width:600px;margin:32px auto;'
        'padding:36px;background:#fff;border-top:5px solid #056839">'
        '<p style="margin:0 0 20px;color:#056839;font-size:12px;font-weight:700;letter-spacing:2px">'
        'EMSP · PORTAIL CANDIDAT</p><h1 style="font-family:Georgia,serif;font-size:30px;font-weight:500">'
        + escape(title)
        + "</h1><p>"
        + escape(greeting)
        + "</p><p style=\"line-height:1.7\">"
        + body
        + "</p>"
        + button
        + '<p style="margin-top:32px;padding-top:18px;border-top:1px solid #e0e4dc;color:#66716a;font-size:12px">'
        "École Multinationale Supérieure des Postes · Treichville, Abidjan</p></div></body></html>"
    )


def send_registration_email(email: str, prenoms: str, numero_dossier: str) -> None:
    name = escape(prenoms.strip() or "candidat")
    dossier = escape(numero_dossier)
    body = (
        f"Bonjour {name}, votre espace EMSP est prêt. Votre numéro de dossier est "
        f"<strong>{dossier}</strong>. Vous pouvez compléter votre candidature à votre rythme."
    )
    url = settings.APP_PUBLIC_URL.rstrip("/") + "/espace-candidat.html"
    _send(email, prenoms, "Bienvenue sur le portail EMSP", _email_shell(
        "Votre dossier est ouvert.", f"Bonjour {prenoms.strip() or 'candidat'},", body,
        "Ouvrir mon espace", url,
    ))


def send_password_reset_email(email: str, nom_affiche: str | None, token: str) -> None:
    name = (nom_affiche or "").strip() or "Bonjour"
    url = (
        settings.APP_PUBLIC_URL.rstrip("/")
        + "/reinitialiser-mot-de-passe.html?token="
        + quote(token, safe="")
    )
    body = (
        "Vous avez demandé à choisir un nouveau mot de passe. Le lien est valable "
        f"<strong>{settings.PASSWORD_RESET_TTL_MINUTES} minutes</strong> et ne peut être utilisé qu'une fois. "
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
    )
    _send(email, name, "Réinitialisation de votre mot de passe EMSP", _email_shell(
        "Choisissez un nouveau mot de passe.", f"Bonjour {name},", body,
        "Réinitialiser mon mot de passe", url,
    ))


def send_password_changed_email(email: str, nom_affiche: str | None) -> None:
    name = (nom_affiche or "").strip() or "Bonjour"
    body = (
        "Le mot de passe de votre compte EMSP vient d'être modifié. Si vous n'êtes pas à l'origine "
        "de ce changement, contactez immédiatement l'équipe de l'école."
    )
    _send(email, name, "Mot de passe EMSP modifié", _email_shell(
        "Votre compte est à jour.", f"Bonjour {name},", body,
        "Ouvrir mon espace", settings.APP_PUBLIC_URL.rstrip("/") + "/profil.html",
    ))
