import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/dev/availability-setup.html");
});

test("empty grid provides a keyboard-usable first window without any bar", async ({ page }) => {
  await expect(page.getByRole("region", { name: "Grille de disponibilités vide" })).toBeVisible();
  await page.getByRole("button", { name: "+ Nouvelle plage" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "Formulaire nouvelle plage" })).toBeVisible();
  await page.getByRole("button", { name: "Prévisualiser" }).click();
  await expect(page.getByRole("alert")).toContainText("Corrige les champs");
  await expect(page.getByText("Crée ou sélectionne une catégorie parente.")).toBeVisible();
  await page.getByRole("button", { name: "Annuler" }).click();
  await expect(page.getByRole("region", { name: "Formulaire nouvelle plage" })).toHaveCount(0);
});

test("mock setup and window preview: no confirmation or API request", async ({ page }) => {
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  await page.getByRole("button", { name: "Créer une catégorie parente" }).click();
  await page.getByRole("button", { name: "Ajouter une sous-catégorie" }).click();
  await page.getByRole("button", { name: "Définir l'enveloppe de travail" }).click();
  await page.getByRole("button", { name: "+ Nouvelle plage" }).click();
  await page.getByLabel("Catégorie parente").selectOption("work");
  await page.getByLabel("Sous-catégorie").selectOption("focus");
  await page.getByRole("checkbox", { name: "Mardi" }).check();
  await page.getByLabel("Heure de fin").fill("11:30");
  await page.getByLabel("Rang de priorité (facultatif)").fill("1");
  await page.getByRole("button", { name: "Prévisualiser" }).click();
  await expect(page.getByRole("status")).toContainText("Aucune plage n'a été enregistrée");
  await expect(page.getByLabel("Aperçu local")).toContainText('"priority":1');
  await expect(page.getByLabel("Aperçu local")).toContainText('"daysOfWeek":[1]');
  expect(apiRequests).toEqual([]);
});
