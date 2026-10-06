from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME
from app.config import settings
from app.db import get_db
from app.models import Session as SessionModel, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Retourne l'utilisateur connecté si le cookie est valide, sinon None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    session = db.get(SessionModel, token)
    if session is None:
        return None
    if session.expires_at <= _utcnow():
        db.delete(session)
        db.commit()
        return None

    user = db.get(User, session.user_id)
    return user


def _nav_items(user: User | None, current_path: str = "") -> list[tuple[str, str]]:
    if user is None:
        # La landing dispose d’une navigation ancrée sur ses sections ; les
        # autres pages publiques gardent les liens institutionnels du portail.
        # La candidature reste le CTA principal dans la barre d’actions.
        if current_path == "/index.html":
            return [
                ("L’école", "#ecole"),
                ("Formations", "#formations"),
                ("Vie étudiante", "#experience"),
                ("Le parcours", "#parcours"),
            ]
        return [
            ("Accueil", "/index.html"),
            ("Conditions", "/conditions.html"),
            ("Candidater", "/candidature.html"),
            ("Contact", "/contact.html"),
        ]

    if (user.role or "CANDIDAT").upper() == "ADMIN":
        return [
            ("Administration", "/admin.html"),
            ("Profil", "/profil.html"),
            ("Contact", "/contact.html"),
        ]

    return [
        ("Espace", "/espace-candidat.html"),
        ("Candidature", "/candidature.html"),
        ("Pièces", "/pieces.html"),
        ("Suivi", "/suivi.html"),
        ("Convocation", "/convocation.html"),
        ("Résultats", "/resultat.html"),
        ("Profil", "/profil.html"),
    ]


def _footer_links(user: User | None) -> list[tuple[str, str]]:
    if user is None:
        return [
            ("Accueil", "/index.html"),
            ("Candidater", "/candidature.html"),
            ("Connexion", "/connexion.html"),
            ("Contact", "/contact.html"),
        ]

    if (user.role or "CANDIDAT").upper() == "ADMIN":
        return [
            ("Administration", "/admin.html"),
            ("Profil", "/profil.html"),
            ("Contact", "/contact.html"),
        ]

    return [
        ("Mon espace", "/espace-candidat.html"),
        ("Ma candidature", "/candidature.html"),
        ("Mes pièces", "/pieces.html"),
        ("Suivi", "/suivi.html"),
    ]


def _nav_html(user: User | None, current_path: str) -> str:
    items = _nav_items(user, current_path)
    links = []
    for label, href in items:
        active = (
            "active"
            if current_path == href or (current_path.endswith(href) and href != "/")
            else ""
        )
        links.append(f'<a class="nav-link {active}" href="{href}">{escape(label)}</a>')

    if user is None:
        actions = '<a class="btn btn-outline" href="/connexion.html">Connexion</a>'
        badge = '<span class="session-label">Visiteur</span>'
        priority_action = '<a class="btn btn-primary nav-priority-link" href="/candidature.html">Candidater <span aria-hidden="true">↗</span></a>'
    else:
        actions = '<button class="btn btn-outline" type="button" data-logout>Déconnexion</button><span class="logout-feedback" data-logout-feedback role="status" hidden></span>'
        badge = f'<span class="session-label">{escape(user.email)}</span>'
        is_admin = (user.role or "CANDIDAT").upper() == "ADMIN"
        priority_href = "/admin.html?section=applications" if is_admin else "/candidature.html"
        priority_label = "Candidatures" if is_admin else "Ma candidature"
        priority_action = f'<a class="btn btn-primary nav-priority-link" href="{priority_href}">{priority_label}</a>'

    theme_toggle = """<button class="theme-toggle" type="button" data-theme-toggle aria-pressed="false" aria-label="Activer le mode sombre" title="Activer le mode sombre">
          <span class="theme-toggle-icon" data-theme-icon aria-hidden="true">☾</span>
          <span class="theme-toggle-label" data-theme-label>Sombre</span>
        </button>"""
    mobile_actions = f"{badge}{theme_toggle}{priority_action}{actions}"

    return f"""
    <header class="site-header">
      <div class="header-utility">
        <div class="container utility-inner">
          <span>École Multinationale Supérieure des Postes</span>
          <span class="utility-location">Treichville · Abidjan, Côte d’Ivoire</span>
        </div>
      </div>
      <div class="container header-inner{' header-inner-landing' if user is None and current_path == '/index.html' else ''}">
        <a href="/index.html" class="brand" aria-label="École Multinationale Supérieure des Postes, accueil">
          <img class="brand-logo" src="/assets/preview.webp" alt="École Multinationale Supérieure des Postes d’Abidjan" width="341" height="110" />
        </a>
        <nav class="main-nav" aria-label="Navigation principale">{''.join(links)}</nav>
        <div class="nav-actions">{badge}{theme_toggle}{priority_action}{actions}</div>
        <details class="mobile-menu">
          <summary aria-label="Ouvrir le menu">Menu</summary>
          <div class="mobile-menu-panel">
            <nav aria-label="Navigation mobile">{''.join(links)}</nav>
            <div class="mobile-menu-actions">{mobile_actions}</div>
          </div>
        </details>
      </div>
    </header>
    """


def _footer_html(user: User | None) -> str:
    links = _footer_links(user)
    rendered_links = "".join(
        f'<li><a href="{href}">{escape(label)}</a></li>' for label, href in links
    )

    return f"""
    <footer class="site-footer">
      <div class="container">
        <div class="footer-grid">
          <div>
            <a class="footer-brand" href="/index.html">EMSP</a>
            <p>Former les talents qui accompagnent les transformations postales et numériques en Afrique de l’Ouest.</p>
          </div>
          <div>
            <h4>Le portail</h4>
            <ul>{rendered_links}</ul>
          </div>
          <div>
            <h4>Informations</h4>
            <ul>
              <li><a href="/conditions.html">Conditions</a></li>
              <li><a href="/contact.html">Contact</a></li>
              <li><a href="/index.html#formations">Nos formations</a></li>
            </ul>
          </div>
          <div>
            <h4>Nous trouver</h4>
            <ul>
              <li>Treichville, Abidjan</li>
              <li>Côte d’Ivoire</li>
              <li>École intergouvernementale fondée en 1970</li>
            </ul>
          </div>
        </div>
        <div class="footer-bottom">
          <span>© 2026 École Multinationale Supérieure des Postes</span>
          <span>{'Session active' if user else 'Concours d’entrée · Session 2026–2027'}</span>
        </div>
      </div>
    </footer>
    """


def _page_template(
    title: str, current_path: str, user: User | None, content: str
) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="fr">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{escape(title)}</title>
    <meta name="theme-color" content="#063e2b" />
    <meta name="description" content="Portail officiel de l’École Multinationale Supérieure des Postes à Abidjan. Découvrez les formations et préparez votre candidature au concours d’entrée." />
    <link rel="icon" href="/assets/emsp-icon.png" type="image/png" sizes="128x128" />
    <link rel="apple-touch-icon" href="/assets/emsp-icon.png" />
    <script>
      (() => {{
        try {{
          const saved = localStorage.getItem('emsp-theme');
          const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
          document.documentElement.dataset.theme = saved === 'dark' || saved === 'light' ? saved : systemDark ? 'dark' : 'light';
        }} catch (_) {{ document.documentElement.dataset.theme = 'light'; }}
      }})();
    </script>
    <style>
      :root {{
        --emsp-green: #056839;
        --emsp-green-deep: #033f22;
        --emsp-yellow: #ffdc00;
        --emsp-paper: #ffffff;
        --emsp-paper-2: #f6f5f1;
        --emsp-ink: #16191a;
        --emsp-ink-soft: #5a6478;
        --emsp-danger: #a3321f;
        --emsp-danger-bg: #fbedea;
        --shadow-soft: 0 20px 40px -15px rgba(5, 104, 57, 0.12);
      }}
      * {{ box-sizing: border-box; }}
      html {{ scroll-behavior: smooth; }}
      body {{
        margin: 0;
        font-family: "Public Sans", "Segoe UI", sans-serif;
        background: var(--emsp-paper-2);
        color: var(--emsp-ink);
        line-height: 1.6;
      }}
      a {{ color: inherit; text-decoration: none; }}
      img {{ max-width: 100%; display: block; }}
      button, input, select, textarea {{ font: inherit; }}
      .container {{ width: min(1180px, calc(100% - 2rem)); margin: 0 auto; }}
      .site-header {{ position: sticky; top: 0; z-index: 50; border-bottom: 1px solid rgba(22, 25, 26, 0.08); background: rgba(255,255,255,0.94); backdrop-filter: blur(12px); }}
      .header-inner {{ display: flex; align-items: center; justify-content: space-between; gap: 1.25rem; min-height: 78px; }}
      .brand {{ display: inline-flex; align-items: center; gap: 0.85rem; font-weight: 800; font-size: 1.1rem; letter-spacing: 0.02em; color: var(--emsp-green-deep); }}
      .brand-mark {{ width: 42px; height: 42px; border-radius: 12px; background: linear-gradient(135deg, var(--emsp-green), #0d7a4a); color: white; display: grid; place-items: center; font-weight: 900; box-shadow: var(--shadow-soft); }}
      .main-nav {{ display: flex; align-items: center; flex-wrap: wrap; justify-content: center; gap: 0.5rem; }}
      .nav-link {{ padding: 0.6rem 0.9rem; border-radius: 999px; color: var(--emsp-ink-soft); font-size: 0.95rem; transition: background-color 0.2s ease, color 0.2s ease, transform 0.2s ease; }}
      .nav-link:hover, .nav-link:focus-visible, .nav-link.active {{ background: rgba(5, 104, 57, 0.08); color: var(--emsp-green-deep); }}
      .nav-actions {{ display: flex; align-items: center; gap: 0.75rem; }}
      .badge-status {{ display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.45rem 0.7rem; border-radius: 999px; background: rgba(5, 104, 57, 0.08); color: var(--emsp-green-deep); font-size: 0.8rem; font-weight: 700; }}
      .badge-status .dot {{ width: 0.62rem; height: 0.62rem; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.12); }}
      .btn {{ display: inline-flex; align-items: center; justify-content: center; border: 1px solid transparent; border-radius: 999px; padding: 0.8rem 1.25rem; font-weight: 700; cursor: pointer; transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease; }}
      .btn:hover, .btn:focus-visible {{ transform: translateY(-1px); }}
      .btn-primary {{ background: var(--emsp-yellow); color: #1d2a1f; box-shadow: 0 10px 18px -12px rgba(255,220,0,0.7); }}
      .btn-secondary {{ background: var(--emsp-green); color: #fff; }}
      .btn-ghost {{ background: transparent; border-color: rgba(5,104,57,0.25); color: var(--emsp-green-deep); }}
      .page-shell {{ padding: 3.5rem 0 5rem; }}
      .hero {{ padding: 4rem 0 3rem; background: linear-gradient(180deg, rgba(5,104,57,0.04), rgba(5,104,57,0.02)); }}
      .hero-card {{ background: var(--emsp-paper); border-radius: 24px; box-shadow: var(--shadow-soft); padding: clamp(1.4rem, 3vw, 3rem); }}
      .hero-grid {{ display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 2rem; align-items: center; }}
      .kicker {{ display: inline-block; margin-bottom: 1rem; padding: 0.4rem 0.8rem; border-radius: 999px; background: rgba(255,220,0,0.18); color: var(--emsp-green-deep); font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; font-size: 0.72rem; }}
      h1, h2, h3 {{ margin: 0 0 1rem; color: var(--emsp-green-deep); line-height: 1.1; }}
      h1 {{ font-size: clamp(2.2rem, 4vw, 4rem); }}
      h2 {{ font-size: clamp(1.7rem, 2.5vw, 2.5rem); }}
      h3 {{ font-size: 1.4rem; }}
      .lead {{ font-size: 1.06rem; color: var(--emsp-ink-soft); max-width: 62ch; }}
      .hero-actions, .inline-actions {{ display: flex; flex-wrap: wrap; gap: 0.9rem; margin-top: 1.5rem; }}
      .metrics {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin-top: 2rem; }}
      .metric {{ padding: 1rem 1.1rem; background: var(--emsp-paper-2); border-radius: 18px; border: 1px solid rgba(5,104,57,0.08); }}
      .metric strong {{ display: block; font-size: 1.5rem; color: var(--emsp-green-deep); }}
      .metric span {{ color: var(--emsp-ink-soft); font-size: 0.9rem; }}
      .side-panel {{ background: linear-gradient(180deg, var(--emsp-green), var(--emsp-green-deep)); color: white; border-radius: 24px; padding: 1.5rem; min-height: 100%; }}
      .side-panel h3, .side-panel p, .side-panel li {{ color: rgba(255,255,255,0.94); }}
      .side-panel ul {{ list-style: none; padding: 0; margin: 1rem 0 0; display: grid; gap: 0.75rem; }}
      .section {{ padding: 1rem 0 0; }}
      .grid-3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1.25rem; }}
      .card {{ background: var(--emsp-paper); border: 1px solid rgba(5,104,57,0.08); border-radius: 22px; padding: 1.4rem; box-shadow: 0 12px 20px -15px rgba(22,25,26,0.18); }}
      .card ul {{ margin: 1rem 0 0; padding-left: 1.1rem; color: var(--emsp-ink-soft); }}
      .section-head {{ margin-bottom: 1.5rem; }}
      .auth-panel {{ max-width: 520px; margin: 0 auto; background: var(--emsp-paper); border-radius: 24px; padding: clamp(1.4rem, 3vw, 2.5rem); box-shadow: var(--shadow-soft); }}
      .form-grid {{ display: grid; gap: 1rem; }}
      .field {{ display: grid; gap: 0.5rem; }}
      .field label {{ font-size: 0.82rem; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; color: var(--emsp-ink-soft); }}
      .field input, .field select, .field textarea {{ width: 100%; border: 1px solid rgba(22,25,26,0.1); background: #fff; border-radius: 14px; padding: 0.9rem 1rem; color: var(--emsp-ink); }}
      .field input:focus, .field select:focus, .field textarea:focus {{ outline: 3px solid rgba(5,104,57,0.15); border-color: var(--emsp-green); }}
      .help-text {{ font-size: 0.88rem; color: var(--emsp-ink-soft); }}
      .alert {{ padding: 0.9rem 1rem; border-radius: 14px; font-size: 0.92rem; }}
      .alert.info {{ background: rgba(5,104,57,0.08); color: var(--emsp-green-deep); }}
      .alert.warning {{ background: rgba(255,220,0,0.13); color: #413401; }}
      .summary-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.25rem; }}
      .stat-box {{ padding: 1.1rem; background: var(--emsp-paper); border-radius: 18px; border: 1px solid rgba(5,104,57,0.08); }}
      .stat-box strong {{ display: block; font-size: 1.8rem; color: var(--emsp-green-deep); }}
      .site-footer {{ background: var(--emsp-green-deep); color: rgba(255,255,255,0.9); padding: 3rem 0 2rem; }}
      .footer-grid {{ display: grid; grid-template-columns: 1.1fr 0.8fr 0.8fr 1fr; gap: 1.5rem; }}
      .site-footer h4, .site-footer p, .site-footer li, .site-footer a {{ color: rgba(255,255,255,0.9); }}
      .site-footer ul {{ list-style: none; padding: 0; margin: 0.8rem 0 0; display: grid; gap: 0.5rem; }}
      .footer-bottom {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.12); display: flex; justify-content: space-between; gap: 1rem; font-size: 0.9rem; }}
      @media (max-width: 900px) {{
        .hero-grid, .grid-3, .summary-grid, .footer-grid {{ grid-template-columns: 1fr; }}
        .header-inner {{ flex-wrap: wrap; padding: 0.9rem 0; }}
        .main-nav {{ justify-content: flex-start; }}
      }}
    </style>
    <style>
      :root {{ color-scheme: light; --vert:#056839; --vert-sombre:#033f22; --jaune:#ffdc00; --papier:#faf9f5; --noir:#1a1c1b; --texte-2:#4a5568; --filet:#e5e2da; --contenu:1200px; }}
      body {{ background:var(--papier); color:var(--noir); font-family:"Public Sans","Segoe UI",sans-serif; }}
      .container {{ width:min(var(--contenu),calc(100% - 48px)); }}
      .site-header {{ position:relative; z-index:10; background:#fff; }}
      .header-utility {{ background:var(--vert-sombre); color:#fff; font-size:13px; }}
      .utility-inner {{ min-height:38px; display:flex; align-items:center; justify-content:space-between; gap:20px; }}
      .utility-location {{ color:rgba(255,255,255,.8); }}
      .header-inner {{ min-height:88px; gap:28px; }}
      .brand {{ gap:12px; flex:0 0 auto; color:var(--vert-sombre); }}
      .brand-mark {{ width:48px; height:48px; border:2px solid var(--vert); border-radius:0; background:#fff; color:var(--vert-sombre); box-shadow:none; font-family:Georgia,serif; }}
      .brand-name {{ font-size:23px; letter-spacing:.04em; }}
      .main-nav {{ gap:4px; }}
      .nav-link {{ min-height:44px; padding:10px 12px; border-bottom:2px solid transparent; border-radius:0; color:var(--noir); font-size:14px; font-weight:600; }}
      .nav-link:hover,.nav-link:focus-visible,.nav-link.active {{ border-bottom-color:var(--jaune); background:transparent; color:var(--vert); }}
      .nav-actions {{ gap:12px; }}
      .session-label {{ max-width:170px; overflow:hidden; color:var(--texte-2); font-size:12px; text-overflow:ellipsis; white-space:nowrap; }}
      .mobile-menu {{ display:none; position:relative; }}
      .mobile-menu summary {{ min-height:42px; padding:8px 14px; cursor:pointer; border:1px solid var(--filet); color:var(--vert-sombre); font-weight:700; list-style:none; }}
      .mobile-menu summary::-webkit-details-marker {{ display:none; }}
      .mobile-menu nav {{ position:absolute; top:calc(100% + 8px); right:0; width:min(320px,calc(100vw - 32px)); padding:10px; background:#fff; border:1px solid var(--filet); box-shadow:0 16px 35px rgba(0,0,0,.13); }}
      .mobile-menu .nav-link {{ width:100%; border:0; }}
      .btn {{ min-height:44px; padding:10px 18px; border-radius:2px; font-size:14px; }}
      .btn-primary {{ background:var(--jaune); color:var(--noir); box-shadow:none; }}
      .btn-primary:hover {{ background:#f0cf00; }}
      .btn-outline {{ background:transparent; border-color:var(--filet); color:var(--vert-sombre); }}
      :focus-visible {{ outline:3px solid var(--vert); outline-offset:3px; }}
      h1,h2,h3,h4 {{ color:var(--vert-sombre); font-family:Georgia,"Times New Roman",serif; font-weight:600; line-height:1.15; }}
      h1 {{ font-size:clamp(38px,5vw,68px); }} h2 {{ font-size:clamp(30px,3.3vw,44px); }} h3 {{ font-size:25px; }}
      .kicker {{ color:var(--vert); font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
      .lead {{ max-width:62ch; color:var(--texte-2); font-size:18px; }}
      .page-shell {{ min-height:55vh; padding:72px 0 96px; }}
      .section {{ padding:76px 0; }}
      .section-tint {{ background:#f0eee7; }}
      .section-head,.section-title {{ max-width:720px; margin-bottom:34px; }}
      .section-title p,.section-head p {{ margin-top:12px; color:var(--texte-2); }}
      .home-hero {{ min-height:500px; position:relative; display:flex; align-items:center; overflow:hidden; background:var(--vert-sombre); color:#fff; }}
      .home-hero-image {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; object-position:center 43%; }}
      .home-hero:after {{ position:absolute; inset:0; content:""; background:linear-gradient(90deg,rgba(3,63,34,.94),rgba(3,63,34,.76) 48%,rgba(3,63,34,.2)); }}
      .home-hero-content {{ position:relative; z-index:1; padding:70px 0; animation:rise-in .55s ease-out both; }}
      .home-hero .kicker {{ color:var(--jaune); }}
      .home-hero h1 {{ max-width:760px; color:#fff; }}
      .home-hero p {{ max-width:600px; margin-top:18px; color:rgba(255,255,255,.9); font-size:18px; }}
      .hero-actions {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:28px; }}
      .hero-secondary {{ min-height:44px; padding:10px 16px; display:inline-flex; align-items:center; color:#fff; font-size:14px; font-weight:700; text-decoration:underline; text-decoration-color:var(--jaune); text-underline-offset:5px; }}
      .hero-facts {{ position:absolute; z-index:1; right:max(24px,calc((100vw - var(--contenu))/2)); bottom:22px; display:flex; gap:24px; color:#fff; font-size:12px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
      .program-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border-top:1px solid var(--filet); border-left:1px solid var(--filet); }}
      .program-item {{ min-height:210px; padding:26px; background:#fff; border-right:1px solid var(--filet); border-bottom:1px solid var(--filet); transition:background .2s ease; }}
      .program-item:hover {{ background:#f3f5ef; }}
      .program-code {{ display:inline-block; margin-bottom:20px; color:var(--vert); font-size:12px; font-weight:800; letter-spacing:.1em; }}
      .program-item h3 {{ margin-bottom:10px; font-size:22px; }}
      .program-item p,.feature p,.story-copy p {{ color:var(--texte-2); font-size:14px; }}
      .program-outcome {{ color:var(--vert); font-size:13px; font-weight:700; }}
      .feature-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:34px; }}
      .feature {{ padding-top:20px; border-top:3px solid var(--vert); }}
      .feature-index {{ display:block; margin-bottom:18px; color:#73796d; font-family:Georgia,serif; font-size:14px; font-weight:700; }}
      .feature h3 {{ margin-bottom:12px; }}
      .story-grid {{ display:grid; grid-template-columns:1fr 1fr; align-items:center; gap:56px; }}
      .story-image {{ width:100%; aspect-ratio:4/3; object-fit:cover; }}
      .story-copy .btn {{ margin-top:10px; }}
      .steps-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); }}
      .step-item {{ padding:20px 22px; border-left:1px solid #c9c7bc; }}
      .step-item:first-child {{ border-left:0; }}
      .step-item strong {{ display:block; margin-bottom:12px; color:var(--vert); font:500 34px Georgia,serif; }}
      .step-item span {{ color:var(--texte-2); font-size:14px; }}
      .cta-band {{ padding:42px; display:flex; align-items:center; justify-content:space-between; gap:24px; background:var(--vert-sombre); color:#fff; }}
      .cta-band h2 {{ color:#fff; font-size:clamp(26px,3vw,38px); }}
      .cta-band p {{ margin:8px 0 0; color:rgba(255,255,255,.8); }}
      .card {{ padding:30px; background:#fff; border:1px solid var(--filet); border-radius:0; box-shadow:none; }}
      .card h3 {{ margin-bottom:12px; }} .card p,.card li {{ color:var(--texte-2); }}
      .grid-3 {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; }}
      .auth-panel {{ width:min(100%,560px); margin:0 auto; padding:clamp(26px,5vw,48px); background:#fff; border-top:4px solid var(--vert); border-radius:0; box-shadow:0 18px 48px rgba(26,28,27,.08); }}
      .auth-panel h1 {{ font-size:clamp(36px,5vw,48px); }}
      .form-grid {{ display:grid; gap:18px; margin-top:24px; }}
      .field {{ display:grid; gap:7px; }} .field label {{ color:var(--noir); font-size:13px; font-weight:700; letter-spacing:0; text-transform:none; }}
      .field input,.field select,.field textarea {{ width:100%; min-height:48px; padding:11px 13px; border:1px solid #c9c7bc; border-radius:0; background:#fff; color:var(--noir); }}
      .field textarea {{ min-height:130px; resize:vertical; }}
      .help-text {{ color:var(--texte-2); font-size:13px; }}
      .inline-actions {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:0; }}
      .alert {{ margin:18px 0; padding:13px 16px; border-left:3px solid var(--vert); border-radius:0; background:#edf4ef; color:var(--vert-sombre); }}
      .alert.warning {{ border-color:#ad7800; background:#fff7d1; color:#3f3300; }}
      .summary-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
      .stat-box {{ min-height:112px; padding:20px; background:#fff; border:1px solid var(--filet); border-radius:0; }}
      .stat-box strong {{ display:block; color:var(--vert-sombre); font:30px Georgia,serif; }}
      .stat-box span {{ color:var(--texte-2); font-size:13px; }}
      table {{ border-collapse:collapse; }} th,td {{ text-align:left; border-bottom:1px solid var(--filet); }}
      .site-footer {{ padding:60px 0 22px; background:var(--vert-sombre); color:#fff; }}
      .footer-grid {{ display:grid; grid-template-columns:1.5fr 1fr 1fr 1.2fr; gap:34px; }}
      .footer-brand {{ display:inline-block; margin-bottom:14px; color:var(--jaune); font:700 30px Georgia,serif; }}
      .site-footer h4 {{ margin:0 0 14px; color:#fff; font:700 13px/1.4 "Public Sans","Segoe UI",sans-serif; letter-spacing:.08em; text-transform:uppercase; }}
      .site-footer p,.site-footer li {{ color:rgba(255,255,255,.8); font-size:14px; }}
      .site-footer ul {{ margin:0; padding:0; list-style:none; }} .site-footer li+li {{ margin-top:8px; }}
      .site-footer a:hover {{ color:var(--jaune); }}
      .footer-bottom {{ margin-top:44px; padding-top:18px; display:flex; justify-content:space-between; gap:16px; border-top:1px solid rgba(255,255,255,.2); color:rgba(255,255,255,.72); font-size:12px; }}
      @keyframes rise-in {{ from {{ opacity:0; transform:translateY(14px); }} to {{ opacity:1; transform:translateY(0); }} }}
      @media(max-width:1050px) {{ .nav-link {{ padding-inline:8px; font-size:13px; }} .session-label {{ display:none; }} .program-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
      @media(max-width:820px) {{
        .container {{ width:min(var(--contenu),calc(100% - 32px)); }} .utility-inner {{ min-height:34px; font-size:11px; }}
        .header-inner {{ min-height:76px; gap:12px; }} .main-nav {{ display:none; }} .mobile-menu {{ display:block; margin-left:auto; }}
        .nav-actions {{ gap:8px; }} .nav-actions .btn {{ min-height:40px; padding:8px 11px; }}
        .home-hero {{ min-height:450px; }} .home-hero-content {{ padding:58px 0 92px; }}
        .hero-facts {{ left:16px; right:16px; bottom:20px; justify-content:space-between; gap:10px; font-size:10px; }}
        .feature-grid,.story-grid {{ grid-template-columns:1fr; }} .story-grid {{ gap:28px; }}
        .steps-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); row-gap:20px; }} .step-item:nth-child(odd) {{ border-left:0; }}
        .summary-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .footer-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
        .cta-band {{ align-items:flex-start; flex-direction:column; padding:30px 24px; }}
      }}
      @media(max-width:560px) {{
        .container {{ width:calc(100% - 32px); }} .utility-location {{ display:none; }}
        .brand {{ gap:8px; }} .brand-mark {{ width:40px; height:40px; }} .brand-name {{ font-size:19px; }}
        .nav-actions .btn {{ font-size:12px; }} .home-hero {{ min-height:440px; }}
        .home-hero-image {{ object-position:54% center; }} .home-hero:after {{ background:linear-gradient(90deg,rgba(3,63,34,.94),rgba(3,63,34,.57)); }}
        .home-hero h1 {{ font-size:40px; }} .home-hero p {{ font-size:16px; }}
        .section {{ padding:54px 0; }} .program-grid,.feature-grid,.steps-grid,.summary-grid,.footer-grid {{ grid-template-columns:1fr; }}
        .program-item {{ min-height:0; }} .step-item,.step-item:nth-child(odd) {{ border-left:2px solid #c9c7bc; }}
        .step-item:first-child {{ border-left:0; }} .page-shell {{ padding:46px 0 64px; }} .card {{ padding:22px; }}
        .footer-bottom {{ flex-direction:column; }}
      }}
      @media(prefers-reduced-motion:reduce) {{ *,*::before,*::after {{ scroll-behavior:auto!important; animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important; }} }}
    </style>
    <link rel="stylesheet" href="/assets/emsp.css?v=20261006-clarity-4" />
  </head>
  <body>
    <div class="reading-progress" aria-hidden="true"><span data-reading-progress></span></div>
    <div class="page-loading-screen" data-page-loader role="status" aria-live="polite" aria-label="Chargement de la page" aria-hidden="true" hidden>
      <div class="page-loader-card">
        <span class="page-loader-orbit" aria-hidden="true"><img src="/assets/emsp-icon.png" alt="" width="36" height="36" /></span>
        <span class="page-loader-kicker">École Multinationale Supérieure des Postes</span>
        <p class="page-loader-copy" data-page-loader-copy>Préparation de votre espace…</p>
        <span class="page-loader-track" aria-hidden="true"><span></span></span>
        <small class="page-loader-location">Abidjan · Côte d’Ivoire</small>
      </div>
    </div>
    {_nav_html(user, current_path)}
    {content}
    {_footer_html(user)}
    <script>
      document.querySelectorAll('[data-logout]').forEach((button) => {{
        button.addEventListener('click', async () => {{
          if (button.disabled) return;
          const feedback = button.parentElement.querySelector('[data-logout-feedback]');
          button.disabled = true;
          button.setAttribute('aria-busy', 'true');
          try {{
            const response = await fetch('/api/auth/logout', {{ method: 'POST', credentials: 'same-origin' }});
            if (!response.ok) throw new Error('La fermeture de session a échoué.');
            if (window.emspNavigate) window.emspNavigate('/index.html');
            else window.location.assign('/index.html');
          }} catch (_) {{
            if (feedback) {{
              feedback.textContent = 'La fermeture n’a pas abouti. Réessayez.';
              feedback.hidden = false;
            }}
            button.disabled = false;
            button.removeAttribute('aria-busy');
          }}
        }});
      }});
      const sharedRevealTargets = document.querySelectorAll('.page-shell .page-intro, .page-shell .application-heading, .page-shell .application-layout, .page-shell .dashboard-welcome, .page-shell .dashboard-highlight, .page-shell .dashboard-stats > *, .page-shell .dashboard-grid > *, .page-shell .official-documents-heading, .page-shell .official-document-grid > *, .page-shell .tracking-status, .page-shell .tracking-next, .page-shell .convocation-card, .page-shell .result-card, .page-shell .profile-layout > *, .page-shell .upload-list > *, .page-shell .conditions-grid > *, .page-shell .conditions-timeline, .page-shell .contact-copy, .page-shell .contact-form, .page-shell .admin-heading, .page-shell .admin-stats > *, .page-shell .admin-overview-grid > *');
      sharedRevealTargets.forEach((target) => target.setAttribute('data-reveal', ''));
      document.documentElement.classList.add('motion-ready');
      const revealTargets = document.querySelectorAll('[data-reveal]');
      if ('IntersectionObserver' in window) {{
        const revealObserver = new IntersectionObserver((entries, observer) => {{
          entries.forEach((entry) => {{
            if (entry.isIntersecting) {{
              entry.target.classList.add('is-visible');
              observer.unobserve(entry.target);
            }}
          }});
        }}, {{ threshold: 0.14, rootMargin: '0px 0px -36px 0px' }});
        revealTargets.forEach((target) => revealObserver.observe(target));
        const revealReachedContent = () => {{
          const revealLine = window.innerHeight * 0.9;
          revealTargets.forEach((target) => {{
            if (target.getBoundingClientRect().top <= revealLine) {{
              target.classList.add('is-visible');
              revealObserver.unobserve(target);
            }}
          }});
        }};
        window.addEventListener('scroll', revealReachedContent, {{ passive: true }});
        window.addEventListener('resize', revealReachedContent, {{ passive: true }});
        window.requestAnimationFrame(revealReachedContent);
      }} else {{
        revealTargets.forEach((target) => target.classList.add('is-visible'));
      }}
    </script>
    <script src="/assets/emsp.js?v=20261006-clarity-4" defer></script>
  </body>
</html>
""")


def render_public_home(user: User | None) -> HTMLResponse:
    from app.schemas import SPECIALITES

    presentations = {
        "LNUM": ("Organisez les flux, les transports et les chaînes d’approvisionnement.", "Logistique · transport"),
        "FDIG": ("Maîtrisez la comptabilité, la finance d’entreprise et les paiements numériques.", "Finance · paiements"),
        "MDIG": ("Faites dialoguer étude de marché, communication et commerce numérique.", "Marketing · communication"),
        "DSER": ("Concevez des services numériques et accompagnez leur transformation.", "Innovation · conduite du changement"),
        "GARE": ("Comprenez le cadre juridique et la régulation des activités économiques.", "Droit · régulation"),
    }
    program_cards: list[str] = []
    for specialite in SPECIALITES:
        code, nom = (part.strip() for part in specialite.split("—", maxsplit=1))
        description, domaine = presentations[code]
        program_cards.append(
            f'<article class="program-item" data-reveal><div class="program-card-top"><span class="program-code">{escape(code)}</span>'
            f'<span class="program-number">{len(program_cards) + 1:02d}</span></div>'
            f"<h3>{escape(nom)}</h3><p>{escape(description)}</p>"
            f'<span class="program-outcome">{escape(domaine)} <span aria-hidden="true">↗</span></span></article>'
        )
    program_cards_html = "".join(program_cards)
    action = (
        '<a class="btn btn-primary" href="/espace-candidat.html">Accéder à mon espace <span aria-hidden="true">↗</span></a>'
        if user
        else '<a class="btn btn-primary" href="/candidature.html">Commencer ma candidature <span aria-hidden="true">↗</span></a>'
    )
    content = f"""
    <main class="home-page">
      <section class="home-hero" aria-label="Bienvenue à l’École Multinationale Supérieure des Postes">
        <img class="home-hero-image" src="/media/Photo%20de%20Al%C3%A8ve%286%29.jpg" alt="Étudiantes et étudiants réunis dans la cour de l’EMSP à Abidjan" fetchpriority="high" data-parallax="22" />
        <div class="hero-shade" aria-hidden="true"></div>
        <div class="container home-hero-content">
          <span class="kicker hero-kicker"><i aria-hidden="true"></i> Concours d’entrée · Licence 1</span>
          <h1>Le prochain chapitre<br />s’écrit <em>avec vous.</em></h1>
          <p>Une école, huit pays fondateurs et des talents prêts à transformer les services en Afrique de l’Ouest.</p>
          <div class="hero-actions">{action}<a class="hero-secondary" href="#formations">Explorer les formations <span aria-hidden="true">↓</span></a></div>
          <div class="hero-footnote"><span>Formation spécialisée</span><span class="hero-footnote-dot" aria-hidden="true"></span><span>Abidjan, Côte d’Ivoire</span></div>
        </div>
        <aside class="hero-note" aria-label="Repères sur l’EMSP"><span class="hero-note-label">Depuis</span><strong>1970</strong><span>Former, relier,<br />faire avancer.</span></aside>
        <a class="hero-scroll" href="#ecole"><span>Faire défiler</span><i aria-hidden="true"></i></a>
      </section>

      <div class="ticker" role="img" aria-label="Transmission, innovation et engagement régional"><div class="ticker-track" aria-hidden="true"><div class="ticker-group"><span>Transmission</span><b>✳</b><span>Innovation</span><b>✳</b><span>Engagement régional</span><b>✳</b></div><div class="ticker-group"><span>Transmission</span><b>✳</b><span>Innovation</span><b>✳</b><span>Engagement régional</span><b>✳</b></div></div></div>

      <section class="section school-intro" id="ecole"><div class="container intro-grid">
        <div class="intro-copy" data-reveal><span class="kicker">Une école, toute une région</span><h2>Des idées qui voyagent.<br /><em>Des parcours qui comptent.</em></h2><p class="intro-lead">Créée sous l’égide de l’Union Postale Universelle par huit pays d’Afrique de l’Ouest, l’EMSP prépare les professionnels qui feront évoluer la logistique, la finance et les services numériques.</p><a class="text-link" href="/conditions.html">Découvrir le concours <span aria-hidden="true">↗</span></a>
          <div class="school-stats"><div><strong>1970</strong><span>année de fondation</span></div><div><strong>08</strong><span>pays fondateurs</span></div><div><strong>05</strong><span>spécialités</span></div></div>
        </div>
        <div class="intro-visual" data-reveal>
          <div class="intro-photo-main"><img src="/media/IMG-20251206-WA0229%281%29.jpg" alt="La communauté de l’EMSP réunie lors d’une rencontre régionale" loading="lazy" data-parallax="18" /><span class="photo-index">La communauté EMSP · Abidjan</span></div>
          <div class="intro-photo-detail"><img src="/media/Photo%20de%20Al%C3%A8ve%284%29.jpg" alt="Un cours en amphithéâtre à l’EMSP" loading="lazy" data-parallax="24" /></div>
          <span class="visual-stamp" aria-hidden="true">EMSP<br /><b>·</b><br />CI</span>
        </div>
      </div></section>

      <section class="section programs-section" id="formations"><div class="container">
        <div class="section-heading" data-reveal><div><span class="kicker">Formation spécialisée · Licence 1</span><h2>Choisissez votre<br /><em>terrain d’avenir.</em></h2></div><p>Cinq spécialités pour apprendre, entreprendre et accompagner les mutations de nos économies.</p></div>
        <div class="program-grid">{program_cards_html}</div>
        <div class="program-note" data-reveal><span class="program-note-mark" aria-hidden="true">+</span><p>Vous hésitez encore ? <a href="/conditions.html">Consultez les conditions du concours</a> et préparez votre choix.</p></div>
      </div></section>

      <section class="section moments-section" id="experience" aria-labelledby="moments-title"><div class="container">
        <div class="moments-heading" data-reveal><div><span class="kicker">La vie à l’EMSP</span><h2 id="moments-title">L’expérience de l’école<br /><em>se vit en partage.</em></h2></div><p>En cours, au milieu d’une communauté, dans les rencontres qui ouvrent d’autres perspectives.</p></div>
        <div class="moments-grid">
          <figure class="moment-card moment-card-feature" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%287%29.jpg" alt="Les étudiants réunis dans le grand amphithéâtre de l’EMSP" loading="lazy" data-parallax="32" /><figcaption><span>01 <i>·</i> Se rassembler</span><strong>Une même énergie.</strong><b aria-hidden="true">↗</b></figcaption></figure>
          <figure class="moment-card moment-card-class" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%2811%29.jpg" alt="Un cours rassemble les étudiants de l’EMSP dans une salle de classe" loading="lazy" data-parallax="24" /><figcaption><span>02 <i>·</i> Apprendre</span><strong>Faire grandir ses savoirs.</strong><b aria-hidden="true">↗</b></figcaption></figure>
          <figure class="moment-card moment-card-campus" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%285%29.jpg" alt="Échanges autour d’une activité sur le campus de l’EMSP" loading="lazy" data-parallax="20" /><figcaption><span>03 <i>·</i> Se rencontrer</span><strong>Ouvrir le champ des possibles.</strong><b aria-hidden="true">↗</b></figcaption></figure>
        </div>
        <div class="moments-foot" data-reveal><span>Une école vivante, tournée vers l’avenir de la région.</span><a class="text-link" href="#parcours">Découvrir votre parcours <span aria-hidden="true">↓</span></a></div>
      </div></section>

      <section class="journey-section" id="parcours"><div class="container journey-inner">
        <div class="journey-heading" data-reveal><span class="kicker">Simple, étape par étape</span><h2>Votre candidature,<br /><em>en sept mouvements.</em></h2><p>Un dossier clair, un espace personnel et toutes les informations réunies au même endroit.</p><a class="btn btn-light" href="/conditions.html">Voir les conditions <span aria-hidden="true">↗</span></a></div>
        <div class="journey-steps">
          <article class="journey-step" data-reveal><span>01</span><div><h3>Ouvrir un dossier</h3><p>Créez votre compte candidat.</p></div></article>
          <article class="journey-step" data-reveal><span>02</span><div><h3>Renseigner votre identité</h3><p>Complétez vos informations personnelles.</p></div></article>
          <article class="journey-step" data-reveal><span>03</span><div><h3>Présenter votre parcours</h3><p>Ajoutez votre parcours académique.</p></div></article>
          <article class="journey-step" data-reveal><span>04</span><div><h3>Choisir vos spécialités</h3><p>Classez vos vœux de formation.</p></div></article>
          <article class="journey-step" data-reveal><span>05</span><div><h3>Ajouter vos tuteurs</h3><p>Renseignez les contacts demandés.</p></div></article>
          <article class="journey-step" data-reveal><span>06</span><div><h3>Déposer vos pièces</h3><p>Ajoutez les dix pièces justificatives.</p></div></article>
          <article class="journey-step" data-reveal><span>07</span><div><h3>Vérifier et soumettre</h3><p>Relisez votre dossier avant envoi.</p></div></article>
        </div>
      </div><div class="journey-orbit" aria-hidden="true"></div></section>

      <section class="section campus-section"><div class="container campus-grid">
        <div class="campus-image" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%281%29.jpg" alt="Les apprenants accueillent une délégation dans la cour de l’école" loading="lazy" data-parallax="22" /><span class="campus-image-caption">Apprendre ensemble, à Abidjan</span></div>
        <div class="campus-copy" data-reveal><span class="kicker">Au cœur d’Abidjan</span><h2>Un campus qui<br /><em>rassemble les talents.</em></h2><p>À Treichville, les parcours se croisent et les idées circulent. L’EMSP relie les ambitions individuelles aux grands enjeux de la région.</p><div class="campus-detail"><span class="campus-pin" aria-hidden="true">↗</span><div><strong>Treichville · Abidjan</strong><span>Côte d’Ivoire</span></div></div><a class="text-link" href="/contact.html">Nous contacter <span aria-hidden="true">↗</span></a></div>
      </div></section>

      <section class="closing-section"><div class="closing-photo"><img src="/media/IMG-20250705-WA0133.jpg" alt="Étudiantes et étudiants célèbrent un moment de vie à l’EMSP" loading="lazy" /></div><div class="closing-content" data-reveal><span class="kicker">La suite commence maintenant</span><h2>Votre place dans<br />cette histoire <em>est à écrire.</em></h2><p>Découvrez les conditions d’accès et préparez votre dossier de candidature au concours.</p><div class="hero-actions">{action}<a class="hero-secondary" href="/conditions.html">Comprendre le concours <span aria-hidden="true">↗</span></a></div></div></section>
    </main>
    """
    return _page_template("Accueil EMSP", "/index.html", user, content)

DOCUMENT_LABELS = {
    "attestation_bac": "Attestation du baccalauréat",
    "releve_notes_bac": "Relevé de notes du baccalauréat",
    "piece_identite": "Pièce d’identité",
    "bulletins_seconde": "Bulletins de seconde",
    "bulletins_premiere": "Bulletins de première",
    "bulletins_terminale": "Bulletins de terminale",
    "photo_identite": "Photo d’identité",
    "lettre_motivation": "Lettre de motivation",
    "acte_naissance": "Extrait d’acte de naissance",
    "cv": "Curriculum vitæ",
}


def _document_cards() -> str:
    from app.storage_service import TYPES_AUTORISES
    cards = []
    for kind in TYPES_AUTORISES:
        cards.append(
            f'<article class="upload-card" data-document-card="{kind}">'
            '<div class="upload-card-info"><span class="upload-card-check" data-document-check aria-hidden="true">○</span>'
            f'<div><h3>{escape(DOCUMENT_LABELS[kind])}</h3><p data-document-status>À déposer · PDF, JPG ou PNG · 5 Mo maximum</p></div></div>'
            f'<div class="upload-card-actions"><a data-document-download hidden></a>'
            f'<label class="btn btn-outline upload-button">Choisir un fichier<input type="file" data-document-input="{kind}" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" hidden /></label>'
            f'<button class="text-button" type="button" data-document-delete="{kind}" hidden>Retirer</button></div></article>'
        )
    return "".join(cards)


def _specialite_options(include_blank: bool = True) -> str:
    from app.schemas import SPECIALITES
    blank = '<option value="">Choisir une spécialité</option>' if include_blank else ""
    return blank + "".join(f'<option value="{escape(item, quote=True)}">{escape(item)}</option>' for item in SPECIALITES)


def render_login(user: User | None) -> HTMLResponse:
    content = """
    <main class="page-shell"><div class="container auth-layout">
      <section class="auth-panel" data-reveal><span class="kicker">Portail candidat · Administration</span><h1>Ravi de vous retrouver.</h1>
        <p class="lead">Connectez-vous pour reprendre votre dossier ou accéder à votre espace.</p>
        <form class="form-grid" id="login-form" action="/api/auth/login">
          <div class="field"><label for="login-identifier">E-mail ou numéro de dossier</label><input id="login-identifier" name="identifiant" type="text" autocomplete="username" required placeholder="prenom.nom@exemple.ci ou CDT_0001" /><small>Votre numéro de dossier figure dans le courriel de confirmation EMSP.</small></div>
          <div class="field"><label for="password">Mot de passe</label><input id="password" name="password" type="password" autocomplete="current-password" required /></div>
          <p class="auth-forgot"><a href="/mot-de-passe-oublie.html">Mot de passe oublié ?</a></p>
          <p class="form-feedback" id="login-error" role="alert" hidden></p>
          <div class="inline-actions"><button class="btn btn-primary" type="submit">Se connecter <span aria-hidden="true">↗</span></button><a class="btn btn-ghost" href="/index.html">Retour à l’accueil</a></div>
        </form><p class="auth-switch">Vous découvrez l’EMSP ? <a href="/candidature.html">Créer mon dossier candidat</a></p>
      </section>
      <aside class="auth-aside" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%284%29.jpg" alt="Une séance de formation au sein de l’EMSP" loading="lazy" data-parallax="22" /><div><span class="kicker">École Multinationale Supérieure des Postes</span><h2>Les idées prennent forme quand on leur donne un espace.</h2><p>Treichville · Abidjan</p></div></aside>
    </div></main>
    """
    return _page_template("Connexion · EMSP", "/connexion.html", user, content)


def render_password_forgot(user: User | None) -> HTMLResponse:
    content = f"""
    <main class="page-shell"><div class="container auth-layout">
      <section class="auth-panel" data-reveal><span class="kicker">Assistance · accès au compte</span><h1>Retrouvons votre espace.</h1>
        <p class="lead">Indiquez l’adresse e-mail de votre compte. Si elle correspond à un compte EMSP et que la messagerie est activée, vous recevrez un lien personnel valable {settings.PASSWORD_RESET_TTL_MINUTES} minutes.</p>
        <form class="form-grid" data-password-forgot>
          <div class="field"><label for="forgot-email">Adresse e-mail</label><input id="forgot-email" name="email" type="email" autocomplete="email" required placeholder="prenom.nom@exemple.ci" /></div>
          <p class="form-feedback" data-password-forgot-feedback role="status" hidden></p>
          <div class="inline-actions"><button class="btn btn-primary" type="submit">Recevoir un lien <span aria-hidden="true">↗</span></button><a class="btn btn-ghost" href="/connexion.html">Retour à la connexion</a></div>
        </form>
        <p class="auth-note"><span aria-hidden="true">✳</span> Pour protéger votre compte, la page ne confirme jamais si une adresse e-mail est enregistrée.</p>
      </section>
      <aside class="auth-aside" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%284%29.jpg" alt="Une séance de formation au sein de l’EMSP" loading="lazy" data-parallax="22" /><div><span class="kicker">Votre parcours continue</span><h2>Retrouvez les étapes de votre candidature, en toute sécurité.</h2><p>Treichville · Abidjan</p></div></aside>
    </div></main>
    """
    return _page_template("Mot de passe oublié · EMSP", "/mot-de-passe-oublie.html", user, content)


def render_password_reset(user: User | None, token: str = "") -> HTMLResponse:
    token_value = escape(token, quote=True)
    content = f"""
    <main class="page-shell"><div class="container auth-layout">
      <section class="auth-panel" data-reveal><span class="kicker">Sécurité du compte</span><h1>Choisissez un nouveau mot de passe.</h1>
        <p class="lead">Utilisez au moins 8 caractères. Le lien reçu par e-mail ne peut être utilisé qu’une fois.</p>
        <form class="form-grid" data-password-reset>
          <input type="hidden" name="token" value="{token_value}" />
          <div class="field"><label for="reset-password">Nouveau mot de passe</label><input id="reset-password" name="new_password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required /><small>8 caractères minimum.</small></div>
          <div class="field"><label for="reset-confirmation">Confirmer le mot de passe</label><input id="reset-confirmation" name="confirmation" type="password" minlength="8" maxlength="128" autocomplete="new-password" required /></div>
          <p class="form-feedback" data-password-reset-feedback role="status" hidden></p>
          <button class="btn btn-primary" type="submit">Enregistrer mon mot de passe <span aria-hidden="true">↗</span></button>
        </form>
        <p class="auth-switch">Vous préférez ? <a href="/connexion.html">Retourner à la connexion</a></p>
      </section>
      <aside class="auth-aside" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%286%29.jpg" alt="La communauté étudiante réunie dans la cour de l’EMSP" loading="lazy" data-parallax="22" /><div><span class="kicker">Compte protégé</span><h2>Un nouveau mot de passe et vous voilà de retour.</h2><p>École Multinationale Supérieure des Postes</p></div></aside>
    </div></main>
    """
    return _page_template("Nouveau mot de passe · EMSP", "/reinitialiser-mot-de-passe.html", user, content)


def render_candidature(user: User | None) -> HTMLResponse:
    if user is None:
        content = """
        <main class="page-shell"><div class="container auth-layout">
          <section class="auth-panel" data-reveal><span class="kicker">Concours d’entrée · Licence 1</span><h1>Ouvrez votre dossier.</h1>
            <p class="lead">Créez votre accès personnel. Vous pourrez compléter votre candidature en plusieurs fois.</p>
            <form class="form-grid" id="register-form" data-auth-form="register">
              <div class="field-row"><div class="field"><label for="register-nom">Nom</label><input id="register-nom" name="nom" autocomplete="family-name" required /></div><div class="field"><label for="register-prenoms">Prénoms</label><input id="register-prenoms" name="prenoms" autocomplete="given-name" required /></div></div>
              <div class="field"><label for="register-email">Adresse e-mail</label><input id="register-email" name="email" type="email" autocomplete="email" required placeholder="prenom.nom@exemple.ci" /></div>
              <div class="field"><label for="register-password">Mot de passe</label><input id="register-password" name="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required /><small>8 caractères minimum.</small></div>
              <div class="field"><label for="register-confirmation">Confirmer le mot de passe</label><input id="register-confirmation" name="confirmation" type="password" minlength="8" maxlength="128" autocomplete="new-password" required /></div>
              <p class="auth-note"><span aria-hidden="true">✳</span> Un courriel d’accueil vous donnera votre numéro de dossier et le lien pour reprendre votre candidature, si la messagerie EMSP est activée.</p>
              <p class="form-feedback" data-form-feedback role="alert" hidden></p><button class="btn btn-primary" type="submit">Créer mon dossier <span aria-hidden="true">↗</span></button>
            </form><p class="auth-switch">Vous avez déjà un compte ? <a href="/connexion.html">Se connecter</a></p>
          </section><aside class="auth-aside" data-reveal><img src="/media/Photo%20de%20Al%C3%A8ve%286%29.jpg" alt="La communauté étudiante réunie dans la cour de l’EMSP" loading="lazy" data-parallax="22" /><div><span class="kicker">Un premier pas vers votre projet</span><h2>Votre ambition a sa place ici.</h2><p>Le dossier peut être enregistré et repris plus tard.</p></div></aside>
        </div></main>
        """
        return _page_template("Candidater · EMSP", "/candidature.html", user, content)
    if (user.role or "CANDIDAT").upper() == "ADMIN":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin.html", status_code=302)
    from app.schemas import SERIES_ADMISES
    series = "".join(f'<option value="{s}">{s}</option>' for s in SERIES_ADMISES)
    content = f"""
    <main class="page-shell application-page" data-portal-view="application"><div class="container">
      <div class="application-heading"><div><span class="kicker">Votre espace candidat</span><h1>Ma candidature</h1><p>Vos informations sont enregistrées au fil des étapes. Vous pouvez quitter et reprendre plus tard.</p></div><div class="application-reference"><span>Numéro de dossier</span><strong data-dossier-number>Chargement…</strong></div></div>
      <div class="application-layout"><aside class="application-sidebar"><div class="progress-label"><span>Progression</span><strong data-progress-label aria-live="polite" aria-atomic="true">Étape 1 sur 7</strong></div><div class="progress-track"><span data-progress-bar></span></div>
        <nav class="application-step-nav" aria-label="Étapes de candidature"><button type="button" class="application-step-link is-current" data-step-link="1"><span>01</span>Informations personnelles</button><button type="button" class="application-step-link" data-step-link="2"><span>02</span>Parcours académique</button><button type="button" class="application-step-link" data-step-link="3"><span>03</span>Choix de formation</button><button type="button" class="application-step-link" data-step-link="4"><span>04</span>Tuteurs</button><button type="button" class="application-step-link" data-step-link="5"><span>05</span>Pièces justificatives</button><button type="button" class="application-step-link" data-step-link="6"><span>06</span>Vérification</button><button type="button" class="application-step-link" data-step-link="7"><span>07</span>Soumission</button></nav>
        <div class="sidebar-help"><span class="sidebar-help-icon" aria-hidden="true">?</span><div><strong>Besoin d’aide ?</strong><a href="/contact.html">Contacter l’équipe EMSP</a></div></div></aside>
        <section class="application-main"><div class="form-feedback" data-application-feedback role="status" hidden></div><form id="application-form" novalidate>
          <section class="application-panel" data-step-panel="1"><div class="panel-heading"><span class="kicker">Étape 01 · Votre identité</span><h2 tabindex="-1">Parlez-nous de vous.</h2><p>Renseignez vos informations telles qu’elles figurent sur vos documents.</p></div><div class="form-grid form-grid-two">
            <div class="field"><label for="nom">Nom</label><input id="nom" name="nom" autocomplete="family-name" /></div><div class="field"><label for="prenoms">Prénoms</label><input id="prenoms" name="prenoms" autocomplete="given-name" /></div>
            <div class="field"><label for="sexe">Sexe</label><select id="sexe" name="sexe"><option value="">Choisir</option><option>Féminin</option><option>Masculin</option></select></div><div class="field"><label for="date_naissance">Date de naissance</label><input id="date_naissance" name="date_naissance" type="date" /></div>
            <div class="field"><label for="lieu_naissance">Lieu de naissance</label><input id="lieu_naissance" name="lieu_naissance" /></div><div class="field"><label for="nationalite">Nationalité</label><input id="nationalite" name="nationalite" /></div>
            <div class="field"><label for="nature_piece">Pièce d’identité</label><select id="nature_piece" name="nature_piece"><option value="">Choisir un document</option><option>CNI</option><option>Attestation d'identité</option><option>Passeport</option><option>Carte consulaire</option></select></div><div class="field"><label for="numero_piece">Numéro de pièce</label><input id="numero_piece" name="numero_piece" /></div>
            <div class="field"><label for="email">Adresse e-mail</label><input id="email" name="email" type="email" autocomplete="email" /></div><div class="field"><label for="telephone">Téléphone</label><input id="telephone" name="telephone" type="tel" autocomplete="tel" /></div>
            <div class="field"><label for="commune">Commune</label><input id="commune" name="commune" /></div><div class="field"><label for="ville">Ville</label><input id="ville" name="ville" /></div>
            <div class="field field-full"><label for="adresse">Adresse de résidence</label><input id="adresse" name="adresse" autocomplete="street-address" /></div><div class="field field-full"><label for="code_tresor_pay">Code TrésorPay <span class="optional-label">Facultatif</span></label><input id="code_tresor_pay" name="code_tresor_pay" /></div>
          </div></section>
          <section class="application-panel" data-step-panel="2" hidden><div class="panel-heading"><span class="kicker">Étape 02 · Votre parcours</span><h2 tabindex="-1">Le chemin déjà parcouru.</h2><p>Indiquez les références de votre baccalauréat et vos résultats.</p></div><div class="form-grid form-grid-two">
            <div class="field"><label for="annee_bac">Année d’obtention</label><input id="annee_bac" name="annee_bac" type="number" min="1970" max="2100" /></div><div class="field"><label for="serie_bac">Série</label><select id="serie_bac" name="serie_bac"><option value="">Choisir une série</option>{series}</select></div>
            <div class="field"><label for="numero_bac">Numéro du baccalauréat</label><input id="numero_bac" name="numero_bac" /></div><div class="field"><label for="numero_table">Numéro de table</label><input id="numero_table" name="numero_table" /></div>
            <div class="field"><label for="mention">Mention</label><select id="mention" name="mention"><option value="">Choisir une mention</option><option>Passable</option><option>Assez Bien</option><option>Bien</option><option>Très Bien</option><option>Excellent</option></select></div><div class="field"><label for="moyenne_bac">Moyenne au bac / 20</label><input id="moyenne_bac" name="moyenne_bac" type="number" min="0" max="20" step="0.01" /></div>
            <div class="field"><label for="note_math_bac">Mathématiques / 20</label><input id="note_math_bac" name="note_math_bac" type="number" min="0" max="20" step="0.01" /></div><div class="field"><label for="note_physique_bac">Physique / 20</label><input id="note_physique_bac" name="note_physique_bac" type="number" min="0" max="20" step="0.01" /></div><div class="field"><label for="note_francais_bac">Français / 20</label><input id="note_francais_bac" name="note_francais_bac" type="number" min="0" max="20" step="0.01" /></div><div class="field"><label for="note_anglais_bac">Anglais / 20</label><input id="note_anglais_bac" name="note_anglais_bac" type="number" min="0" max="20" step="0.01" /></div>
          </div></section>
          <section class="application-panel" data-step-panel="3" hidden><div class="panel-heading"><span class="kicker">Étape 03 · Vos choix</span><h2 tabindex="-1">Où souhaitez-vous aller ?</h2><p>Classez une ou deux spécialités par ordre de préférence.</p></div><div class="form-grid form-grid-two"><div class="field"><label for="choix_1_filiere">Premier choix</label><select id="choix_1_filiere" name="choix_1_filiere">{_specialite_options()}</select></div><div class="field"><label for="choix_2_filiere">Deuxième choix <span class="optional-label">Facultatif</span></label><select id="choix_2_filiere" name="choix_2_filiere">{_specialite_options()}</select></div></div><p class="help-card">Les deux choix doivent être différents. <a href="/conditions.html#specialites">Comparer les spécialités</a></p></section>
          <section class="application-panel" data-step-panel="4" hidden><div class="panel-heading"><span class="kicker">Étape 04 · Vos tuteurs</span><h2 tabindex="-1">Vos personnes ressources.</h2><p>Renseignez au moins un tuteur. Le second contact reste facultatif.</p></div><h3 class="subsection-title">Tuteur principal</h3><div class="form-grid form-grid-two"><div class="field"><label for="tuteur1_nom">Nom et prénoms</label><input id="tuteur1_nom" name="tuteur1_nom" /></div><div class="field"><label for="tuteur1_contact">Téléphone</label><input id="tuteur1_contact" name="tuteur1_contact" type="tel" /></div><div class="field"><label for="tuteur1_lien">Lien avec le candidat</label><select id="tuteur1_lien" name="tuteur1_lien"><option value="">Choisir</option><option>Père</option><option>Mère</option><option>Tuteur</option><option>Autre</option></select></div><div class="field"><label for="tuteur1_residence">Lieu de résidence</label><input id="tuteur1_residence" name="tuteur1_residence" /></div></div><h3 class="subsection-title subsection-optional">Second tuteur <span class="optional-label">Facultatif</span></h3><div class="form-grid form-grid-two"><div class="field"><label for="tuteur2_nom">Nom et prénoms</label><input id="tuteur2_nom" name="tuteur2_nom" /></div><div class="field"><label for="tuteur2_contact">Téléphone</label><input id="tuteur2_contact" name="tuteur2_contact" type="tel" /></div><div class="field"><label for="tuteur2_lien">Lien avec le candidat</label><select id="tuteur2_lien" name="tuteur2_lien"><option value="">Choisir</option><option>Père</option><option>Mère</option><option>Tuteur</option><option>Autre</option></select></div><div class="field"><label for="tuteur2_residence">Lieu de résidence</label><input id="tuteur2_residence" name="tuteur2_residence" /></div></div></section>
          <section class="application-panel" data-step-panel="5" hidden><div class="panel-heading"><span class="kicker">Étape 05 · Vos pièces</span><h2 tabindex="-1">Les documents à réunir.</h2><p>Déposez les dix pièces justificatives. PDF, JPG ou PNG, 5 Mo maximum par fichier.</p></div><div class="upload-list" data-document-list>{_document_cards()}</div></section>
          <section class="application-panel" data-step-panel="6" hidden><div class="panel-heading"><span class="kicker">Étape 06 · Relecture</span><h2 tabindex="-1">Un dernier regard.</h2><p>Vérifiez vos informations et revenez modifier une étape si nécessaire.</p></div><div class="review-list" data-application-review></div><div class="review-documents" data-review-documents></div></section>
          <section class="application-panel" data-step-panel="7" hidden><div class="panel-heading"><span class="kicker">Étape 07 · Envoi au jury</span><h2 tabindex="-1">Prêt à transmettre ?</h2><p>Après soumission, votre dossier ne pourra plus être modifié.</p></div><label class="check-card"><input type="checkbox" name="confirmation" data-submit-confirmation /><span><strong>Je certifie l’exactitude des informations.</strong><small>Je confirme que les renseignements et documents transmis sont conformes.</small></span></label><label class="check-card check-card-secondary"><input type="checkbox" name="consentement_tiers" data-submit-consent /><span><strong>J’accepte l’analyse assistée des pièces.</strong><small>Ce consentement est facultatif et ne conditionne pas l’envoi de ma candidature.</small></span></label><div class="alert info" data-submit-readiness>Vérifiez que les étapes 1 à 4 sont renseignées et que les 10 pièces sont déposées.</div><button class="btn btn-primary" type="button" data-submit-application>Soumettre mon dossier <span aria-hidden="true">↗</span></button></section>
          <div class="application-footer"><button class="btn btn-ghost" type="button" data-step-back>← Précédent</button><span data-save-indicator role="status" aria-live="polite">Enregistrement automatique à chaque étape</span><button class="btn btn-primary" type="button" data-step-next>Enregistrer et continuer <span aria-hidden="true">→</span></button></div>
        </form></section></div></div></main>
    """
    return _page_template("Ma candidature · EMSP", "/candidature.html", user, content)


def render_dashboard(user: User | None) -> HTMLResponse:
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/connexion.html?next=/espace-candidat.html", status_code=302)
    if (user.role or "CANDIDAT").upper() == "ADMIN":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin.html", status_code=302)
    content = """
    <main class="page-shell" data-portal-view="dashboard"><div class="container"><div class="dashboard-welcome"><div><span class="kicker">Votre espace personnel</span><h1>Bienvenue<span data-candidate-name></span>.</h1><p>Retrouvez ici votre numéro de dossier et la prochaine étape de votre parcours.</p></div><a class="btn btn-primary" href="/candidature.html">Reprendre ma candidature <span aria-hidden="true">↗</span></a></div>
      <section class="dashboard-highlight" data-parallax="14"><div><span class="kicker">Concours d’entrée · Licence 1</span><h2 data-dashboard-status>Chargement de votre dossier…</h2><p data-dashboard-summary></p></div><div class="dashboard-progress"><span>Progression du dossier</span><strong data-dashboard-progress>—</strong><div class="progress-track"><span data-dashboard-progress-bar></span></div><small data-dashboard-stage></small></div></section>
      <div class="dashboard-stats"><article class="stat-box"><strong data-dashboard-number>—</strong><span>Numéro de dossier</span></article><article class="stat-box"><strong data-dashboard-documents>—</strong><span>Pièces déposées sur 10</span></article><article class="stat-box"><strong data-dashboard-step>—</strong><span>Étape en cours</span></article></div>
      <div class="dashboard-grid"><a class="dashboard-card" href="/candidature.html"><span>01</span><h3>Compléter mon dossier</h3><p>Renseigner mes informations et mes choix de formation.</p><b>Continuer →</b></a><a class="dashboard-card" href="/pieces.html"><span>02</span><h3>Mes pièces justificatives</h3><p>Déposer, remplacer ou retirer un document.</p><b>Gérer mes pièces →</b></a><a class="dashboard-card" href="/suivi.html"><span>03</span><h3>Suivre mon dossier</h3><p>Consulter l’état actuel du traitement.</p><b>Voir le suivi →</b></a></div>
      <section class="official-documents" aria-labelledby="official-documents-title"><div class="official-documents-heading"><div><span class="kicker">Mes documents officiels</span><h2 id="official-documents-title">Les prochaines étapes, en clair.</h2></div><span class="official-documents-mark" aria-hidden="true">EMSP</span></div><div class="official-document-grid"><article class="official-document-card"><span class="official-document-index">01 · CONCOURS</span><h3 data-dashboard-convocation-title>Convocation à venir</h3><p data-dashboard-convocation-copy>Le centre, la date et l’horaire apparaîtront ici dès leur programmation.</p><a data-dashboard-convocation-link href="/convocation.html" hidden>Consulter ma convocation <span aria-hidden="true">↗</span></a></article><article class="official-document-card official-document-card-result"><span class="official-document-index">02 · DÉLIBÉRATION</span><h3 data-dashboard-result-title>Résultat du jury</h3><p data-dashboard-result-copy>Votre décision sera publiée dans cet espace personnel.</p><a data-dashboard-result-link href="/resultat.html" hidden>Consulter mon résultat <span aria-hidden="true">↗</span></a></article></div></section></div></main>
    """
    return _page_template("Mon espace candidat · EMSP", "/espace-candidat.html", user, content)


def render_admin(user: User | None) -> HTMLResponse:
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/connexion.html?next=/admin.html", status_code=302)
    if (user.role or "CANDIDAT").upper() != "ADMIN":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/espace-candidat.html", status_code=302)
    content = f"""
    <main class="page-shell admin-page" data-portal-view="admin"><div class="container"><div class="admin-heading"><div><span class="kicker">Espace administration · Gestion complète</span><h1>Centre de gestion EMSP</h1><p>Suivez les candidatures, vérifiez les pièces, publiez les décisions et convocations, traitez les messages et gérez les comptes de l’équipe.</p></div><div class="admin-user"><span class="admin-avatar">EM</span><span data-admin-email>Administration</span></div></div>
      <nav class="admin-tabs" aria-label="Sections administration"><button class="is-active" type="button" data-admin-tab="overview">Vue d’ensemble</button><button type="button" data-admin-tab="applications">Candidatures</button><button type="button" data-admin-tab="messages">Messages</button><button type="button" data-admin-tab="accounts">Comptes</button></nav><div class="form-feedback" data-admin-feedback role="status" hidden></div>
      <section class="admin-panel" data-admin-panel="overview"><div class="admin-stats"><article class="stat-box"><span>Dossiers au total</span><strong data-admin-total>—</strong><small>toutes étapes confondues</small></article><article class="stat-box"><span>Dossiers soumis</span><strong data-admin-submitted>—</strong><small>transmis au jury</small></article><article class="stat-box"><span>Pièces déposées</span><strong data-admin-documents>—</strong><small>documents reçus</small></article><article class="stat-box"><span>Messages à traiter</span><strong data-admin-unread>—</strong><small>nouvelles demandes</small></article></div><div class="admin-shortcuts" aria-label="Accès rapide à la gestion"><button class="admin-shortcut" type="button" data-admin-shortcut="applications"><span class="admin-shortcut-kicker">01 · DOSSIERS</span><strong>Traiter les candidatures</strong><span>Recherche, pièces, décisions et convocations</span><b aria-hidden="true">↗</b></button><button class="admin-shortcut" type="button" data-admin-shortcut="messages"><span class="admin-shortcut-kicker">02 · CONTACT</span><strong>Gérer les messages</strong><span>Consulter les demandes et suivre leur traitement</span><b aria-hidden="true">↗</b></button><button class="admin-shortcut" type="button" data-admin-shortcut="accounts"><span class="admin-shortcut-kicker">03 · ÉQUIPE</span><strong>Gérer les comptes</strong><span>Créer et consulter les accès de l’équipe</span><b aria-hidden="true">↗</b></button></div><div class="admin-overview-grid"><section class="card"><div class="panel-inline-heading"><div><span class="kicker">Concours</span><h2>Répartition des dossiers</h2></div><button class="text-button" type="button" data-admin-refresh>Actualiser ↻</button></div><div class="status-breakdown" data-admin-breakdown></div></section><section class="card"><span class="kicker">Journal d’activité</span><h2>Dernières actions</h2><div class="activity-list" data-admin-activity></div></section></div></section>
      <section class="admin-panel" data-admin-panel="applications" hidden><div class="panel-inline-heading"><div><span class="kicker">Concours d’entrée</span><h2>Candidatures</h2></div><span data-admin-result-count></span></div><form class="admin-filters" data-admin-filter><div class="field"><label for="admin-search">Rechercher un dossier</label><input id="admin-search" name="q" type="search" placeholder="N° de dossier, nom ou e-mail" /></div><div class="field"><label for="admin-status">Statut</label><select id="admin-status" name="statut"><option value="">Tous les statuts</option><option value="DRAFT">Brouillon</option><option value="SUBMITTED">Dossier soumis</option><option value="UNDER_REVIEW">En cours d’examen</option><option value="VALIDATED">Dossier validé</option><option value="RETAINED">Dossier retenu</option><option value="COMPOSITION_SCHEDULED">Composition programmée</option><option value="ADMITTED">Admis</option><option value="REJECTED">Non retenu</option></select></div><button class="btn btn-primary" type="submit">Filtrer</button></form><div class="table-scroll"><table class="data-table"><thead><tr><th>Dossier</th><th>Candidat</th><th>Formation</th><th>Pièces</th><th>Statut</th><th></th></tr></thead><tbody data-admin-results><tr><td colspan="6">Chargement des dossiers…</td></tr></tbody></table></div><nav class="pagination" data-admin-pagination></nav>
        <section class="admin-detail card" data-admin-detail hidden><div class="panel-inline-heading"><div><span class="kicker">Fiche candidat</span><h2 data-detail-title>Dossier</h2></div><button type="button" class="text-button" data-detail-close>Fermer ×</button></div><div class="detail-overview" data-detail-summary></div><div class="detail-documents" data-detail-documents></div><div class="detail-verification" data-detail-verification></div><form class="decision-form" data-decision-form><h3>Décision et convocation</h3><div class="form-grid form-grid-two"><div class="field"><label for="decision-status">Statut</label><select id="decision-status" name="statut"><option value="DRAFT">Brouillon</option><option value="SUBMITTED">Dossier soumis</option><option value="UNDER_REVIEW">En cours d’examen</option><option value="VALIDATED">Dossier validé</option><option value="RETAINED">Dossier retenu</option><option value="COMPOSITION_SCHEDULED">Composition programmée</option><option value="ADMITTED">Admis</option><option value="REJECTED">Non retenu</option></select></div><div class="field"><label for="decision-filiere">Filière retenue</label><select id="decision-filiere" name="filiere_formation">{_specialite_options()}</select></div><div class="field"><label for="decision-date">Date de composition</label><input id="decision-date" type="date" name="date_compo" /></div><div class="field"><label for="decision-time">Heure de composition</label><input id="decision-time" type="time" name="heure_compo" /></div><div class="field field-full"><label for="decision-centre">Centre de composition</label><input id="decision-centre" name="centre_compo" /></div><div class="field field-full"><label for="decision-note">Note interne</label><textarea id="decision-note" name="note_interne" rows="3"></textarea></div><div class="field"><label for="decision-fr">Français</label><input id="decision-fr" name="note_francais_compo" type="number" min="0" max="20" step="0.01" /></div><div class="field"><label for="decision-math">Mathématiques</label><input id="decision-math" name="note_math_compo" type="number" min="0" max="20" step="0.01" /></div><div class="field"><label for="decision-en">Anglais</label><input id="decision-en" name="note_anglais_compo" type="number" min="0" max="20" step="0.01" /></div><div class="field"><label for="decision-psy">Psychotechnique</label><input id="decision-psy" name="note_psycho_compo" type="number" min="0" max="20" step="0.01" /></div><div class="field field-full"><label for="decision-comment">Commentaire pour l’historique</label><textarea id="decision-comment" name="commentaire" rows="2"></textarea></div><div class="field field-full"><label for="decision-reason">Motif interne de refus <span class="optional-label">Visible administration seulement</span></label><textarea id="decision-reason" name="motif_refus" rows="2"></textarea></div></div><div class="inline-actions"><button class="btn btn-primary" type="submit">Enregistrer la décision</button></div></form><p class="document-generation-note">La convocation PDF est générée depuis ces informations. Vous pouvez aussi déposer un PDF signé et tamponné qui remplacera la version générée.</p><form class="convocation-upload" data-convocation-form><label class="field"><span>Déposer le PDF signé de la convocation (facultatif)</span><input type="file" name="file" accept="application/pdf,.pdf" required /></label><button class="btn btn-outline" type="submit">Déposer le PDF</button></form></section></section>
      <section class="admin-panel" data-admin-panel="messages" hidden><div class="panel-inline-heading"><div><span class="kicker">Service candidats</span><h2>Messages reçus</h2></div><select data-message-filter aria-label="Filtrer les messages"><option value="">Tous</option><option value="NOUVEAU">Nouveaux</option><option value="EN_COURS">En cours</option><option value="TRAITE">Traités</option><option value="ARCHIVE">Archivés</option></select></div><div class="message-list" data-admin-messages></div></section>
      <section class="admin-panel" data-admin-panel="accounts" hidden><div class="panel-inline-heading"><div><span class="kicker">Accès de l’équipe</span><h2>Comptes administration</h2></div></div><div class="account-layout"><form class="card form-grid" data-create-admin><h3>Créer un compte administrateur</h3><div class="field"><label for="admin-account-name">Nom affiché</label><input id="admin-account-name" name="nom_affiche" required /></div><div class="field"><label for="admin-account-email">Adresse e-mail</label><input id="admin-account-email" name="email" type="email" required /></div><div class="field"><label for="admin-account-password">Mot de passe temporaire</label><input id="admin-account-password" name="password" type="password" minlength="8" required /></div><button class="btn btn-primary" type="submit">Créer le compte</button></form><section class="card"><h3>Comptes enregistrés</h3><div class="account-list" data-admin-accounts></div></section></div></section>
    </div></main>
    """
    return _page_template("Administration · EMSP", "/admin.html", user, content)


def render_conditions(user: User | None) -> HTMLResponse:
    from app.schemas import SERIES_ADMISES, SPECIALITES
    from app.storage_service import TYPES_AUTORISES
    descriptions = {"LNUM": "Logistique, transport et entreposage", "FDIG": "Comptabilité, finance d’entreprise et paiements numériques", "MDIG": "Étude de marché, communication et commerce numérique", "DSER": "Conception de services numériques et conduite du changement", "GARE": "Cadre juridique et régulation des activités économiques"}
    specialties = "".join(f'<article class="condition-specialty"><span>{escape(item.split("—", 1)[0].strip())}</span><div><h3>{escape(item.split("—", 1)[1].strip())}</h3><p>{escape(descriptions[item.split("—", 1)[0].strip()])}</p></div></article>' for item in SPECIALITES)
    documents = "".join(f'<li>{escape(DOCUMENT_LABELS[kind])}</li>' for kind in TYPES_AUTORISES)
    series = " · ".join(escape(s) for s in SERIES_ADMISES)
    content = f"""
    <main class="page-shell conditions-page"><div class="container"><div class="page-intro"><span class="kicker">Concours d’entrée · Licence 1</span><h1>Tout ce qu’il faut<br /><em>savoir avant de candidater.</em></h1><p>Retrouvez les conditions, les séries admises et les pièces à préparer pour la Formation Spécialisée.</p></div>
      <div class="conditions-grid"><article class="condition-card condition-card-feature"><span class="kicker">Votre admission</span><h2>Un concours pour rejoindre la formation spécialisée.</h2><p>L’entrée en Licence 1 se fait par concours. Votre dossier est transmis au jury une fois les étapes complétées et les pièces requises déposées.</p><a class="btn btn-primary" href="/candidature.html">Ouvrir mon dossier <span aria-hidden="true">↗</span></a></article><article class="condition-card"><span class="condition-index">01</span><h3>Séries de baccalauréat</h3><p>Sont admises les séries :</p><strong class="series-list">{series}</strong></article><article class="condition-card"><span class="condition-index">02</span><h3>Dossier complet</h3><p>Préparez les dix pièces justificatives avant la soumission.</p><ul class="document-checklist">{documents}</ul></article></div>
      <section class="conditions-specialties" id="specialites"><div class="panel-inline-heading"><div><span class="kicker">Formation spécialisée</span><h2>Les cinq spécialités du concours</h2></div></div><div class="condition-specialty-list">{specialties}</div></section><section class="conditions-timeline"><span class="kicker">Votre parcours</span><h2>De la candidature au résultat.</h2><div class="conditions-flow"><span>Créer un dossier</span><b>→</b><span>Renseigner les 7 étapes</span><b>→</b><span>Soumettre au jury</span><b>→</b><span>Suivre la décision</span></div></section><p class="conditions-help">Une question ? <a href="/contact.html">Écrivez à l’équipe EMSP</a>.</p></div></main>
    """
    return _page_template("Conditions du concours · EMSP", "/conditions.html", user, content)


def render_contact(user: User | None) -> HTMLResponse:
    content = """
    <main class="page-shell contact-page"><div class="container"><div class="contact-layout"><section class="contact-copy"><span class="kicker">Nous sommes à votre écoute</span><h1>Une question ?<br /><em>Parlons-en.</em></h1><p>Écrivez à l’équipe de l’EMSP pour toute question concernant les candidatures, les documents ou le concours.</p><div class="contact-address"><span class="contact-icon" aria-hidden="true">↗</span><div><strong>Treichville · Abidjan</strong><span>Côte d’Ivoire</span></div></div><div class="contact-address"><span class="contact-icon" aria-hidden="true">@</span><div><strong>contact@emsp.ci</strong><span>Équipe du portail candidat</span></div></div></section><form class="contact-form card" data-contact-form><span class="kicker">Formulaire de contact</span><h2>Envoyer un message</h2><div class="form-grid form-grid-two"><div class="field"><label for="contact-nom">Nom et prénoms</label><input id="contact-nom" name="nom" required /></div><div class="field"><label for="contact-email">Adresse e-mail</label><input id="contact-email" name="email" type="email" required /></div><div class="field"><label for="contact-tel">Téléphone <span class="optional-label">Facultatif</span></label><input id="contact-tel" name="telephone" type="tel" /></div><div class="field"><label for="contact-objet">Objet</label><select id="contact-objet" name="objet" required><option value="">Choisir un sujet</option><option>Candidature</option><option>Inscription</option><option>Documents</option><option>Admission</option></select></div><div class="field field-full"><label for="contact-message">Votre message</label><textarea id="contact-message" name="message" rows="5" minlength="10" required placeholder="Décrivez votre demande en quelques mots…"></textarea></div></div><p class="form-feedback" data-contact-feedback role="status" hidden></p><button class="btn btn-primary" type="submit">Envoyer le message <span aria-hidden="true">↗</span></button></form></div></div></main>
    """
    return _page_template("Contact · EMSP", "/contact.html", user, content)


def render_profils(user: User | None) -> HTMLResponse:
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/connexion.html?next=/profil.html", status_code=302)
    content = """
    <main class="page-shell" data-portal-view="profile"><div class="container"><div class="page-intro"><span class="kicker">Espace personnel</span><h1>Mon profil.</h1><p>Vos informations de connexion et les réglages de sécurité de votre compte.</p></div>
      <div class="profile-layout"><section class="card profile-card"><div class="profile-avatar" data-profile-initials>EM</div><div class="profile-details"><span class="kicker">Compte actif</span><h2 data-profile-name>Chargement…</h2><dl><div><dt>Adresse e-mail</dt><dd data-profile-email>—</dd></div><div><dt>Rôle</dt><dd data-profile-role>—</dd></div><div data-profile-dossier-row><dt>Numéro de dossier</dt><dd data-profile-dossier>—</dd></div></dl></div></section>
        <section class="card profile-security"><span class="kicker">Sessions ouvertes</span><h2>Gardez le contrôle.</h2><p>Fermez toutes les sessions de votre compte sur les autres appareils.</p><button class="btn btn-outline" type="button" data-logout-all>Fermer toutes les sessions</button><p class="form-feedback" data-profile-feedback role="status" hidden></p></section></div>
      <section class="card profile-password-panel" data-reveal><div><span class="kicker">Sécurité du compte</span><h2>Modifier mon mot de passe.</h2><p>Nous vérifions votre mot de passe actuel avant chaque changement. Un e-mail de confirmation suivra si la messagerie EMSP est activée.</p></div>
        <form class="profile-password-form" data-password-change><div class="field"><label for="current-password">Mot de passe actuel</label><input id="current-password" name="current_password" type="password" autocomplete="current-password" required /></div><div class="field"><label for="new-password">Nouveau mot de passe</label><input id="new-password" name="new_password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required /><small>8 caractères minimum.</small></div><div class="field"><label for="new-password-confirmation">Confirmer le nouveau mot de passe</label><input id="new-password-confirmation" name="confirmation" type="password" minlength="8" maxlength="128" autocomplete="new-password" required /></div>
          <p class="form-feedback" data-password-change-feedback role="status" hidden></p><button class="btn btn-primary" type="submit">Mettre à jour mon mot de passe <span aria-hidden="true">↗</span></button></form>
      </section></div></main>
    """
    return _page_template("Mon profil · EMSP", "/profil.html", user, content)


def render_pieces(user: User | None) -> HTMLResponse:
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/connexion.html?next=/pieces.html", status_code=302)
    if (user.role or "CANDIDAT").upper() == "ADMIN":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin.html", status_code=302)
    content = f"""
    <main class="page-shell" data-portal-view="documents"><div class="container"><div class="page-intro"><span class="kicker">Mon dossier · Pièces justificatives</span><h1>Les documents<br /><em>de ma candidature.</em></h1><p>Déposez les pièces demandées et vérifiez leur état. Un nouveau fichier remplace le précédent du même type.</p></div><div class="document-progress"><strong data-documents-progress>Chargement…</strong><span>pièces déposées sur 10</span><div class="progress-track"><span data-documents-progress-bar></span></div></div><div class="upload-list" data-document-list>{_document_cards()}</div><p class="form-feedback" data-documents-feedback role="status" hidden></p><div class="page-bottom-actions"><a class="btn btn-ghost" href="/candidature.html">Retour à ma candidature</a></div></div></main>
    """
    return _page_template("Mes pièces · EMSP", "/pieces.html", user, content)


def render_suivi(user: User | None) -> HTMLResponse:
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/connexion.html?next=/suivi.html", status_code=302)
    if (user.role or "CANDIDAT").upper() == "ADMIN":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin.html", status_code=302)
    content = """
    <main class="page-shell" data-portal-view="tracking"><div class="container"><div class="page-intro"><span class="kicker">Mon dossier · Suivi</span><h1>Où en est<br /><em>ma candidature ?</em></h1><p>La chronologie vous indique l’état actuel de votre dossier et les prochaines étapes.</p></div><section class="tracking-status card"><div><span class="kicker">Statut actuel</span><h2 data-tracking-status>Chargement…</h2><p data-tracking-copy></p></div><span class="tracking-dossier" data-dossier-number>—</span></section><div class="tracking-timeline" data-tracking-timeline></div><section class="tracking-next"><span class="kicker">À suivre</span><h2 data-tracking-next>Chargement des prochaines étapes…</h2><p data-tracking-next-copy></p><a class="btn btn-primary" href="/candidature.html">Accéder à mon dossier</a></section></div></main>
    """
    return _page_template("Suivi de candidature · EMSP", "/suivi.html", user, content)


def render_convocation(user: User | None) -> HTMLResponse:
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/connexion.html?next=/convocation.html", status_code=302)
    if (user.role or "CANDIDAT").upper() == "ADMIN":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin.html", status_code=302)
    content = """
    <main class="page-shell" data-portal-view="convocation"><div class="container"><div class="page-intro"><span class="kicker">Concours d’entrée · Convocation</span><h1>Votre prochaine<br /><em>étape en présentiel.</em></h1><p>Les informations et le document de convocation seront mis à jour par l’équipe admissions depuis votre dossier personnel.</p></div><section class="convocation-card card"><span class="kicker">Votre convocation</span><h2 data-convocation-heading>Vérification en cours…</h2><p data-convocation-message></p><div class="convocation-details" data-convocation-details hidden><div><span>Date et heure</span><strong data-convocation-date>—</strong></div><div><span>Centre de composition</span><strong data-convocation-centre>—</strong></div><div><span>Numéro de dossier</span><strong data-dossier-number>—</strong></div></div><p class="document-generation-note">Votre PDF personnel reprend les informations publiées pour votre dossier. Présentez-le le jour du concours avec une pièce d’identité.</p><a class="btn btn-primary" data-convocation-download href="/api/candidature/convocation/download" hidden>Télécharger ma convocation (PDF) <span aria-hidden="true">↓</span></a></section><div class="document-page-links"><a href="/resultat.html">Consulter mes résultats <span aria-hidden="true">↗</span></a><a href="/suivi.html">Retour au suivi du dossier <span aria-hidden="true">↗</span></a></div></div></main>
    """
    return _page_template("Convocation · EMSP", "/convocation.html", user, content)


def render_resultat(user: User | None) -> HTMLResponse:
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/connexion.html?next=/resultat.html", status_code=302)
    if (user.role or "CANDIDAT").upper() == "ADMIN":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin.html", status_code=302)
    content = """
    <main class="page-shell" data-portal-view="result"><div class="container result-wrap"><section class="result-card card"><span class="result-seal" aria-hidden="true">EMSP</span><span class="kicker">Décision du jury</span><h1 data-result-heading>Votre résultat<br /><em>sera bientôt disponible.</em></h1><p class="lead" data-result-message>Nous vous informerons ici dès que la décision du jury sera publiée.</p><div class="result-specialty" data-result-specialty hidden><span>Formation attribuée</span><strong data-result-program></strong></div><div class="result-meta" data-result-meta hidden><span>Date de publication</span><strong data-result-date></strong></div><div class="result-grades" data-result-grades hidden></div><div class="result-actions"><a class="btn btn-primary" data-result-certificate href="/api/candidature/admission/certificat.pdf" hidden>Télécharger mon attestation (PDF) <span aria-hidden="true">↓</span></a><a class="btn btn-outline" href="/suivi.html">Consulter le suivi de mon dossier</a><a class="text-link" href="/convocation.html">Voir ma convocation <span aria-hidden="true">↗</span></a></div><p class="document-generation-note">L’attestation reprend la décision publiée par l’administration. La signature et le cachet de la direction doivent être ajoutés par l’établissement habilité.</p></section></div></main>
    """
    return _page_template("Résultat du concours · EMSP", "/resultat.html", user, content)
