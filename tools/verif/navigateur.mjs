/* Moteur de mesure — partie navigateur.
 *
 * Reçoit une job JSON sur stdin, rend des mesures brutes sur stdout.
 * Aucune interprétation ici : ce fichier calcule des chiffres, le
 * module Python en fait des verdicts. Le pilote Playwright retenu est
 * celui qui fonctionne réellement sur cette machine (le paquet Python
 * 1.55 et les pilotes Node 1.62/1.63 ne parlent pas le même protocole).
 *
 *   node navigateur.mjs < ../job.json
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW_MODULE);
const { spawn } = require('node:child_process');

const job = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const { base, seuils: S, pages, comptes, etapesAttendues, piecesAttendees } = job;

/* ── Audit : contraste, typographie, mise en page, cibles ────────────── */
const AUDIT = (S) => {
  const parse = (s) => {
    const m = String(s).match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    if (!m) return null;
    return { c: [+m[1], +m[2], +m[3]], a: m[4] === undefined ? 1 : +m[4] };
  };
  const lum = (c) => {
    const [r, g, b] = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => {
    const l1 = lum(a), l2 = lum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };
  /* Fond effectif : premier ancêtre qui porte une couleur de fond.
     Pour un dégradé, on retient la nuance la MOINS favorable au texte :
     mieux vaut un signalement à vérifier qu'un défaut de contraste
     réellement absent du rapport. */
  const pireFond = (st) => [...String(st.backgroundImage).matchAll(
    /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/g
  )].map((m) => ({ c: [+m[1], +m[2], +m[3]], a: m[4] === undefined ? 1 : +m[4] }))
    .filter((s) => s.a >= 0.05);
  const fondEffectif = (el, texte) => {
    let pire = null;
    let n = el;
    while (n && n !== document.documentElement) {
      const st = getComputedStyle(n);
      const uni = parse(st.backgroundColor);
      if (uni && uni.a > 0.85) return uni;
      for (const stop of pireFond(st)) {
        if (!pire || ratio(texte.c, stop.c) < ratio(texte.c, pire.c)) pire = stop;
      }
      n = n.parentElement;
    }
    return pire || { c: [255, 255, 255], a: 1 };
  };
  const dansDefilement = (el) => {
    let n = el.parentElement;
    while (n && n !== document.body) {
      const st = getComputedStyle(n);
      if (st.overflowX === 'auto' || st.overflowX === 'scroll') return true;
      n = n.parentElement;
    }
    return false;
  };
  const chemin = (el) => {
    const parts = [];
    let n = el;
    for (let i = 0; n && n.nodeType === 1 && i < 4; i++) {
      let p = n.tagName.toLowerCase();
      if (n.id) { parts.unshift(p + '#' + n.id); break; }
      if (typeof n.className === 'string' && n.className.trim()) {
        p += '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.');
      }
      parts.unshift(p);
      n = n.parentElement;
    }
    return parts.join(' > ');
  };

  const out = { contraste: [], police: [], mise_en_page: [] };
  const vw = document.documentElement.clientWidth;

  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('.sr-only, [hidden]')) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || +st.opacity === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;

    const texte = [...el.childNodes]
      .filter((n) => n.nodeType === 3 && n.textContent.trim().length > 1)
      .map((n) => n.textContent.trim()).join(' ');
    const taille = parseFloat(st.fontSize);
    const gras = +st.fontWeight >= 700;

    if (texte) {
      const fg = parse(st.color);
      if (fg) {
        const bg = fondEffectif(el, fg);
        const eff = fg.c.map((v, i) => v * fg.a + bg.c[i] * (1 - fg.a));
        const r = Math.round(ratio(eff, bg.c) * 100) / 100;
        const grand = taille >= S.taillePoliceGrandTexte ||
                      (taille >= S.taillePoliceGrandTexteGras && gras);
        const seuil = grand ? S.contrasteGrandTexte : S.contrasteTexte;
        if (r < seuil) {
          out.contraste.push({
            texte: texte.slice(0, 46), ratio: r, seuil, taille: Math.round(taille), gras,
            couleur: st.color, fond: 'rgb(' + bg.c.join(',') + ')', selecteur: chemin(el),
          });
        }
      }
      if (taille < S.policeMinPx) {
        out.police.push({ texte: texte.slice(0, 46), taille: Math.round(taille * 10) / 10, selecteur: chemin(el) });
      }
      if (el.scrollWidth > el.clientWidth + 1 && st.overflow !== 'visible' && st.textOverflow !== 'ellipsis') {
        out.mise_en_page.push({ type: 'tronque', texte: texte.slice(0, 46), lost: el.scrollWidth - el.clientWidth, selecteur: chemin(el) });
      }
    }
    if (rect.right > vw + S.debordementTolerePx && !dansDefilement(el)) {
      out.mise_en_page.push({ type: 'debordement', texte: (el.textContent || '').trim().slice(0, 40), excess: Math.round(rect.right - vw), selecteur: chemin(el) });
    }
  }

  /* ═══ Contrat de design (DESIGN.md) ═══════════════════════════════════
     Ces contrôles n'existaient pas, et c'est pourquoi la dérive a pu se
     produire : aucun test ne regardait la profondeur ni les familles de
     caractères. Une feuille pouvait déclarer `radius: 0` et `shadow: none`
     pendant des mois sans qu'aucune mesure ne s'en aperçoive.

     On contrôle donc ce que DESIGN.md interdit explicitement :
     · plus de 2 familles réellement rendues (une grotesque + une monospace) ;
     · un rayon nul sur un composant qui en doit un ;
     · l'absence de toute ombre sur une carte ;
     · une transition en `linear` autre que la durée la plus courte ;
     · un bloc masqué par l'entrée en scène qui le resterait. */

  const styles = getComputedStyle(document.documentElement);
  const lire = (nom) => (styles.getPropertyValue(nom) || '').trim();

  const rendues = new Map();
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('.sr-only, [hidden], script, style')) continue;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    const st = getComputedStyle(el);
    const f = st.fontFamily.split(',')[0].replace(/["']/g, '').trim();
    if (f) rendues.set(f, (rendues.get(f) || 0) + 1);
  }
  out.contrat = {
    familles: [...rendues.keys()],
    polices: [...document.fonts].map((f) => f.family).filter((v, i, a) => a.indexOf(v) === i),
    rayons: lire('--radius-card'),
    ombres: lire('--shadow-1'),
    motionVif: lire('--motion-vif'),
    ease: lire('--ease-vif'),
  };

  // Cartes réellement visibles : on ne juge pas une carte absente.
  const cartes = [...document.querySelectorAll('.card, .spec, .encart, .tile')]
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 40 && r.height > 40; });
  out.contrat.cartes = cartes.length;
  out.contrat.sansRayon = cartes.filter((el) => parseFloat(getComputedStyle(el).borderRadius) < 0.5).length;
  out.contrat.sansOmbre = cartes.filter((el) => {
    const b = getComputedStyle(el).boxShadow;
    return !b || b === 'none';
  }).length;

  // Bloc masqué par l'entrée en scène ET visible à l'écran : c'est le seul
  // cas où l'animation retire du contenu. Un bloc masqué mais hors champ
  // est normal — il se révélera au retour.
  //
  // Le test d'opacité suffit : sans la classe `js-entree` sur <html>, aucune
  // règle de masquage ne s'applique et l'opacité vaut 1. La classe se
  // vérifie donc ailleurs, une fois par page.
  const cachesVisibles = [...document.querySelectorAll('[data-entree]')].filter((el) => {
    if (+getComputedStyle(el).opacity >= 1) return false;
    const r = el.getBoundingClientRect();
    return r.top < window.innerHeight && r.bottom > 0;
  });
  out.contrat.blocsMasques = cachesVisibles.length;

  if (vw <= S.largeurMobile + 10) {
    for (const el of document.querySelectorAll('a, button, input, select, textarea, label.btn')) {
      if (el.closest('.sr-only, [hidden]')) continue;
      // Une case à cocher ou un bouton radio se mesure sur son ÉTIQUETTE
      // englobante, pas sur le contrôle de 18px : le clic tombe sur le
      // label, c'est donc lui qui est la cible.
      const portee = (el.tagName === 'INPUT'
                      && (el.type === 'checkbox' || el.type === 'radio')
                      && el.closest('label'))
        ? el.closest('label')
        : el;
      const r = portee.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      const stEl = getComputedStyle(portee);
      if (stEl.display === 'none') continue;
      // Lien insere dans une phrase : la norme l'exclut du minimum.
      // On teste la presence de texte autour plutot que le `display` :
      // un lien suivi d'un point ou precede d'un mot est dans une
      // phrase, meme si la feuille lui donne `inline-block`.
      const parent = portee.parentElement;
      const autour = parent
        ? parent.textContent.replace(portee.textContent || '', '').trim()
        : '';
      const dansPhrase = portee.tagName === 'A' && autour.length > 0;
      // `plancher` = seuil en dessous duquel on signale. Un lien dans
      // une phrase n'est jamais signale (la norme l'exclut). Pour un
      // vrai bouton, on signale sous le confort (36) et on downgrade en
      // mineur tout ce qui reste au-dessus de la norme (24).
      const plancher = dansPhrase ? 0 : S.cibleTactilePx;
      if (r.height < plancher) {
        out.mise_en_page.push({
          type: 'cible', texte: (portee.textContent || portee.tagName).trim().slice(0, 34),
          hauteur: Math.round(r.height), seuil: S.cibleTactilePx,
          // `norme` = minimum AA (24 px). C'est lui qui décide de la
          // gravite ; le seuil de confort (36) ne declenche que le
          // signalement, pas l'alarme.
          norme: S.cibleTactileMinPx, plancher,
          selecteur: chemin(el),
        });
      }
    }
  }

  const c = document.createElement('canvas').getContext('2d');
  for (const p of document.querySelectorAll('p, li')) {
    if (p.closest('.sr-only, [hidden]')) continue;
    const st = getComputedStyle(p);
    const t = (p.textContent || '').trim();
    if (t.length < 140) continue;
    c.font = st.font || (st.fontSize + ' ' + st.fontFamily);
    const largeurCar = c.measureText('abcdefghijklmnopqrstuvwxyz ').width / 27;
    const range = document.createRange();
    range.selectNodeContents(p);
    const lignes = [...range.getClientRects()].filter((r) => r.width > 20);
    if (!lignes.length) continue;
    const car = Math.round(Math.max(...lignes.map((r) => r.width)) / largeurCar);
    if (car > S.mesureMaxCaracteres) {
      out.mise_en_page.push({ type: 'mesure', texte: t.slice(0, 40), caracteres: car, seuil: S.mesureMaxCaracteres, selecteur: chemin(p) });
    }
  }
  return out;
};

/* Quel compte ouvrir pour chaque rôle mesuré. Un même rôle peut avoir
   plusieurs états : le formulaire connecté n'a pas le même rendu avec un
   dossier en cours qu'avec un dossier verrouillé. */
const COMPTE_DU_ROLE = {
  candidat: 'soumis',
  formulaire: 'presque',
  admin: 'admin',
};

const corps = (page) => page.evaluate(() => document.body.innerText.replace(/\s+/g, ' '));

const connecter = async (page, role) => {
  const c = comptes[role];
  await page.goto(base + '/connexion.html', { waitUntil: 'networkidle' });
  await page.fill('#email', c[0]);
  await page.fill('#password', c[1]);
  await page.click('#btn-submit');
  await page.waitForTimeout(1700);
};

const navigateur = await chromium.launch();
const resultat = { pages: [], parcours: [], securite: [] };

/* ── 1. audit de rendu ───────────────────────────────────────────────────
   Une seule connexion par rôle et par mode : on redimensionne la fenêtre
   au lieu d'ouvrir une session par page. Trente-deux sessions de moins,
   et le limiteur du site n'a plus à être sollicité pour rien. */
for (const role of [...new Set(pages.map((p) => p.role))]) {
  const duRole = pages.filter((p) => p.role === role);
  for (const mobile of [false, true]) {
    const largeurs = duRole[0].largeurs.filter((l) => (l <= S.largeurMobile + 10) === mobile);
    if (!largeurs.length) continue;
    const ctx = await navigateur.newContext({
      viewport: { width: largeurs[0], height: 900 },
      isMobile: mobile, hasTouch: mobile,
    });
    const page = await ctx.newPage();
    try {
      if (role !== 'anonyme') await connecter(page, COMPTE_DU_ROLE[role] || 'soumis');
      for (const { chemin: url } of duRole) {
        for (const largeur of largeurs) {
          try {
            await page.setViewportSize({ width: largeur, height: 900 });
            await page.goto(base + url, { waitUntil: 'networkidle' });
            await page.waitForTimeout(700);
            resultat.pages.push({ page: url, largeur, brut: await page.evaluate(AUDIT, S) });
          } catch (e) {
            resultat.pages.push({ page: url, largeur, erreur: String(e.message || e).slice(0, 120) });
          }
        }
      }
    } catch (e) {
      for (const { chemin: url } of duRole) {
        for (const largeur of largeurs) {
          resultat.pages.push({ page: url, largeur, erreur: 'session impossible : ' + String(e.message || e).slice(0, 90) });
        }
      }
    } finally {
      await ctx.close();
    }
  }
}

/* ── 2. parcours : la fonctionnalité, jamais réparée automatiquement ─── */
const attendreLimiteur = async (page) => (await corps(page)).includes('Trop de tentatives');

for (const role of ['soumis', 'convoque', 'admis', 'refuse']) {
  const ctx = await navigateur.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  try {
    await connecter(page, role);
    await page.goto(base + '/dashboard.html', { waitUntil: 'networkidle' });
    await page.waitForTimeout(900);
    const t = await corps(page);
    if (t.includes('Trop de tentatives')) {
      resultat.parcours.push({ role, etat: 'limite', message: 'limiteur de débit (5/min/IP) — relancer le test' });
    } else if (role === 'soumis') {
      resultat.parcours.push({
        role, etat: t.toUpperCase().includes('DOSSIER SOUMIS') ? 'ok' : 'echec',
        message: 'un dossier soumis doit afficher son statut',
      });
    }
    if (role === 'convoque') {
      await page.goto(base + '/convocation.html', { waitUntil: 'networkidle' });
      await page.waitForTimeout(800);
      const r = await page.request.get(base + '/api/candidature/convocation');
      resultat.parcours.push({
        role, etat: r.status() === 200 ? 'ok' : 'echec',
        message: 'convocation programmée non téléchargeable', mesure: String(r.status()), seuil: '200',
      });
    }
    if (role === 'admis') {
      await page.goto(base + '/admis.html', { waitUntil: 'networkidle' });
      await page.waitForTimeout(1000);
      const texte = await page.evaluate(() => document.body.innerText);
      const n = (texte.match(/Félicitations, vous êtes admis\./g) || []).length;
      resultat.parcours.push({
        role, etat: n === 1 ? 'ok' : 'echec',
        message: n === 0 ? 'page de résultat vide pour un candidat admis'
                        : 'message de résultat répété',
        mesure: 'x' + n, seuil: 'x1',
      });
    }
  } catch (e) {
    resultat.parcours.push({ role, etat: 'echec', message: String(e.message || e).slice(0, 100) });
  } finally {
    await ctx.close();
  }
}

/* ── 3. sécurité ─────────────────────────────────────────────────────── */
if (job.motifInterne) {
  const ctx = await navigateur.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  try {
    await connecter(page, 'refuse');
    for (const url of ['/dashboard.html', '/suivi.html', '/admis.html', '/profil.html']) {
      await page.goto(base + url, { waitUntil: 'networkidle' });
      await page.waitForTimeout(500);
      const t = await corps(page);
      const api = await page.evaluate(async () => (await fetch('/api/candidature/me')).text());
      resultat.securite.push({
        page: url, etat: t.includes(job.motifInterne) || api.includes(job.motifInterne) ? 'echec' : 'ok',
        message: 'le motif interne de refus est exposé au candidat',
      });
    }
  } catch (e) {
    resultat.securite.push({ page: 'motif', etat: 'echec', message: String(e.message || e).slice(0, 100) });
  } finally {
    await ctx.close();
  }
}

{
  const ctx = await navigateur.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  try {
    // Le contrôle doit partir de la même origine que le site : depuis
    // about:blank, le navigateur refuse la requête et on mesurerait
    // l'échec de la sonde plutôt que l'accès à l'API.
    await page.goto(base + '/index.html', { waitUntil: 'networkidle' });
    const code = await page.evaluate(async () =>
      (await fetch('/api/admin/candidatures', { credentials: 'same-origin' })).status);
    resultat.securite.push({
      page: 'api/admin', etat: code === 401 ? 'ok' : 'echec',
      message: "l'API d'administration répond à un visiteur anonyme",
      mesure: String(code), seuil: '401',
    });
  } catch (e) {
    resultat.securite.push({ page: 'api/admin', etat: 'echec', message: 'contrôle d\'accès impossible : ' + String(e.message || e).slice(0, 80) });
  } finally {
    await ctx.close();
  }
}

/* ── 4. le formulaire tient-il ses promesses ? ───────────────────────── */
{
  const ctx = await navigateur.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await ctx.newPage();
  try {
    await connecter(page, 'presque');
    await page.goto(base + '/candidature.html', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1300);
    const f = await page.evaluate(() => {
      const etapes = document.querySelectorAll('#steps .step').length;
      // Les pièces sont rendues en grille de cartes OU en liste chaînée
      // selon la largeur. L'outil doit reconnaître les deux rendus : coller
      // une classe « carte » sur une ligne de liste ferait passer le
      // contrôle, mais ce serait une variante mensongère.
      const carte = (c) => c.querySelector('h3');
      const ligne = (c) => c.querySelector('.liste-chaine-titre');
      const pieces = [...document.querySelectorAll('.doc-card, #doc-grid .liste-chaine > li')];
      const intitules = pieces.map((c) => (carte(c) || ligne(c))?.textContent?.trim() || '');
      const tronques = pieces
        .filter((c) => { const t = carte(c) || ligne(c); return t && t.scrollWidth > t.clientWidth + 1; })
        .map((c) => (carte(c) || ligne(c)).textContent.trim().slice(0, 30));
      const doublons = intitules.filter((v, i, a) => v && a.indexOf(v) !== i);
      return { etapes, pieces: pieces.length, tronques, doublons };
    });
    if (f.etapes !== etapesAttendues) {
      resultat.parcours.push({ role: 'formulaire', etat: 'echec',
        message: 'le formulaire n\'a pas ses 7 étapes', mesure: String(f.etapes), seuil: String(etapesAttendues) });
    }
    if (f.pieces !== piecesAttendees) {
      resultat.parcours.push({ role: 'formulaire', etat: 'echec',
        message: 'le formulaire n\'a pas ses 10 pièces', mesure: String(f.pieces), seuil: String(piecesAttendees) });
    }
    for (const t of f.tronques) {
      resultat.parcours.push({ role: 'formulaire', etat: 'echec', message: `intitulé de pièce tronqué : ${t}` });
    }
    for (const d of f.doublons) {
      resultat.parcours.push({ role: 'formulaire', etat: 'echec', message: `intitulé de pièce en double : ${d}` });
    }
    if (f.etapes === etapesAttendues && f.pieces === piecesAttendees && !f.tronques.length && !f.doublons.length) {
      resultat.parcours.push({ role: 'formulaire', etat: 'ok',
        message: `${f.etapes} étapes, ${f.pieces} pièces, intitulés entiers` });
    }
  } catch (e) {
    resultat.parcours.push({ role: 'formulaire', etat: 'echec', message: String(e.message || e).slice(0, 100) });
  } finally {
    await ctx.close();
  }
}

await navigateur.close();
process.stdout.write(JSON.stringify(resultat));
