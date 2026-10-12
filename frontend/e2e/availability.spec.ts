import { expect, test, type Page } from "@playwright/test";

async function mockApi(page: Page) {
  let rule: object | null = null;
  let confirmed = false;
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
    if (/\/time-blocks$/.test(path)) return respond([booking]);
    if (/\/resolution\/preview$/.test(path)) return respond({
      state: "PROPOSED", fingerprint: "a".repeat(64), booking,
      decision: "KEEP", conflict_codes: [issue.code], calendar_checked: false,
      replacement: null, consequences: ["Conflit OPEN conservé"], calendar_written: false,
    });
    if (/\/resolution\/confirm$/.test(path)) {
      const body = request.postDataJSON();
      if (body.confirmed !== true || body.fingerprint !== "a".repeat(64) ||
          !body.decision_id || !body.reason) return respond({ detail: "bad confirmation" }, 422);
      confirmed = true;
      return respond({ state: "CONFIRMED_LOCAL", decision: "KEEP", booking: {
        ...booking, revision: 2 }, calendar_written: false, replacement: null });
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

test("une règle hebdomadaire se crée par API depuis la vue desktop", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Scénario desktop.");
  await expect(page.getByRole("heading", { name: "Disponibilités" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nouvelle plage récurrente" })).toBeVisible();
  await page.getByLabel("Date d'effet").fill("2026-10-19");
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
