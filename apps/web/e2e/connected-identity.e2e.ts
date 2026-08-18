import { expect, test, type Locator, type Page } from "@playwright/test";

import { ACME_MEMBER, ACME_OWNER, GLOBEX_OWNER, type SeededAccount } from "./stack.js";

/**
 * Claiming a provider account, and giving it back.
 *
 * This is the one flow in Step 34 that no component test can prove, because
 * every part of it is a join: a session decides which person is asking, the
 * database decides whether the account is already held, reconciliation decides
 * which existing records the claim reaches, and the screen decides what any of
 * that is allowed to say. Each half passed its own tests throughout the whole
 * period the identity layer had no production caller at all.
 *
 * **No provider is contacted and none can be.** Confirming an account here is a
 * person asserting ownership from an authenticated session — that is one of the
 * two verification methods the product supports, and the only one available for
 * Slack and Google Chat, neither of which returns a verified address to CAIRN.
 * Nothing in this file mocks a connector into looking connected.
 */

/** The seeded Slack account nobody has claimed — `db/seed.py`. */
const UNCLAIMED_SLACK_ACCOUNT = "U0SEEDALI";

async function signIn(page: Page, account: SeededAccount): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
}

/** The personal section, reached the way a person reaches it. */
async function openConnectedIdentities(page: Page): Promise<Locator> {
  await page.goto("/settings");
  const section = page.getByRole("region", { name: /connected identities/i });
  await expect(section).toBeVisible();
  return section;
}

test("a person claims a source account, sees it, and gives it back", async ({ page }) => {
  await signIn(page, ACME_OWNER);
  const identities = await openConnectedIdentities(page);

  // --- Claim it ------------------------------------------------------------
  //
  // Deliberately no assertion about the starting state. This runs against a
  // seeded database that persists between runs, and the test ends by unlinking
  // — which leaves a revoked row behind, exactly as it should, since ending a
  // link keeps its history. A test that demanded an empty start would pass once
  // and fail forever after, which is worse than not asserting it: the empty
  // state is covered by the member and second-workspace cases below, where it
  // is true and stays true.
  //
  // Typed, not chosen from a list. A pick-list of the workspace's unclaimed
  // accounts would be a directory for claiming a colleague's history, which is
  // why the API does not offer one and why this screen has a field instead.
  await identities.getByRole("combobox", { name: /source/i }).selectOption("slack");
  await identities.getByRole("textbox", { name: /account id/i }).fill(UNCLAIMED_SLACK_ACCOUNT);
  await identities.getByRole("button", { name: /confirm/i }).click();

  await expect(identities).toContainText(/confirmed by you/i);

  // **The account id itself is never rendered.** It is a private provider
  // identifier; showing one as somebody's name would be a disclosure, and this
  // is the screen most likely to do it by accident.
  await expect(page.locator("main")).not.toContainText(UNCLAIMED_SLACK_ACCOUNT);

  // --- The work it produced is now theirs ----------------------------------
  //
  // Reconciliation ran inside the confirm, so the seeded Slack fact that had no
  // owner a moment ago is on this person's own record now.
  await page.goto("/me");
  await expect(page.getByRole("heading", { level: 1, name: "Your record" })).toBeVisible();
  await expect(page.locator("main")).toContainText(/retry logic/i);

  // --- Give it back --------------------------------------------------------
  await openConnectedIdentities(page);
  await identities
    .getByRole("button", { name: /unlink/i })
    .first()
    .click();

  // Confirmation states the consequence, and the consequence is not deletion.
  const confirmation = page.getByRole("group", { name: /unlink|confirm/i }).first();
  await expect(confirmation).toContainText(/nothing is deleted/i);
  await confirmation
    .getByRole("button", { name: /unlink|yes/i })
    .first()
    .click();

  await expect(identities).toContainText(/no longer attributed to you/i);

  // --- The evidence survives, the attribution does not ---------------------
  //
  // The distinction this whole step rests on: CAIRN stops saying the work is
  // theirs, and does not pretend the work never happened. The statement is
  // still in the workspace's record; it is simply no longer on their page.
  await page.goto("/feed");
  await expect(page.locator("main")).toContainText(/retry logic/i);

  await page.goto("/me");
  await expect(page.locator("main")).not.toContainText(/retry logic/i);
});

test("a colleague cannot see or claim what somebody else holds", async ({ browser }) => {
  // A second, independent cookie jar: the point is what a different signed-in
  // person can reach, which a shared context could not demonstrate.
  const context = await browser.newContext();
  const page = await context.newPage();

  await signIn(page, ACME_MEMBER);
  const identities = await openConnectedIdentities(page);

  // A member has their own section and their own empty state. What they must
  // not have is any sight of a colleague's links.
  await expect(identities).toContainText(/nothing connected yet/i);
  await expect(page.locator("main")).not.toContainText(UNCLAIMED_SLACK_ACCOUNT);
  await expect(page.locator("main")).not.toContainText(/ali@acme\.example\.com/i);

  await context.close();
});

test("another workspace's owner reaches none of it", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  await signIn(page, GLOBEX_OWNER);
  const identities = await openConnectedIdentities(page);

  // The same Slack account id in two workspaces is two different questions, and
  // Globex's answer is "nothing" regardless of what Acme has claimed.
  await expect(identities).toContainText(/nothing connected yet/i);
  await expect(page.locator("main")).not.toContainText(UNCLAIMED_SLACK_ACCOUNT);

  await context.close();
});

test("an administrator sees counts and nothing about any individual", async ({ page }) => {
  await signIn(page, ACME_OWNER);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { level: 1, name: /workspace settings/i })).toBeVisible();

  const health = page.getByRole("region", { name: /attribution/i });
  await expect(health).toBeVisible();

  // **The aggregate names nobody.** md/15 §2.3: an administrator may not see
  // more about a member than the member sees about themselves, and md/05 §B.3.3
  // makes a per-person breakdown a product-reclassifying feature. A count is
  // what an Owner needs to ask people to connect their accounts; a list of who
  // has not is a management report about individuals.
  const text = (await health.textContent()) ?? "";
  expect(text).not.toMatch(/ali|sara|priya|jordan/i);
  expect(text).not.toMatch(/@|most|top|rank|leaderboard|score/i);
  expect(text).not.toContain(UNCLAIMED_SLACK_ACCOUNT);

  // No override: an Owner has no control here that writes a colleague's link.
  await expect(health.getByRole("button", { name: /assign|reassign|link .* to/i })).toHaveCount(0);
});
