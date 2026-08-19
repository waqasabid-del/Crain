import { ApiError, type CairnClient, type Member, type Session } from "@cairn/api-client";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";

import { setRoute } from "./router-mock.js";

import { Providers } from "../app/providers.js";

/** Shared test scaffolding, so a test says what it is about rather than
 * spending fifteen lines constructing a session. */

export const SESSION: Session = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    email: "ali@example.com",
    displayName: "Ali Rahman",
    emailVerified: true,
  },
  workspaces: [
    {
      role: "owner",
      workspace: {
        id: "22222222-2222-2222-2222-222222222222",
        name: "Northwind",
        slug: "northwind",
      },
    },
  ],
};

export const MEMBERS: Member[] = [
  {
    userId: "11111111-1111-1111-1111-111111111111",
    email: "ali@example.com",
    displayName: "Ali Rahman",
    role: "owner",
    capacity: "not_stated",
    joinedAt: "2026-01-04T09:00:00Z",
  },
  {
    userId: "33333333-3333-3333-3333-333333333333",
    email: "jo@example.com",
    displayName: null,
    role: "member",
    capacity: "open_to_work",
    capacityStatedAt: "2026-08-18T09:00:00Z",
    joinedAt: "2026-03-19T09:00:00Z",
  },
];

/** An `ApiError` with a given status, for exercising the error copy. */
export function apiError(status: number, type = "about:blank"): ApiError {
  return new ApiError({ type, title: "Failed", status, detail: "" });
}

/** Every method rejects unless the test stubs it, so an unanticipated call fails
 * loudly instead of rendering an empty state that looks like a pass. */
export function createStubClient(overrides: Partial<CairnClient> = {}): CairnClient {
  const unexpected = (name: string) => (): Promise<never> =>
    Promise.reject(new Error(`${name} was called but the test did not stub it`));

  return {
    signUp: vi.fn(unexpected("signUp")),
    logIn: vi.fn(unexpected("logIn")),
    verifyEmail: vi.fn(unexpected("verifyEmail")),
    // Benign default, like `listFacts` above: the dashboard's portfolio panel
    // renders on screens whose tests are about something else, and an empty
    // portfolio is the honest default for a workspace nobody has filed work
    // into. The project tests override it.
    listProjects: vi.fn(() => Promise.resolve({ projects: [] })),
    getProject: vi.fn(unexpected("getProject")),
    createProject: vi.fn(unexpected("createProject")),
    updateProject: vi.fn(unexpected("updateProject")),
    archiveProject: vi.fn(unexpected("archiveProject")),
    restoreProject: vi.fn(unexpected("restoreProject")),
    claimProjectSource: vi.fn(unexpected("claimProjectSource")),
    releaseProjectSource: vi.fn(unexpected("releaseProjectSource")),
    addProjectMember: vi.fn(unexpected("addProjectMember")),
    removeProjectMember: vi.fn(unexpected("removeProjectMember")),
    findRelatedWork: vi.fn(unexpected("findRelatedWork")),
    setMyCapacity: vi.fn(unexpected("setMyCapacity")),
    forgotPassword: vi.fn(unexpected("forgotPassword")),
    resetPassword: vi.fn(unexpected("resetPassword")),
    resendVerification: vi.fn(unexpected("resendVerification")),
    getSession: vi.fn(() => Promise.resolve(null)),
    logOut: vi.fn(() => Promise.resolve()),
    logOutEverywhere: vi.fn(unexpected("logOutEverywhere")),
    getWorkspace: vi.fn(unexpected("getWorkspace")),
    listMembers: vi.fn(unexpected("listMembers")),
    listInvitations: vi.fn(unexpected("listInvitations")),
    invite: vi.fn(unexpected("invite")),
    withdrawInvitation: vi.fn(unexpected("withdrawInvitation")),
    previewInvitation: vi.fn(unexpected("previewInvitation")),
    acceptInvitation: vi.fn(unexpected("acceptInvitation")),
    getOnboarding: vi.fn(unexpected("getOnboarding")),
    getBrief: vi.fn(unexpected("getBrief")),
    listBriefs: vi.fn(unexpected("listBriefs")),
    getArchivedBrief: vi.fn(unexpected("getArchivedBrief")),
    // Benign defaults, not `unexpected`: the overview's side panels read both
    // on every render of `/`, so every test that mounts BriefPage for some
    // other assertion would otherwise flood the page with panel error alerts.
    // Tests about the panels themselves override these.
    listFacts: vi.fn(() => Promise.resolve({ items: [] })),
    getFacets: vi.fn(() => Promise.resolve({ people: [], projects: [], sources: [] })),
    changeRole: vi.fn(unexpected("changeRole")),
    removeMember: vi.fn(unexpected("removeMember")),
    listIntegrations: vi.fn(unexpected("listIntegrations")),
    disconnectGitHub: vi.fn(unexpected("disconnectGitHub")),
    startSlackInstall: vi.fn(unexpected("startSlackInstall")),
    listSlackChannels: vi.fn(unexpected("listSlackChannels")),
    setSlackChannels: vi.fn(unexpected("setSlackChannels")),
    disconnectSlack: vi.fn(unexpected("disconnectSlack")),
    startGoogleChatInstall: vi.fn(unexpected("startGoogleChatInstall")),
    listGoogleChatSpaces: vi.fn(unexpected("listGoogleChatSpaces")),
    setGoogleChatSpaces: vi.fn(unexpected("setGoogleChatSpaces")),
    disconnectGoogleChat: vi.fn(unexpected("disconnectGoogleChat")),
    // Not benign defaults: both are destructive or navigational, and a test that
    // reaches one without saying so should fail loudly. The Meet *card* renders
    // on every workspace and Trust screen, but it renders from the integration
    // list alone — there is no Meet status endpoint to stub, which is why no
    // default is needed here for unrelated tests to pass.
    startGoogleMeetInstall: vi.fn(unexpected("startGoogleMeetInstall")),
    disconnectGoogleMeet: vi.fn(unexpected("disconnectGoogleMeet")),
    // Benign defaults, like `listSupportSessions` above: the identities block
    // renders on screens whose tests are about something else entirely, and
    // failing those on an unstubbed call would move the cost of this feature
    // onto every unrelated test.
    getMyIdentities: vi.fn(() => Promise.resolve({ identities: [], proposals: [], notice: "" })),
    confirmMyIdentity: vi.fn(unexpected("confirmMyIdentity")),
    revokeMyIdentity: vi.fn(unexpected("revokeMyIdentity")),
    getAttributionHealth: vi.fn(unexpected("getAttributionHealth")),
    createMeetingCaptureRequest: vi.fn(unexpected("createMeetingCaptureRequest")),
    // A benign default, for the same reason as `getMyIdentities` above and
    // `listMyMeetingRequests` below: the workspace's capture requests render on
    // the Workspace settings screen, whose tests are about members, connectors
    // and retention, and failing those on an unstubbed call would move the cost
    // of this feature onto every one of them — as a second `role="alert"` on a
    // screen whose tests assert there is one. An empty list is also the honest
    // default: nobody has asked about a meeting, and no connector exists that
    // could act on it if they had.
    listMeetingCaptureRequests: vi.fn(() =>
      Promise.resolve({
        requests: [],
        totals: { pending: 0, eligible: 0, refused: 0, expired: 0, cancelled: 0, completed: 0 },
        notice: "",
      }),
    ),
    cancelMeetingCaptureRequest: vi.fn(unexpected("cancelMeetingCaptureRequest")),
    // A benign default, like `listSupportSessions` and `getMyIdentities` above:
    // the meetings a person has been asked about are shown alongside screens
    // whose tests are about something else, and failing those on an unstubbed
    // call would move the cost of this feature onto every unrelated test. An
    // empty list is also the honest default — nobody has been asked anything.
    listMyMeetingRequests: vi.fn(() => Promise.resolve({ requests: [], notice: "" })),
    decideMeetingRequest: vi.fn(unexpected("decideMeetingRequest")),
    getPrivacy: vi.fn(unexpected("getPrivacy")),
    setRetention: vi.fn(unexpected("setRetention")),
    getNotifications: vi.fn(unexpected("getNotifications")),
    getTrust: vi.fn(unexpected("getTrust")),
    listSupportSessions: vi.fn(() => Promise.resolve([])),
    decideSupportSession: vi.fn(unexpected("decideSupportSession")),
    revokeSupportSession: vi.fn(unexpected("revokeSupportSession")),
    setWorkRole: vi.fn(() => Promise.resolve({ workRole: null })),
    search: vi.fn(unexpected("search")),
    myWeek: vi.fn(unexpected("myWeek")),
    mySources: vi.fn(unexpected("mySources")),
    setSourceConsent: vi.fn(unexpected("setSourceConsent")),
    correctFact: vi.fn(unexpected("correctFact")),
    connectGitHub: vi.fn(unexpected("connectGitHub")),
    ...overrides,
  };
}

export interface RenderRouteOptions {
  client?: CairnClient;
  /** The URL the screen believes it is at. Drives `usePathname`. */
  route?: string;
  /** Query parameters, for the screens that read one. */
  search?: string;
}

/** Takes the element rather than resolving a route table: the App Router is the
 * file system, so URL-to-file is checked by the build, not here. */
export function renderRoute(ui: ReactNode, options: RenderRouteOptions = {}): RenderResult {
  const { client = createStubClient(), route = "/", search = "" } = options;
  setRoute(route, search);

  return render(<Providers client={client}>{ui}</Providers>);
}

/** Replace `fetch` with a table of path suffix to response, for the tests that
 * exercise the transport rather than a stubbed client. */
export function stubFetch(routes: Record<string, { status: number; body?: unknown }>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request) => {
      // `Request.toString()` yields "[object Request]", so every route match
      // would fail silently as a 404 the test reads as a legitimate miss.
      const url = input instanceof Request ? input.url : input.toString();
      const match = Object.entries(routes).find(([suffix]) => url.endsWith(suffix));
      if (!match) {
        return Promise.resolve(new Response("{}", { status: 404 }));
      }
      const [, { status, body }] = match;
      return Promise.resolve(
        new Response(body === undefined ? null : JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

export { router } from "./router-mock.js";
