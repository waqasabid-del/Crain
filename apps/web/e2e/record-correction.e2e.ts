import { expect, test, type APIRequestContext, type Locator } from "@playwright/test";

import { ACME_OWNER, API_ORIGIN, GLOBEX_OWNER, type SeededAccount } from "./stack.js";

/**
 * One browser, one session, one flow: sign in, read the Brief, correct the
 * record, confirm the correction kept its evidence, confirm the session cannot
 * reach the workspace next door.
 *
 * Written as a single test rather than five, because they are not five
 * questions. Each step depends on the session the previous one established, and
 * splitting them would either mean five sign-ins or a shared storage state —
 * which is the "injected session" this test exists to avoid.
 */

/** Any evidence identifier CAIRN renders, e.g. `github:commit:a1b2c3d4e5f6`. */
const EVIDENCE_ID = /(?:github|chat|meeting|document):\S+/;

/** The shape of `SessionResponse` this test reads. Narrower than the generated
 * client's type on purpose: a browser test asserts what the wire carries. */
interface SessionBody {
  workspaces: { workspace: { id: string } }[];
}

/** The first workspace a session response names. Throws rather than returning
 * `undefined`, so a setup failure never presents as a missing assertion. */
function firstWorkspaceId(session: SessionBody, who: string): string {
  const id = session.workspaces[0]?.workspace.id;
  if (id === undefined) throw new Error(`${who} is a member of no workspace`);
  return id;
}

/**
 * The workspace an account owns, learned by signing that account in through a
 * cookie jar of its own.
 *
 * A separate `APIRequestContext`, never the browser's: the point of the last
 * assertion is that Acme's session cannot reach Globex, and a step that put
 * Globex's cookie in the same jar would be proving something else.
 */
async function workspaceIdOf(request: APIRequestContext, account: SeededAccount): Promise<string> {
  const response = await request.post(`${API_ORIGIN}/v1/auth/login`, { data: account });
  expect(response.status(), `sign-in for ${account.email}`).toBe(200);
  return firstWorkspaceId((await response.json()) as SessionBody, account.email);
}

/** The evidence identifier a row cites, read from what the reader can see. */
async function citedEvidence(row: Locator): Promise<string> {
  const rendered = await row.innerText();
  const [evidence] = EVIDENCE_ID.exec(rendered) ?? [];
  if (evidence === undefined) throw new Error(`No citation rendered in: ${rendered}`);
  return evidence;
}

test("a reader signs in, corrects their record with its evidence intact, and cannot read the next workspace", async ({
  page,
  request,
}) => {
  // Learned before the browser has any session at all, so nothing the browser
  // does can be the reason it knows this id.
  const globexWorkspaceId = await workspaceIdOf(request, GLOBEX_OWNER);

  // -- 1. The real sign-in form. No injected cookie, no seeded storage state --

  await page.goto("/login");
  await page.getByLabel("Email address").fill(ACME_OWNER.email);
  await page.getByLabel("Password").fill(ACME_OWNER.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  // -- 2. The Brief, and the promise it rests on ---------------------------

  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();

  const claims = page.getByRole("list", { name: "Claims in today's brief" });
  await expect(claims.getByRole("listitem").first()).toBeVisible();

  // Citations are behind a collapsed `<details>` — reachable, not printed. A
  // claim CAIRN cannot source is the one thing this product may not ship, so
  // the assertion is that opening a claim's sources reveals an evidence
  // identifier.
  //
  // Any claim with a *linked* citation, not blindly the first claim: the brief
  // deliberately orders newest-first, URL-less sources (meetings) deliberately
  // render unlinked, and an assertion pinned to whichever claim happens to
  // lead was passing or failing on seed ordering rather than on the promise
  // under test. Every claim still opens; the identifier is asserted where a
  // link exists to carry it.
  // Iterate the source disclosures themselves - a claim with no citations
  // renders no disclosure, and indexing listitems assumed one each.
  const disclosures = claims.getByRole("group");
  const count = await disclosures.count();
  expect(count).toBeGreaterThan(0);
  let linked = 0;
  for (let index = 0; index < count; index += 1) {
    const disclosure = disclosures.nth(index);
    await disclosure.click();
    if ((await disclosure.getByRole("link").count()) > 0) {
      await expect(disclosure.getByRole("link").first()).toHaveText(EVIDENCE_ID);
      linked += 1;
    }
  }
  expect(linked, "no claim in the brief carried a resolvable citation").toBeGreaterThan(0);

  // -- 3. The correction, on the screen that actually offers it -------------
  //
  // My Week, not the Brief: `correctFact` is called from exactly one place in
  // the app (routes/MyWeekPage.tsx), and inventing a control on the Brief would
  // be testing a product that does not exist.

  // Scoped to the primary navigation. The page a reader is on also links to
  // their record in prose, so an unscoped query matches two elements and fails
  // as ambiguous — and the point here is that the *navigation* reaches it.
  await page
    .getByRole("navigation", { name: /primary/i })
    .getByRole("link", { name: "Your record" })
    .click();

  const record = page.getByRole("list", { name: "What CAIRN believes about you" });
  const firstFact = record.getByRole("listitem").first();
  await expect(firstFact).toBeVisible();

  const evidence = await citedEvidence(firstFact);

  await firstFact.getByRole("button", { name: /Not right\?/ }).click();

  // Unique per run, so a green result can never be yesterday's row still on the
  // screen. Corrections supersede rather than overwrite, so the next run
  // corrects this sentence in turn — the flow stays repeatable without the test
  // ever needing to reset the database.
  const corrected = `Corrected by the browser suite at ${new Date().toISOString()}.`;

  await firstFact.getByLabel("Or say what it should have said").fill(corrected);
  await firstFact.getByRole("button", { name: "Save correction" }).click();

  // The outcome, not the "Recorded. Thank you" confirmation `FactRow` sets
  // alongside it — see the note at the end of this file. What the reader is
  // owed is their record reading correctly, and that is what is asserted.
  await expect(record.getByRole("listitem").filter({ hasText: corrected })).toBeVisible();

  // -- 4. The corrected record, still traceable ----------------------------
  //
  // Re-read from the server rather than trusting the re-render: the claim is
  // that the correction was *stored* with its provenance, and a component
  // holding the old citations in state would pass either way.

  await page.reload();

  const correctedFact = record.getByRole("listitem").filter({ hasText: corrected });
  await expect(correctedFact).toBeVisible();

  // The whole product claim, in one assertion: the sentence changed, and the
  // evidence it was always traceable to came with it.
  await expect(correctedFact).toContainText(evidence);

  // A human saying "this is what happened" is the strongest evidence CAIRN
  // holds, and `corrections.py` records that by promoting the replacement to
  // `verified`. If it ever silently inherited the extractor's certainty, the
  // screen would understate a fact a person confirmed.
  await expect(correctedFact).toContainText("Verified");

  // -- 5. The gate that must never open ------------------------------------
  //
  // `page.request` shares the browser context's cookies, so this is the signed-
  // in reader's own session asking — the exact request a confused-deputy bug or
  // a dropped RLS policy would answer.

  const session = await page.request.get(`${API_ORIGIN}/v1/auth/session`);
  expect(session.status(), "the browser really is signed in").toBe(200);
  const acmeWorkspaceId = firstWorkspaceId((await session.json()) as SessionBody, ACME_OWNER.email);
  expect(acmeWorkspaceId, "the two workspaces are genuinely different").not.toBe(globexWorkspaceId);

  // The control. Without it, a 404 below would be equally consistent with the
  // API being broken, the session being absent, or the route not existing.
  const own = await page.request.get(`${API_ORIGIN}/v1/workspaces/${acmeWorkspaceId}/facts`);
  expect(own.status(), "this session can read its own workspace").toBe(200);

  const other = await page.request.get(`${API_ORIGIN}/v1/workspaces/${globexWorkspaceId}/facts`);
  expect([403, 404], "Acme's session must be refused Globex's facts, not served them").toContain(
    other.status(),
  );
  // Refused, and refused *empty*: a body carrying rows alongside an error status
  // is still a cross-tenant read.
  expect(await other.text()).not.toContain('"items"');

  const otherBrief = await page.request.get(
    `${API_ORIGIN}/v1/workspaces/${globexWorkspaceId}/brief`,
  );
  expect([403, 404], "and refused the other workspace's brief too").toContain(otherBrief.status());
});

/*
 * Two things this test found, recorded here because the next person to read a
 * failure will look here first.
 *
 * 1. **Step 3 cannot pass on a real deployment.** `GET /me/week` and
 *    `POST .../correction` both resolve the caller through
 *    `Person.user_id == user.id`, and *nothing in the application ever sets
 *    that column*. It is written in exactly two places: `identity/merge`, which
 *    copies it from a person that never had it either, and the fixtures in
 *    `tests/test_corrections.py`. No route exposes a way to claim an identity.
 *    So My Week is permanently "Nothing about you yet" for every real account,
 *    and every correction is a 403 — the employee-owned record commitment is
 *    unreachable through the product. This test is red until an identity a
 *    person can claim links their `Person` to their `User`.
 *
 * 2. **The correction confirmation is never seen.** `FactRow` sets "Recorded.
 *    Thank you" and then calls `onChanged()`; `useAsync.reload` immediately
 *    re-enters `loading`, which unmounts the whole list — and with it the state
 *    holding that sentence. The row does exactly what its own comment says it
 *    must not: it simply vanishes. Cosmetic next to (1), and not asserted here,
 *    because a test may not require behaviour the product does not have.
 */
