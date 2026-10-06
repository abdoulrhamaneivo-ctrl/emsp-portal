import os
import re

def main():
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Extract head
    head_match = re.search(r'(<head>.*?</head>)', html, re.DOTALL)
    head_content = head_match.group(1) if head_match else ""
    head_content = head_content.replace("A1 Pharmacy", "EMSP")

    # Extract header
    header_match = re.search(r'(<header.*?</header>)', html, re.DOTALL)
    header_content = header_match.group(1) if header_match else ""

    # Customize header for EMSP
    header_content = header_content.replace("A1", "EMSP")
    header_content = header_content.replace("Pharmacy", "Portail")
    # Replace nav links in header
    nav_pattern = r'<ul class="primary-nav">.*?</ul>'
    new_nav = """<ul class="primary-nav" id="dynamic-nav">
        <li><a href="/" class="nav-link">Accueil</a></li>
        <li><a href="conditions.html" class="nav-link">Conditions</a></li>
        <li><a href="contact.html" class="nav-link">Contact</a></li>
    </ul>"""
    header_content = re.sub(nav_pattern, new_nav, header_content, flags=re.DOTALL)

    # Replace Right utilities in header
    tools_pattern = r'<div class="header-tools">.*?</div>'
    new_tools = """<div class="header-tools" id="dynamic-tools">
        <a href="connexion.html" class="nav-link">Connexion</a>
        <a href="candidater.html" class="nav-link nav-link--emphasis">Candidater</a>
    </div>"""
    header_content = re.sub(tools_pattern, new_tools, header_content, flags=re.DOTALL)

    # Remove mega panels
    header_content = re.sub(r'<div class="mega-panel".*?</div>\s*</header>', '</header>', header_content, flags=re.DOTALL)

    # Extract footer
    footer_match = re.search(r'(<footer class="site-footer".*?</footer>)', html, re.DOTALL)
    footer_content = footer_match.group(1) if footer_match else ""
    footer_content = footer_content.replace("A1 Pharmacy", "EMSP Portail")
    # Simplify footer
    footer_content = """<footer class="site-footer" data-surface="dark" style="padding: 4rem 2rem; background: #056839; color: white;">
        <div class="shell">
            <h2>EMSP</h2>
            <p>École Multinationale Supérieure des Postes.<br>Institution intergouvernementale fondée en 1970.</p>
            <p class="mt-4">© 2026 EMSP — Tous droits réservés.</p>
        </div>
    </footer>"""

    # Extract JS at the bottom
    js_match = re.search(r'(<script src="js/main.js" type="module"></script>.*?)</body>', html, re.DOTALL)
    js_content = js_match.group(1) if js_match else '<script src="js/main.js" type="module"></script>'

    base_template = f"""<!doctype html>
<html lang="fr">
{head_content}
<body data-full-bleed>
    <div class="page">
        {header_content}
        <main class="page__main" id="main">
            {{CONTENT}}
        </main>
        {footer_content}
    </div>
    {js_content}
    <script src="js/emsp_app.js"></script>
</body>
</html>
"""
    # Insert custom CSS link
    base_template = base_template.replace('</head>', '    <link rel="stylesheet" href="css/emsp.css">\n</head>')

    with open("base_template.html", "w", encoding="utf-8") as f:
        f.write(base_template)

if __name__ == "__main__":
    main()
