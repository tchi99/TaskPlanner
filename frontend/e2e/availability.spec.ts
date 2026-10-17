import { expect, test, type Page } from "@playwright/test";

async function mockApi(page: Page) {
  let rule: object | null = null;
  let weeklySections: unknown[] = [];
  const compatibilityScope = "22222222-2222-4222-8222-222222222222";
  const workScope = "11111111-1111-4111-8111-111111111111";
  const personalScope = "33333333-3333-4333-8333-333333333333";
  let scopes = [
    { id: compatibilityScope, name: "Compatibilité", version: 1, state: "ACTIVE", is_compatibility: true },
    { id: workScope, name: "Travail", version: 1, state: "ACTIVE", is_compatibility: false },
    { id: personalScope, name: "Personnel", version: 1, state: "ACTIVE", is_compatibility: false },
  ];
  let affiliations: { work_type_id: string; scope_id: string; effective_from: string; version: number }[] = [];
  let workTypes = [{ id: "focus-type", name: "Concentration" }];
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
    if (path === "/api/work-types") {
      if (request.method() === "POST") {
        const value = request.postDataJSON();
        const created = { id: "leaf-" + (workTypes.length + 1), name: value.name };
        workTypes = [...workTypes, created];
        return respond(created, 201);
      }
      return respond(workTypes);
    }
    if (path === "/api/schedule-scopes") {
      if (request.method() === "POST") {
        const created = { id: "44444444-4444-4444-8444-444444444444",
          name: request.postDataJSON().name, version: 1, state: "ACTIVE", is_compatibility: false };
        scopes = [...scopes, created]; return respond(created, 201);
      }
      return respond({ scopes, compatibility_scope_id: compatibilityScope, affiliations,
        affiliation_versions: Object.fromEntries(affiliations.map((item) =>
          [item.work_type_id, item.version])), legacy_unassigned_work_type_ids:
          workTypes.filter((item) => !affiliations.some((a) => a.work_type_id === item.id))
            .map((item) => item.id) });
    }
    if (path.startsWith("/api/schedule-scopes/") && request.method() === "PATCH") {
      const id = path.split("/")[3];
      const body = request.postDataJSON();
      scopes = scopes.map((item) => item.id === id ?
        { ...item, name: body.name, state: body.state, version: item.version + 1 } : item);
      return respond(scopes.find((item) => item.id === id));
    }
    if (path === "/api/schedule-scopes/affiliations/preview") {
      const draft = request.postDataJSON();
      return respond({ fingerprint: "b".repeat(64), has_changes: true,
        projection_days: 93, from_scope_id: compatibilityScope, to_scope_id: draft.scope_id,
        before_minutes_93d: { [compatibilityScope]: 60 }, after_minutes_93d: { [draft.scope_id]: 60 },
        global_before_minutes_93d: 60, global_after_minutes_93d: 60,
        conflicts: [], civil_time_issues: [], unresolved_rule_migrations: [],
        rules_inventory: [], exceptions_inventory: [], manual_blocks_inventory: [],
        all_future_bookings: [], explicitly_remapped_rule_ids: [] });
    }
    if (path === "/api/schedule-scopes/affiliations/confirm") {
      const draft = request.postDataJSON();
      if (!draft.confirmed || draft.fingerprint !== "b".repeat(64))
        return respond({ detail: "confirmation invalid" }, 422);
      affiliations = [...affiliations, { work_type_id: draft.work_type_id,
        scope_id: draft.scope_id, effective_from: draft.effective_from, version: 1 }];
      return respond({ applied: true, calendar_written: false });
    }
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
    if (path === "/api/availability/eligibility-week") {
      const selectedWeek = url.searchParams.get("week_start") || "2026-10-12";
      const startDay = new Date(selectedWeek + "T00:00:00Z");
      const days = Array.from({ length: 7 }, (_, index) => {
        const d = new Date(startDay);
        d.setUTCDate(d.getUTCDate() + index);
        const next = new Date(d);
        next.setUTCDate(next.getUTCDate() + 1);
        return { local_date: d.toISOString().slice(0, 10), weekday: index,
          starts_at: d.toISOString(), ends_at: next.toISOString(), minutes: 1440 };
      });
      const day = days[1];
      const startAt = day.local_date + "T10:00:00Z";
      const endAt = day.local_date + "T11:00:00Z";
      const typeIds = ["focus-type", "second-type", "third-type"];
      return respond({
        week_start: selectedWeek, timezone_name: "UTC",
        scope_id: compatibilityScope, read_only: true,
        projection: "PHYSICAL_ELIGIBILITY_NON_ADDITIVE",
        calendar_state: "NOT_CONFIGURED", calendar_checked: false,
        calendar_error: "Google Calendar non configuré : libre non vérifié.",
        physical_minutes: 60, local_occupied_minutes: 0,
        verified_occupied_minutes: null, verified_free_minutes: null,
        potential_minutes: typeIds.map((id) => ({
          work_type_id: id, minutes: 60, non_additive: true,
        })),
        days, fragments: [{
          local_date: day.local_date, weekday: 1,
          starts_at: startAt, ends_at: endAt,
          starts_at_local: startAt, ends_at_local: endAt,
          start_minute: 600, end_minute: 660, day_minutes: 1440, minutes: 60,
          scope_id: compatibilityScope, sources: ["RULE:general"],
          null_residual: false, verification: "DECLARED_ONLY",
          choices: typeIds.map((id, index) => ({
            work_type_id: id, priority_rank: index + 1,
            exclusive: false, legacy_mode: null,
            sources: ["ELIGIBILITY:mock-" + id + ":" + day.local_date + ":v1"],
            source_details: [{ series_id: "mock-" + id, revision: 1,
              effective_from: selectedWeek, valid_until: null, timezone_name: "UTC",
              original_local_date: day.local_date, source: id }],
          })),
        }],
        occupations: [], issues: [], expansion_issues: [],
      });
    }
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
  await page.getByLabel("Lundi plage 1 début", { exact: true }).fill("07:15");
  await page.getByLabel("Lundi plage 1 fin", { exact: true }).fill("16:15");
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
  await expect(page.getByLabel("Lundi plage 1 début", { exact: true })).toHaveValue("07:15");
});

test("TP-023B : copie ciblée après aperçu local, puis aperçu serveur groupé", async ({ page }) => {
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByLabel("Lundi plage 1 début", { exact: true }).fill("11:00");
  await page.getByLabel("Lundi plage 1 fin", { exact: true }).fill("12:00");
  await page.getByRole("region", { name: "Copier la journée" })
    .getByRole("checkbox", { name: "Mardi", exact: true }).check();
  await page.getByRole("button", { name: "Préparer la copie" }).click();
  await expect(page.getByText("Remplacements dans le brouillon (aucune sauvegarde)")).toBeVisible();
  await page.getByRole("button", { name: "Appliquer la copie au brouillon" }).click();
  await expect(page.getByLabel("Mardi plage 1 début", { exact: true })).toHaveValue("11:00");
  const preview = page.waitForRequest((request) => request.url().endsWith("/weekly-schedule/preview") &&
    request.method() === "POST");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const body = (await preview).postDataJSON();
  expect(body.sections.map((cell: { weekday: number }) => cell.weekday).sort()).toEqual([0, 1]);
});

test("TP-023D : la grille remplace la création legacy, archive en lecture seule", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Scénario desktop.");
  await expect(page.getByRole("heading", { name: "Disponibilités" })).toBeVisible();
  await page.getByLabel("Section de l'horaire").selectOption("focus-type");
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByLabel("Lundi plage 1 mode").selectOption("PROTECTED");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  await page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }).click();
  await expect(page.getByText(/Horaire futur enregistré atomiquement/)).toBeVisible();
  await page.getByText("Consulter les séries historiques (lecture seule)").click();
  await expect(page.getByRole("heading", { name: "Sources de l'horaire conservées" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Créer la règle" })).toHaveCount(0);
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
  await page.getByText("Consulter les séries historiques (lecture seule)").click();
  await expect(page.getByRole("heading", { name: "Sources de l'horaire conservées" })).toBeVisible();
  await page.getByRole("button", { name: "Annuler la réservation booking-" }).click();
  await page.getByRole("button", { name: "Prévisualiser la résolution" }).click();
  await expect(page.getByText(/les règles récurrentes restent intactes/)).toBeVisible();
  await page.getByRole("button", { name: "Semaine réelle" }).click();
  await expect(page.getByText("Annulation locale uniquement")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer cette décision" }).click();
  await expect(page.getByText("Aucune réservation locale active sur la semaine.")).toBeVisible();
  await page.getByRole("button", { name: "Horaire habituel" }).click();
  await page.getByText("Consulter les séries historiques (lecture seule)").click();
  await expect(page.getByRole("heading", { name: "Sources de l'horaire conservées" })).toBeVisible();
  await expect(page.getByText("Aucune règle historique.")).toBeVisible();
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


// TP-023C: recette UX de la grille. Les endpoints sont simulés; aucune donnée réelle,
// écriture Google Calendar ou réservation de production n'est impliquée.
function tp023cPreview(draft: {
  timezone_name: string;
  sections: { weekday: number; kind: string; work_type_id: string | null; slots: unknown[] }[];
}, extra: Record<string, unknown> = {}) {
  const section = (cell: typeof draft.sections[number]) =>
    cell.weekday + ":" + cell.kind + ":" + (cell.work_type_id || "NULL") +
    ":" + draft.timezone_name;
  return {
    fingerprint: "f".repeat(64), has_changes: true, projection_days: 93,
    before_declared_minutes_93d: 240, after_declared_minutes_93d: 180,
    changed_sections: draft.sections.map(section),
    cell_changes: draft.sections.map((cell) => ({
      section: section(cell), before: [], after: cell.slots, previous_future: [],
    })),
    series_cutovers: [], exception_remaps: [], unresolved_exceptions: [],
    booking_conflicts: [], invalid_conflicts: [], civil_time_issues: [],
    calendar_verified: false, ...extra,
  };
}

test("TP-023C : deux fenêtres disjointes, copie ciblée, jour OFF et rechargement", async ({ page }) => {
  let confirms = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/weekly-schedule/confirm")) confirms++;
  });
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByLabel("Lundi plage 1 début", { exact: true }).fill("11:00");
  await page.getByLabel("Lundi plage 1 fin", { exact: true }).fill("12:00");
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByLabel("Lundi plage 2 début", { exact: true }).fill("13:00");
  await page.getByLabel("Lundi plage 2 fin", { exact: true }).fill("14:00");
  const copier = page.getByRole("region", { name: "Copier la journée" });
  await copier.getByRole("checkbox", { name: "Mardi", exact: true }).check();
  await copier.getByRole("checkbox", { name: "Mercredi", exact: true }).check();
  await page.getByRole("button", { name: "Préparer la copie" }).click();
  await expect(page.getByText("Remplacements dans le brouillon (aucune sauvegarde)")).toBeVisible();
  expect(confirms).toBe(0);
  await page.getByRole("button", { name: "Appliquer la copie au brouillon" }).click();
  await expect(page.getByLabel("Mardi plage 2 début", { exact: true })).toHaveValue("13:00");
  await expect(page.getByLabel("Mercredi plage 1 fin", { exact: true })).toHaveValue("12:00");
  // OFF est explicite, sans suppression d'un autre jour ou section.
  await page.getByRole("button", { name: "Ajouter une plage au Jeudi" }).click();
  await page.locator(".weeklyDays").getByRole("checkbox", { name: "Jeudi", exact: true }).uncheck();
  await expect(page.locator(".weeklyDay").filter({ has: page.locator("strong").getByText("Jeudi", { exact: true }) })
    .getByText("Jour désactivé pour cette section.")).toBeVisible();
  const request = page.waitForRequest((r) => r.url().endsWith("/weekly-schedule/preview") &&
    r.method() === "POST");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const draft = (await request).postDataJSON();
  expect(draft.sections.map((cell: { weekday: number }) => cell.weekday).sort())
    .toEqual([0, 1, 2, 3]);
  for (const cell of draft.sections.slice(0, 3)) {
    expect(cell.slots.map((s: { starts_at_local: string; ends_at_local: string }) =>
      [s.starts_at_local, s.ends_at_local])).toEqual([
        ["11:00", "12:00"], ["13:00", "14:00"],
      ]);
  }
  expect(draft.sections[3].slots).toEqual([]);
  expect(confirms).toBe(0);
  await expect(page.getByText(/Capacité déclarée sur 93 jours/)).toBeVisible();
  await page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }).click();
  await expect(page.getByText(/Horaire futur enregistré atomiquement/)).toBeVisible();
  expect(confirms).toBe(1);
  await page.reload();
  // Le rechargement revient sur « Aujourd'hui » : rouvrir Planification
  // pour vérifier les plages relues depuis l'API simulée persistante.
  await page.getByRole("navigation", { name: "Navigation principale" })
    .getByRole("button", { name: /Planification|Planifier/ }).click();
  await expect(page.getByRole("heading", { name: "Grille de l'horaire habituel" })).toBeVisible();
  await expect(page.getByLabel("Mardi plage 2 début", { exact: true })).toHaveValue("13:00");
  await expect(page.getByLabel("Mercredi plage 2 fin", { exact: true })).toHaveValue("14:00");
  await expect(page.locator(".weeklyDays").getByRole("checkbox", { name: "Jeudi", exact: true })).not.toBeChecked();
  await expect(page.locator(".weeklyDays").getByRole("checkbox", { name: "Vendredi", exact: true })).not.toBeChecked();
});

test("TP-023C : une série partagée ne modifie pas les jours non sélectionnés", async ({ page }) => {
  const shared = [0, 1, 2, 3, 4].map((weekday) => ({
    weekday, kind: "GENERAL", work_type_id: null, slots: [{
      starts_at_local: "09:00", ends_at_local: "10:00",
      mode: null, start_fold: null, end_fold: null,
      sources: [{ rule_id: "shared-weekdays", revision: 1 }],
    }],
  }));
  await page.route((url) => url.pathname === "/api/availability/weekly-schedule",
    (route) => route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ effective_from: route.request().url().split("effective_from=")[1]?.slice(0, 10),
        timezone_name: "America/Toronto", source_versions: { "shared-weekdays": 1 },
        sections: shared, future_revisions: [] }),
    }));
  await page.getByRole("button", { name: "Actualiser la grille" }).click();
  await expect(page.getByLabel("Jeudi plage 1 début", { exact: true })).toHaveValue("09:00");
  await page.getByRole("button", { name: "Retirer la plage 1 du Mardi" }).click();
  await expect(page.locator(".weeklyDays").getByRole("checkbox", { name: "Mardi", exact: true })).not.toBeChecked();
  await expect(page.getByLabel("Jeudi plage 1 début", { exact: true })).toHaveValue("09:00");
  const request = page.waitForRequest((r) => r.url().endsWith("/weekly-schedule/preview"));
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const body = (await request).postDataJSON();
  expect(body.sections).toEqual([{ weekday: 1, kind: "GENERAL",
    work_type_id: null, slots: [] }]);
  expect(body.expected_versions).toEqual({ "shared-weekdays": 1 });
  await page.getByRole("button", { name: "Annuler les modifications" }).click();
  await expect(page.getByLabel("Mardi plage 1 début", { exact: true })).toHaveValue("09:00");
  await expect(page.getByLabel("Vendredi plage 1 fin", { exact: true })).toHaveValue("10:00");
});

test("TP-023C : catégorie protégée, date d'effet et DST sont transmis sans inférence locale", async ({ page }) => {
  await page.getByLabel("Date d'effet de la grille").fill("2027-11-07");
  await page.getByLabel("Section de l'horaire").selectOption("focus-type");
  await page.getByRole("button", { name: "Ajouter une plage au Dimanche" }).click();
  await page.getByLabel("Dimanche plage 1 début", { exact: true }).fill("01:00");
  await page.getByLabel("Dimanche plage 1 fin", { exact: true }).fill("02:00");
  await page.getByLabel("Dimanche plage 1 mode").selectOption("PROTECTED");
  await page.getByText("Transitions DST · automatique").click();
  await page.getByLabel("Dimanche plage 1 début DST").selectOption("1");
  const request = page.waitForRequest((r) => r.url().endsWith("/weekly-schedule/preview"));
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const body = (await request).postDataJSON();
  expect(body.effective_from).toBe("2027-11-07");
  expect(body.timezone_name).toBe("America/Toronto");
  expect(body.sections).toMatchObject([{
    weekday: 6, kind: "CATEGORIZED", work_type_id: "focus-type",
    slots: [{ starts_at_local: "01:00", ends_at_local: "02:00",
      mode: "PROTECTED", start_fold: 1, end_fold: null }],
  }]);
  await expect(page.getByText(/Google Calendar non vérifié/)).toBeVisible();
});

test("TP-023C : conflit CONFIRMED visible et reconnu, sans annulation de réservation", async ({ page }) => {
  let resolutionWrites = 0;
  let googleWrites = 0;
  page.on("request", (request) => {
    if (request.url().includes("/resolution/confirm")) resolutionWrites++;
    if (request.method() !== "GET" && /google|calendar/i.test(request.url())) googleWrites++;
  });
  await page.route("**/api/availability/weekly-schedule/preview", (route) => {
    const body = route.request().postDataJSON();
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(tp023cPreview(body, {
        booking_conflicts: [{ booking_id: "booking-one",
          starts_at: "2026-10-20T09:00:00-04:00", new: true }],
      })),
    });
  });
  await page.getByRole("button", { name: "Ajouter une plage au Mardi" }).click();
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  await expect(page.getByRole("heading", { name: "Réservations CONFIRMED : conservées" })).toBeVisible();
  const confirm = page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" });
  await expect(confirm).toBeDisabled();
  await page.getByRole("checkbox", {
    name: "Je reconnais les nouveaux conflits sans annuler ni déplacer les réservations.",
  }).check();
  await expect(confirm).toBeEnabled();
  const request = page.waitForRequest((r) => r.url().endsWith("/weekly-schedule/confirm"));
  await confirm.click();
  expect((await request).postDataJSON()).toMatchObject({
    confirmed: true, acknowledge_conflicts: true,
  });
  await expect(page.getByText(/Horaire futur enregistré atomiquement/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Annuler la réservation booking-" })).toBeVisible();
  expect(resolutionWrites).toBe(0);
  expect(googleWrites).toBe(0);
});

test("TP-023C : 409 conserve le brouillon et exige un nouvel aperçu", async ({ page }) => {
  await page.route("**/api/availability/weekly-schedule/confirm", (route) =>
    route.fulfill({ status: 409, contentType: "application/json",
      body: JSON.stringify({ detail: "versions obsolètes" }) }));
  await page.getByRole("button", { name: "Ajouter une plage au Mardi" }).click();
  await page.getByLabel("Mardi plage 1 début", { exact: true }).fill("07:15");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  await page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Conflit de versions (409)" })).toBeVisible();
  await expect(page.getByLabel("Mardi plage 1 début", { exact: true })).toHaveValue("07:15");
  await expect(page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }))
    .toHaveCount(0);
  await page.getByRole("button", { name: "Réactualiser les versions sans perdre le brouillon" }).click();
  await expect(page.getByLabel("Mardi plage 1 début", { exact: true })).toHaveValue("07:15");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  await expect(page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" })).toBeVisible();
});

test("TP-023C : anomalie civile empêche de confirmer; grille utilisable au clavier et sur mobile", async ({ page }) => {
  const toggle = page.locator(".weeklyDays").getByRole("checkbox", { name: "Samedi", exact: true });
  await toggle.focus();
  await page.keyboard.press("Space");
  await expect(toggle).toBeChecked();
  const add = page.getByRole("button", { name: "Ajouter une plage au Samedi" });
  await add.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Samedi plage 2 début", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Annuler les modifications" }).click();
  await expect(toggle).not.toBeChecked();
  await page.route("**/api/availability/weekly-schedule/preview", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(tp023cPreview(route.request().postDataJSON(), {
        civil_time_issues: [{ date: "2027-03-14", reason: "NONEXISTENT_LOCAL_TIME" }],
      })),
    }));
  await page.getByLabel("Date d'effet de la grille").fill("2027-03-14");
  await page.getByRole("button", { name: "Ajouter une plage au Dimanche" }).click();
  await page.getByLabel("Dimanche plage 1 début", { exact: true }).fill("02:30");
  await page.getByLabel("Dimanche plage 1 fin", { exact: true }).fill("03:30");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  await expect(page.getByText(/NONEXISTENT_LOCAL_TIME/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }))
    .toBeDisabled();
  const hasOverflow = await page.evaluate(() =>
    document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(hasOverflow).toBe(false);
});


test("TP-023D : diagnostic contextualisé, autre fuseau et brouillon conservé", async ({ page }) => {
  await page.route("**/api/availability/weekly-schedule/preview", (route) => {
    const body = route.request().postDataJSON();
    const diagnostic = (status: "NEW" | "PREEXISTING", start: string, end: string) => ({
      code: "OUTSIDE_GENERAL_ENVELOPE", status, date: "2027-10-19", weekday: 1,
      timezone_name: "America/Toronto", starts_at: start, ends_at: end,
      work_type_id: "focus-type", work_type_ids: ["focus-type"],
      rule_ids: ["foreign-rule"], sources: ["RULE:foreign-rule:2027-10-19:v1"],
      source_timezones: ["UTC"], source_local_dates: ["2027-10-19"],
      cause: "NO_COVERING_GENERAL", remediation: "Corriger les deux sections.",
    });
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(tp023cPreview(body, {
        invalid_conflicts: ["OUTSIDE_GENERAL_ENVELOPE"],
        invalid_diagnostics: [
          diagnostic("NEW", "2027-10-19T10:00:00-04:00", "2027-10-19T10:30:00-04:00"),
          diagnostic("PREEXISTING", "2027-10-19T07:00:00-04:00", "2027-10-19T08:00:00-04:00"),
        ],
      })),
    });
  });
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByLabel("Lundi plage 1 début", { exact: true }).fill("08:00");
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const diagnostics = page.getByRole("region", { name: "Diagnostics des disponibilités" });
  await expect(diagnostics.getByText("Nouveau conflit bloquant").first()).toBeVisible();
  await expect(diagnostics.getByText("Conflit déjà présent").first()).toBeVisible();
  await expect(diagnostics.getByText(/Attention : source dans un autre fuseau \(UTC\)/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" })).toBeDisabled();
  await diagnostics.getByRole("button", { name: "Afficher la section Concentration" }).first().click();
  await expect(page.getByLabel("Section de l'horaire")).toHaveValue("focus-type");
  await page.getByRole("button", { name: "Retour au brouillon" }).click();
  await page.getByLabel("Section de l'horaire").selectOption("GENERAL");
  await expect(page.getByLabel("Lundi plage 1 début", { exact: true })).toHaveValue("08:00");
});

test("TP-023D : conflit structurel préexistant seul n'interdit pas la réparation", async ({ page }) => {
  await page.route("**/api/availability/weekly-schedule/preview", (route) => {
    const body = route.request().postDataJSON();
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(tp023cPreview(body, {
        invalid_conflicts: [], invalid_diagnostics: [{
          code: "OUTSIDE_GENERAL_ENVELOPE", status: "PREEXISTING",
          date: "2027-10-19", weekday: 1, timezone_name: "America/Toronto",
          starts_at: "2027-10-19T07:00:00-04:00", ends_at: "2027-10-19T08:00:00-04:00",
          work_type_id: "focus-type", work_type_ids: ["focus-type"],
          rule_ids: ["old-rule"], sources: ["RULE:old-rule:2027-10-19:v1"],
          source_timezones: ["America/Toronto"], source_local_dates: ["2027-10-19"],
          cause: "NO_COVERING_GENERAL", remediation: "Réparer l'enveloppe.",
        }],
      })),
    });
  });
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  await expect(page.getByText("Conflit déjà présent")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" })).toBeEnabled();
});

test("TP-024B : enveloppe hebdomadaire isolée au parent Travail", async ({ page }) => {
  await page.getByLabel("Catégorie parente de l'horaire").selectOption(
    "11111111-1111-4111-8111-111111111111");
  const gridRequest = page.waitForRequest((value) =>
    value.url().includes("weekly-schedule?") &&
    value.url().includes("scope_id=11111111-1111-4111-8111-111111111111"));
  await page.getByRole("button", { name: "Actualiser la grille" }).click();
  await gridRequest;
  await page.getByRole("button", { name: "Ajouter une plage au Lundi" }).click();
  const preview = page.waitForRequest((value) => value.url().endsWith("/weekly-schedule/preview"));
  await page.getByRole("button", { name: "Prévisualiser les changements" }).click();
  const payload = (await preview).postDataJSON();
  expect(payload.sections).toMatchObject([{
    weekday: 0, kind: "GENERAL", work_type_id: null,
    scope_id: "11111111-1111-4111-8111-111111111111",
  }]);
  await expect(page.getByText(/Capacité déclarée sur 93 jours/)).toBeVisible();
});

test("TP-024B : rattachement daté avec aperçu et confirmation explicites", async ({ page }) => {
  await page.getByRole("combobox", { name: "Sous-catégorie", exact: true }).selectOption("focus-type");
  await page.getByRole("combobox", { name: "Catégorie cible", exact: true }).selectOption("11111111-1111-4111-8111-111111111111");
  const preview = page.waitForRequest((value) =>
    value.url().endsWith("/affiliations/preview") && value.method() === "POST");
  await page.getByRole("button", { name: "Prévisualiser le rattachement" }).click();
  const draft = (await preview).postDataJSON();
  expect(draft).toMatchObject({
    work_type_id: "focus-type", scope_id: "11111111-1111-4111-8111-111111111111",
    expected_affiliation_version: 0, expected_scope_version: 1, remap_rule_ids: [],
  });
  const confirm = page.waitForRequest((value) =>
    value.url().endsWith("/affiliations/confirm") && value.method() === "POST");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer le rattachement futur" }).click();
  expect((await confirm).postDataJSON()).toMatchObject({
    ...draft, fingerprint: "b".repeat(64), confirmed: true, acknowledge_bookings: false,
  });
  await expect(page.getByText(/Rattachement futur confirmé atomiquement/)).toBeVisible();
});

test("TP-024B : conflit interparent nouveau bloque la confirmation", async ({ page }) => {
  await page.route("**/api/schedule-scopes/affiliations/preview", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({
      fingerprint: "c".repeat(64), has_changes: true, projection_days: 93,
      from_scope_id: "22222222-2222-4222-8222-222222222222",
      to_scope_id: "11111111-1111-4111-8111-111111111111",
      before_minutes_93d: {}, after_minutes_93d: {},
      global_before_minutes_93d: 60, global_after_minutes_93d: 60,
      conflicts: [{ code: "INCOMPATIBLE_SCOPES", status: "NEW",
        starts_at: "2026-10-20T13:00:00Z", ends_at: "2026-10-20T14:00:00Z",
        scope_ids: ["11111111-1111-4111-8111-111111111111",
          "33333333-3333-4333-8333-333333333333"], sources: ["RULE:abc"] }],
      civil_time_issues: [], unresolved_rule_migrations: [], rules_inventory: [],
      exceptions_inventory: [], manual_blocks_inventory: [], all_future_bookings: [],
    }) }));
  await page.getByRole("combobox", { name: "Sous-catégorie", exact: true }).selectOption("focus-type");
  await page.getByRole("combobox", { name: "Catégorie cible", exact: true }).selectOption("11111111-1111-4111-8111-111111111111");
  await page.getByRole("button", { name: "Prévisualiser le rattachement" }).click();
  await expect(page.getByText(/Nouveau — bloquant/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer le rattachement futur" })).toBeDisabled();
});


// TP-024C: all data and endpoints are mocked. These scenarios exercise UX
// contract boundaries without any real Google writes or production migration.
test("TP-024C : réservations futures conservées avec consentement explicite", async ({ page }) => {
  const workScope = "11111111-1111-4111-8111-111111111111";
  const compatibility = "22222222-2222-4222-8222-222222222222";
  const preserved = {
    booking_id: "booking-future", starts_at: "2027-01-18T14:00:00Z",
    scope_id: null, work_type_id: "focus-type", status: "CONFIRMED",
  };
  await page.route("**/api/schedule-scopes/affiliations/preview", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({
      fingerprint: "d".repeat(64), has_changes: true, projection_days: 93,
      from_scope_id: compatibility, to_scope_id: workScope,
      before_minutes_93d: { [compatibility]: 60 },
      after_minutes_93d: { [workScope]: 60 },
      global_before_minutes_93d: 60, global_after_minutes_93d: 60,
      conflicts: [], civil_time_issues: [], unresolved_rule_migrations: [],
      rules_inventory: [], exceptions_inventory: [], manual_blocks_inventory: [],
      all_future_bookings: [preserved],
    }) }));
  // The shared API mock validates fingerprint "b"; this preview deliberately
  // issues "d". Model the successful acknowledged confirmation for this case.
  await page.route("**/api/schedule-scopes/affiliations/confirm", (route) => {
    const payload = route.request().postDataJSON();
    const accepted = payload.confirmed === true && payload.acknowledge_bookings === true &&
      payload.fingerprint === "d".repeat(64);
    return route.fulfill({
      status: accepted ? 200 : 422, contentType: "application/json",
      body: JSON.stringify(accepted ?
        { applied: true, calendar_written: false } :
        { detail: "explicit booking acknowledgement required" }),
    });
  });
  await page.getByRole("combobox", { name: "Sous-catégorie", exact: true })
    .selectOption("focus-type");
  await page.getByRole("combobox", { name: "Catégorie cible", exact: true })
    .selectOption(workScope);
  await page.getByRole("button", { name: "Prévisualiser le rattachement" }).click();
  await expect(page.getByText(/provenance inconnue/)).toBeVisible();
  const confirmButton = page.getByRole("button", { name: "Confirmer le rattachement futur" });
  await expect(confirmButton).toBeDisabled();
  await page.getByRole("checkbox", {
    name: /Je reconnais que ces réservations CONFIRMED restent inchangées/,
  }).check();
  await expect(confirmButton).toBeEnabled();
  const confirmation = page.waitForRequest((request) =>
    request.url().endsWith("/affiliations/confirm") && request.method() === "POST");
  const acceptedResponse = page.waitForResponse((response) =>
    response.url().endsWith("/affiliations/confirm") &&
    response.request().method() === "POST");
  page.once("dialog", (dialog) => dialog.accept());
  await confirmButton.click();
  expect((await confirmation).postDataJSON()).toMatchObject({
    work_type_id: "focus-type", scope_id: workScope,
    confirmed: true, acknowledge_bookings: true, fingerprint: "d".repeat(64),
  });
  const accepted = await acceptedResponse;
  expect(accepted.status()).toBe(200);
  expect(await accepted.json()).toMatchObject({ applied: true, calendar_written: false });
  await expect(page.getByText(/Aucune réservation ni événement Google déplacé/)).toBeVisible();
});


test("TP-024C : aperçu d'affiliation périmé 409 est invalidé sans confirmation", async ({ page }) => {
  const workScope = "11111111-1111-4111-8111-111111111111";
  await page.route("**/api/schedule-scopes/affiliations/confirm", (route) =>
    route.fulfill({ status: 409, contentType: "application/json",
      body: JSON.stringify({ detail: "affiliation preview is stale" }) }));
  await page.getByRole("combobox", { name: "Sous-catégorie", exact: true })
    .selectOption("focus-type");
  await page.getByRole("combobox", { name: "Catégorie cible", exact: true })
    .selectOption(workScope);
  await page.getByRole("button", { name: "Prévisualiser le rattachement" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer le rattachement futur" }).click();
  await expect(page.getByRole("alert")).toContainText("409");
  await expect(page.getByRole("button", { name: "Confirmer le rattachement futur" }))
    .toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Sous-catégorie", exact: true }))
    .toHaveValue("focus-type");
  await expect(page.getByRole("button", { name: "Prévisualiser le rattachement" }))
    .toBeEnabled();
});


test("TP-024C : conflit interparent hérité est visible sans fausse nouvelle erreur", async ({ page }) => {
  await page.route("**/api/schedule-scopes/affiliations/preview", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({
      fingerprint: "e".repeat(64), has_changes: true, projection_days: 93,
      from_scope_id: "22222222-2222-4222-8222-222222222222",
      to_scope_id: "11111111-1111-4111-8111-111111111111",
      before_minutes_93d: {}, after_minutes_93d: {},
      global_before_minutes_93d: 60, global_after_minutes_93d: 60,
      conflicts: [{
        code: "INCOMPATIBLE_SCOPES", status: "PREEXISTING",
        starts_at: "2026-11-02T14:00:00Z", ends_at: "2026-11-02T14:30:00Z",
        scope_ids: ["11111111-1111-4111-8111-111111111111",
          "33333333-3333-4333-8333-333333333333"],
        sources: ["RULE:historic"],
      }],
      civil_time_issues: [], unresolved_rule_migrations: [],
      rules_inventory: [], exceptions_inventory: [], manual_blocks_inventory: [],
      all_future_bookings: [],
    }) }));
  await page.getByRole("combobox", { name: "Sous-catégorie", exact: true })
    .selectOption("focus-type");
  await page.getByRole("combobox", { name: "Catégorie cible", exact: true })
    .selectOption("11111111-1111-4111-8111-111111111111");
  await page.getByRole("button", { name: "Prévisualiser le rattachement" }).click();
  await expect(page.getByText(/Préexistant · INCOMPATIBLE_SCOPES/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer le rattachement futur" }))
    .toBeEnabled();
  const noOverflow = await page.evaluate(() =>
    document.documentElement.scrollWidth <= window.innerWidth + 1);
  expect(noOverflow).toBe(true);
});


test("TP-024C : créer une feuille ne l'affecte pas automatiquement à son parent", async ({ page }) => {
  let affiliationConfirms = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/affiliations/confirm")) affiliationConfirms++;
  });
  const scopeManager = page.getByRole("region", { name: "Catégories hiérarchiques" });
  const createLeaf = scopeManager.locator("form").filter({
    has: page.getByRole("heading", { name: "Nouvelle sous-catégorie" }),
  });
  await createLeaf.getByRole("textbox", { name: "Nom" }).fill("Famille");
  await createLeaf.getByRole("combobox", { name: "Parent souhaité" })
    .selectOption("33333333-3333-4333-8333-333333333333");
  await createLeaf.getByRole("button", { name: "Créer puis rattacher" }).click();
  await expect(page.getByText(/Sous-catégorie créée en compatibilité/)).toBeVisible();
  await expect(scopeManager.getByRole("combobox", { name: "Sous-catégorie", exact: true }))
    .toHaveValue("leaf-2");
  await expect(scopeManager.getByRole("combobox", { name: "Catégorie cible", exact: true }))
    .toHaveValue("33333333-3333-4333-8333-333333333333");
  expect(affiliationConfirms).toBe(0);
  const preview = page.waitForRequest((request) =>
    request.url().endsWith("/affiliations/preview") && request.method() === "POST");
  await page.getByRole("button", { name: "Prévisualiser le rattachement" }).click();
  expect((await preview).postDataJSON()).toMatchObject({
    work_type_id: "leaf-2",
    scope_id: "33333333-3333-4333-8333-333333333333",
    expected_affiliation_version: 0,
  });
  expect(affiliationConfirms).toBe(0);
});


test("TP-025C : trois barres, détails clavier, mobile et absence Google sécurisée", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Grille visuelle" }).click();
  await expect(page.getByText("60 minutes physiques déclarées")).toBeVisible();
  await expect(page.getByText(/Temps libre inconnu/)).toBeVisible();
  await expect(page.locator(".eligBar")).toHaveCount(3);
  await page.locator(".eligBar").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Fermer les détails" })).toBeVisible();
  await expect(page.getByText(/révision 1/)).toBeVisible();
  await page.getByRole("button", { name: "Occupation réelle" }).click();
  await expect(page.locator(".eligBar")).toHaveCount(0);
  await page.getByRole("button", { name: "Plan proposé" }).click();
  await expect(page.getByText(/Aucun plan prévisualisé/)).toBeVisible();
  await page.getByText("Vue tabulaire accessible des intervalles et occupations").click();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("table").locator("tbody tr")).toHaveCount(3);
});
