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
    joinedAt: "2026-01-04T09:00:00Z",
  },
  {
    userId: "33333333-3333-3333-3333-333333333333",
    email: "jo@example.com",
    displayName: null,
    role: "member",
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
    getSession: vi.fn(() => Promise.resolve(null)),
    logOut: vi.fn(() => Promise.resolve()),
    logOutEverywhere: vi.fn(unexpected("logOutEverywhere")),
    getWorkspace: vi.fn(unexpected("getWorkspace")),
    listMembers: vi.fn(unexpected("listMembers")),
    listInvitations: vi.fn(unexpected("listInvitations")),
    invite: vi.fn(unexpected("invite")),
    withdrawInvitation: vi.fn(unexpected("withdrawInvitation")),
    acceptInvitation: vi.fn(unexpected("acceptInvitation")),
    getOnboarding: vi.fn(unexpected("getOnboarding")),
    getBrief: vi.fn(unexpected("getBrief")),
    listBriefs: vi.fn(unexpected("listBriefs")),
    getArchivedBrief: vi.fn(unexpected("getArchivedBrief")),
    listFacts: vi.fn(unexpected("listFacts")),
    getFacets: vi.fn(unexpected("getFacets")),
    changeRole: vi.fn(unexpected("changeRole")),
    removeMember: vi.fn(unexpected("removeMember")),
    listIntegrations: vi.fn(unexpected("listIntegrations")),
    disconnectGitHub: vi.fn(unexpected("disconnectGitHub")),
    startSlackInstall: vi.fn(unexpected("startSlackInstall")),
    listSlackChannels: vi.fn(unexpected("listSlackChannels")),
    setSlackChannels: vi.fn(unexpected("setSlackChannels")),
    disconnectSlack: vi.fn(unexpected("disconnectSlack")),
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
