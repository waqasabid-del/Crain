import { expect, test, type Locator, type Page } from "@playwright/test";

import { ACME_MEMBER, ACME_OWNER, type SeededAccount } from "./stack.js";

/**
 * Google Chat on the screen a customer actually decides from.
 *
 * **No Google OAuth round trip happens here, and none can.**
 * `chat.messages.readonly` is a RESTRICTED scope: granting it needs a published
 * and verified consent screen, a CASA Letter of Assessment, and an authorising
 * account that belongs to a Google Workspace organisation. None of those exist
 * for this repository (see `docs/runbooks/connectors.md`), no real Google
 * credentials are present, and none may be added.
 *
 * So this suite asserts the half of the product that is reachable without them,
 * which is the half that matters most before anybody consents: **what CAIRN
 * tells a reader it will ask Google for, and who is allowed to ask.** It
 * deliberately installs no mocked "connected" state. A faked connection would
 * assert a screen the product cannot currently reach, and an E2E that proves a
 * fiction is worse than one that proves less — the honest counterpart is the
 * last assertion in each test: with no backend data, no space is ever shown as
 * selected or delivering.
 */

/**
 * The two scopes, exactly as `GOOGLE_CHAT_SCOPES` in `ops/connectors.py` names
 * them and in the order the card lists them.
 *
 * Listed here as literals rather than imported from `src/`: the point of a
 * browser test is that the reader sees these two strings, and a test that
 * imported the same constant the component renders would pass if both were
 * wrong together.
 */
const CHAT_SCOPES = ["chat.spaces.readonly", "chat.messages.readonly"] as const;

/** The sentence a personal Gmail account's owner has to read *before* pressing
 * Connect, because Google's own refusal afterwards explains nothing. */
const WORKSPACE_ACCOUNT_RULE = /account you sign in with has to belong to a Google Workspace/i;

/** A Chat space resource name — `spaces/AAAA…`. Nothing in a state with no
 * connection may render one, so this is matched in order to be absent. */
const SPACE_RESOURCE_NAME = /spaces\/[A-Za-z0-9_-]+/;

/** The connection screen, reached the way a person reaches it: the real login
 * form, then the app's own URL. No injected cookie and no seeded storage state —
 * the session is half of what this screen depends on. */
async function signInAndOpenConnections(page: Page, account: SeededAccount): Promise<Locator> {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Brief" })).toBeVisible();

  // `/admin` directly rather than through the nav: `AppShell` hides the
  // "Workspace" link from anyone who does not administer, and the whole point of
  // the Member case below is that the screen itself is still readable.
  await page.goto("/admin");
  await expect(page.getByRole("heading", { level: 1, name: "Workspace" })).toBeVisible();

  const sources = page.getByRole("list", { name: "Connected sources" });
  await expect(sources).toBeVisible();
  return sources;
}

/** The Google Chat card. `exact` matters: without it "Google Chat" would also
 * match a future card whose heading merely mentions it. */
function googleChatCard(sources: Locator): Locator {
  return sources.getByRole("article", { name: "Google Chat", exact: true });
}

test("an Owner is shown what Google Chat would be asked for, and can start it", async ({
  page,
}) => {
  const sources = await signInAndOpenConnections(page, ACME_OWNER);

  const chat = googleChatCard(sources);
  await expect(chat).toBeVisible();

  // Rendered while the answer is still "no". Consent explained only after
  // Google's own consent screen is consent to something the reader had not been
  // told, so the state and the explanation are asserted together.
  await expect(chat).toContainText("Not connected, so CAIRN is reading nothing from Google Chat.");

  // -- The two scopes, verbatim ------------------------------------------

  await expect(
    chat.getByRole("heading", { name: "What CAIRN asks Google Chat for" }),
  ).toBeVisible();

  const scopeNames = chat.locator("dt");
  // Exactly these two, in this order, and *no third*. `toHaveText` with an array
  // asserts the count as well as the contents, which is the assertion that
  // catches a scope quietly added later — the failure mode a per-scope
  // `toBeVisible` loop would pass straight through.
  await expect(scopeNames).toHaveText([...CHAT_SCOPES]);

  // -- The prerequisite that decides whether any of it can work ----------
  //
  // Chat's equivalent of Slack's `/invite` rule, and it fails the same silent
  // way: a personal Gmail account passes every credential, scope and endpoint
  // check and can still authorise nothing. Asserted as being on the card
  // *before* the control, which is where `ConnectionCard` puts a notice — a
  // caveat printed under the button that acts on it is read after the press.
  await expect(chat).toContainText(WORKSPACE_ACCOUNT_RULE);

  // The refusal a reader would otherwise have to infer from the complement of a
  // set whose size they do not know.
  await expect(chat.getByRole("heading", { name: "What CAIRN cannot do" })).toBeVisible();
  await expect(chat).toContainText("CAIRN asks for no permission to write to Google Chat");

  // -- The control an Owner gets ------------------------------------------

  await expect(chat.getByRole("button", { name: "Connect Google Chat" })).toBeVisible();

  // -- And the state it must not claim ------------------------------------
  //
  // The honest floor of this suite. Nothing has authorised anything at Google,
  // no `google_chat_space_selections` row exists and no subscription does
  // either — so the screen may not show a space, may not show one as chosen,
  // and may not show one as delivering. `connected` + a listed space with no
  // lease behind it is precisely the "green while nothing ingests" state the
  // runbook calls worse than an honest failure.
  await expect(chat).not.toContainText(SPACE_RESOURCE_NAME);
  await expect(chat).not.toContainText(/Delivering|Chosen|Selected/);
  await expect(chat.getByRole("group", { name: /spaces CAIRN reads/i })).toHaveCount(0);
  await expect(chat.getByRole("checkbox")).toHaveCount(0);
});

test("a Member is shown the same Google Chat record with nothing to press", async ({ page }) => {
  const sources = await signInAndOpenConnections(page, ACME_MEMBER);

  const chat = googleChatCard(sources);
  await expect(chat).toBeVisible();

  // Read-only means shown the same record, not shown less. What is connected
  // decides what CAIRN can see about the person reading, which is why
  // `list_integrations` is readable by every member rather than by
  // administrators only — so both scopes and the account rule must still be here.
  await expect(chat.locator("dt")).toHaveText([...CHAT_SCOPES]);
  await expect(chat).toContainText(WORKSPACE_ACCOUNT_RULE);

  // The whole of the read-only claim: the explanation is present, and every
  // control that would change the connection is *absent*, not disabled. A
  // disabled button is still a control whose role check has to hold; an absent
  // one is not, and `ConnectionCard` computes `connectable` from `canManage`
  // rather than rendering and greying it.
  await expect(chat).toContainText(
    "An Owner or an Admin of this workspace connects and disconnects sources.",
  );
  await expect(chat.getByRole("button", { name: "Connect Google Chat" })).toHaveCount(0);
  await expect(chat.getByRole("button", { name: "Reconnect Google Chat" })).toHaveCount(0);
  await expect(chat.getByRole("button", { name: "Disconnect" })).toHaveCount(0);
  await expect(chat.getByRole("button")).toHaveCount(0);

  // Same invariant, from the role least able to notice it is wrong.
  await expect(chat).not.toContainText(SPACE_RESOURCE_NAME);
  await expect(chat.getByRole("checkbox")).toHaveCount(0);
});

/*
 * What this file covers, and what it deliberately does not.
 *
 * **Covered.** A real sign-in through the real form for two roles; the Google
 * Chat card on the Workspace screen; both scope strings verbatim *and the
 * absence of a third*; the Workspace-account requirement; the refusals block;
 * the connect control present for an Owner and absent — not disabled — for a
 * Member; and, in both roles, that no space is named, chosen or shown as
 * delivering while nothing has been authorised.
 *
 * **Not covered, and why.**
 *
 * 1. **The OAuth round trip.** `POST .../integrations/google-chat/install`
 *    mints a `state` nonce and returns a Google URL; following it needs a real
 *    Google Workspace account and a consent screen that has passed restricted-
 *    scope verification plus a CASA assessment. No such credentials exist here
 *    and none may be added, so pressing Connect is left unpressed rather than
 *    stubbed.
 * 2. **Space selection and lease state.** `GoogleChatSpaces` renders only when
 *    the connection is `connected`, which requires (1). Everything it shows —
 *    the chosen spaces, the "renewal failed" notice, the deleted-lease notice —
 *    is therefore unreachable from a browser in this repository. The tests
 *    instead assert that none of it is on screen, which is the property that
 *    must hold until (1) is real.
 * 3. **Inbound delivery.** A Chat message arrives over an authenticated Pub/Sub
 *    push from Google's own topic. There is no Google project, no topic and no
 *    subscription, so `inboundVerified` stays false and the release gate stays
 *    `MANUAL`. Nothing in a browser can change that.
 *
 * The renewal sweep behind all of this *is* wired — `jobs/main.py::run_maintenance`
 * calls `renew_expiring_subscriptions` — but it operates on rows that only a real
 * connection creates, so it is covered by `apps/api/tests/test_gchat_subscriptions.py`
 * and is not reachable from here.
 */
