import { expect, test, type Page } from "@playwright/test";

import { ACME_MEMBER, ACME_OWNER, GLOBEX_OWNER, type SeededAccount } from "./stack.js";

/**
 * What the product says about Google Meet, checked in a browser.
 *
 * **No Google call happens here and none can.** Meet needs an OAuth client this
 * repository does not have, and transcript retrieval additionally needs
 * `drive.meet.readonly` — a RESTRICTED scope requiring an independent CASA
 * security assessment nobody has completed. So this suite asserts the half that
 * is reachable without them, which is the half a customer reads before deciding
 * anything: what CAIRN says it will do, what it says it will never do, and
 * whether it claims to be working when it is not.
 *
 * A test that mocked a connected Meet would be proving a fiction about the most
 * sensitive connector in the product.
 */

async function signIn(page: Page, account: SeededAccount): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
}

/** Every string that would be a disclosure if it reached a screen. */
const FORBIDDEN = [
  // A Meet joining code. Anybody holding one can attempt to join the call.
  /\b[a-z]{3}-[a-z]{4}-[a-z]{3}\b/,
  // Google's own resource shapes.
  /spaces\/[A-Za-z0-9_-]+/,
  /conferenceRecords\//,
  /meetingCode|meetingUri/,
  // A Drive file id or link — the transcript itself.
  /drive\.google\.com|docs\.google\.com/,
  // Anybody's address.
  /@acme\.example|@globex\.example/,
];

test("the workspace screen states the boundary before anything else", async ({ page }) => {
  await signIn(page, ACME_OWNER);
  await page.goto("/admin");

  const meet = page.getByRole("article", { name: "Google Meet", exact: true });
  await expect(meet).toBeVisible();

  // The sentence a person needs before they read anything else on the card.
  await expect(meet).toContainText(/does not join calls or start recordings/i);
  await expect(meet).toContainText(/every participant/i);

  // The scope, and what it does *not* buy. A connector that listed a scope
  // without saying what it excludes is asking somebody to look it up.
  await expect(meet).toContainText(/meetings\.space\.readonly/);
  await expect(meet).toContainText(/does not let CAIRN read one/i);

  const markup = await meet.innerHTML();
  for (const pattern of FORBIDDEN) {
    expect(markup).not.toMatch(pattern);
  }
});

test("nothing claims Meet is live", async ({ page }) => {
  await signIn(page, ACME_OWNER);
  await page.goto("/admin");

  const meet = page.getByRole("article", { name: "Google Meet", exact: true });
  const text = ((await meet.textContent()) ?? "").toLowerCase();

  // "Connected" is a state a workspace can reach; "live", "active" and
  // "recording" are claims this connector cannot make yet.
  expect(text).not.toMatch(/is live|now recording|recording in progress/);
  // And no status word invented from an absent field: with nothing connected,
  // the card carries no subscription state at all.
  expect(text).not.toMatch(/subscribed|subscription expiring/);
});

test("the trust centre explains the meeting boundary and the gate", async ({ page }) => {
  await signIn(page, ACME_OWNER);
  await page.goto("/trust");

  const meetings = page.getByRole("region", { name: /meetings/i });
  await expect(meetings).toBeVisible();

  await expect(meetings).toContainText(/never joins|does not join/i);
  await expect(meetings).toContainText(/every participant|everyone|everybody/i);

  // The honest present tense: verification is outstanding, so it is not live.
  await expect(meetings).toContainText(/verification|not yet live|cannot be connected/i);

  const markup = await meetings.innerHTML();
  for (const pattern of FORBIDDEN) {
    expect(markup).not.toMatch(pattern);
  }
});

test("a member reads the record and gets no controls", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  await signIn(page, ACME_MEMBER);
  await page.goto("/trust");

  // The Trust Center is where a member sees what is connected. They are
  // entitled to the same record as an Owner — md/15 §2.3 — and to none of the
  // controls, because connecting a source is a configuration decision.
  const meetings = page.getByRole("region", { name: /meetings/i });
  await expect(meetings).toContainText(/does not join|never joins/i);
  await expect(meetings.getByRole("button", { name: /connect|disconnect/i })).toHaveCount(0);

  await context.close();
});

test("another workspace sees its own Meet record and nothing of Acme's", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  await signIn(page, GLOBEX_OWNER);
  await page.goto("/admin");

  const meet = page.getByRole("article", { name: "Google Meet", exact: true });
  await expect(meet).toBeVisible();

  const markup = await meet.innerHTML();
  for (const pattern of FORBIDDEN) {
    expect(markup).not.toMatch(pattern);
  }

  await context.close();
});
