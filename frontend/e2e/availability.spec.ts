import { expect, test, type Page } from "@playwright/test";

async function mockApi(page: Page) {
  let rule: object | null = null;
  let weeklySections: unknown[] = [];
  let confirmed = false;
  let cancelled = false;
  let bookedWeek: string | null = null;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const respond = (value: unknown, status = 200) => route.fulfill({
      status, contentType: "application/json", body: JSON.stringify(value),
    });
    const week = path.match(/weeks\/(\d{4}-\d{2}-\d{2})/)?.[1] ||
      url.searchParams.get("from") || "2026-10-12";
    const date = new Date(week + "T12:00:00Z");
    date.setUTCDate(date.getUTCDate() + 1);
    const tuesday = date.toISOString().slice(0, 10);
    const start = tuesday + "T09:00:00-04:00";
    const end = tuesday + "T10:00:00-04:00";
    const issue = { code: "BOOKING_OUTSIDE_EFFECTIVE_AVAILABILITY",
      starts_at: start, ends_at: end, booking_id: "booking-one", state: "OPEN",
      sources: ["BOOKING:booking-one", "EXCEPTION:appointment"] };
    const booking = { id: "booking-one", task_id: "task-one", work_type_id: null,
      starts_at: start, ends_at: end, revision: confirmed ? 2 : 1, status: "CONFIRMED" };
    if (path === "/api/tasks") return respond([]);
    if (path === "/api/projects") return respond([]);
    if (path === "/api/work-types") return respond([{ id: "focus-type", name: "Concentration" }]);
    if (path === "/api/availability/weekly-schedule") {
      return respond({
        effective_from: url.searchParams.get("effective_from"), timezone_name:
          url.searchParams.get("timezone_name"), source_versions: {},
        sections: weeklySections, future_revisions: [],
      });
    }
    if (path === "/api/availability/weekly-schedule/preview") {
      const draft = request.postDataJSON();
      return respond({
        fingerprint: "f".repeat(64), has_changes: true, projection_days: 93,
        before_declared_minutes_93d: 0, after_declared_minutes_93d: 60,
        changed_sections: draft.sections.map((cell: { weekday: number; kind: string }) =>
          cell.weekday + ":" + cell.kind + ":NULL:" + draft.timezone_name),
        cell_changes: draft.sections.map((cell: { weekday: number; kind: string; slots: unknown[] }) => ({
          section: cell.weekday + ":" + cell.kind + ":NULL:" + draft.timezone_name,
          before: [], after: cell.slots, previous_future: [],
        })),
        series_cutovers: [], exception_remaps: [], unresolved_exceptions: [],
        booking_conflicts: [], invalid_conflicts: [], civil_time_issues: [],
        calendar_verified: false,
      });
    }
    if (path === "/api/availability/weekly-schedule/confirm") {
      const draft = request.postDataJSON();
      if (!draft.confirmed || draft.fingerprint !== "f".repeat(64) || !draft.command_id)
        return respond({ detail: "confirmation required" }, 422);
      weeklySections = draft.sections;
      return respond({ applied: true, calendar_written: false });
    }
    if (path === "/api/availability/rules") {
      if (request.method() === "POST") {
        const body = request.postDataJSON();
        rule = { id: "rule-one", version: 1, revisions: [{ ...body,
          number: 1, mode: body.kind === "CATEGORIZED" ? body.mode : null }] };
        return respond(rule, 201);
      }
      return respond(rule ? [rule] : []);
    }
    if (path === "/api/availability/rules/occurrences")
      return respond({ occurrences: [], issues: [] });
    if (path === "/api/availability/exceptions")
      return respond([]);
    if (path === "/api/availability/effective")
      return respond({ projection: "DECLARED_NOT_CALENDAR_VERIFIED", declared_minutes: 0,
        blocks: [], issues: [issue], expansion_issues: [] });
    if (path.match(/^\/api\/capacity\/weeks\/\d{4}-\d{2}-\d{2}$/))
      return respond({ blocks: [], capacity: { available_minutes: 0 } });
    if (/\/time-blocks$/.test(path)) {
      if (bookedWeek === null) bookedWeek = week;
      return respond(!cancelled && week === bookedWeek ? [booking] : []);
    }
    if (/\/resolution\/preview$/.test(path)) {
      const body = request.postDataJSON();
      return respond({ state: "PROPOSED", fingerprint: "a".repeat(64), booking,
        decision: body.decision, conflict_codes: body.decision === "KEEP" ? [issue.code] : [],
        calendar_checked: false, replacement: null,
        consequences: [body.decision === "CANCEL" ? "Annulation locale uniquement" : "Conflit OPEN conservé"],
        calendar_written: false });
    }
    if (/\/resolution\/confirm$/.test(path)) {
      const body = request.postDataJSON();
      if (body.confirmed !== true || body.fingerprint !== "a".repeat(64) ||
          !body.decision_id || !body.reason) return respond({ detail: "bad confirmation" }, 422);
      if (cancelled || body.expected_revision !== (confirmed ? 2 : 1))
        return respond({ detail: "stale booking" }, 409);
      confirmed = true;
      if (body.decision === "CANCEL") cancelled = true;
      return respond({ state: "CONFIRMED_LOCAL", decision: body.decision, booking: {
        ...booking, status: cancelled ? "CANCELLED" : "CONFIRMED", revision: 2 },
        calendar_written: false, replacement: null });
    }
    if (/\/resolution\/history$/.test(path)) return respond([]);
    if (path === "/api/availability/verified")
      return respond({ detail: "Google Calendar non configuré" }, 503);
    return respond({ detail: "Unexpected mocked endpoint: " + path }, 404);
  });
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await page.getByRole("navigation", { name: "Navigation principale" })
    .getByRole("button", { name: /Planification|Planifier/ }).click();
});

test("TP-023B : édition d'un lundi par aperçu et sauvegarde atomique", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Grille de l'horaire habituel" })).toBeVisible();
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByLabel("Lundi plage 1 début").fill("07:15");
  await page.getByLabel("Lundi plage 1 fin").fill("16:15");
  const request = page.waitForRequest((value) => value.url().endsWith("/weekly-schedule/preview") &&
    value.method() === "POST");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const body = (await request).postDataJSON();
  expect(body.sections).toEqual([{
    weekday: 0, kind: "GENERAL", work_type_id: null, slots: [{
      starts_at_local: "07:15", ends_at_local: "16:15", mode: null,
      start_fold: null, end_fold: null,
    }],
  }]);
  await expect(page.getByText(/Capacité déclarée sur 93 jours/)).toBeVisible();
  const confirmation = page.waitForRequest((value) => value.url().endsWith("/weekly-schedule/confirm") &&
    value.method() === "POST");
  await page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }).click();
  const confirmed = (await confirmation).postDataJSON();
  expect(confirmed).toMatchObject({ confirmed: true, fingerprint: "f".repeat(64),
    acknowledge_conflicts: false });
  await expect(page.getByText(/Horaire futur enregistré atomiquement/)).toBeVisible();
  await expect(page.getByLabel("Lundi plage 1 début")).toHaveValue("07:15");
});

test("TP-023B : copie ciblée après aperçu local, puis aperçu serveur groupé", async ({ page }) => {
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByLabel("Lundi plage 1 début").fill("11:00");
  await page.getByLabel("Lundi plage 1 fin").fill("12:00");
  await page.getByRole("region", { name: "Copier la journée" })
    .getByLabel("Mardi").check();
  await page.getByRole("button", { name: "Préparer la copie" }).click();
  await expect(page.getByText("Remplacements dans le brouillon (aucune sauvegarde)")).toBeVisible();
  await page.getByRole("button", { name: "Appliquer la copie au brouillon" }).click();
  await expect(page.getByLabel("Mardi plage 1 début")).toHaveValue("11:00");
  const preview = page.waitForRequest((request) => request.url().endsWith("/weekly-schedule/preview") &&
    request.method() === "POST");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const body = (await preview).postDataJSON();
  expect(body.sections.map((cell: { weekday: number }) => cell.weekday).sort()).toEqual([0, 1]);
});

test("une règle hebdomadaire se crée par API depuis la vue desktop", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Scénario desktop.");
  await expect(page.getByRole("heading", { name: "Disponibilités" })).toBeVisible();
  await page.getByText("Gestion avancée des anciennes séries et règles").click();
  await expect(page.getByRole("heading", { name: "Nouvelle plage récurrente" })).toBeVisible();
  await page.getByLabel("Date d'effet", { exact: true }).fill("2026-10-19");
  await page.getByLabel("Nature").selectOption("CATEGORIZED");
  await page.getByLabel("Type de travail").selectOption("focus-type");
  await page.getByLabel("Protection de la plage").selectOption("PROTECTED");
  await page.getByRole("button", { name: "Créer la règle" }).click();
  await expect(page.getByText("Horaire habituel enregistré.")).toBeVisible();
  await expect(page.getByText("Protégée", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Semaine réelle" }).click();
  await expect(page.getByText("minutes déclarées")).toBeVisible();
  await expect(page.getByText(/BOOKING_OUTSIDE_EFFECTIVE_AVAILABILITY/)).toBeVisible();
  await page.getByRole("button", { name: "Vérifier avec Google Calendar" }).click();
  await expect(page.getByRole("alert")).toContainText("Google Calendar non configuré");
});

test("sur mobile, conserver un conflit exige aperçu et confirmation", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "Scénario mobile.");
  await page.getByRole("button", { name: "Semaine réelle" }).click();
  await expect(page.getByRole("heading", { name: "Conflits et réservations" })).toBeVisible();
  await expect(page.getByText("Aucun conflit ouvert")).toHaveCount(0);
  await page.getByRole("button", { name: "Résoudre" }).click();
  await page.getByLabel("Réservation en conflit").selectOption("booking-one");
  await page.getByLabel("Raison de la décision").fill("Vérifié en recette.");
  await page.getByRole("button", { name: "Prévisualiser la résolution" }).click();
  await expect(page.getByText("Conflit OPEN conservé")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer cette décision" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Décision enregistrée" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Résoudre" })).toBeVisible();
  const hasOverflow = await page.evaluate(() =>
    document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(hasOverflow).toBe(false);
});

test("une réservation sans conflit s'annule dans la semaine réelle sans mutation de règle", async ({ page }) => {
  await page.route("**/api/availability/effective?**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      projection: "DECLARED_NOT_CALENDAR_VERIFIED", declared_minutes: 60,
      blocks: [], issues: [], expansion_issues: [],
    }) }));
  await page.getByRole("button", { name: "Semaine réelle" }).click();
  await page.getByRole("button", { name: "Actualiser" }).click();
  await expect(page.getByText("Aucun conflit ouvert de réservation")).toBeVisible();
  await page.getByRole("button", { name: "Annuler la réservation booking-", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Réservation locale", exact: true })).toHaveValue("booking-one");
  await expect(page.getByLabel("Raison de la décision")).toHaveValue("Annulation manuelle");
  const previewRequest = page.waitForRequest((request) =>
    request.url().includes("/resolution/preview") && request.method() === "POST");
  await page.getByRole("button", { name: "Prévisualiser la résolution" }).click();
  const payload = (await previewRequest).postDataJSON();
  expect(payload).toMatchObject({ decision: "CANCEL", expected_revision: 1,
    reason: "Annulation manuelle" });
  await expect(page.getByText("Annulation locale uniquement")).toBeVisible();
  await expect(page.getByText(/Seule cette réservation locale sera annulée/)).toBeVisible();
  await expect(page.getByText(/Tâche task-one/)).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer cette décision" }).click();
  await expect(page.getByText("Aucune réservation locale active sur la semaine.")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Décision enregistrée" })).toBeVisible();
});

test("l'horaire habituel annule seulement la réservation datée, sans toucher la série", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Réservations de la semaine" })).toBeVisible();
  await page.getByText("Gestion avancée des anciennes séries et règles").click();
  await expect(page.getByRole("heading", { name: "Règles hebdomadaires" })).toBeVisible();
  await page.getByRole("button", { name: "Annuler la réservation booking-" }).click();
  await page.getByRole("button", { name: "Prévisualiser la résolution" }).click();
  await expect(page.getByText(/les règles récurrentes restent intactes/)).toBeVisible();
  await page.getByRole("button", { name: "Semaine réelle" }).click();
  await expect(page.getByText("Annulation locale uniquement")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer cette décision" }).click();
  await expect(page.getByText("Aucune réservation locale active sur la semaine.")).toBeVisible();
  await page.getByRole("button", { name: "Horaire habituel" }).click();
  await page.getByText("Gestion avancée des anciennes séries et règles").click();
  await expect(page.getByRole("heading", { name: "Règles hebdomadaires" })).toBeVisible();
  await expect(page.getByText("Aucune règle habituelle.")).toBeVisible();
  await page.getByRole("button", { name: "Semaine suivante" }).click();
  await expect(page.getByText("Aucune réservation locale active sur la semaine.")).toBeVisible();
});

test("409 sur confirmation conserve la réservation et invalide l'aperçu", async ({ page }) => {
  await page.route("**/resolution/confirm", (route) =>
    route.fulfill({ status: 409, contentType: "application/json",
      body: JSON.stringify({ detail: "stale booking" }) }));
  await page.getByRole("button", { name: "Annuler la réservation booking-" }).click();
  await page.getByRole("button", { name: "Prévisualiser la résolution" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer cette décision" }).click();
  await expect(page.getByRole("alert")).toContainText("409");
  await expect(page.getByRole("button", { name: "Annuler la réservation booking-" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer cette décision" })).toHaveCount(0);
});

test("le planificateur de créneaux exige aperçu puis confirmation et rafraîchit sa liste", async ({ page }) => {
  await page.getByRole("button", { name: "Capacité et propositions" }).click();
  await expect(page.getByRole("heading", { name: "Créneaux déjà confirmés dans TaskPlanner" })).toBeVisible();
  await page.getByRole("button", { name: "Annuler la réservation booking-" }).click();
  await expect(page.getByRole("heading", { name: /Aperçu d’annulation/ })).toBeVisible();
  await expect(page.getByText(/tâche reste inchangée/i)).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer l’annulation locale" }).click();
  await expect(page.getByText("Aucune réservation locale active.")).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Réservation annulée localement");
});
