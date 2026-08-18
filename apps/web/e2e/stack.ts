import type { APIRequestContext } from "@playwright/test";

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
 * Acme's Member. Same workspace as {@link ACME_OWNER}, one role down.
 *
 * `administers()` in `routes/AdminPage.tsx` admits `owner` and `admin` only, so
 * a Member is the cheapest account that proves the connection screen is
 * readable-but-not-actionable. Acme rather than Globex on purpose: a role test
 * that changed the workspace as well as the role would not isolate which of the
 * two decided the outcome.
 */
export const ACME_MEMBER: SeededAccount = {
  email: "sara@acme.example.com",
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

/**
 * The local mail sink, and the reason these journeys can assert on mail at all.
 *
 * Mailpit accepts SMTP on 1025 and exposes what it captured over HTTP on 8025.
 * It is started by `docker compose up -d` alongside PostgreSQL — see the compose
 * file — and the API is pointed at it by `playwright.config.ts`, so the browser
 * journeys exercise the same `SmtpSender` a deployment uses.
 *
 * The alternative was the console backend, where a message is a log line. That
 * is what allowed a verification link to point at a route that did not exist:
 * the link was *written* correctly, printed correctly, and 404'd when clicked,
 * and no test on either side of the boundary could see it.
 */
export const MAILPIT_ORIGIN = "http://localhost:8025";

export interface CapturedMessage {
  ID: string;
  Subject: string;
  To: { Address: string }[];
  From: { Address: string };
}

/** Everything the sink is currently holding, newest first. */
export async function capturedMessages(request: APIRequestContext): Promise<CapturedMessage[]> {
  const response = await request.get(`${MAILPIT_ORIGIN}/api/v1/messages`);
  const body = (await response.json()) as { messages: CapturedMessage[] };
  return body.messages;
}

/** The plain-text body, which is where the links are — every message is text. */
export async function messageBody(request: APIRequestContext, id: string): Promise<string> {
  const response = await request.get(`${MAILPIT_ORIGIN}/api/v1/message/${id}`);
  const body = (await response.json()) as { Text: string };
  return body.Text;
}

/**
 * Empty the sink.
 *
 * Called at the start of a journey rather than the end: a run that fails
 * half-way leaves its messages behind on purpose, because the message is the
 * evidence somebody needs to see.
 */
export async function clearMail(request: APIRequestContext): Promise<void> {
  await request.delete(`${MAILPIT_ORIGIN}/api/v1/messages`);
}

/** The first link in a message body. Every CAIRN email carries exactly one. */
export function linkIn(body: string): string {
  const match = /https?:\/\/\S+/.exec(body);
  if (match === null) {
    throw new Error("the message carried no link");
  }
  return match[0];
}
