import { expect, test } from "@playwright/test";
import { devLoginAndCreateWorkspace, uniqueSlug } from "./helpers";

test.describe("PID-11 hire UX (US-6, US-7, US-8, US-9, US-10)", () => {
  test("US-6 hire wizard uses operator vocabulary, not recipe", async ({ page }) => {
    const slug = uniqueSlug("e2e-vocab");
    await devLoginAndCreateWorkspace(page, "Vocab Co", slug);

    await page.goto(`/${slug}/hire`);
    await expect(page.getByText("Pidgin role templates")).toBeVisible();
    await expect(page.getByText("Your role templates")).toBeVisible();
    await expect(page.getByRole("button", { name: "Create blank template" })).toBeVisible();

    const visible = await page.locator("main").innerText();
    expect(visible.toLowerCase()).not.toMatch(/\brecipe\b/);
  });

  test("US-6 hire executive assistant through four-step wizard", async ({ page }) => {
    const slug = uniqueSlug("e2e-hire");
    await devLoginAndCreateWorkspace(page, "Hire Co", slug);

    await page.goto(`/${slug}/hire`);
    await page
      .locator(".template-card")
      .filter({ hasText: "Executive Assistant" })
      .getByRole("button", { name: "Use this template" })
      .click();

    await expect(page.getByText("Step 2 of 4")).toBeVisible();
    await page.getByLabel("Mission").fill("E2E mission for Casey");
    await page.getByLabel("Your take").fill("E2E operator notes");

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Step 3 of 4")).toBeVisible();
    await page.getByLabel("Agent display name").fill("Casey");
    await page.getByLabel("Handle").fill("casey");

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Step 4 of 4")).toBeVisible();
    await expect(page.getByText("E2E mission for Casey")).toBeVisible();
    await expect(page.getByText("E2E operator notes")).toBeVisible();

    await page.getByRole("button", { name: "Hire and continue" }).click();
    await expect(page).toHaveURL(new RegExp(`/${slug}/agents/casey`));
    await expect(page.getByRole("heading", { name: "Casey" })).toBeVisible();
    await expect(page.getByText("draft")).toBeVisible();
  });

  test("US-7 HR assist suggests copy and Apply to form works", async ({ page }) => {
    const slug = uniqueSlug("e2e-hr");
    await devLoginAndCreateWorkspace(page, "HR Co", slug);

    await page.goto(`/${slug}/hire`);
    await page
      .locator(".template-card")
      .filter({ hasText: "Executive Assistant" })
      .getByRole("button", { name: "Use this template" })
      .click();

    await expect(page.getByText("Discuss with Pidgin")).toBeVisible();
    await page.getByPlaceholder("Ask Pidgin…").fill("Help me write a mission statement");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByRole("button", { name: "Apply to form" })).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: "Apply to form" }).click();

    const mission = page.getByLabel("Mission");
    await expect(mission).not.toHaveValue("");
  });

  test("US-8 duplicate bundled template appears under Your role templates", async ({ page }) => {
    const slug = uniqueSlug("e2e-tmpl");
    await devLoginAndCreateWorkspace(page, "Template Co", slug);

    await page.goto(`/${slug}/hire`);
    await page
      .locator(".template-card")
      .filter({ hasText: "Support Agent" })
      .getByRole("button", { name: "Duplicate" })
      .click();

    await expect(page.getByText("Step 2 of 4")).toBeVisible();
    await page.goto(`/${slug}/templates`);
    await expect(page.getByText("(copy)")).toBeVisible();
  });

  test("US-9 and US-10 agent profile save brief and create template", async ({ page }) => {
    const slug = uniqueSlug("e2e-profile");
    await devLoginAndCreateWorkspace(page, "Profile Co", slug);

    await page.goto(`/${slug}/hire`);
    await page
      .locator(".template-card")
      .filter({ hasText: "Executive Assistant" })
      .getByRole("button", { name: "Use this template" })
      .click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Agent display name").fill("Riley");
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Hire and continue" }).click();

    await page.getByLabel("Mission").fill("Updated mission on profile");
    await page.getByRole("button", { name: "Save brief" }).click();
    await expect(page.getByText("Brief saved.")).toBeVisible();

    await page.getByRole("button", { name: "Create template from this agent" }).click();
    await page.getByPlaceholder("Our tuned support playbook").fill("Riley Playbook");
    await page.getByRole("button", { name: "Save as Your role template" }).click();

    await expect(page).toHaveURL(new RegExp(`/${slug}/templates/`));
    await expect(page.getByText("Riley Playbook")).toBeVisible();
  });

  test("US-6 hired agent appears on Team with draft status", async ({ page }) => {
    const slug = uniqueSlug("e2e-team");
    await devLoginAndCreateWorkspace(page, "Team Co", slug);

    await page.goto(`/${slug}/hire`);
    await page
      .locator(".template-card")
      .filter({ hasText: "Executive Assistant" })
      .getByRole("button", { name: "Use this template" })
      .click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Agent display name").fill("Jordan");
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Hire and continue" }).click();

    await page.goto(`/${slug}/`);
    await expect(page.getByRole("link", { name: "Jordan" })).toBeVisible();
    await expect(page.getByText("draft")).toBeVisible();
  });
});
