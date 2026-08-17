/**
 * The stack the browser test drives, and the accounts it signs in as.
 *
 * Shared by `playwright.config.ts` (which starts the processes) and the spec
 * (which talks to them), so the ports cannot drift apart between the two.
 */

/**
 * Dedicated ports, not 8000/3000.
 *
 * Two reasons, and the second is the one that matters:
 *
 * 1. A developer with `make serve` and `next dev` already running should be
 *    able to run this without losing either.
 * 2. **The API this test needs is configured differently.** `get_brief`
 *    synthesises through whichever model adapter `CAIRN_MODEL_BACKEND`
 *    selects, and the default (`auto`, with no `CAIRN_GCP_PROJECT_ID`) is the
 *    offline provider, which correctly abstains — an empty Brief with no
 *    claims and no citations. Reusing a developer's ordinary API would make
 *    this test pass or fail on how their shell happened to be exported.
 *    Owning the process means owning that setting.
 */
export const API_PORT = 8001;
export const WEB_PORT = 3001;

export const API_ORIGIN = `http://localhost:${String(API_PORT)}`;
export const WEB_ORIGIN = `http://localhost:${String(WEB_PORT)}`;

export interface SeededAccount {
  readonly email: string;
  readonly password: string;
}

/**
 * `SEED_PASSWORD` from `apps/api/src/cairn_api/db/seed.py`.
 *
 * Public by construction rather than by carelessness: `config.py` refuses to
 * start a deployed environment on the development database these accounts live
 * in, so this string cannot be a credential anywhere that holds customer data.
 */
const SEED_PASSWORD = "correct-horse-battery";

/** Acme's owner. The workspace the seed gives real activity, a brief and facts. */
export const ACME_OWNER: SeededAccount = {
  email: "ali@acme.example.com",
  password: SEED_PASSWORD,
};

/**
 * Globex's owner — the second tenant, and the point of the isolation step.
 *
 * The seed exists in this shape deliberately: "one proves nothing about
 * isolation". Signing in as this account through a *separate* cookie jar is
 * how the test learns Globex's workspace id without ever giving Acme's session
 * a legitimate way to know it.
 */
export const GLOBEX_OWNER: SeededAccount = {
  email: "jordan@globex.example.com",
  password: SEED_PASSWORD,
};
