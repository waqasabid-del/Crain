import { expect, test } from "@playwright/test";

import { capturedMessages, clearMail, linkIn, messageBody } from "./stack.js";

/**
 * Mail-dependent journeys, against a real SMTP sender and a real inbox.
 *
 * **This suite exists because a verification link 404'd for the entire life of
 * the signup flow.** The API built `/verify?token=...`, the web app had no such
 * route, and nothing failed: the endpoint's tests passed, the message builder's
 * tests passed, and local development used the console backend, where a message
 * is a log line nobody clicks.
 *
 * Every journey here therefore does the two things a unit test on either side
 * cannot: it asserts a message was actually *captured* by an SMTP server, and
 * it *follows the link in it* to a page that has to exist.
 *
 * Requires the compose stack (`docker compose up -d`) for Mailpit on 1025/8025.
 */

/** A fresh address per run: signup is idempotent about nothing. */
function newAddress(): string {
  return `e2e-${Date.now().toString(36)}@acme.example.com`;
}

test("signing up sends a verification link that resolves", async ({ page, request }) => {
  await clearMail(request);
  const address = newAddress();

  await page.goto("/signup");
  await page.getByLabel("Work email").fill(address);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery");
  await page.getByLabel("Company or team name").fill("E2E Mail");
  await page.getByRole("button", { name: "Create workspace" }).click();

  // The message, in an SMTP server, addressed to the person who signed up.
  await expect
    .poll(async () => (await capturedMessages(request)).length, { timeout: 20_000 })
    .toBeGreaterThan(0);

  const [message] = await capturedMessages(request);
  expect(message.To[0].Address).toBe(address);
  expect(message.Subject).toMatch(/confirm your cairn email address/i);

  // The assertion the original defect needed: follow the link a person would
  // click, and require a page rather than a 404.
  const link = linkIn(await messageBody(request, message.ID));
  expect(link).toContain("/verify?token=");

  const response = await page.goto(link);
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: /address is confirmed/i })).toBeVisible();
});

test("an invitation link reaches a screen the invited person can use", async ({
  page,
  request,
}) => {
  await clearMail(request);
  const owner = newAddress();
  const invited = newAddress();

  await page.goto("/signup");
  await page.getByLabel("Work email").fill(owner);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery");
  await page.getByLabel("Company or team name").fill("E2E Invite");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await page.goto("/settings");
  await page.getByLabel(/email/i).first().fill(invited);
  await page
    .getByRole("button", { name: /invite/i })
    .first()
    .click();

  await expect
    .poll(
      async () => {
        const messages = await capturedMessages(request);
        return messages.filter((m) => m.To[0]?.Address === invited).length;
      },
      { timeout: 20_000 },
    )
    .toBeGreaterThan(0);

  const invitation = (await capturedMessages(request)).find((m) => m.To[0]?.Address === invited);
  if (invitation === undefined) {
    throw new Error("no invitation reached the sink");
  }
  expect(invitation.Subject).toMatch(/invited to/i);

  const link = linkIn(await messageBody(request, invitation.ID));
  expect(link).toContain("/invite?token=");

  // A separate context would be more faithful, but the assertion that matters
  // is the same either way: the link resolves to the redemption screen rather
  // than to a 404 or a sign-in page that discards the token.
  const response = await page.goto(link);
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: /invited to cairn/i })).toBeVisible();
});
