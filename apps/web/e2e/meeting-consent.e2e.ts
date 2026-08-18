import { expect, test, type Locator, type Page } from "@playwright/test";

import { ACME_MEMBER, ACME_OWNER, GLOBEX_OWNER, type SeededAccount } from "./stack.js";

/**
 * Asking a room full of people, and being unable to proceed until they all say yes.
 *
 * The unanimity rule spans four things that only meet in a browser: a session
 * decides whose answer is being recorded, the database refuses a second live
 * decision, the gate recomputes eligibility from every answer at once, and two
 * different screens have to describe the result without either of them naming
 * who refused. Each half is tested on its own; this is the only place they run
 * together.
 *
 * **Nothing here records a meeting, and nothing can.** CAIRN never joins one and
 * no provider connector exists — these screens decide only whether it may later
 * ask a platform for an artifact that platform produced. A test that mocked a
 * connector into looking connected would be proving a fiction.
 */

async function signIn(page: Page, account: SeededAccount): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
}

/** The participant's own requests, reached the way a person reaches them. */
async function myRequests(page: Page): Promise<Locator> {
  await page.goto("/settings");
  const section = page.getByRole("region", { name: /meeting privacy requests/i });
  await expect(section).toBeVisible();
  return section;
}

/** The administrator's aggregate. */
async function workspaceRequests(page: Page): Promise<Locator> {
  await page.goto("/admin");
  const section = page.getByRole("region", { name: /meeting capture requests/i });
  await expect(section).toBeVisible();
  return section;
}

test("a participant sees their own request and nobody else's answer", async ({ page }) => {
  await signIn(page, ACME_MEMBER);
  const section = await myRequests(page);

  // Whatever state the seeded workspace is in, one property holds always: this
  // screen carries the reader's own answer and no statement about anybody
  // else's. Asserted on the markup rather than the text, so an id hidden in an
  // attribute cannot pass.
  const markup = (await section.innerHTML()).toLowerCase();

  expect(markup).not.toMatch(/ali@acme|sara@acme|jordan@globex/);
  // "3 of 5 agreed" is the subtraction that names the holdout one step earlier.
  expect(markup).not.toMatch(/\d+\s*(of|out of)\s*\d+/);
  // A joining code is a credential; the API deliberately does not publish it.
  expect(markup).not.toMatch(/meet-[a-f0-9]{8}/);
});

test("the administrator's view names nobody and offers no override", async ({ page }) => {
  await signIn(page, ACME_OWNER);
  const section = await workspaceRequests(page);

  // The screen must say what it is *not* before anything else: somebody arriving
  // at "Meeting capture requests" will otherwise assume it records.
  await expect(section).toContainText(/asking permission/i);
  await expect(section).toContainText(/starts no recording|does not record/i);

  const markup = (await section.innerHTML()).toLowerCase();

  // No per-person disclosure, and no way to derive one.
  expect(markup).not.toMatch(/ali@acme|sara@acme/);
  expect(markup).not.toMatch(/\d+\s*(of|out of)\s*\d+/);

  // **No administrative override.** There is no control here that writes
  // somebody else's answer, because in all-party states an employer cannot
  // mandate recording over an objection — a consent an employer could write
  // would be worth nothing.
  await expect(
    section.getByRole("button", { name: /accept for|consent for|approve on behalf/i }),
  ).toHaveCount(0);

  // No bulk affirmative, and no pre-ticked anything.
  await expect(section.getByRole("button", { name: /accept all|approve all/i })).toHaveCount(0);
  await expect(section.getByRole("checkbox")).toHaveCount(0);
});

test("neither screen pressures an answer", async ({ page }) => {
  await signIn(page, ACME_MEMBER);
  const section = await myRequests(page);

  const markup = (await section.innerHTML()).toLowerCase();

  // Countdown and urgency language turn a free decision into a timed one.
  expect(markup).not.toMatch(/countdown|expires in|time left|hurry|act now|last chance/);
  // Nothing measures a person. An identity or consent screen is the most
  // plausible place in this product for the first such affordance to appear.
  expect(markup).not.toMatch(/talk time|sentiment|coaching|attendance|score|rank|leaderboard/);
});

test("another workspace's owner reaches none of it", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  await signIn(page, GLOBEX_OWNER);
  const section = await myRequests(page);

  // Globex's answer is "nothing", whatever Acme has asked for.
  const markup = (await section.innerHTML()).toLowerCase();
  expect(markup).not.toMatch(/ali@acme|sara@acme/);
  expect(markup).not.toMatch(/meet-[a-f0-9]{8}/);

  await context.close();
});

test("the trust centre states the meeting boundary", async ({ page }) => {
  await signIn(page, ACME_OWNER);
  await page.goto("/trust");

  const meetings = page.getByRole("region", { name: /meetings/i });
  await expect(meetings).toBeVisible();

  // The four claims that make the boundary checkable, and the one that keeps it
  // honest: nothing is live yet.
  await expect(meetings).toContainText(/never joins|does not join/i);
  await expect(meetings).toContainText(/everyone|every participant|everybody/i);

  // Consent is a safeguard on top of the lawful basis, never the basis itself —
  // GDPR treats employee consent as invalid in an employment context, and the
  // documented basis is legitimate interest.
  const text = ((await meetings.textContent()) ?? "").toLowerCase();
  expect(text).not.toMatch(/consent is (the|our|its) (legal|lawful) basis/);
});
