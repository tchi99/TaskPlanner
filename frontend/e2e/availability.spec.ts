import { expect, test, type Page } from "@playwright/test";

// TP-026B: integrated API mocks for the *new* parented availability model.
// No auto-created parent, historical affiliation, or manual block editor.
const parentId = "11111111-1111-4111-8111-111111111111";
const leafId = "22222222-2222-4222-8222-222222222222";
const seriesId = "33333333-3333-4333-8333-333333333333";
const ruleId = "44444444-4444-4444-8444-444444444444";
const headers = { contentType: "application/json" };

// Mirror app/application/weekly_schedule.py::_key_str: the UI labels each changed
// cell by the full backend section identity, not by weekday alone.
function sectionKey(section: {
  weekday: number; kind: string; work_type_id: string | null; scope_id?: string | null;
}, timezone: string): string {
  const base = `${section.weekday}:${section.kind}:${section.work_type_id || "NULL"}:${timezone}`;
  return section.scope_id ? base + ":SCOPE:" + section.scope_id : base;
}

async function setup(page: Page, { stale = false, existingBooking = false } = {}) {
  const requests: { path: string; method: string; body: any }[] = [];
  let parents: { id: string; name: string; version: number; state: "ACTIVE" | "INACTIVE" }[] = [];
  let types: { id: string; name: string; scope_id: string; description: null; version: number }[] = [];
  let envelope = false;
  let permissions = 0;
  let confirmed = 0;
  let bookingCancelled = false;
  await page.route("**/api/**", async (route) => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    const method = req.method();
    const body = method === "GET" ? null : req.postDataJSON?.() ?? null;
    requests.push({ path, method, body });
    const respond = (value: unknown, status = 200) => route.fulfill({
      ...headers, status, body: JSON.stringify(value),
    });
    if (path === "/api/tasks" || path === "/api/projects") return respond([]);
    if (path === "/api/work-types") {
      if (method === "POST") {
        if (!parents.some((parent) => parent.id === body.scope_id))
          return respond({ detail: "Parent requis" }, 422);
        const created = { id: leafId, name: body.name, scope_id: body.scope_id,
          description: null, version: 1 };
        types = [...types, created];
        return respond(created, 201);
      }
      return respond(types);
    }
    if (path === "/api/schedule-scopes") {
      if (method === "POST") {
        const value = { id: parentId, name: body.name, version: 1, state: "ACTIVE" as const };
        parents = [...parents, value]; return respond(value, 201);
      }
      return respond({ scopes: parents });
    }
    if (path.startsWith("/api/schedule-scopes/") && method === "PATCH") {
      parents = parents.map((p) => p.id === path.split("/")[3] ?
        { ...p, name: body.name, state: body.state, version: p.version + 1 } : p);
      return respond(parents[0]);
    }
    if (path === "/api/availability/rules") return respond(envelope ? [{
      id: ruleId, version: 1, revisions: [{
        number: 1, effective_from: "2026-10-19", valid_until: null,
        timezone_name: "America/Toronto", days_of_week: [0, 1, 2, 3, 4],
        starts_at_local: "09:00", ends_at_local: "12:00",
        kind: "GENERAL", work_type_id: null, scope_id: parentId,
        mode: null, enabled: true, start_fold: null, end_fold: null,
      }],
    }] : []);
    if (path === "/api/availability/rules/occurrences") return respond({ occurrences: [] });
    if (path === "/api/availability/exceptions") return respond([]);
    if (path === "/api/availability/effective") return respond({
      projection: "DECLARED_NOT_CALENDAR_VERIFIED",
      declared_minutes: envelope ? 180 : 0, blocks: [], issues: [], expansion_issues: [],
    });
    if (path === "/api/availability/weekly-schedule") {
      return respond({ effective_from: url.searchParams.get("effective_from"),
        timezone_name: url.searchParams.get("timezone_name"),
        source_versions: {}, sections: [], future_revisions: [] });
    }
    if (path === "/api/availability/weekly-schedule/preview") return respond({
      fingerprint: "f".repeat(64), has_changes: true, projection_days: 93,
      before_declared_minutes_93d: envelope ? 180 : 0, after_declared_minutes_93d: 9000,
      changed_sections: body.sections.map((section: { weekday: number; kind: string; work_type_id: string | null; scope_id?: string | null }) => sectionKey(section, body.timezone_name)),
      cell_changes: body.sections.map((section: { weekday: number; kind: string; work_type_id: string | null; scope_id?: string | null; slots: unknown[] }) => ({
        section: sectionKey(section, body.timezone_name), before: [], after: section.slots, previous_future: [],
      })),
      series_cutovers: [], exception_remaps: [], unresolved_exceptions: [],
      booking_conflicts: [], invalid_conflicts: [], invalid_diagnostics: [],
      civil_time_issues: [], calendar_verified: false,
    });
    if (path === "/api/availability/weekly-schedule/confirm") {
      if (!body.confirmed || body.fingerprint !== "f".repeat(64))
        return respond({ detail: "Preview required" }, 409);
      envelope = true; return respond({ applied: true, calendar_written: false });
    }
    if (path === "/api/availability/eligibility-week") {
      const week = url.searchParams.get("week_start") || "2026-10-19";
      const offset = (date: string, n: number) => {
        const d = new Date(date + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n);
        return d.toISOString().slice(0, 10);
      };
      const days = Array.from({ length: 7 }, (_, weekday) => ({
        weekday, local_date: offset(week, weekday), minutes: 1440,
        starts_at: offset(week, weekday) + "T00:00:00-04:00",
        ends_at: offset(week, weekday + 1) + "T00:00:00-04:00",
        ticks: [{ minute: 0, label: "00 h" }, { minute: 1440, label: "24 h" }],
      }));
      const fragment = {
        scope_id: parentId, weekday: 1, local_date: offset(week, 1),
        starts_at: offset(week, 1) + "T09:00:00-04:00",
        ends_at: offset(week, 1) + "T11:00:00-04:00",
        starts_at_local: "09:00", ends_at_local: "11:00",
        start_minute: 540, end_minute: 660, day_minutes: 1440,
        minutes: 120, sources: [seriesId], null_residual: false,
        choices: [{ work_type_id: leafId, priority_rank: 1, exclusive: false,
          legacy_mode: null, sources: [seriesId], source_details: [{
            series_id: seriesId, revision: 1, effective_from: "2026-10-19",
            valid_until: null, timezone_name: "America/Toronto",
            original_local_date: offset(week, 1), source: seriesId,
          }] }], verification: "NOT_VERIFIED",
      };
      return respond({
        week_start: week, timezone_name: url.searchParams.get("timezone_name"),
        scope_id: parentId, read_only: true, calendar_state: "NOT_CONFIGURED",
        calendar_checked: false, calendar_error: null, physical_minutes: envelope ? 120 : 0,
        verified_free_minutes: null, verified_occupied_minutes: null, local_occupied_minutes: 0,
        potential_minutes: permissions ? [{ work_type_id: leafId,
          minutes: 120, non_additive: true }] : [],
        days, fragments: envelope && permissions ? [fragment] : [],
        editable_permissions: envelope && permissions ? [{
          series_id: seriesId, expected_version: 1, revision: 1,
          effective_from: "2026-10-19", timezone_name: "America/Toronto",
          days_of_week: [1], starts_at_local: "09:00", ends_at_local: "11:00",
          start_fold: null, end_fold: null, priority_rank: 1,
          scope_id: parentId, work_type_id: leafId,
          original_local_date: offset(week, 1),
          starts_at: fragment.starts_at, ends_at: fragment.ends_at,
          source: "SERIES", exception_id: null, exception_version: null,
        }] : [],
        occupations: [], issues: [], expansion_issues: [],
      });
    }
    if (path === "/api/availability/eligibility-edits/series/" + seriesId) {
      return respond({ id: seriesId, version: 1, revisions: [{
        effective_from: "2026-10-19", timezone_name: "America/Toronto",
        days_of_week: [1], starts_at_local: "09:00", ends_at_local: "11:00",
        priority_rank: 1, enabled: true, start_fold: null, end_fold: null,
      }] });
    }
    if (path === "/api/availability/eligibility-edits/preview") {
      if (!envelope) return respond({ detail: "Outside envelope" }, 409);
      return respond({
        fingerprint: "e".repeat(64), blocking_issues: [], booking_inventory: [],
        before_physical_minutes: 120, after_physical_minutes: 120,
        calendar_checked: false, projection_days: 93, consequences: [
          "Les deux permissions peuvent partager la même capacité physique.",
        ],
      });
    }
    if (path === "/api/availability/eligibility-edits/confirm") {
      if (stale) return respond({ detail: "Version modifiée" }, 409);
      if (body.fingerprint !== "e".repeat(64) || !body.confirmed ||
          body.command_id !== body.draft_id)
        return respond({ detail: "Confirmation incorrecte" }, 422);
      confirmed++; permissions++; return respond({
        applied: true, calendar_written: false, series_id: seriesId,
      });
    }
    if (path.match(/^\/api\/capacity\/weeks\/\d{4}-\d{2}-\d{2}\/time-blocks$/)) {
      return respond(existingBooking && !bookingCancelled ? [{
        id: "booking-1", task_id: "task-1", work_type_id: leafId,
        starts_at: "2026-10-20T09:00:00-04:00",
        ends_at: "2026-10-20T10:00:00-04:00", status: "CONFIRMED", revision: 1,
      }] : []);
    }
    if (path.endsWith("/resolution/preview")) return respond({
      fingerprint: "r".repeat(64), decision: body.decision, conflict_codes: [],
      calendar_checked: false, consequences: ["Réservation conservée jusqu'à confirmation"],
      replacement: null,
    });
    if (path.endsWith("/resolution/confirm")) {
      if (!body.confirmed || body.fingerprint !== "r".repeat(64))
        return respond({ detail: "Confirmation requise" }, 422);
      bookingCancelled = true; return respond({ applied: true, calendar_written: false });
    }
    if (path.endsWith("/resolution/history")) return respond([]);
    if (path === "/api/availability/verified")
      return respond({ detail: "Google Calendar indisponible" }, 503);
    if (path.match(/^\/api\/capacity\/weeks\/\d{4}-\d{2}-\d{2}$/)) {
      return respond({ blocks: [], capacity: { available_minutes: 0, status: "INCOMPLETE",
        known_demand_minutes: 0, remaining_minutes: 0, unestimated_units: 0,
        by_work_type: [] } });
    }
    if (path.endsWith("/evaluate")) return respond({
      status: "INCOMPLETE", available_minutes: envelope ? 120 : 0,
      known_demand_minutes: 0, remaining_minutes: envelope ? 120 : 0,
      unestimated_units: 0, by_work_type: [],
    });
    return respond({ detail: "Unmocked endpoint: " + path }, 404);
  });
  await page.goto("/");
  await page.getByRole("navigation", { name: "Navigation principale" })
    .getByRole("button", { name: /Planification|Planifier/ }).click();
  return { requests, getState: () => ({ parents, types, envelope, permissions, confirmed }) };
}

async function prepareParentAndType(page: Page) {
  await page.locator("#tp26-new-parent").fill("Travail");
  await page.getByRole("button", { name: "Créer le parent" }).click();
  await expect(page.getByText("Travail", { exact: true }).first()).toBeVisible();
  await page.locator("#tp26-new-work-type").fill("Focus work");
  await page.getByRole("button", { name: "Ajouter la sous-catégorie" }).click();
  await expect(page.getByText("Focus work", { exact: true }).first()).toBeVisible();
}

async function prepareEnvelope(page: Page) {
  const editor = page.getByRole("region", { name: "Éditeur hebdomadaire" });
  const details = page.locator("details").filter({ has: page.locator("section.weeklyEditor") });
  await editor.getByRole("button", { name: "Ajouter une plage au Mardi" }).click();
  await editor.getByRole("button", { name: "Prévisualiser les changements" }).click();
  await expect(editor.getByText(/Capacité déclarée sur 93 jours/)).toBeVisible();
  const confirmed = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/availability/weekly-schedule/confirm" &&
    response.request().method() === "POST");
  await editor.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }).click();
  const receipt = await confirmed;
  expect(receipt.ok()).toBe(true);
  expect(await receipt.json()).toMatchObject({ applied: true, calendar_written: false });
  // When a parent's first envelope is saved, the unified setup intentionally
  // collapses its editor. Reopen it before inspecting the saved-status message.
  await expect(details).not.toHaveAttribute("open", "");
  await details.locator("summary").click();
  await expect(editor.getByText(/Horaire futur enregistré atomiquement/)).toBeVisible();
}

async function prepareWindow(page: Page, priority = "") {
  await page.getByRole("button", { name: "+ Nouvelle plage" }).last().click();
  const panel = page.getByRole("region", { name: "Panneau contextuel de la grille" });
  await panel.getByRole("checkbox", { name: "Lundi" }).uncheck();
  await panel.getByRole("checkbox", { name: "Mardi" }).check();
  if (priority) await panel.getByLabel("Rang contextuel (vide = neutre)").fill(priority);
  await panel.getByRole("button", { name: "Prévisualiser les conséquences" }).click();
  await expect(panel.getByText(/Aperçu serveur/)).toBeVisible();
  return panel;
}

test("base vierge : parcours guidé, grille sans barre et aucun parent synthétique", async ({ page }) => {
  const app = await setup(page);
  await expect(page.getByRole("region", { name: "Première configuration" })).toBeVisible();
  await expect(page.getByText(/Aucune catégorie n.est créée automatiquement/)).toBeVisible();
  await expect(page.getByText("Compatibilité (héritage)")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "+ Nouvelle plage" }).first()).toBeEnabled();
  expect(app.getState().parents).toEqual([]);
});

test("sous-catégorie créée directement sous son parent, sans affiliation", async ({ page }) => {
  const app = await setup(page);
  await prepareParentAndType(page);
  expect(app.getState().types[0]).toMatchObject({ name: "Focus work", scope_id: parentId });
  expect(app.requests.some((req) => req.path.includes("/affiliations"))).toBe(false);
  await expect(page.getByText("Créer puis rattacher")).toHaveCount(0);
});

test("enveloppe GENERAL versionnée : aperçu avant confirmation, sans modèle catégorisé", async ({ page }) => {
  const app = await setup(page);
  await prepareParentAndType(page);
  const editor = page.getByRole("region", { name: "Éditeur hebdomadaire" });
  await editor.getByRole("button", { name: "Ajouter une plage au Mardi" }).click();
  await editor.getByRole("button", { name: "Prévisualiser les changements" }).click();
  expect(app.getState().envelope).toBe(false);
  const preview = app.requests.find((request) =>
    request.path === "/api/availability/weekly-schedule/preview");
  expect(preview?.body.sections).toMatchObject([
    { weekday: 1, kind: "GENERAL", work_type_id: null, scope_id: parentId },
  ]);
  await editor.getByRole("button", { name: "Confirmer et enregistrer l'horaire futur" }).click();
  await expect.poll(() => app.getState().envelope).toBe(true);
  await expect(page.getByLabel("Section de l'horaire")).toHaveCount(0);
});

test("première permission créée depuis grille vide après aperçu confirmé, clavier", async ({ page }) => {
  const app = await setup(page);
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  await page.getByRole("button", { name: "+ Nouvelle plage" }).first().focus();
  await page.keyboard.press("Enter");
  const panel = page.getByRole("region", { name: "Panneau contextuel de la grille" });
  await panel.getByRole("checkbox", { name: "Lundi" }).uncheck();
  await panel.getByRole("checkbox", { name: "Mardi" }).check();
  await panel.getByRole("button", { name: "Prévisualiser les conséquences" }).click();
  expect(app.getState().confirmed).toBe(0);
  await expect(page.getByText(/Les deux permissions peuvent partager/)).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer explicitement" }).click();
  await expect.poll(() => app.getState().confirmed).toBe(1);
  const confirmed = app.requests.find((request) =>
    request.path === "/api/availability/eligibility-edits/confirm");
  expect(confirmed?.body).toMatchObject({ confirmed: true, expected_version: 0,
    scope_id: parentId, work_type_id: leafId, days_of_week: [1],
    priority_rank: null, fingerprint: "e".repeat(64) });
  await expect(page.getByText("Compatibilité (héritage)")).toHaveCount(0);
});

test("priorité facultative et capacités non additives sur permissions superposables", async ({ page }) => {
  const app = await setup(page);
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  await prepareWindow(page, "1");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer explicitement" }).click();
  await expect.poll(() => app.getState().confirmed).toBe(1);
  expect(app.requests.find((v) => v.path.endsWith("/eligibility-edits/preview"))?.body.priority_rank)
    .toBe(1);
  await expect(page.getByText(/minutes physiques/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Occupation réelle", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Plan proposé", exact: true })).toBeEnabled();
  await expect(page.getByText(/les permissions superposées/i).first()).toBeVisible();
});

test("édition contextuelle d'une permission existante sans conversion historique", async ({ page }) => {
  const app = await setup(page);
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  await prepareWindow(page, "1");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer explicitement" }).click();
  await expect.poll(() => app.getState().confirmed).toBe(1);
  await page.locator(".eligVBar").first().click();
  await expect(page.getByRole("region", { name: "Panneau contextuel de la grille" })).toBeVisible();
  await expect(page.getByText(/Convertir la règle historique/)).toHaveCount(0);
});

test("modification d'un champ invalide l'ancien aperçu et empêche une confirmation périmée", async ({ page }) => {
  const app = await setup(page);
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  const form = await prepareWindow(page, "1");
  await form.getByLabel("Fin locale (24:00 permis)").fill("11:30");
  await expect(page.getByRole("button", { name: "Confirmer explicitement" })).toHaveCount(0);
  expect(app.getState().confirmed).toBe(0);
  await form.getByRole("button", { name: "Prévisualiser les conséquences" }).click();
  await expect(page.getByRole("button", { name: "Confirmer explicitement" })).toBeVisible();
});

test("409 sur confirmation conserve le brouillon et exige un nouvel aperçu", async ({ page }) => {
  const app = await setup(page, { stale: true });
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  const form = await prepareWindow(page, "1");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer explicitement" }).click();
  await expect(page.getByText(/Le brouillon est conservé/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer explicitement" })).toHaveCount(0);
  await expect(form.getByLabel("Début local")).toHaveValue("09:00");
  expect(app.getState().confirmed).toBe(0);
});

test("interface mobile : configuration au clavier et aucune écriture Google", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "Recette mobile.");
  const app = await setup(page);
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  await page.getByRole("button", { name: "+ Nouvelle plage" }).first().click();
  await expect(page.getByRole("region", { name: "Panneau contextuel de la grille" })).toBeVisible();
  expect(app.requests.some((v) => v.path.includes("/calendar") && v.method !== "GET")).toBe(false);
});

test("aucune saisie manuelle exclusive dans Capacité et propositions", async ({ page }) => {
  await setup(page);
  await page.getByRole("button", { name: "Capacité et propositions" }).click();
  await expect(page.getByRole("button", { name: "Ajouter un bloc disponible" })).toHaveCount(0);
  await expect(page.getByText(/ne crée aucun bloc manuel parallèle/)).toBeVisible();
});


test("TP-027B : sélection de plage dans la grille crée un brouillon sans mutation", async ({ page }) => {
  const app = await setup(page);
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  const track = page.locator('.eligDayCol[data-day="1"] .eligDayTrack');
  const box = await track.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  const x = box.x + box.width / 2;
  const y = box.y + 3 * 54 + 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 54, { steps: 4 });
  await page.mouse.up();
  const panel = page.getByRole("region", { name: "Panneau contextuel de la grille" });
  await expect(panel).toBeVisible();
  await expect(panel.getByLabel("Début local")).toHaveValue("09:00");
  await expect(panel.getByLabel("Fin locale (24:00 permis)")).toHaveValue("10:00");
  expect(app.requests.some((req) => req.path.endsWith("/eligibility-edits/confirm"))).toBe(false);
  await panel.getByRole("button", { name: "Annuler le brouillon" }).click();
  await expect(panel).toHaveCount(0);
  expect(app.getState().confirmed).toBe(0);
});

test("TP-027B : source éditable entière au clavier, sans confirmer l'occupation", async ({ page }) => {
  const app = await setup(page, { existingBooking: true });
  await prepareParentAndType(page);
  await prepareEnvelope(page);
  await prepareWindow(page);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirmer explicitement" }).click();
  await expect.poll(() => app.getState().confirmed).toBe(1);
  const bar = page.locator(".eligVBar").first();
  await bar.focus();
  await page.keyboard.press("Enter");
  const panel = page.getByRole("region", { name: "Panneau contextuel de la grille" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/Occurrences futures des jours ciblés/)).toBeVisible();
  await panel.getByLabel("Fin locale (24:00 permis)").fill("11:30");
  await expect(panel.getByRole("button", { name: "Confirmer explicitement" })).toHaveCount(0);
  expect(app.requests.some((req) => req.path.endsWith("/resolution/confirm"))).toBe(false);
});
