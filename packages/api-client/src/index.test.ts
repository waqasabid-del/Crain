import { describe, expect, expectTypeOf, it, vi } from "vitest";

import { ApiError, type Invitation, type Member, type Session, type Workspace } from "./index.js";
import { createClient } from "./index.js";

/**
 * Two jobs.
 *
 * The runtime tests cover the handful of decisions the wrapper actually makes —
 * credentials, the 204 case, error parsing.
 *
 * The type tests are the more important half, and are the mechanism behind Step
 * 9's exit criterion: *a breaking backend change fails the frontend build*. The
 * drift test in Python proves the schema is current; these prove someone is
 * actually depending on its shape. A generated type nothing references cannot
 * break, so renaming a Pydantic field would pass CI in silence.
 */

/** Await a rejection and return it narrowed, or fail if it resolved. */
async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error: unknown) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("Expected the request to reject, but it resolved.");
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

const SESSION: Session = {
  user: { id: "u1", email: "a@example.com", displayName: null, emailVerified: true },
  workspaces: [{ workspace: { id: "w1", name: "Acme", slug: "acme" }, role: "owner" }],
};

describe("createClient", () => {
  it("sends credentials on every request", async () => {
    // The session is an HttpOnly cookie, so a request without this is
    // unauthenticated. Omitting it is the single most common way a
    // cookie-authenticated frontend ends up signed out on every call — and it
    // fails as a 401, which reads as a backend bug.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SESSION));
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    await client.getSession();

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "include" });
  });

  it("strips a trailing slash from the base URL", async () => {
    // `https://api.test//v1/auth/session` is a 404 on most routers, and the
    // trailing slash is the sort of thing that differs between an env var and a
    // hardcoded default.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SESSION));
    const client = createClient({ baseUrl: "https://api.test/", fetch: fetchMock });

    await client.getSession();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.test/v1/auth/session");
  });

  it("returns null rather than throwing when signed out", async () => {
    // Not being signed in is the expected state on a first page load. Making
    // callers wrap this in try/catch guarantees some of them get it wrong and
    // render an error page to logged-out visitors.
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(
          { type: "about:blank", title: "Not authenticated", status: 401, detail: "Sign in." },
          { status: 401 },
        ),
      );
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    await expect(client.getSession()).resolves.toBeNull();
  });

  it("throws ApiError carrying the problem document", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          type: "https://cairn.dev/problems/invalid-credentials",
          title: "Invalid credentials",
          status: 401,
          detail: "That email and password combination is not correct.",
          requestId: "req-123",
        },
        { status: 401 },
      ),
    );
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    const error = await rejection(client.logIn({ email: "a@example.com", password: "x" }));

    expect(error.is("invalid-credentials")).toBe(true);
    // The correlation ID is what turns a support ticket into a log query.
    expect(error.problem.requestId).toBe("req-123");
  });

  it("does not choke on a non-JSON error body", async () => {
    // A 502 from a load balancer returns HTML. A client that throws
    // "SyntaxError: Unexpected token <" while parsing it has replaced a
    // diagnosable outage with a confusing one.
    const fetchMock = vi.fn().mockResolvedValue(new Response("<html>502</html>", { status: 502 }));
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    const error = await rejection(client.getWorkspace("w1"));

    expect(error.status).toBe(502);
  });

  it("handles a 204 without trying to parse a body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    await expect(client.logOut()).resolves.toBeUndefined();
  });

  it("forwards a caller-supplied correlation ID", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SESSION));
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    await client.getSession({ requestId: "abc" });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-Request-ID"]).toBe("abc");
  });
});

describe("the generated contract", () => {
  /**
   * These assertions exist to be *depended on*.
   *
   * Renaming `slug` to `handle` in the Pydantic model regenerates the schema,
   * regenerates these types, and breaks this file — which is what "a breaking
   * backend change fails the frontend build" means in practice. Without a
   * consumer, the generated types are a file nothing reads.
   */

  it("carries whether the caller has verified their address", () => {
    // Added when email verification closed the pre-registration hijack. The
    // interface needs it to prompt for verification — and this assertion is
    // what made the change break the frontend build rather than pass silently.
    expectTypeOf<Session["user"]>().toHaveProperty("emailVerified");
  });

  it("describes a workspace", () => {
    expectTypeOf<Workspace>().toHaveProperty("id");
    expectTypeOf<Workspace>().toHaveProperty("name");
    expectTypeOf<Workspace>().toHaveProperty("slug");
  });

  it("describes a member without any visibility field", () => {
    expectTypeOf<Member>().toHaveProperty("userId");
    expectTypeOf<Member>().toHaveProperty("role");
    expectTypeOf<Member>().toHaveProperty("joinedAt");

    // Roles govern configuration; they do not govern how much is visible about
    // a person (md/05 §A.2). A members list is exactly where `lastActive` or
    // `commitCount` first gets added, because every other SaaS product has one.
    // @ts-expect-error — there is deliberately no activity field on a member.
    expectTypeOf<Member>().toHaveProperty("lastActive");
  });

  it("never exposes an invitation token", () => {
    expectTypeOf<Invitation>().toHaveProperty("email");
    expectTypeOf<Invitation>().toHaveProperty("expiresAt");

    // The token reaches the invitee by email and nowhere else. Returning it
    // would let anyone who can issue an invitation also redeem it.
    // @ts-expect-error — the token is deliberately absent from the response.
    expectTypeOf<Invitation>().toHaveProperty("token");
  });

  it("types the role as the four-role union", () => {
    // Four roles, deliberately. Role explosion is a documented trap, and a
    // widened union here would be the first sign someone added a fifth.
    expectTypeOf<Session["workspaces"][number]["role"]>().toEqualTypeOf<
      "owner" | "admin" | "member" | "viewer"
    >();
  });
});
