import os

with open("base_template.html", "r", encoding="utf-8") as f:
    base = f.read()

def write_page(filename, content):
    with open(f"frontend/{filename}", "w", encoding="utf-8") as f:
        f.write(base.replace("{CONTENT}", content))

pages = {
    "index.html": """
<section class="shell section section--snug">
    <div class="section-heading section-heading--strong">
        <p class="label label--mark">Concours 2026</p>
        <h1 class="text-d2 section-heading__title">Construisez votre avenir à l'EMSP.</h1>
        <p class="section-heading__lede">Le portail officiel de candidature pour la Licence 1 MENUM.</p>
        <div style="margin-top:2rem">
            <a href="candidater.html" class="button button--primary button--lg"><span class="button__label">Candidater maintenant</span></a>
        </div>
    </div>
</section>
<section class="shell section" style="padding-bottom:4rem">
    <div class="grid" style="display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:2rem">
        <div class="card">
            <h3 style="font-size:1.5rem">1. Créer le dossier</h3>
            <p>Obtenez votre numéro CDT_XXXX.</p>
        </div>
        <div class="card">
            <h3 style="font-size:1.5rem">2. Remplir</h3>
            <p>7 étapes simples en ligne.</p>
        </div>
        <div class="card">
            <h3 style="font-size:1.5rem">3. Déposer</h3>
            <p>Téléversez vos 10 documents.</p>
        </div>
        <div class="card">
            <h3 style="font-size:1.5rem">4. Soumettre</h3>
            <p>Consultez votre résultat.</p>
        </div>
    </div>
</section>
""",
    "connexion.html": """
<section class="shell section section--snug">
    <div class="section-heading">
        <h1 class="text-d2 section-heading__title">Connexion</h1>
    </div>
    <div style="max-width:500px; margin:0 auto">
        <div id="login-error" class="emsp-alert error" style="display:none"></div>
        <form class="form-grid" onsubmit="event.preventDefault(); window.login(this)">
            <div class="field">
                <label class="label">Email</label>
                <div class="field__control-wrap">
                    <input type="email" name="email" class="field__control field__control--input" required>
                </div>
            </div>
            <div class="field">
                <label class="label">Mot de passe</label>
                <div class="field__control-wrap">
                    <input type="password" name="password" class="field__control field__control--input" required>
                </div>
            </div>
            <button type="submit" class="button button--primary button--lg"><span class="button__label">Se connecter</span></button>
        </form>
    </div>
</section>
""",
    "candidater.html": """
<section class="shell section section--snug">
    <div class="section-heading">
        <h1 class="text-d2 section-heading__title">Candidater</h1>
    </div>
    <div style="max-width:500px; margin:0 auto">
        <div id="register-error" class="emsp-alert error" style="display:none"></div>
        <form class="form-grid" onsubmit="event.preventDefault(); window.register(this)">
            <div class="field">
                <label class="label">Nom</label>
                <input type="text" name="nom" class="field__control field__control--input" required>
            </div>
            <div class="field">
                <label class="label">Prénoms</label>
                <input type="text" name="prenoms" class="field__control field__control--input" required>
            </div>
            <div class="field">
                <label class="label">Email</label>
                <input type="email" name="email" class="field__control field__control--input" required>
            </div>
            <div class="field">
                <label class="label">Mot de passe</label>
                <input type="password" name="password" class="field__control field__control--input" required>
            </div>
            <button type="submit" class="button button--primary button--lg"><span class="button__label">Créer mon dossier</span></button>
        </form>
    </div>
</section>
""",
    "espace-candidat.html": """
<section class="shell section section--snug" data-auth="candidat">
    <div class="section-heading">
        <h1 class="text-d2 section-heading__title">Mon espace candidat</h1>
    </div>
    <div>
        <p>Numéro de dossier : <strong id="dash-numero">...</strong></p>
        <p>Statut : <span id="dash-statut">...</span></p>
        <div style="display:flex; gap:1rem; margin-top:2rem">
            <a href="candidature.html" class="button button--primary button--lg"><span class="button__label">Ma candidature</span></a>
            <a href="pieces.html" class="button button--light button--lg"><span class="button__label">Mes pièces</span></a>
            <a href="suivi.html" class="button button--light button--lg"><span class="button__label">Suivi & Résultats</span></a>
        </div>
    </div>
</section>
""",
    "candidature.html": """
<section class="shell section section--snug" data-auth="candidat">
    <div class="section-heading"><h1 class="text-d2 section-heading__title">Formulaire de candidature</h1></div>
    <div id="stepper" style="display:flex; gap:1rem; margin-bottom:2rem; font-weight:bold; overflow-x:auto;"></div>

    <div id="step-1" class="step-panel" style="display:none">
        <h2>1. Informations</h2>
        <form class="form-grid" onsubmit="event.preventDefault(); window.saveStep(1)">
            <input type="text" name="lieu_naissance" placeholder="Lieu de naissance" class="field__control field__control--input" required>
            <input type="text" name="nationalite" placeholder="Nationalité" class="field__control field__control--input" required>
            <button type="submit" class="button button--primary">Suivant</button>
        </form>
    </div>

    <div id="step-7" class="step-panel" style="display:none">
        <h2>7. Soumission</h2>
        <p>En soumettant ce dossier, il sera transmis au jury.</p>
        <button onclick="window.submitDossier()" class="button button--primary button--lg"><span class="button__label">Soumettre définitivement</span></button>
    </div>
</section>
""",
    "pieces.html": """
<section class="shell section section--snug" data-auth="candidat">
    <div class="section-heading"><h1 class="text-d2 section-heading__title">Mes Pièces</h1></div>
    <div id="pieces-grid" style="display:grid; gap:1rem; grid-template-columns:1fr 1fr;"></div>
</section>
""",
    "suivi.html": """
<section class="shell section section--snug" data-auth="candidat">
    <div class="section-heading"><h1 class="text-d2 section-heading__title">Suivi du dossier</h1></div>
    <div id="suivi-content">Chargement...</div>
</section>
""",
    "admin.html": """
<section class="shell section section--snug" data-auth="admin">
    <div class="section-heading"><h1 class="text-d2 section-heading__title">Administration</h1></div>
    <div id="admin-content">Chargement...</div>
</section>
""",
    "contact.html": """
<section class="shell section section--snug">
    <div class="section-heading"><h1 class="text-d2 section-heading__title">Contact</h1></div>
    <p>contact@emsp.ci</p>
</section>
""",
    "conditions.html": """
<section class="shell section section--snug">
    <div class="section-heading"><h1 class="text-d2 section-heading__title">Conditions</h1></div>
    <p>Être bachelier.</p>
</section>
""",
}

for name, content in pages.items():
    write_page(name, content)
