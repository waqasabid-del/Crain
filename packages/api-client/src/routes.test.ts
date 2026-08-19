import { describe, expect, it, vi } from "vitest";

import { createClient, type CairnClient } from "./index.js";

/**
 * Every client method, pinned to the verb and path it sends.
 *
 * The table is the point. Each method here is a thin wrapper over `request`,
 * and the one way it breaks in production is silently: a path typo or a verb
 * change compiles cleanly, type-checks cleanly, and 404s at runtime — the
 * exact failure mode of the `/verify` page, where a route the API wrote and a
 * route the app served drifted apart with every test green. This suite makes
 * the wire contract of all of them an assertion rather than a hope, and covers
 * the coverage the package's threshold demands with tests that actually pin
 * behaviour.
 *
 * Written after CI caught the package below its own coverage floor — a floor
 * that had been quietly failing since the client grew through Stage D. The
 * honest fix is coverage of the real surface, not a smaller floor.
 */

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const W = "ws-1";

/** [method name, invocation, expected verb, expected path] */
const ROUTES: [string, (client: CairnClient) => Promise<unknown>, string, string][] = [
  [
    "signUp",
    (c) => c.signUp({ email: "a@b.c", password: "p", workspaceName: "W", workspaceSlug: "w-s" }),
    "POST",
    "/v1/auth/signup",
  ],
  ["logIn", (c) => c.logIn({ email: "a@b.c", password: "p" }), "POST", "/v1/auth/login"],
  ["verifyEmail", (c) => c.verifyEmail({ token: "t" }), "POST", "/v1/auth/verify-email"],
  ["logOut", (c) => c.logOut(), "POST", "/v1/auth/logout"],
  ["logOutEverywhere", (c) => c.logOutEverywhere(), "POST", "/v1/auth/logout-everywhere"],
  ["getWorkspace", (c) => c.getWorkspace(W), "GET", `/v1/workspaces/${W}`],
  ["listMembers", (c) => c.listMembers(W), "GET", `/v1/workspaces/${W}/members`],
  ["listInvitations", (c) => c.listInvitations(W), "GET", `/v1/workspaces/${W}/invitations`],
  [
    "invite",
    (c) => c.invite(W, { email: "a@b.c", role: "member" }),
    "POST",
    `/v1/workspaces/${W}/invitations`,
  ],
  [
    "acceptInvitation",
    (c) => c.acceptInvitation({ token: "t", email: "a@b.c" }),
    "POST",
    "/v1/invitations/accept",
  ],
  ["getOnboarding", (c) => c.getOnboarding(W), "GET", `/v1/workspaces/${W}/onboarding`],
  ["getBrief", (c) => c.getBrief(W), "GET", `/v1/workspaces/${W}/brief`],
  [
    "getArchivedBrief",
    (c) => c.getArchivedBrief(W, "b-1"),
    "GET",
    `/v1/workspaces/${W}/briefs/b-1`,
  ],
  ["listBriefs", (c) => c.listBriefs(W), "GET", `/v1/workspaces/${W}/briefs`],
  ["listFacts", (c) => c.listFacts(W), "GET", `/v1/workspaces/${W}/facts`],
  ["getFacets", (c) => c.getFacets(W), "GET", `/v1/workspaces/${W}/facets`],
  [
    "changeRole",
    (c) => c.changeRole(W, "u-1", "admin"),
    "PATCH",
    `/v1/workspaces/${W}/members/u-1`,
  ],
  ["listIntegrations", (c) => c.listIntegrations(W), "GET", `/v1/workspaces/${W}/integrations`],
  ["getPrivacy", (c) => c.getPrivacy(W), "GET", `/v1/workspaces/${W}/privacy`],
  ["setRetention", (c) => c.setRetention(W, 90), "PUT", `/v1/workspaces/${W}/privacy`],
  ["getNotifications", (c) => c.getNotifications(W), "GET", `/v1/workspaces/${W}/notifications`],
  ["getTrust", (c) => c.getTrust(W), "GET", `/v1/workspaces/${W}/trust`],
  [
    "listSupportSessions",
    (c) => c.listSupportSessions(W),
    "GET",
    `/v1/workspaces/${W}/support-sessions`,
  ],
  [
    "decideSupportSession",
    (c) => c.decideSupportSession(W, "s-1", true),
    "POST",
    `/v1/workspaces/${W}/support-sessions/s-1/decision`,
  ],
  [
    "revokeSupportSession",
    (c) => c.revokeSupportSession(W, "s-1"),
    "POST",
    `/v1/workspaces/${W}/support-sessions/s-1/revoke`,
  ],
  [
    "startSlackInstall",
    (c) => c.startSlackInstall(W),
    "POST",
    `/v1/workspaces/${W}/integrations/slack/install`,
  ],
  [
    "listSlackChannels",
    (c) => c.listSlackChannels(W),
    "GET",
    `/v1/workspaces/${W}/integrations/slack/channels`,
  ],
  [
    "setSlackChannels",
    (c) => c.setSlackChannels(W, ["C1"]),
    "PUT",
    `/v1/workspaces/${W}/integrations/slack/channels`,
  ],
  [
    "disconnectSlack",
    (c) => c.disconnectSlack(W),
    "POST",
    `/v1/workspaces/${W}/integrations/slack/disconnect`,
  ],
  [
    "startGoogleChatInstall",
    (c) => c.startGoogleChatInstall(W),
    "POST",
    `/v1/workspaces/${W}/integrations/google-chat/install`,
  ],
  [
    "listGoogleChatSpaces",
    (c) => c.listGoogleChatSpaces(W),
    "GET",
    `/v1/workspaces/${W}/integrations/google-chat/spaces`,
  ],
  [
    "setGoogleChatSpaces",
    (c) => c.setGoogleChatSpaces(W, ["spaces/a"]),
    "PUT",
    `/v1/workspaces/${W}/integrations/google-chat/spaces`,
  ],
  [
    "disconnectGoogleChat",
    (c) => c.disconnectGoogleChat(W),
    "POST",
    `/v1/workspaces/${W}/integrations/google-chat/disconnect`,
  ],
  [
    "startGoogleMeetInstall",
    (c) => c.startGoogleMeetInstall(W),
    "POST",
    `/v1/workspaces/${W}/integrations/google-meet/install`,
  ],
  [
    "disconnectGoogleMeet",
    (c) => c.disconnectGoogleMeet(W),
    "POST",
    `/v1/workspaces/${W}/integrations/google-meet/disconnect`,
  ],
  ["getMyIdentities", (c) => c.getMyIdentities(W), "GET", `/v1/workspaces/${W}/me/identities`],
  [
    "confirmMyIdentity",
    (c) => c.confirmMyIdentity(W, "slack", "U1"),
    "POST",
    `/v1/workspaces/${W}/me/identities`,
  ],
  [
    "revokeMyIdentity",
    (c) => c.revokeMyIdentity(W, "i-1", false),
    "POST",
    `/v1/workspaces/${W}/me/identities/i-1/revoke`,
  ],
  [
    "getAttributionHealth",
    (c) => c.getAttributionHealth(W),
    "GET",
    `/v1/workspaces/${W}/attribution-health`,
  ],
  [
    "createMeetingCaptureRequest",
    (c) =>
      c.createMeetingCaptureRequest(W, {
        provider: "google_meet",
        externalMeetingRef: "spaces/x",
        scheduledStart: "2026-01-01T00:00:00Z",
        scheduledEnd: "2026-01-01T01:00:00Z",
        purpose: "p",
        participantPersonIds: ["p-1"],
      }),
    "POST",
    `/v1/workspaces/${W}/meetings/capture-requests`,
  ],
  [
    "listMeetingCaptureRequests",
    (c) => c.listMeetingCaptureRequests(W),
    "GET",
    `/v1/workspaces/${W}/meetings/capture-requests`,
  ],
  [
    "cancelMeetingCaptureRequest",
    (c) => c.cancelMeetingCaptureRequest(W, "m-1"),
    "POST",
    `/v1/workspaces/${W}/meetings/capture-requests/m-1/cancel`,
  ],
  [
    "listMyMeetingRequests",
    (c) => c.listMyMeetingRequests(W),
    "GET",
    `/v1/workspaces/${W}/me/meeting-requests`,
  ],
  [
    "decideMeetingRequest",
    (c) => c.decideMeetingRequest(W, "m-1", "accepted"),
    "POST",
    `/v1/workspaces/${W}/me/meeting-requests/m-1/decision`,
  ],
  ["setWorkRole", (c) => c.setWorkRole(W, "founder"), "PUT", `/v1/workspaces/${W}/me/role`],
  [
    "findRelatedWork",
    (c) => c.findRelatedWork(W, "rate limiting"),
    "GET",
    `/v1/workspaces/${W}/related-work?topic=rate%20limiting`,
  ],
  [
    "setMyCapacity",
    (c) => c.setMyCapacity(W, "open_to_work"),
    "PUT",
    `/v1/workspaces/${W}/me/capacity`,
  ],
  ["mySources", (c) => c.mySources(W), "GET", `/v1/workspaces/${W}/me/sources`],
  [
    "setSourceConsent",
    (c) => c.setSourceConsent(W, { source: "github", optedOut: true }),
    "PUT",
    `/v1/workspaces/${W}/me/sources`,
  ],
  ["myWeek", (c) => c.myWeek(W), "GET", `/v1/workspaces/${W}/me/week`],
  [
    "correctFact",
    (c) => c.correctFact(W, "f-1", { kind: "restate", statement: "s" }),
    "POST",
    `/v1/workspaces/${W}/facts/f-1/correction`,
  ],
  [
    "connectGitHub",
    (c) => c.connectGitHub(W, { installationId: 1, accountLogin: "a", accountType: "User" }),
    "POST",
    `/v1/workspaces/${W}/integrations/github`,
  ],
  ["removeMember", (c) => c.removeMember(W, "u-1"), "DELETE", `/v1/workspaces/${W}/members/u-1`],
  [
    "withdrawInvitation",
    (c) => c.withdrawInvitation(W, "inv-1"),
    "DELETE",
    `/v1/workspaces/${W}/invitations/inv-1`,
  ],
  [
    "disconnectGitHub",
    (c) => c.disconnectGitHub(W, 7),
    "DELETE",
    `/v1/workspaces/${W}/integrations/github/7`,
  ],
];

describe("every method sends the verb and path it promises", () => {
  it.each(ROUTES)("%s", async (_name, call, verb, path) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    await call(client);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe(verb);
    expect(url).toBe(`https://api.test${path}`);
    // The session cookie rides on this; a method that forgot it produces
    // "please sign in" loops that depend on which screen called it.
    expect(init.credentials).toBe("include");
  });

  it("query-taking methods serialise their parameters", async () => {
    // A fresh Response per call: a Body reads once.
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    const client = createClient({ baseUrl: "https://api.test", fetch: fetchMock });

    await client.getBrief(W, { since: "2026-01-01T00:00:00Z" });
    await client.search(W, { q: "retry" });

    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toContain("/brief?");
    expect(urls[0]).toContain("since=");
    expect(urls[1]).toContain("/search?q=retry");
  });
});
