(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const enhancePasswordFields = (root = document) => {
    $$('input[type="password"]:not([data-password-enhanced])', root).forEach((input, index) => {
      input.dataset.passwordEnhanced = "true";
      if (!input.id) input.id = `password-field-${index + 1}`;
      const wrapper = document.createElement("span");
      wrapper.className = "password-input-wrap";
      input.parentNode.insertBefore(wrapper, input);
      wrapper.append(input);
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "password-reveal-toggle";
      toggle.dataset.passwordToggle = "";
      toggle.setAttribute("aria-controls", input.id);
      toggle.setAttribute("aria-label", "Afficher le mot de passe");
      toggle.title = "Afficher le mot de passe";
      toggle.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.3-6 9.5-6 9.5 6 9.5 6-3.3 6-9.5 6-9.5-6-9.5-6Z"></path><circle cx="12" cy="12" r="2.5"></circle></svg><span>Afficher</span>';
      wrapper.append(toggle);
    });
  };
  enhancePasswordFields();
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-password-toggle]");
    if (!toggle) return;
    const input = document.getElementById(toggle.getAttribute("aria-controls"));
    if (!input) return;
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    toggle.classList.toggle("is-visible", reveal);
    toggle.setAttribute("aria-label", reveal ? "Masquer le mot de passe" : "Afficher le mot de passe");
    toggle.title = reveal ? "Masquer le mot de passe" : "Afficher le mot de passe";
    $("span", toggle).textContent = reveal ? "Masquer" : "Afficher";
    input.focus({ preventScroll: true });
  });
  const navigateTo = (url) => window.emspNavigate ? window.emspNavigate(url) : window.location.assign(url);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const messageOf = (detail) => typeof detail === "string" ? detail : detail && typeof detail === "object" ? Object.values(detail).join(" · ") : "Une erreur est survenue. Réessayez.";

  const pageLoader = $("[data-page-loader]");
  const pageLoaderCopy = $("[data-page-loader-copy]", pageLoader || document);
  const pageReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let pageNavigationPending = false;
  let pageNavigationTimer = 0;
  let pageRecoveryTimer = 0;
  let pageEntryTimer = 0;

  const setPageArriving = () => {
    document.documentElement.classList.remove("is-page-leaving");
    document.documentElement.classList.add("is-page-arriving");
    window.clearTimeout(pageEntryTimer);
    pageEntryTimer = window.setTimeout(() => document.documentElement.classList.remove("is-page-arriving"), 900);
  };
  const clearPageLoader = () => {
    pageNavigationPending = false;
    window.clearTimeout(pageNavigationTimer);
    window.clearTimeout(pageRecoveryTimer);
    document.documentElement.classList.remove("is-page-leaving");
    document.documentElement.removeAttribute("aria-busy");
    if (pageLoader) {
      pageLoader.classList.remove("is-active");
      pageLoader.hidden = true;
      pageLoader.setAttribute("aria-hidden", "true");
      pageLoader.removeAttribute("aria-busy");
    }
  };
  const pageMessageFor = (pathname) => {
    if (pathname === "/" || pathname === "/index.html") return "Bienvenue à l’EMSP…";
    if (pathname === "/connexion.html") return "Ouverture de votre espace sécurisé…";
    if (pathname === "/admin.html") return "Chargement du tableau de bord…";
    if (pathname === "/candidature.html") return "Préparation de votre dossier…";
    if (pathname === "/espace-candidat.html") return "Ouverture de votre espace candidat…";
    if (pathname === "/convocation.html") return "Préparation de votre convocation…";
    if (pathname === "/resultat.html") return "Consultation des résultats…";
    if (pathname === "/suivi.html") return "Mise à jour du suivi…";
    return "Chargement de votre page…";
  };
  const navigateWithPageTransition = (destination) => {
    const next = new URL(destination, window.location.href);
    if (next.origin !== window.location.origin || !pageLoader || pageReducedMotion?.matches
      || (next.pathname === window.location.pathname && next.search === window.location.search)) {
      window.location.assign(next.href);
      return;
    }

    if (pageNavigationPending) return;
    pageNavigationPending = true;
    const currentPageUrl = window.location.href;
    if (pageLoaderCopy) pageLoaderCopy.textContent = pageMessageFor(next.pathname);
    pageLoader.hidden = false;
    pageLoader.setAttribute("aria-hidden", "false");
    pageLoader.setAttribute("aria-busy", "true");
    document.documentElement.setAttribute("aria-busy", "true");
    document.documentElement.classList.remove("is-page-arriving");
    document.documentElement.classList.add("is-page-leaving");
    window.requestAnimationFrame(() => pageLoader.classList.add("is-active"));
    pageNavigationTimer = window.setTimeout(() => window.location.assign(next.href), 360);
    pageRecoveryTimer = window.setTimeout(() => {
      if (pageNavigationPending && window.location.href === currentPageUrl) clearPageLoader();
    }, 6500);
  };

  window.emspNavigate = navigateWithPageTransition;
  document.documentElement.classList.add("is-page-arriving");
  pageEntryTimer = window.setTimeout(() => document.documentElement.classList.remove("is-page-arriving"), 900);
  window.addEventListener("pageshow", (event) => {
    clearPageLoader();
    if (event.persisted) setPageArriving();
  });
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!link || link.hasAttribute("download") || link.dataset.noPageTransition !== undefined) return;
    if (link.target && link.target !== "_self") return;
    const next = new URL(link.href, window.location.href);
    if (next.origin !== window.location.origin || next.pathname.startsWith("/api/")) return;
    if (next.pathname === window.location.pathname && next.search === window.location.search) return;
    event.preventDefault();
    navigateWithPageTransition(next.href);
  }, { capture: true });

  const themeRoot = document.documentElement;
  const themeMeta = $('meta[name="theme-color"]');
  const syncThemeControls = () => {
    const dark = themeRoot.dataset.theme === "dark";
    $$('[data-theme-toggle]').forEach((button) => {
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", dark ? "Activer le mode clair" : "Activer le mode sombre");
      button.title = dark ? "Activer le mode clair" : "Activer le mode sombre";
      const icon = $('[data-theme-icon]', button);
      const label = $('[data-theme-label]', button);
      if (icon) icon.textContent = dark ? "☀" : "☾";
      if (label) label.textContent = dark ? "Clair" : "Sombre";
    });
    if (themeMeta) themeMeta.content = dark ? "#0b1510" : "#063e2b";
  };
  syncThemeControls();
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-theme-toggle]");
    if (!button) return;
    const nextTheme = themeRoot.dataset.theme === "dark" ? "light" : "dark";
    themeRoot.dataset.theme = nextTheme;
    try { localStorage.setItem("emsp-theme", nextTheme); } catch (_) { /* Le thème reste actif pour cette page. */ }
    syncThemeControls();
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== "emsp-theme" || !["dark", "light"].includes(event.newValue)) return;
    themeRoot.dataset.theme = event.newValue;
    syncThemeControls();
  });

  const readingProgress = $("[data-reading-progress]");
  if (readingProgress) {
    let progressFrame = 0;
    const updateReadingProgress = () => {
      progressFrame = 0;
      const root = document.documentElement;
      const scrollableHeight = Math.max(0, root.scrollHeight - window.innerHeight);
      const progress = scrollableHeight ? Math.min(1, Math.max(0, window.scrollY / scrollableHeight)) : 0;
      readingProgress.style.transform = `scaleX(${progress.toFixed(4)})`;
    };
    const scheduleReadingProgress = () => {
      if (!progressFrame) progressFrame = window.requestAnimationFrame(updateReadingProgress);
    };
    window.addEventListener("scroll", scheduleReadingProgress, { passive: true });
    window.addEventListener("resize", scheduleReadingProgress, { passive: true });
    window.addEventListener("load", scheduleReadingProgress, { once: true });
    scheduleReadingProgress();
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    const type = response.headers.get("content-type") || "";
    const result = type.includes("application/json") ? await response.json() : null;
    if (!response.ok) throw new Error(messageOf(result?.detail || result?.message));
    return result;
  }
  const showFeedback = (element, message, kind = "info") => {
    if (!element) return;
    element.textContent = message;
    element.classList.remove("is-error", "is-success");
    if (kind === "error") element.classList.add("is-error");
    if (kind === "success") element.classList.add("is-success");
    element.hidden = false;
  };
  const hideFeedback = (element) => { if (element) element.hidden = true; };
  const dateFr = (value, options = { dateStyle: "long" }) => value ? new Intl.DateTimeFormat("fr-FR", options).format(new Date(value)) : "—";
  const docLabels = {
    attestation_bac: "Attestation du baccalauréat", releve_notes_bac: "Relevé de notes du baccalauréat",
    piece_identite: "Pièce d’identité", bulletins_seconde: "Bulletins de seconde", bulletins_premiere: "Bulletins de première",
    bulletins_terminale: "Bulletins de terminale", photo_identite: "Photo d’identité", lettre_motivation: "Lettre de motivation",
    acte_naissance: "Extrait d’acte de naissance", cv: "Curriculum vitæ"
  };
  const steps = ["Informations personnelles", "Parcours académique", "Choix de formation", "Tuteurs", "Pièces justificatives", "Vérification", "Soumission"];

  const parallaxTargets = $$('[data-parallax]');
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  function animateCounter(element, value, suffix = "") {
    if (!element) return;
    const target = Math.max(0, Number(value) || 0);
    if (reducedMotion?.matches || !window.requestAnimationFrame) {
      element.textContent = `${target}${suffix}`;
      return;
    }
    const startedAt = performance.now();
    const duration = 720;
    const tick = (now) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = `${Math.round(target * eased)}${suffix}`;
      if (progress < 1) window.requestAnimationFrame(tick);
    };
    window.requestAnimationFrame(tick);
  }
  if (parallaxTargets.length && !reducedMotion?.matches) {
    let parallaxFrame = 0;
    const updateParallax = () => {
      parallaxFrame = 0;
      const viewportHeight = window.innerHeight || 1;
      parallaxTargets.forEach((target) => {
        const rect = target.getBoundingClientRect();
        const centerProgress = (rect.top + rect.height / 2 - viewportHeight / 2) / viewportHeight;
        const progress = Math.max(-1, Math.min(1, centerProgress));
        const distance = Math.max(0, Number(target.dataset.parallax) || 0);
        target.style.setProperty('--motion-y', `${(-progress * distance * 0.36).toFixed(1)}px`);
      });
    };
    const scheduleParallax = () => {
      if (!parallaxFrame) parallaxFrame = window.requestAnimationFrame(updateParallax);
    };
    window.addEventListener('scroll', scheduleParallax, { passive: true });
    window.addEventListener('resize', scheduleParallax, { passive: true });
    scheduleParallax();
    reducedMotion?.addEventListener?.('change', (event) => {
      if (event.matches) parallaxTargets.forEach((target) => target.style.removeProperty('--motion-y'));
      else scheduleParallax();
    });
  }

  const journeySection = $(".journey-section");
  const journeyTrack = $(".journey-steps", journeySection || document);
  const journeySteps = $$(".journey-step", journeyTrack || document);
  if (journeySection && journeyTrack && journeySteps.length && !reducedMotion?.matches) {
    let journeyFrame = 0;
    const updateJourneyMotion = () => {
      journeyFrame = 0;
      if (reducedMotion?.matches) {
        journeySection.style.removeProperty("--journey-fill");
        journeySteps.forEach((step) => step.classList.remove("is-current", "is-past"));
        return;
      }
      const viewportHeight = window.innerHeight || 1;
      const sectionRect = journeySection.getBoundingClientRect();
      const sectionProgress = Math.max(0, Math.min(1, (viewportHeight - sectionRect.top) / (sectionRect.height + viewportHeight)));
      const trackHeight = Math.max(0, journeyTrack.clientHeight - 36);
      journeySection.style.setProperty("--journey-fill", `${(trackHeight * sectionProgress).toFixed(1)}px`);

      if (sectionRect.bottom < 0 || sectionRect.top > viewportHeight) return;
      const readingLine = viewportHeight * 0.48;
      const activeIndex = journeySteps.reduce((nearest, step, index) => {
        const rect = step.getBoundingClientRect();
        const distance = Math.abs(rect.top + rect.height / 2 - readingLine);
        return distance < nearest.distance ? { index, distance } : nearest;
      }, { index: 0, distance: Infinity }).index;
      journeySteps.forEach((step, index) => {
        step.classList.toggle("is-current", index === activeIndex);
        step.classList.toggle("is-past", index < activeIndex);
      });
    };
    const scheduleJourneyMotion = () => {
      if (!journeyFrame) journeyFrame = window.requestAnimationFrame(updateJourneyMotion);
    };
    window.addEventListener("scroll", scheduleJourneyMotion, { passive: true });
    window.addEventListener("resize", scheduleJourneyMotion);
    reducedMotion?.addEventListener?.("change", scheduleJourneyMotion);
    scheduleJourneyMotion();
  }

  const loginForm = $("#login-form");
  loginForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = $("#login-error");
    const button = $("[type=submit]", loginForm);
    hideFeedback(feedback);
    button.disabled = true;
    try {
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ identifiant: loginForm.elements.identifiant.value, password: loginForm.elements.password.value }) });
      const next = new URLSearchParams(location.search).get("next");
      navigateTo(next && next.startsWith("/") && !next.startsWith("//") ? next : result.role === "ADMIN" ? "/admin.html" : "/espace-candidat.html");
    } catch (error) { showFeedback(feedback, error.message, "error"); }
    finally { button.disabled = false; }
  });

  const registerForm = $("#register-form");
  registerForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = $("[data-form-feedback]", registerForm);
    const button = $("[type=submit]", registerForm);
    hideFeedback(feedback);
    if (registerForm.elements.password.value !== registerForm.elements.confirmation.value) {
      showFeedback(feedback, "La confirmation du mot de passe ne correspond pas.", "error");
      registerForm.elements.confirmation.focus();
      return;
    }
    button.disabled = true;
    try {
      const result = await api("/api/auth/register", { method: "POST", body: JSON.stringify({ nom: registerForm.elements.nom.value, prenoms: registerForm.elements.prenoms.value, email: registerForm.elements.email.value, password: registerForm.elements.password.value, confirmation: registerForm.elements.confirmation.value }) });
      showFeedback(feedback, result.message || "Votre dossier est créé. Vous pouvez commencer à le compléter.", "success");
      window.setTimeout(() => navigateTo("/candidature.html"), 850);
    } catch (error) { showFeedback(feedback, error.message, "error"); }
    finally { button.disabled = false; }
  });

  const forgotPasswordForm = $("[data-password-forgot]");
  forgotPasswordForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = $("[data-password-forgot-feedback]", forgotPasswordForm);
    const button = $("[type=submit]", forgotPasswordForm);
    hideFeedback(feedback);
    button.disabled = true;
    try {
      const result = await api("/api/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ email: forgotPasswordForm.elements.email.value }),
      });
      showFeedback(feedback, result.message, "success");
    } catch (error) { showFeedback(feedback, error.message, "error"); }
    finally { button.disabled = false; }
  });

  const resetPasswordForm = $("[data-password-reset]");
  resetPasswordForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = $("[data-password-reset-feedback]", resetPasswordForm);
    const button = $("[type=submit]", resetPasswordForm);
    hideFeedback(feedback);
    if (resetPasswordForm.elements.new_password.value !== resetPasswordForm.elements.confirmation.value) {
      showFeedback(feedback, "La confirmation du mot de passe ne correspond pas.", "error");
      resetPasswordForm.elements.confirmation.focus();
      return;
    }
    if (!resetPasswordForm.elements.token.value) {
      showFeedback(feedback, "Ce lien est incomplet ou expiré. Demandez-en un nouveau.", "error");
      return;
    }
    button.disabled = true;
    try {
      const result = await api("/api/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({
          token: resetPasswordForm.elements.token.value,
          new_password: resetPasswordForm.elements.new_password.value,
          confirmation: resetPasswordForm.elements.confirmation.value,
        }),
      });
      showFeedback(feedback, result.message, "success");
      resetPasswordForm.reset();
      window.setTimeout(() => navigateTo("/connexion.html"), 1200);
    } catch (error) { showFeedback(feedback, error.message, "error"); }
    finally { button.disabled = false; }
  });

  $$('[data-logout-all]').forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    try { await api("/api/auth/logout-all", { method: "POST" }); navigateTo("/index.html"); }
    catch (error) { showFeedback(button.closest(".card")?.querySelector(".form-feedback"), error.message, "error"); button.disabled = false; }
  }));

  const contactForm = $("[data-contact-form]");
  contactForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = $(`[data-contact-feedback]`, contactForm);
    const button = $("[type=submit]", contactForm);
    hideFeedback(feedback); button.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(contactForm));
      const result = await api("/api/contact", { method: "POST", body: JSON.stringify(data) });
      contactForm.reset(); showFeedback(feedback, result.message, "success");
    } catch (error) { showFeedback(feedback, error.message, "error"); }
    finally { button.disabled = false; }
  });

  async function fetchDocuments() {
    const documents = await api("/api/candidature/documents");
    // La convocation est un document officiel séparé, pas une pièce à fournir.
    return documents.filter((document) => Object.hasOwn(docLabels, document.type_document));
  }
  function updateDocumentCards(documents, feedbackSelector = "[data-documents-feedback]") {
    const byType = new Map(documents.map((doc) => [doc.type_document, doc]));
    $$('[data-document-card]').forEach((card) => {
      const type = card.dataset.documentCard;
      const doc = byType.get(type);
      const status = $(`[data-document-status]`, card);
      const check = $(`[data-document-check]`, card);
      const download = $(`[data-document-download]`, card);
      const remove = $(`[data-document-delete]`, card);
      card.classList.toggle("is-uploaded", Boolean(doc));
      if (status) status.textContent = doc ? `${doc.nom_original} · déposé le ${dateFr(doc.created_at, { dateStyle: "medium" })}` : "À déposer · PDF, JPG ou PNG · 5 Mo maximum";
      if (check) { check.textContent = doc ? "✓" : "○"; check.setAttribute("aria-label", doc ? "Pièce déposée" : "Pièce manquante"); }
      if (download) { download.hidden = !doc; download.href = doc ? `/api/candidature/documents/${doc.id}/download` : "#"; download.textContent = "Télécharger"; }
      if (remove) { remove.hidden = !doc; remove.dataset.documentId = doc?.id || ""; }
    });
    const count = documents.length;
    const progress = $("[data-documents-progress]");
    if (progress) progress.textContent = String(count);
    const bar = $("[data-documents-progress-bar]");
    if (bar) bar.style.width = `${count * 10}%`;
    const reviewCount = $("[data-review-documents]");
    if (reviewCount) reviewCount.innerHTML = `<div class="review-row"><strong>Pièces justificatives</strong><span>${count} sur 10 déposées</span><button type="button" class="text-button" data-jump-step="5">Modifier</button></div>`;
    const readiness = $("[data-submit-readiness]");
    if (readiness) readiness.textContent = count === 10 ? "Vos dix pièces sont déposées. Vous pouvez transmettre votre dossier après vérification." : `Il vous reste ${10 - count} pièce${10 - count > 1 ? "s" : ""} à déposer avant la soumission.`;
  }
  async function loadDocuments() {
    const docs = await fetchDocuments();
    updateDocumentCards(docs);
    return docs;
  }
  document.addEventListener("change", async (event) => {
    const input = event.target.closest("[data-document-input]");
    if (!input || !input.files?.[0]) return;
    const file = input.files[0];
    const feedback = $("[data-documents-feedback]") || $("[data-application-feedback]");
    if (file.size > 5 * 1024 * 1024) { showFeedback(feedback, "Le fichier dépasse la limite de 5 Mo.", "error"); input.value = ""; return; }
    const formData = new FormData(); formData.append("type_document", input.dataset.documentInput); formData.append("file", file);
    const card = input.closest("[data-document-card]");
    const status = card && $(`[data-document-status]`, card);
    if (status) status.textContent = "Envoi en cours…";
    card?.classList.add("is-uploading");
    try { await api("/api/candidature/documents", { method: "POST", body: formData }); await loadDocuments(); showFeedback(feedback, "Document enregistré.", "success"); }
    catch (error) { showFeedback(feedback, error.message, "error"); if (status) status.textContent = "À déposer · PDF, JPG ou PNG · 5 Mo maximum"; }
    finally { card?.classList.remove("is-uploading"); input.value = ""; }
  });
  document.addEventListener("click", async (event) => {
    const remove = event.target.closest("[data-document-delete]");
    if (remove) {
      const feedback = $("[data-documents-feedback]") || $("[data-application-feedback]");
      remove.disabled = true;
      try { await api(`/api/candidature/documents/${remove.dataset.documentId}`, { method: "DELETE" }); await loadDocuments(); showFeedback(feedback, "Document retiré.", "success"); }
      catch (error) { showFeedback(feedback, error.message, "error"); remove.disabled = false; }
      return;
    }
    const jump = event.target.closest("[data-jump-step]");
    if (jump) setApplicationStep(Number(jump.dataset.jumpStep));
  });

  const application = $('[data-portal-view="application"]');
  if (application) {
    const form = $("#application-form", application);
    const feedback = $(`[data-application-feedback]`, application);
    const indicator = $(`[data-save-indicator]`, application);
    const fieldsByStep = {
      1: ["code_tresor_pay", "nom", "prenoms", "sexe", "date_naissance", "lieu_naissance", "nationalite", "nature_piece", "numero_piece", "email", "telephone", "commune", "ville", "adresse"],
      2: ["annee_bac", "serie_bac", "numero_bac", "numero_table", "mention", "moyenne_bac", "note_math_bac", "note_physique_bac", "note_francais_bac", "note_anglais_bac"],
      3: ["choix_1_filiere", "choix_2_filiere"],
      4: ["tuteur1_nom", "tuteur1_contact", "tuteur1_lien", "tuteur1_residence", "tuteur2_nom", "tuteur2_contact", "tuteur2_lien", "tuteur2_residence"]
    };
    let currentStep = 1, candidature = null, submitted = false, documentData = [];
    function setApplicationStep(step, { focus = true } = {}) {
      const nextStep = Math.max(1, Math.min(7, step));
      application.dataset.stepDirection = nextStep < currentStep ? "back" : "forward";
      currentStep = nextStep;
      $$('[data-step-panel]', application).forEach((panel) => { panel.hidden = Number(panel.dataset.stepPanel) !== currentStep; });
      $$('[data-step-link]', application).forEach((link) => { const n = Number(link.dataset.stepLink); link.classList.toggle("is-current", n === currentStep); link.classList.toggle("is-complete", n < currentStep); link.setAttribute("aria-current", n === currentStep ? "step" : "false"); });
      const label = $(`[data-progress-label]`, application); if (label) label.textContent = `Étape ${currentStep} sur 7`;
      const progress = `${(currentStep / 7) * 100}%`;
      const bar = $(`[data-progress-bar]`, application); if (bar) bar.style.width = progress;
      application.style.setProperty("--step-progress", progress);
      if (indicator) {
        indicator.removeAttribute("data-save-state");
        indicator.textContent = currentStep < 5 ? "Vos réponses se sauvegardent à chaque étape" : currentStep === 5 ? "Chaque pièce se dépose séparément" : currentStep === 6 ? "Vérifiez chaque élément avant l’envoi" : "Votre confirmation est nécessaire avant l’envoi";
      }
      const back = $(`[data-step-back]`, application), next = $(`[data-step-next]`, application);
      if (back) back.disabled = currentStep === 1;
      if (next) { next.hidden = currentStep === 7 || submitted; next.textContent = currentStep === 6 ? "Continuer vers la soumission →" : "Enregistrer et continuer →"; }
      if (currentStep === 6) buildReview();
      application.scrollIntoView({ behavior: "smooth", block: "start" });
      if (focus) requestAnimationFrame(() => $(`[data-step-panel="${currentStep}"] h2`, application)?.focus({ preventScroll: true }));
    }
    window.setApplicationStep = setApplicationStep;
    function fillApplication(data) {
      candidature = data;
      const dossier = $(`[data-dossier-number]`, application); if (dossier) dossier.textContent = data.numero_dossier || "—";
      for (const [key, value] of Object.entries(data)) {
        const field = form.elements.namedItem(key);
        if (field && value !== null && value !== undefined) field.value = value;
      }
      const displayStep = Math.min(7, Math.max(1, data.etape_courante || 1));
      submitted = data.statut !== "DRAFT";
      if (submitted) {
        showFeedback(feedback, "Votre dossier a été transmis au jury. Les modifications sont désactivées.", "success");
        $$('input,select,textarea,button[data-step-next],button[data-submit-application]', form).forEach((el) => { if (!el.matches("[data-step-back], [data-step-link]")) el.disabled = true; });
        $$('[data-step-link]', application).forEach((el) => { el.disabled = true; });
      }
      setApplicationStep(displayStep, { focus: false });
    }
    function collectStep(step) {
      const payload = { etape_courante: step };
      for (const name of fieldsByStep[step] || []) {
        const field = form.elements.namedItem(name);
        if (!field || !String(field.value).trim()) continue;
        payload[name] = field.type === "number" ? Number(field.value) : field.value.trim();
      }
      return payload;
    }
    async function saveStep(step) {
      if (step > 4) return true;
      const payload = collectStep(step);
      if (step === 3 && payload.choix_1_filiere && payload.choix_2_filiere === payload.choix_1_filiere) { showFeedback(feedback, "Les deux choix de formation doivent être différents.", "error"); return false; }
      if (indicator) { indicator.textContent = "Enregistrement…"; indicator.dataset.saveState = "saving"; }
      hideFeedback(feedback);
      try { candidature = await api("/api/candidature", { method: "PATCH", body: JSON.stringify(payload) }); if (indicator) { indicator.textContent = "Enregistré"; indicator.dataset.saveState = "saved"; } return true; }
      catch (error) { showFeedback(feedback, error.message, "error"); if (indicator) { indicator.textContent = "Enregistrement à reprendre"; indicator.dataset.saveState = "error"; } return false; }
    }
    function buildReview() {
      const target = $(`[data-application-review]`, application); if (!target) return;
      const groups = [
        ["Informations personnelles", 1, ["nom", "prenoms", "sexe", "date_naissance", "lieu_naissance", "nationalite", "nature_piece", "numero_piece", "email", "telephone", "commune", "ville", "adresse"]],
        ["Parcours académique", 2, ["annee_bac", "serie_bac", "numero_bac", "numero_table", "mention", "moyenne_bac"]],
        ["Choix de formation", 3, ["choix_1_filiere", "choix_2_filiere"]],
        ["Tuteurs", 4, ["tuteur1_nom", "tuteur1_contact", "tuteur1_lien", "tuteur1_residence", "tuteur2_nom", "tuteur2_contact", "tuteur2_lien", "tuteur2_residence"]]
      ];
      target.innerHTML = groups.map(([title, step, fields]) => `<section class="review-section"><div class="review-section-head"><h3>${escapeHtml(title)}</h3><button type="button" class="text-button" data-jump-step="${step}">Modifier</button></div>${fields.map((name) => { const field = form.elements.namedItem(name); const label = field?.id ? $(`label[for="${field.id}"]`, form)?.textContent : name; return `<div class="review-row"><span>${escapeHtml(label || name)}</span><strong>${escapeHtml(field?.value || "—")}</strong></div>`; }).join("")}</section>`).join("");
    }
    $$('[data-step-link]', application).forEach((button) => button.addEventListener("click", async () => { if (await saveStep(currentStep)) { if (currentStep === 5) documentData = await loadDocuments().catch(() => []); setApplicationStep(Number(button.dataset.stepLink)); } }));
    $(`[data-step-next]`, application)?.addEventListener("click", async () => { if (currentStep === 5) { try { documentData = await loadDocuments(); } catch (error) { showFeedback(feedback, error.message, "error"); return; } } if (await saveStep(currentStep)) setApplicationStep(currentStep + 1); });
    $(`[data-step-back]`, application)?.addEventListener("click", () => setApplicationStep(currentStep - 1));
    $(`[data-submit-application]`, application)?.addEventListener("click", async (event) => {
      const confirm = $(`[data-submit-confirmation]`, application);
      if (!confirm.checked) { showFeedback(feedback, "Cochez la certification avant de transmettre votre dossier.", "error"); return; }
      const button = event.currentTarget; button.disabled = true;
      try { const result = await api("/api/candidature/submit", { method: "POST", body: JSON.stringify({ confirmation: true, consentement_tiers: $(`[data-submit-consent]`, application).checked }) }); showFeedback(feedback, `${result.message} Numéro de dossier : ${result.numero_dossier}.`, "success"); setTimeout(() => navigateTo("/suivi.html"), 1100); }
      catch (error) { showFeedback(feedback, error.message, "error"); button.disabled = false; }
    });
    Promise.all([api("/api/candidature"), loadDocuments()]).then(([data, docs]) => { documentData = docs; fillApplication(data); }).catch((error) => showFeedback(feedback, error.message, "error"));
  }

  const documentsView = $('[data-portal-view="documents"]');
  if (documentsView) loadDocuments().catch((error) => showFeedback($(`[data-documents-feedback]`, documentsView), error.message, "error"));

  const dashboard = $('[data-portal-view="dashboard"]');
  if (dashboard) Promise.all([api("/api/me"), api("/api/candidature"), fetchDocuments(), api("/api/candidature/status"), api("/api/candidature/convocation"), api("/api/candidature/admission")]).then(([me, app, docs, status, convocation, admission]) => {
    const name = app.prenoms || me.nom_affiche || ""; $(`[data-candidate-name]`, dashboard).textContent = name ? `, ${name}` : "";
    $(`[data-dashboard-status]`, dashboard).textContent = status.statut_label || "Dossier en cours";
    $(`[data-dashboard-summary]`, dashboard).textContent = status.statut === "DRAFT" ? "Votre dossier est enregistré. Continuez à renseigner les informations nécessaires." : "Votre dossier a quitté le formulaire candidat. Consultez son avancement et les prochaines informations ici.";
    const percent = Math.round(((status.etape_courante || 1) / 7) * 100);
    animateCounter($(`[data-dashboard-progress]`, dashboard), percent, "%"); $(`[data-dashboard-progress-bar]`, dashboard).style.width = `${percent}%`;
    $(`[data-dashboard-stage]`, dashboard).textContent = `Étape ${status.etape_courante || 1} sur 7 · ${steps[(status.etape_courante || 1) - 1]}`;
    $(`[data-dashboard-number]`, dashboard).textContent = app.numero_dossier; animateCounter($(`[data-dashboard-documents]`, dashboard), docs.length); $(`[data-dashboard-step]`, dashboard).textContent = `${status.etape_courante || 1} / 7`;
    if (status.statut !== "DRAFT") {
      const applicationCard = $('[data-portal-view="dashboard"] .dashboard-card[href="/candidature.html"]', dashboard);
      if (applicationCard) {
        const title = $("h3", applicationCard); const copy = $("p", applicationCard); const action = $("b", applicationCard);
        if (title) title.textContent = "Ma candidature";
        if (copy) copy.textContent = "Retrouver les informations transmises au jury.";
        if (action) action.textContent = "Consulter le dossier →";
      }
    }
    const convocationTitle = $(`[data-dashboard-convocation-title]`, dashboard);
    const convocationCopy = $(`[data-dashboard-convocation-copy]`, dashboard);
    const convocationLink = $(`[data-dashboard-convocation-link]`, dashboard);
    if (convocation.disponible) {
      convocationTitle.textContent = "Convocation publiée";
      convocationCopy.textContent = `${dateFr(convocation.date_compo)}${convocation.heure_compo ? ` à ${convocation.heure_compo}` : ""} · ${convocation.centre_compo}`;
      convocationLink.hidden = false;
    }
    const resultTitle = $(`[data-dashboard-result-title]`, dashboard);
    const resultCopy = $(`[data-dashboard-result-copy]`, dashboard);
    const resultLink = $(`[data-dashboard-result-link]`, dashboard);
    if (admission.disponible) {
      resultTitle.textContent = admission.admis ? "Résultat : admis(e)" : "Résultat publié";
      resultCopy.textContent = admission.admis && admission.filiere_formation ? `Formation attribuée : ${admission.filiere_formation}` : admission.message;
      resultLink.hidden = false;
    }
    if (status.statut !== "DRAFT") {
      const primaryAction = $(".dashboard-welcome > a", dashboard);
      if (primaryAction) {
        if (admission.disponible) { primaryAction.href = "/resultat.html"; primaryAction.textContent = "Voir ma décision ↗"; }
        else if (convocation.disponible) { primaryAction.href = "/convocation.html"; primaryAction.textContent = "Voir ma convocation ↗"; }
        else { primaryAction.href = "/suivi.html"; primaryAction.textContent = "Consulter mon suivi ↗"; }
      }
    }
  }).catch((error) => showFeedback($(`[data-dashboard-summary]`, dashboard), error.message, "error"));

  const profile = $('[data-portal-view="profile"]');
  if (profile) api("/api/me").then(async (me) => {
    const app = me.role === "ADMIN" ? null : await api("/api/candidature").catch(() => null);
    const display = app && `${app.prenoms || ""} ${app.nom || ""}`.trim() || me.nom_affiche || me.email;
    $(`[data-profile-name]`, profile).textContent = display; $(`[data-profile-email]`, profile).textContent = me.email;
    $(`[data-profile-role]`, profile).textContent = me.role === "ADMIN" ? "Administration" : "Candidat";
    if (me.numero_dossier) $(`[data-profile-dossier]`, profile).textContent = me.numero_dossier; else $(`[data-profile-dossier-row]`, profile).hidden = true;
    $(`[data-profile-initials]`, profile).textContent = display.split(/\s+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
    const consentPanel = $(`[data-profile-ai-consent]`, profile);
    if (me.role !== "ADMIN" && consentPanel && app) {
      consentPanel.hidden = false;
      try {
        const consent = await api("/api/candidature/consentement-ia");
        $(`[data-ai-consent-toggle]`, consentPanel).checked = consent.accorde;
      } catch (error) {
        showFeedback($(`[data-ai-consent-feedback]`, consentPanel), error.message, "error");
      }
    }
  }).catch((error) => showFeedback($("[data-profile-feedback]", profile), error.message, "error"));

  const aiConsentPanel = $(`[data-profile-ai-consent]`);
  const aiConsentToggle = $(`[data-ai-consent-toggle]`, aiConsentPanel || document);
  aiConsentToggle?.addEventListener("change", async () => {
    const feedback = $(`[data-ai-consent-feedback]`, aiConsentPanel);
    const accepted = aiConsentToggle.checked;
    aiConsentToggle.disabled = true;
    hideFeedback(feedback);
    try {
      const result = await api("/api/candidature/consentement-ia", {
        method: "PUT",
        body: JSON.stringify({ consentement: accepted }),
      });
      showFeedback(feedback, accepted
        ? "Accord enregistré. L’administration pourra lancer une lecture assistée des pièces."
        : "Accord retiré. Aucune nouvelle pièce ne sera envoyée au fournisseur IA.", "success");
    } catch (error) {
      aiConsentToggle.checked = !accepted;
      showFeedback(feedback, error.message, "error");
    } finally { aiConsentToggle.disabled = false; }
  });

  const passwordChangeForm = $("[data-password-change]");
  passwordChangeForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = $("[data-password-change-feedback]", passwordChangeForm);
    const button = $("[type=submit]", passwordChangeForm);
    hideFeedback(feedback);
    if (passwordChangeForm.elements.new_password.value !== passwordChangeForm.elements.confirmation.value) {
      showFeedback(feedback, "La confirmation du mot de passe ne correspond pas.", "error");
      passwordChangeForm.elements.confirmation.focus();
      return;
    }
    button.disabled = true;
    try {
      const result = await api("/api/auth/password/change", {
        method: "POST",
        body: JSON.stringify({
          current_password: passwordChangeForm.elements.current_password.value,
          new_password: passwordChangeForm.elements.new_password.value,
          confirmation: passwordChangeForm.elements.confirmation.value,
        }),
      });
      passwordChangeForm.reset();
      showFeedback(feedback, result.message, "success");
    } catch (error) { showFeedback(feedback, error.message, "error"); }
    finally { button.disabled = false; }
  });

  const tracking = $('[data-portal-view="tracking"]');
  if (tracking) Promise.all([api("/api/candidature/status"), api("/api/candidature")]).then(([status, app]) => {
    $$('[data-dossier-number]', tracking).forEach((el) => el.textContent = status.numero_dossier);
    $(`[data-tracking-status]`, tracking).textContent = status.statut_label;
    const submitted = status.statut !== "DRAFT";
    $(`[data-tracking-copy]`, tracking).textContent = submitted ? "Votre dossier a été transmis. Les prochaines informations seront publiées dans cet espace." : "Votre dossier est encore en préparation. Vous pouvez reprendre les étapes à tout moment.";
    const current = Math.min(7, status.etape_courante || 1);
    $(`[data-tracking-timeline]`, tracking).innerHTML = steps.map((label, i) => `<div class="tracking-event ${i + 1 < current || submitted ? "is-complete" : i + 1 === current ? "is-current" : ""}"><span>${String(i + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(label)}</strong><small>${i + 1 < current || submitted ? "Étape franchie" : i + 1 === current ? "Étape en cours" : "À venir"}</small></div></div>`).join("");
    $(`[data-tracking-next]`, tracking).textContent = submitted ? "Suivre les prochaines décisions du jury." : `Compléter : ${steps[current - 1]}.`;
    $(`[data-tracking-next-copy]`, tracking).textContent = submitted ? "La convocation et la décision seront ajoutées ici lorsqu’elles seront disponibles." : `Votre progression est à l’étape ${current} sur 7. Le dossier peut être repris dans votre espace candidat.`;
  }).catch((error) => showFeedback($(`[data-tracking-copy]`, tracking), error.message, "error"));

  const convocation = $('[data-portal-view="convocation"]');
  if (convocation) api("/api/candidature/convocation").then((data) => {
    $$('[data-dossier-number]', convocation).forEach((el) => el.textContent = data.numero_dossier || "—");
    $(`[data-convocation-heading]`, convocation).textContent = data.disponible ? "Votre composition est programmée." : "La date n’est pas encore disponible.";
    $(`[data-convocation-message]`, convocation).textContent = data.message || (data.disponible ? "Retrouvez ci-dessous les informations de votre composition." : "La convocation apparaîtra ici dès que le jury aura fixé votre centre et votre date.");
    if (data.disponible) {
      $(`[data-convocation-details]`, convocation).hidden = false;
      $(`[data-convocation-date]`, convocation).textContent = `${dateFr(data.date_compo)}${data.heure_compo ? ` · ${data.heure_compo}` : " · horaire à confirmer"}`;
      $(`[data-convocation-centre]`, convocation).textContent = data.centre_compo;
      if (data.convocation_url) $(`[data-convocation-download]`, convocation).hidden = false;
      convocation.classList.add("is-ready");
    }
  }).catch((error) => showFeedback($(`[data-convocation-message]`, convocation), error.message, "error"));

  const resultView = $('[data-portal-view="result"]');
  if (resultView) api("/api/candidature/admission").then((data) => {
    if (!data.disponible) return;
    $(`[data-result-heading]`, resultView).innerHTML = data.admis ? "Félicitations,<br /><em>vous êtes admis.</em>" : "La décision<br /><em>du jury est publiée.</em>";
    $(`[data-result-message]`, resultView).textContent = data.message;
    if (data.filiere_formation) { $(`[data-result-specialty]`, resultView).hidden = false; $(`[data-result-program]`, resultView).textContent = data.filiere_formation; }
    if (data.date_decision) {
      $(`[data-result-meta]`, resultView).hidden = false;
      $(`[data-result-date]`, resultView).textContent = dateFr(data.date_decision);
    }
    const grades = Object.entries(data.notes || {});
    if (grades.length) {
      const gradesList = $(`[data-result-grades]`, resultView);
      gradesList.innerHTML = grades.map(([subject, score]) => `<div class="result-grade-row"><span>${escapeHtml(subject)}</span><strong>${escapeHtml(score)} / 20</strong></div>`).join("");
      gradesList.hidden = false;
    }
    const certificate = $(`[data-result-certificate]`, resultView);
    if (data.certificat_url) { certificate.href = data.certificat_url; certificate.hidden = false; }
    resultView.classList.toggle("is-admitted", Boolean(data.admis));
    resultView.classList.add("is-published");
  }).catch((error) => showFeedback($(`[data-result-message]`, resultView), error.message, "error"));

  const admin = $('[data-portal-view="admin"]');
  if (admin) {
    let offset = 0, limit = 50, selectedDossier = null;
    const feedback = $(`[data-admin-feedback]`, admin);
    const statusLabels = { DRAFT: "Brouillon", SUBMITTED: "Dossier soumis", UNDER_REVIEW: "En cours d’examen", VALIDATED: "Dossier validé", RETAINED: "Dossier retenu", REJECTED: "Non retenu", COMPOSITION_SCHEDULED: "Composition programmée", ADMITTED: "Admis" };
    function renderVerification(report, panel) {
      const target = $(`[data-verification-report]`, panel);
      const modelStates = {
        terminee: "Analyse IA terminée",
        partielle: "Analyse IA partielle",
        erreur: "Le fournisseur IA a rencontré une erreur",
        sans_piece: "Aucune pièce à analyser",
        consentement_requis: "Accord du candidat requis",
        non_configuree: "Variables IA manquantes dans Render",
        desactivee: "Analyse IA désactivée",
        url_invalide: "URL IA non sécurisée",
        a_lancer: "Modèle prêt à lancer",
      };
      const statuses = { signalement: "À examiner", indeterminate: "À vérifier manuellement", conforme: "Aucune incohérence apparente" };
      const findings = report?.constats || [];
      const message = report?.lecture_modele_message || "";
      target.innerHTML = `<div class="verification-status-grid"><article><span>Contrôles déterministes</span><strong>${report?.analyse ? "Effectués" : "Pas encore lancés"}</strong><small>${Number(report?.resume?.signalements || 0)} signalement(s) · ${Number(report?.resume?.indetermines || 0)} point(s) indéterminé(s)</small></article><article><span>Lecture par modèle IA</span><strong>${escapeHtml(modelStates[report?.lecture_modele] || "En attente")}</strong><small>${escapeHtml(message)}</small></article></div>${findings.length ? `<ul class="verification-findings">${findings.map((item) => `<li><div><strong>${escapeHtml(item.libelle || item.controle || "Constat")}</strong>${item.type_document ? `<small>${escapeHtml(item.type_document)}</small>` : ""}</div><span class="verification-finding-status is-${escapeHtml(item.statut)}">${escapeHtml(statuses[item.statut] || item.statut)}</span><p>${escapeHtml(item.message)}</p></li>`).join("")}</ul>` : `<p class="verification-empty">${report?.analyse ? "Aucun écart signalé par les contrôles effectués." : "Aucun contrôle n’a encore été lancé sur ce dossier."}</p>`}<p class="verification-consent ${report?.consentement?.accorde ? "is-accepted" : "is-missing"}"><strong>Accord pour l’IA :</strong> ${report?.consentement?.accorde ? `donné le ${escapeHtml(dateFr(report.consentement.le, { dateStyle: "medium" }))}` : "non donné. Les pièces ne sont pas envoyées au fournisseur."}</p>`;
    }
    async function loadOverview() {
      const [data, me] = await Promise.all([api("/api/admin/overview"), api("/api/me")]);
      $(`[data-admin-total]`, admin).textContent = data.dossiers_total; $(`[data-admin-submitted]`, admin).textContent = data.dossiers_soumis;
      $(`[data-admin-documents]`, admin).textContent = data.documents; $(`[data-admin-unread]`, admin).textContent = data.messages_non_lus; $(`[data-admin-email]`, admin).textContent = me.email;
      const codes = Object.keys(statusLabels);
      $(`[data-admin-breakdown]`, admin).innerHTML = codes.map((code) => { const count = data.par_statut?.[code] || 0; const ratio = data.dossiers_total ? count / data.dossiers_total * 100 : 0; return `<div class="breakdown-row"><span>${statusLabels[code]}</span><strong>${count}</strong><i><b style="width:${ratio}%"></b></i></div>`; }).join("");
      const actions = data.dernieres_actions || [];
      $(`[data-admin-activity]`, admin).innerHTML = actions.length ? actions.map((a) => `<article><span>${escapeHtml(a.action)}</span><strong>${escapeHtml(a.numero_dossier || "Portail")}</strong><small>${dateFr(a.horodatage, { dateStyle: "short", timeStyle: "short" })} · ${escapeHtml(a.admin)}</small></article>`).join("") : '<p class="empty-state">Aucune action enregistrée pour le moment.</p>';
    }
    async function loadApplications() {
      const form = $(`[data-admin-filter]`, admin); const q = new FormData(form).get("q") || ""; const statut = new FormData(form).get("statut") || "";
      const params = new URLSearchParams({ limite: limit, decalage: offset }); if (q) params.set("q", q); if (statut) params.set("statut", statut);
      const data = await api(`/api/admin/candidatures?${params}`);
      $(`[data-admin-result-count]`, admin).textContent = `${data.total} dossier${data.total === 1 ? "" : "s"}`;
      const tbody = $(`[data-admin-results]`, admin);
      tbody.innerHTML = data.resultats.length ? data.resultats.map((r) => `<tr><td><strong>${escapeHtml(r.numero_dossier)}</strong></td><td>${escapeHtml(`${r.prenoms || ""} ${r.nom || ""}`.trim() || "Candidat")}</td><td>${escapeHtml(r.choix_1_filiere || "—")}</td><td>${r.pieces_deposees}/${r.pieces_total}</td><td><span class="status-chip">${escapeHtml(r.statut_label)}</span></td><td><button type="button" class="text-button" data-open-dossier="${escapeHtml(r.numero_dossier)}">Ouvrir →</button></td></tr>`).join("") : '<tr><td colspan="6">Aucun dossier ne correspond à ces filtres.</td></tr>';
      const pagination = $(`[data-admin-pagination]`, admin);
      pagination.innerHTML = `<button type="button" data-page-back ${offset <= 0 ? "disabled" : ""}>← Précédent</button><span>${data.total ? offset + 1 : 0}–${Math.min(offset + data.resultats.length, data.total)} sur ${data.total}</span><button type="button" data-page-next ${offset + limit >= data.total ? "disabled" : ""}>Suivant →</button>`;
    }
    async function openDossier(numero) {
      selectedDossier = numero; const result = await api(`/api/admin/candidatures/${encodeURIComponent(numero)}`); const d = result.dossier;
      const panel = $(`[data-admin-detail]`, admin); panel.hidden = false; $(`[data-detail-title]`, panel).textContent = `${d.numero_dossier} · ${d.prenoms || ""} ${d.nom || ""}`;
      $(`[data-detail-summary]`, panel).innerHTML = [["Identité", `${d.prenoms || ""} ${d.nom || ""}`, d.email, d.telephone, d.date_naissance, d.lieu_naissance, d.nationalite, d.nature_piece, d.numero_piece, d.adresse], ["Baccalauréat", d.annee_bac, d.serie_bac, d.numero_bac, d.numero_table, d.mention, d.moyenne_bac], ["Choix", d.choix_1_filiere, d.choix_2_filiere], ["Tuteur principal", d.tuteur1?.nom, d.tuteur1?.contact, d.tuteur1?.lien, d.tuteur1?.residence], ["Second tuteur", d.tuteur2?.nom, d.tuteur2?.contact, d.tuteur2?.lien, d.tuteur2?.residence]].map(([title, ...values]) => `<section><h3>${escapeHtml(title)}</h3><p>${values.filter(Boolean).map(escapeHtml).join(" · ") || "—"}</p></section>`).join("");
      $(`[data-detail-documents]`, panel).innerHTML = `<h3>Pièces déposées (${result.documents.length}/10)</h3><ul>${result.documents.map((doc) => `<li><a href="${escapeHtml(doc.url)}">${escapeHtml(doc.nom_original || doc.type_document)} ↓</a><small>${escapeHtml(doc.type_document)} · ${dateFr(doc.depose_le, { dateStyle: "medium" })}</small></li>`).join("") || "<li>Aucune pièce déposée.</li>"}</ul>`;
      renderVerification(result.verification, panel);
      const convocationDownload = $(`[data-admin-convocation-download]`, panel);
      convocationDownload.hidden = !d.date_compo || !d.centre_compo;
      convocationDownload.href = `/api/admin/candidatures/${encodeURIComponent(numero)}/convocation.pdf`;
      const resultDownload = $(`[data-admin-result-download]`, panel);
      resultDownload.hidden = d.admis_concours === null || d.admis_concours === undefined;
      resultDownload.href = `/api/admin/candidatures/${encodeURIComponent(numero)}/resultat.pdf`;
      const decision = $(`[data-decision-form]`, panel); decision.elements.statut.value = d.statut || "SUBMITTED"; decision.elements.filiere_formation.value = d.filiere_formation || ""; decision.elements.date_compo.value = d.date_compo || ""; decision.elements.heure_compo.value = d.heure_compo || ""; decision.elements.centre_compo.value = d.centre_compo || ""; decision.elements.note_interne.value = d.note_interne || ""; decision.elements.note_francais_compo.value = d.notes_compo?.francais ?? ""; decision.elements.note_math_compo.value = d.notes_compo?.math ?? ""; decision.elements.note_anglais_compo.value = d.notes_compo?.anglais ?? ""; decision.elements.note_psycho_compo.value = d.notes_compo?.psycho ?? ""; decision.elements.motif_refus.value = d.motif_refus || "";
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    async function loadMessages() {
      const status = $(`[data-message-filter]`, admin).value; const query = status ? `?statut=${encodeURIComponent(status)}` : ""; const data = await api(`/api/admin/messages${query}`);
      $(`[data-admin-messages]`, admin).innerHTML = data.messages.length ? data.messages.map((m) => `<article class="message-card"><div class="panel-inline-heading"><div><span class="kicker">${escapeHtml(m.objet)}</span><h3>${escapeHtml(m.nom)}</h3></div><select aria-label="Statut du message" data-message-status="${m.id}"><option value="NOUVEAU" ${m.statut === "NOUVEAU" ? "selected" : ""}>Nouveau</option><option value="EN_COURS" ${m.statut === "EN_COURS" ? "selected" : ""}>En cours</option><option value="TRAITE" ${m.statut === "TRAITE" ? "selected" : ""}>Traité</option><option value="ARCHIVE" ${m.statut === "ARCHIVE" ? "selected" : ""}>Archivé</option></select></div><p>${escapeHtml(m.message)}</p><small>${escapeHtml(m.email)}${m.telephone ? ` · ${escapeHtml(m.telephone)}` : ""} · ${dateFr(m.cree_le, { dateStyle: "medium", timeStyle: "short" })}</small></article>`).join("") : '<p class="empty-state">Aucun message pour ce filtre.</p>';
    }
    async function loadAccounts() {
      const data = await api("/api/admin/comptes");
      $(`[data-admin-accounts]`, admin).innerHTML = data.comptes.length ? data.comptes.map((u) => `<article><span class="admin-avatar">${escapeHtml((u.nom_affiche || u.email).slice(0, 2).toUpperCase())}</span><div><strong>${escapeHtml(u.nom_affiche || u.email)}</strong><small>${escapeHtml(u.email)} · ${escapeHtml(u.role)} · ${u.actif ? "Actif" : "Désactivé"}</small></div></article>`).join("") : '<p class="empty-state">Aucun compte.</p>';
    }
    loadOverview().catch((error) => showFeedback(feedback, error.message, "error"));
    $(`[data-admin-refresh]`, admin)?.addEventListener("click", () => loadOverview().catch((error) => showFeedback(feedback, error.message, "error")));
    $$('[data-admin-tab]', admin).forEach((tab) => tab.addEventListener("click", async () => {
      $$('[data-admin-tab]', admin).forEach((t) => t.classList.toggle("is-active", t === tab));
      $$('[data-admin-panel]', admin).forEach((panel) => panel.hidden = panel.dataset.adminPanel !== tab.dataset.adminTab);
      hideFeedback(feedback);
      try { if (tab.dataset.adminTab === "applications") await loadApplications(); if (tab.dataset.adminTab === "messages") await loadMessages(); if (tab.dataset.adminTab === "accounts") await loadAccounts(); }
      catch (error) { showFeedback(feedback, error.message, "error"); }
    }));
    $$('[data-admin-shortcut]', admin).forEach((shortcut) => shortcut.addEventListener("click", () => {
      const tab = $$('[data-admin-tab]', admin).find((item) => item.dataset.adminTab === shortcut.dataset.adminShortcut);
      tab?.click();
    }));
    if (new URLSearchParams(location.search).get("section") === "applications") {
      $('[data-admin-tab="applications"]', admin)?.click();
    }
    $(`[data-admin-filter]`, admin)?.addEventListener("submit", (event) => { event.preventDefault(); offset = 0; loadApplications().catch((error) => showFeedback(feedback, error.message, "error")); });
    admin.addEventListener("click", (event) => {
      const open = event.target.closest("[data-open-dossier]"); if (open) openDossier(open.dataset.openDossier).catch((error) => showFeedback(feedback, error.message, "error"));
      if (event.target.closest("[data-page-back]")) { offset = Math.max(0, offset - limit); loadApplications().catch((error) => showFeedback(feedback, error.message, "error")); }
      if (event.target.closest("[data-page-next]")) { offset += limit; loadApplications().catch((error) => showFeedback(feedback, error.message, "error")); }
      if (event.target.closest("[data-detail-close]")) $(`[data-admin-detail]`, admin).hidden = true;
    });
    $(`[data-run-verification]`, admin)?.addEventListener("click", async (event) => {
      if (!selectedDossier) return;
      const button = event.currentTarget;
      const panel = $(`[data-admin-detail]`, admin);
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.textContent = "Analyse en cours…";
      hideFeedback(feedback);
      try {
        const report = await api(`/api/admin/candidatures/${encodeURIComponent(selectedDossier)}/controles`, { method: "POST" });
        renderVerification(report, panel);
        button.textContent = "Relancer les contrôles";
        showFeedback(feedback, "Le rapport de contrôle a été actualisé.", "success");
      } catch (error) {
        showFeedback(feedback, error.message, "error");
        button.textContent = "Réessayer les contrôles";
      } finally {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    });
    $(`[data-decision-form]`, admin)?.addEventListener("submit", async (event) => {
      event.preventDefault(); if (!selectedDossier) return;
      const form = event.currentTarget; const button = $("[type=submit]", form); button.disabled = true;
      try {
        const patch = {}; ["filiere_formation", "date_compo", "heure_compo", "centre_compo", "note_interne", "note_francais_compo", "note_math_compo", "note_anglais_compo", "note_psycho_compo"].forEach((key) => { const value = form.elements[key]?.value; if (value !== undefined && String(value).trim() !== "") patch[key] = form.elements[key].type === "number" ? Number(value) : value.trim(); });
        if (Object.keys(patch).length) await api(`/api/admin/candidatures/${encodeURIComponent(selectedDossier)}`, { method: "PATCH", body: JSON.stringify(patch) });
        await api(`/api/admin/candidatures/${encodeURIComponent(selectedDossier)}/statut`, { method: "POST", body: JSON.stringify({ statut: form.elements.statut.value, commentaire: form.elements.commentaire.value, motif_refus: form.elements.motif_refus.value }) });
        showFeedback(feedback, "Décision et informations du dossier enregistrées.", "success"); await loadOverview(); await loadApplications(); await openDossier(selectedDossier);
      } catch (error) { showFeedback(feedback, error.message, "error"); }
      finally { button.disabled = false; }
    });
    $(`[data-convocation-form]`, admin)?.addEventListener("submit", async (event) => {
      event.preventDefault(); if (!selectedDossier) return;
      const form = event.currentTarget; const data = new FormData(form); const button = $("[type=submit]", form); button.disabled = true;
      try { const result = await api(`/api/admin/candidatures/${encodeURIComponent(selectedDossier)}/convocation`, { method: "POST", body: data }); showFeedback(feedback, result.message, "success"); await openDossier(selectedDossier); }
      catch (error) { showFeedback(feedback, error.message, "error"); }
      finally { button.disabled = false; }
    });
    $(`[data-message-filter]`, admin)?.addEventListener("change", () => loadMessages().catch((error) => showFeedback(feedback, error.message, "error")));
    admin.addEventListener("change", async (event) => {
      const select = event.target.closest("[data-message-status]"); if (!select) return;
      try { await api(`/api/admin/messages/${select.dataset.messageStatus}`, { method: "PATCH", body: JSON.stringify({ statut: select.value }) }); showFeedback(feedback, "Statut du message mis à jour.", "success"); await loadOverview(); }
      catch (error) { showFeedback(feedback, error.message, "error"); }
    });
    $(`[data-create-admin]`, admin)?.addEventListener("submit", async (event) => {
      event.preventDefault(); const form = event.currentTarget; const button = $("[type=submit]", form); button.disabled = true;
      try { const result = await api("/api/admin/comptes/admin", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) }); showFeedback(feedback, result.message, "success"); form.reset(); await loadAccounts(); }
      catch (error) { showFeedback(feedback, error.message, "error"); }
      finally { button.disabled = false; }
    });
  }
})();
