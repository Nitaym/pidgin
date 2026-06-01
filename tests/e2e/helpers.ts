import { expect, type Page } from "@playwright/test";

export async function devLoginAndCreateWorkspace(
  page: Page,
  name: string,
  slug: string,
): Promise<string> {
  await page.goto("/login");
  await page.getByRole("button", { name: "Dev sign-in (local only)" }).click();
  await page.waitForURL(/\/welcome/);
  await page.getByRole("button", { name: "Get started" }).click();
  await page.getByLabel("Company name").fill(name);
  await page.getByPlaceholder("acme-corp").fill(slug);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.waitForURL(new RegExp(`/${slug}/`));
  await expect(page.getByRole("link", { name: "Hire a role" })).toBeVisible();
  return slug;
}

export function uniqueSlug(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}`;
}
