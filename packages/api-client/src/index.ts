/**
 * Typed HTTP client for the CAIRN API. `generated/schema.ts` comes from the
 * backend's OpenAPI document and is never edited by hand; this is the thin part
 * on top — the fetch call, the error shape, credentials and correlation IDs.
 */

import type { paths } from "./generated/schema.js";

export type { paths } from "./generated/schema.js";

export type Session =
  paths["/v1/auth/session"]["get"]["responses"][200]["content"]["application/json"];

export type Workspace =
  paths["/v1/workspaces/{workspace_id}"]["get"]["responses"][200]["content"]["application/json"];

export type Member =
  paths["/v1/workspaces/{workspace_id}/members"]["get"]["responses"][200]["content"]["application/json"][number];

export type Invitation =
  paths["/v1/workspaces/{workspace_id}/invitations"]["post"]["responses"][201]["content"]["application/json"];

export type Brief =
  paths["/v1/workspaces/{workspace_id}/brief"]["get"]["responses"][200]["content"]["application/json"];

export type BriefArchive =
  paths["/v1/workspaces/{workspace_id}/briefs"]["get"]["responses"][200]["content"]["application/json"];

export type Consent =
  paths["/v1/workspaces/{workspace_id}/me/sources"]["get"]["responses"][200]["content"]["application/json"];

export type ConsentUpdateBody =
  paths["/v1/workspaces/{workspace_id}/me/sources"]["put"]["requestBody"]["content"]["application/json"];

export type ConsentUpdateResult =
  paths["/v1/workspaces/{workspace_id}/me/sources"]["put"]["responses"][200]["content"]["application/json"];

export type Correction =
  paths["/v1/workspaces/{workspace_id}/facts/{fact_id}/correction"]["post"]["responses"][201]["content"]["application/json"];

export type FactPage =
  paths["/v1/workspaces/{workspace_id}/facts"]["get"]["responses"][200]["content"]["application/json"];

export type Integration =
  paths["/v1/workspaces/{workspace_id}/integrations"]["get"]["responses"][200]["content"]["application/json"][number];

export type Privacy =
  paths["/v1/workspaces/{workspace_id}/privacy"]["get"]["responses"][200]["content"]["application/json"];

export type Notifications =
  paths["/v1/workspaces/{workspace_id}/notifications"]["get"]["responses"][200]["content"]["application/json"];

/** Every time CAIRN staff asked to look at this workspace (md/15 §5.2). */
export type SupportSession =
  paths["/v1/workspaces/{workspace_id}/support-sessions"]["get"]["responses"][200]["content"]["application/json"][number];

/** Where to send a customer to authorise Slack, and when the link lapses. */
export type SlackInstall =
  paths["/v1/workspaces/{workspace_id}/integrations/slack/install"]["post"]["responses"][200]["content"]["application/json"];

/** The public channels CAIRN could read, and which are already chosen. */
export type SlackChannelList =
  paths["/v1/workspaces/{workspace_id}/integrations/slack/channels"]["get"]["responses"][200]["content"]["application/json"];

/** The selection the server confirmed — the only thing that may draw a tick. */
export type SlackChannelSelection =
  paths["/v1/workspaces/{workspace_id}/integrations/slack/channels"]["put"]["responses"][200]["content"]["application/json"];

export type SlackDisconnect =
  paths["/v1/workspaces/{workspace_id}/integrations/slack/disconnect"]["post"]["responses"][200]["content"]["application/json"];

/*
 * ---------------------------------------------------------------------------
 * Google Chat
 * ---------------------------------------------------------------------------
 *
 * Derived from `paths[...]`, exactly as the Slack types above are. These were
 * hand-written for one commit while the server router was landing; that is the
 * shape that can silently stop matching the server, and on this screen a shape
 * that stops matching the server describes surveillance wrongly.
 */

/** Where to send a customer to authorise Google Chat, and when the link lapses. */
export type GoogleChatInstall =
  paths["/v1/workspaces/{workspace_id}/integrations/google-chat/install"]["post"]["responses"][200]["content"]["application/json"];

/** The spaces CAIRN could read, and which are already chosen. */
export type GoogleChatSpaceList =
  paths["/v1/workspaces/{workspace_id}/integrations/google-chat/spaces"]["get"]["responses"][200]["content"]["application/json"];

/**
 * One Google Chat space, as the API describes it.
 *
 * Indexed out of the list response rather than declared separately, so the row a
 * component renders and the payload the server sends cannot diverge. `name` is
 * Google's resource name (`spaces/AAAA…`) and is the identity the `PUT` takes
 * back; `displayName` is the only thing a reader ever sees.
 */
export type GoogleChatSpace = NonNullable<GoogleChatSpaceList["spaces"]>[number];

/** The selection the server confirmed — the only thing that may draw a tick. */
export type GoogleChatSpaceSelection =
  paths["/v1/workspaces/{workspace_id}/integrations/google-chat/spaces"]["put"]["responses"][200]["content"]["application/json"];

export type GoogleChatDisconnect =
  paths["/v1/workspaces/{workspace_id}/integrations/google-chat/disconnect"]["post"]["responses"][200]["content"]["application/json"];

/*
 * ---------------------------------------------------------------------------
 * Connected identities
 * ---------------------------------------------------------------------------
 *
 * Which provider accounts belong to the signed-in person, and how CAIRN knows.
 * Every type is indexed out of the generated document, so a field the server
 * renames is a compile error here rather than a blank on the one screen whose
 * subject is whether the record about somebody is right.
 */

/** The caller's own links, plus the identifiers already proposed for them. */
export type MyIdentities =
  paths["/v1/workspaces/{workspace_id}/me/identities"]["get"]["responses"][200]["content"]["application/json"];

/**
 * One link between a provider account and the signed-in person.
 *
 * Indexed out of the list rather than declared separately, so a row a component
 * renders and a row the server sends cannot drift apart.
 */
export type ExternalIdentity = NonNullable<MyIdentities["identities"]>[number];

/**
 * An identifier CAIRN has already associated with this person and has not been
 * confirmed. **Proposals are the caller's own and nobody else's** — the server
 * never lists unclaimed accounts belonging to the workspace at large, because a
 * menu of colleagues' accounts beside a "that's me" button is the exact attack
 * the verification rules exist to prevent.
 */
export type IdentityProposal = NonNullable<MyIdentities["proposals"]>[number];

/** How CAIRN came to believe a link is real. Categorical, never a score. */
export type IdentityVerification = ExternalIdentity["verification"];

/** Where a link stands now: live, withdrawn, or disputed. */
export type IdentityLinkState = ExternalIdentity["state"];

/**
 * Attribution across the workspace, in counts only.
 *
 * Read by Owners and Admins so they can ask members to confirm their own
 * accounts. It carries no name, no per-person row and no measure of anybody's
 * activity — an "unresolved by person" breakdown is a leaderboard with the
 * ranking left to the reader, and md/15 §2.3 forbids an administrator seeing
 * more about a member than the member sees about themselves.
 */
export type AttributionHealth =
  paths["/v1/workspaces/{workspace_id}/attribution-health"]["get"]["responses"][200]["content"]["application/json"];

/*
 * ---------------------------------------------------------------------------
 * Meeting capture consent
 * ---------------------------------------------------------------------------
 *
 * **Nothing here records a meeting.** CAIRN never joins one, and no provider
 * integration exists. These types describe only the permission a future
 * connector would have to hold before it could ask a platform for a transcript
 * that platform produced under its own flow.
 *
 * Two views, and the difference between them is the whole design. The workspace
 * view is counts and states; the participant's view is their own answer.
 * **Neither carries another person's decision, id, name or address**, and every
 * type below is indexed out of the generated document so a field the server adds
 * cannot appear on a screen without somebody choosing to render it.
 */

/** Every capture request in one workspace, with the totals by state. */
export type MeetingCaptureList =
  paths["/v1/workspaces/{workspace_id}/meetings/capture-requests"]["get"]["responses"][200]["content"]["application/json"];

/**
 * One capture request, as the workspace that asked for it may see it.
 *
 * Indexed out of the list rather than declared separately, so the row a
 * component renders and the payload the server sends cannot drift apart.
 * `acceptedCount` is deliberately absent once a request is refused: printed
 * beside a refusal, a count of acceptances names the person who refused by
 * arithmetic.
 */
export type MeetingCaptureRequest = NonNullable<MeetingCaptureList["requests"]>[number];

/** How many requests stand where. Totals only — there is no per-person view. */
export type MeetingStateCounts = MeetingCaptureList["totals"];

/** Where a request stands. Computed by the server's eligibility gate, never
 * asserted by a client: there is no field on any request body that could. */
export type MeetingCaptureState = MeetingCaptureRequest["state"];

/** Which platform produced the meeting. */
export type MeetingProvider = MeetingCaptureRequest["provider"];

/** The body for asking. It has no consent field, and no route accepts one. */
export type MeetingCaptureBody =
  paths["/v1/workspaces/{workspace_id}/meetings/capture-requests"]["post"]["requestBody"]["content"]["application/json"];

/** The meetings the signed-in person has been asked about. Theirs only. */
export type MyMeetingRequestList =
  paths["/v1/workspaces/{workspace_id}/me/meeting-requests"]["get"]["responses"][200]["content"]["application/json"];

/** One request as the person who was asked sees it: their own answer, and the
 * request's standing. No field here can carry anybody else's decision. */
export type MyMeetingRequest = NonNullable<MyMeetingRequestList["requests"]>[number];

/**
 * What a participant may say about their own request.
 *
 * Derived from the server's request body rather than restated, so a value added
 * or removed on the server is a compile error here — the alternative is a client
 * offering a button for an answer the server will refuse, on the one screen
 * where being refused looks like the product ignoring you.
 */
export type MeetingDecision =
  paths["/v1/workspaces/{workspace_id}/me/meeting-requests/{meeting_id}/decision"]["post"]["requestBody"]["content"]["application/json"]["decision"];

/**
 * How far a support session reaches.
 *
 * Derived from the generated schema rather than restated, so that a scope added
 * on the server becomes a compile error in every consumer that describes one to
 * a customer — the alternative is a new, broader scope silently displayed with
 * the narrower one's wording.
 */
export type SupportScope = SupportSession["requestedScope"];

/** The Trust & Privacy Center for one workspace (md/05 §B.6). */
export type Trust =
  paths["/v1/workspaces/{workspace_id}/trust"]["get"]["responses"][200]["content"]["application/json"];

export type Facets =
  paths["/v1/workspaces/{workspace_id}/facets"]["get"]["responses"][200]["content"]["application/json"];

export type SearchResults =
  paths["/v1/workspaces/{workspace_id}/search"]["get"]["responses"][200]["content"]["application/json"];

/** How far a workspace has got through its first ten minutes (md/11 §3). */
export type Onboarding =
  paths["/v1/workspaces/{workspace_id}/onboarding"]["get"]["responses"][200]["content"]["application/json"];

export type GitHubInstallation =
  paths["/v1/workspaces/{workspace_id}/integrations/github"]["post"]["responses"][201]["content"]["application/json"];

/** An RFC 9457 problem document. Every failure has this shape, so the client
 * needs one error type rather than a per-endpoint guess. */
export interface Problem {
  /** Stable identifier. Branch on this, never on `detail`, which is prose. */
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  /** Correlation ID. Quote it in a support conversation. */
  requestId?: string;
  errors?: { field: string; message: string }[];
}

/** An `Error` subclass, not a result type, so an unhandled failure rejects
 * rather than becoming a value someone forgot to check. */
export class ApiError extends Error {
  readonly problem: Problem;
  readonly status: number;

  constructor(problem: Problem) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
    this.problem = problem;
    this.status = problem.status;
  }

  /** Whether this is a specific problem type, e.g. `"invalid-credentials"`. */
  is(problemType: string): boolean {
    return this.problem.type.endsWith(`/${problemType}`) || this.problem.type === problemType;
  }
}

export interface ClientOptions {
  /** Base URL of the API, without a trailing slash. */
  baseUrl: string;
  /** Injected for tests and for SSR, where the global `fetch` is wrong. */
  fetch?: typeof globalThis.fetch;
}

export interface RequestOptions {
  /** Correlation ID to send, so one ID spans the whole chain. */
  requestId?: string;
  signal?: AbortSignal;
}

type SignUpBody = paths["/v1/auth/signup"]["post"]["requestBody"]["content"]["application/json"];
type LogInBody = paths["/v1/auth/login"]["post"]["requestBody"]["content"]["application/json"];
type InviteBody =
  paths["/v1/workspaces/{workspace_id}/invitations"]["post"]["requestBody"]["content"]["application/json"];
export type CorrectionBody =
  paths["/v1/workspaces/{workspace_id}/facts/{fact_id}/correction"]["post"]["requestBody"]["content"]["application/json"];

export interface BriefQuery {
  /** ISO 8601. Defaults to the API's recent window. */
  since?: string;
  until?: string;
}

export interface ArchiveQuery {
  limit?: number;
  cursor?: string;
}

export interface FactQuery {
  kind?: string[];
  /** Person ids, from `getFacets`. Repeatable. */
  person?: string[];
  /** Project names, from `getFacets`. Repeatable. */
  project?: string[];
  source?: string[];
  since?: string;
  until?: string;
  includeSuperseded?: boolean;
  limit?: number;
  cursor?: string;
}

/** `FactQuery` minus the pagination: relevance has no stable order to page
 * through, so search returns a ranked answer rather than a stream. */
export interface SearchQuery extends Omit<FactQuery, "cursor" | "includeSuperseded"> {
  q: string;
}

/** Returns `""` rather than `"?"` for an empty query: a trailing question mark
 * is a different URL to a cache and to path-matching middleware. */
function searchParams(query: object | undefined): string {
  if (query === undefined) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
    } else {
      params.set(key, String(value));
    }
  }
  const encoded = params.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

type ConnectGitHubBody =
  paths["/v1/workspaces/{workspace_id}/integrations/github"]["post"]["requestBody"]["content"]["application/json"];

type AcceptBody =
  paths["/v1/invitations/accept"]["post"]["requestBody"]["content"]["application/json"];

/** Declared rather than inferred from the object literal, so an accidental
 * signature change is a compile error rather than a widened type. */
export interface CairnClient {
  /** Create an account and its first workspace. Signs the caller in. */
  signUp(body: SignUpBody, options?: RequestOptions): Promise<Session>;
  logIn(body: LogInBody, options?: RequestOptions): Promise<Session>;
  /** Who the caller is. Resolves to null when signed out, rather than throwing. */
  getSession(options?: RequestOptions): Promise<Session | null>;
  logOut(options?: RequestOptions): Promise<void>;
  logOutEverywhere(options?: RequestOptions): Promise<void>;
  getWorkspace(workspaceId: string, options?: RequestOptions): Promise<Workspace>;
  listMembers(workspaceId: string, options?: RequestOptions): Promise<Member[]>;
  listInvitations(workspaceId: string, options?: RequestOptions): Promise<Invitation[]>;
  invite(workspaceId: string, body: InviteBody, options?: RequestOptions): Promise<Invitation>;
  withdrawInvitation(
    workspaceId: string,
    invitationId: string,
    options?: RequestOptions,
  ): Promise<void>;
  acceptInvitation(body: AcceptBody, options?: RequestOptions): Promise<Workspace>;
  /** One request rather than four, so the onboarding screen cannot disagree
   * with itself while a history import runs. */
  getOnboarding(workspaceId: string, options?: RequestOptions): Promise<Onboarding>;
  /** A finished period comes from the archive, the current one is generated on
   * the spot; `stored` says which, and only the stored one is a record. */
  getBrief(workspaceId: string, query?: BriefQuery, options?: RequestOptions): Promise<Brief>;
  /** The permalink: a period reconstructed from query parameters stops being a
   * stable address as soon as the boundaries are computed differently. */
  getArchivedBrief(workspaceId: string, briefId: string, options?: RequestOptions): Promise<Brief>;
  listBriefs(
    workspaceId: string,
    query?: ArchiveQuery,
    options?: RequestOptions,
  ): Promise<BriefArchive>;
  listFacts(workspaceId: string, query?: FactQuery, options?: RequestOptions): Promise<FactPage>;
  /** Read from the facts, not from what CAIRN could hold, so a filter menu
   * never offers a value that matches nothing. */
  getFacets(workspaceId: string, options?: RequestOptions): Promise<Facets>;
  /** Change what somebody may configure. Never what they can see. */
  changeRole(
    workspaceId: string,
    userId: string,
    role: string,
    options?: RequestOptions,
  ): Promise<Member>;
  /** End somebody's access. Their record stays: it is the team's history. */
  removeMember(workspaceId: string, userId: string, options?: RequestOptions): Promise<void>;
  listIntegrations(workspaceId: string, options?: RequestOptions): Promise<Integration[]>;
  /** Stop capturing from an installation. What was captured stays. */
  disconnectGitHub(
    workspaceId: string,
    installationId: number,
    options?: RequestOptions,
  ): Promise<void>;
  getPrivacy(workspaceId: string, options?: RequestOptions): Promise<Privacy>;
  setRetention(
    workspaceId: string,
    retentionDays: number,
    options?: RequestOptions,
  ): Promise<Privacy>;
  getNotifications(workspaceId: string, options?: RequestOptions): Promise<Notifications>;
  /** Readable by every member, deliberately (md/05 §B.6). */
  getTrust(workspaceId: string, options?: RequestOptions): Promise<Trust>;
  /**
   * The workspace's own support-access history.
   *
   * Readable by every member: who looked at your workspace is not
   * administrative information (md/15 §5.2).
   */
  listSupportSessions(workspaceId: string, options?: RequestOptions): Promise<SupportSession[]>;
  /** Approve or refuse a support request. Owner and Admin only. */
  decideSupportSession(
    workspaceId: string,
    sessionId: string,
    approve: boolean,
    options?: RequestOptions,
  ): Promise<SupportSession>;
  /** End approved access now. */
  revokeSupportSession(
    workspaceId: string,
    sessionId: string,
    options?: RequestOptions,
  ): Promise<SupportSession>;

  /** Begin connecting Slack. Returns where to send the customer.
   *
   * The API returns the authorise URL rather than redirecting, because the
   * caller is a browser application making a credentialed request: a 302 to
   * slack.com would be followed by `fetch`, not by the window, and the customer
   * would never see the consent screen.
   */
  startSlackInstall(workspaceId: string, options?: RequestOptions): Promise<SlackInstall>;

  /** The public channels CAIRN could read, and which are already chosen. */
  listSlackChannels(workspaceId: string, options?: RequestOptions): Promise<SlackChannelList>;

  /** Replace the whole selection.
   *
   * The full state, never a delta: a partial update makes "unselect everything"
   * indistinguishable from "change nothing", and that is the direction where
   * being wrong means reading a channel nobody chose.
   */
  setSlackChannels(
    workspaceId: string,
    channelIds: string[],
    options?: RequestOptions,
  ): Promise<SlackChannelSelection>;

  /** Stop new collection and clear the stored credential. */
  disconnectSlack(workspaceId: string, options?: RequestOptions): Promise<SlackDisconnect>;

  /** Begin connecting Google Chat. Returns where to send the customer.
   *
   * Same shape as Slack's and for the same reason: the API answers with the
   * authorise URL rather than a 302, because a redirect on a credentialed
   * request is followed by `fetch` and Google's consent screen would never
   * appear. The caller moves the window itself.
   */
  startGoogleChatInstall(workspaceId: string, options?: RequestOptions): Promise<GoogleChatInstall>;

  /** The spaces CAIRN could read, and which are already chosen. */
  listGoogleChatSpaces(workspaceId: string, options?: RequestOptions): Promise<GoogleChatSpaceList>;

  /** Replace the whole selection.
   *
   * Resource names, not display names, and the full state rather than a delta —
   * a partial update makes "unselect everything" indistinguishable from "change
   * nothing", and being wrong in that direction means reading a space nobody
   * chose.
   */
  setGoogleChatSpaces(
    workspaceId: string,
    spaceNames: string[],
    options?: RequestOptions,
  ): Promise<GoogleChatSpaceSelection>;

  /** Stop new collection and clear the stored credential. */
  disconnectGoogleChat(
    workspaceId: string,
    options?: RequestOptions,
  ): Promise<GoogleChatDisconnect>;

  /**
   * The provider accounts CAIRN believes are the caller's, and how it knows.
   *
   * Self only, by construction: there is deliberately no subject parameter on
   * this or either mutation below, so no administrator has a route through
   * which to claim, merge or reassign a colleague's identity. md/05 makes the
   * record the person's own, and an override would be the one thing the product
   * promises cannot be overridden.
   */
  getMyIdentities(workspaceId: string, options?: RequestOptions): Promise<MyIdentities>;

  /** Confirm that a provider account is the caller's own. */
  confirmMyIdentity(
    workspaceId: string,
    provider: string,
    providerAccountId: string,
    options?: RequestOptions,
  ): Promise<ExternalIdentity>;

  /**
   * Stop attributing a provider account to the caller.
   *
   * `disputed` separates "this was mine and I am unlinking it" from "this was
   * never mine". Both stop attribution; only the second says the original link
   * was wrong, and the person is entitled to have that recorded in their words.
   * Neither deletes anything: the link, its evidence and every fact it produced
   * survive.
   */
  revokeMyIdentity(
    workspaceId: string,
    identityId: string,
    disputed: boolean,
    options?: RequestOptions,
  ): Promise<ExternalIdentity>;

  /** Counts of resolved and unresolved links, for Owners and Admins. Never a
   * name, a per-person row, or any measure of anybody's activity. */
  getAttributionHealth(workspaceId: string, options?: RequestOptions): Promise<AttributionHealth>;

  /**
   * Ask everybody in a meeting whether CAIRN may collect it. Owner and Admin.
   *
   * Creates a question and grants nothing. The request stays pending until every
   * person named has personally agreed from their own session, and there is no
   * argument here — or anywhere else in this client — by which the caller could
   * answer on somebody's behalf.
   */
  createMeetingCaptureRequest(
    workspaceId: string,
    body: MeetingCaptureBody,
    options?: RequestOptions,
  ): Promise<MeetingCaptureRequest>;

  /** Every capture request and the totals. Counts and states only: this call
   * cannot tell you who agreed, who declined, or who has not answered. */
  listMeetingCaptureRequests(
    workspaceId: string,
    options?: RequestOptions,
  ): Promise<MeetingCaptureList>;

  /** Call off a request. Only an open one — a refusal stays on the record as a
   * refusal rather than being tidied into a cancellation. */
  cancelMeetingCaptureRequest(
    workspaceId: string,
    meetingId: string,
    options?: RequestOptions,
  ): Promise<MeetingCaptureRequest>;

  /**
   * The meetings the signed-in person has been asked about.
   *
   * Self only, by construction: there is no subject parameter here or on the
   * decision below, so no administrator has a call through which to read what a
   * colleague was asked or how they answered.
   */
  listMyMeetingRequests(
    workspaceId: string,
    options?: RequestOptions,
  ): Promise<MyMeetingRequestList>;

  /**
   * Agree, refuse, or take an agreement back — for the caller and nobody else.
   *
   * A request that is not the caller's answers 404 rather than 403: whether a
   * meeting exists is not a non-participant's to confirm. Each answer is
   * appended rather than replacing the last, so changing your mind is a thing
   * the record can later be shown to have honoured.
   */
  decideMeetingRequest(
    workspaceId: string,
    meetingId: string,
    decision: MeetingDecision,
    options?: RequestOptions,
  ): Promise<MyMeetingRequest>;
  /** The caller and nobody else: there is deliberately no subject parameter, so
   * no administrator can label a colleague's role. */
  setWorkRole(
    workspaceId: string,
    workRole: string | null,
    options?: RequestOptions,
  ): Promise<{ workRole?: string | null }>;
  /** Returns stored facts with their evidence, never generated prose. */
  search(workspaceId: string, query: SearchQuery, options?: RequestOptions): Promise<SearchResults>;
  /** Lists every source, not only connected ones, so a person can opt out in
   * advance — md/11 §4.1. */
  mySources(workspaceId: string, options?: RequestOptions): Promise<Consent>;
  setSourceConsent(
    workspaceId: string,
    body: ConsentUpdateBody,
    options?: RequestOptions,
  ): Promise<ConsentUpdateResult>;
  /** What CAIRN believes about the caller, and nothing else. */
  myWeek(workspaceId: string, query?: BriefQuery, options?: RequestOptions): Promise<FactPage>;
  /** One call, no review queue: md/09 §9 makes correction an input, not a
   * request to be triaged. */
  correctFact(
    workspaceId: string,
    factId: string,
    body: CorrectionBody,
    options?: RequestOptions,
  ): Promise<Correction>;
  connectGitHub(
    workspaceId: string,
    body: ConnectGitHubBody,
    options?: RequestOptions,
  ): Promise<GitHubInstallation>;
}

/** A factory, not a singleton: browser and server use different base URLs. */
export function createClient(options: ClientOptions): CairnClient {
  const fetchImpl = options.fetch ?? globalThis.fetch;
  const baseUrl = options.baseUrl.replace(/\/$/, "");

  async function rawRequest(
    method: string,
    path: string,
    body: unknown,
    requestOptions: RequestOptions,
  ): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (requestOptions.requestId) headers["X-Request-ID"] = requestOptions.requestId;

    // Assembled conditionally: under `exactOptionalPropertyTypes` "no body"
    // and "a body that is undefined" differ, and `fetch` treats them so.
    const init: RequestInit = {
      method,
      headers,
      // The session is an HttpOnly cookie; without this every call is
      // unauthenticated.
      credentials: "include",
    };
    if (body !== undefined) init.body = JSON.stringify(body);
    if (requestOptions.signal) init.signal = requestOptions.signal;

    return fetchImpl(`${baseUrl}${path}`, init);
  }

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    requestOptions: RequestOptions = {},
  ): Promise<T> {
    const response = await rawRequest(method, path, body, requestOptions);

    if (!response.ok) {
      throw new ApiError(await readProblem(response));
    }

    return (await response.json()) as T;
  }

  /** Separate from `request` because a 204 has nothing to parse. */
  async function requestNoContent(
    method: string,
    path: string,
    requestOptions: RequestOptions = {},
  ): Promise<void> {
    const response = await rawRequest(method, path, undefined, requestOptions);
    if (!response.ok) {
      throw new ApiError(await readProblem(response));
    }
  }

  return {
    signUp: (
      body: paths["/v1/auth/signup"]["post"]["requestBody"]["content"]["application/json"],
      options?: RequestOptions,
    ) => request<Session>("POST", "/v1/auth/signup", body, options),

    logIn: (
      body: paths["/v1/auth/login"]["post"]["requestBody"]["content"]["application/json"],
      options?: RequestOptions,
    ) => request<Session>("POST", "/v1/auth/login", body, options),

    getSession: async (options?: RequestOptions): Promise<Session | null> => {
      try {
        return await request<Session>("GET", "/v1/auth/session", undefined, options);
      } catch (error: unknown) {
        // Signed out is the expected state on a first page load, not an
        // exception callers must remember to catch.
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },

    logOut: (options?: RequestOptions) => requestNoContent("POST", "/v1/auth/logout", options),

    logOutEverywhere: (options?: RequestOptions) =>
      requestNoContent("POST", "/v1/auth/logout-everywhere", options),

    getWorkspace: (workspaceId: string, options?: RequestOptions) =>
      request<Workspace>("GET", `/v1/workspaces/${workspaceId}`, undefined, options),

    listMembers: (workspaceId: string, options?: RequestOptions) =>
      request<Member[]>("GET", `/v1/workspaces/${workspaceId}/members`, undefined, options),

    listInvitations: (workspaceId: string, options?: RequestOptions) =>
      request<Invitation[]>("GET", `/v1/workspaces/${workspaceId}/invitations`, undefined, options),

    invite: (
      workspaceId: string,
      body: paths["/v1/workspaces/{workspace_id}/invitations"]["post"]["requestBody"]["content"]["application/json"],
      options?: RequestOptions,
    ) => request<Invitation>("POST", `/v1/workspaces/${workspaceId}/invitations`, body, options),

    withdrawInvitation: (workspaceId: string, invitationId: string, options?: RequestOptions) =>
      requestNoContent(
        "DELETE",
        `/v1/workspaces/${workspaceId}/invitations/${invitationId}`,
        options,
      ),

    getBrief: (workspaceId: string, query?: BriefQuery, options?: RequestOptions) =>
      request<Brief>(
        "GET",
        `/v1/workspaces/${workspaceId}/brief${searchParams(query)}`,
        undefined,
        options,
      ),

    getArchivedBrief: (workspaceId: string, briefId: string, options?: RequestOptions) =>
      request<Brief>("GET", `/v1/workspaces/${workspaceId}/briefs/${briefId}`, undefined, options),

    listBriefs: (workspaceId: string, query?: ArchiveQuery, options?: RequestOptions) =>
      request<BriefArchive>(
        "GET",
        `/v1/workspaces/${workspaceId}/briefs${searchParams(query)}`,
        undefined,
        options,
      ),

    mySources: (workspaceId: string, options?: RequestOptions) =>
      request<Consent>("GET", `/v1/workspaces/${workspaceId}/me/sources`, undefined, options),

    setSourceConsent: (workspaceId: string, body: ConsentUpdateBody, options?: RequestOptions) =>
      request<ConsentUpdateResult>(
        "PUT",
        `/v1/workspaces/${workspaceId}/me/sources`,
        body,
        options,
      ),

    myWeek: (workspaceId: string, query?: BriefQuery, options?: RequestOptions) =>
      request<FactPage>(
        "GET",
        `/v1/workspaces/${workspaceId}/me/week${searchParams(query)}`,
        undefined,
        options,
      ),

    correctFact: (
      workspaceId: string,
      factId: string,
      body: CorrectionBody,
      options?: RequestOptions,
    ) =>
      request<Correction>(
        "POST",
        `/v1/workspaces/${workspaceId}/facts/${factId}/correction`,
        body,
        options,
      ),

    listFacts: (workspaceId: string, query?: FactQuery, options?: RequestOptions) =>
      request<FactPage>(
        "GET",
        `/v1/workspaces/${workspaceId}/facts${searchParams(query)}`,
        undefined,
        options,
      ),

    getFacets: (workspaceId: string, options?: RequestOptions) =>
      request<Facets>("GET", `/v1/workspaces/${workspaceId}/facets`, undefined, options),

    changeRole: (workspaceId: string, userId: string, role: string, options?: RequestOptions) =>
      request<Member>(
        "PATCH",
        `/v1/workspaces/${workspaceId}/members/${userId}`,
        { role },
        options,
      ),

    removeMember: (workspaceId: string, userId: string, options?: RequestOptions) =>
      requestNoContent("DELETE", `/v1/workspaces/${workspaceId}/members/${userId}`, options),

    listIntegrations: (workspaceId: string, options?: RequestOptions) =>
      request<Integration[]>(
        "GET",
        `/v1/workspaces/${workspaceId}/integrations`,
        undefined,
        options,
      ),

    disconnectGitHub: (workspaceId: string, installationId: number, options?: RequestOptions) =>
      requestNoContent(
        "DELETE",
        `/v1/workspaces/${workspaceId}/integrations/github/${String(installationId)}`,
        options,
      ),

    getPrivacy: (workspaceId: string, options?: RequestOptions) =>
      request<Privacy>("GET", `/v1/workspaces/${workspaceId}/privacy`, undefined, options),

    setRetention: (workspaceId: string, retentionDays: number, options?: RequestOptions) =>
      request<Privacy>("PUT", `/v1/workspaces/${workspaceId}/privacy`, { retentionDays }, options),

    getNotifications: (workspaceId: string, options?: RequestOptions) =>
      request<Notifications>(
        "GET",
        `/v1/workspaces/${workspaceId}/notifications`,
        undefined,
        options,
      ),

    getTrust: (workspaceId: string, options?: RequestOptions) =>
      request<Trust>("GET", `/v1/workspaces/${workspaceId}/trust`, undefined, options),

    listSupportSessions: (workspaceId: string, options?: RequestOptions) =>
      request<SupportSession[]>(
        "GET",
        `/v1/workspaces/${workspaceId}/support-sessions`,
        undefined,
        options,
      ),

    decideSupportSession: (
      workspaceId: string,
      sessionId: string,
      approve: boolean,
      options?: RequestOptions,
    ) =>
      request<SupportSession>(
        "POST",
        `/v1/workspaces/${workspaceId}/support-sessions/${sessionId}/decision`,
        { approve },
        options,
      ),

    revokeSupportSession: (workspaceId: string, sessionId: string, options?: RequestOptions) =>
      request<SupportSession>(
        "POST",
        `/v1/workspaces/${workspaceId}/support-sessions/${sessionId}/revoke`,
        undefined,
        options,
      ),

    startSlackInstall: (workspaceId: string, options?: RequestOptions) =>
      request<SlackInstall>(
        "POST",
        `/v1/workspaces/${workspaceId}/integrations/slack/install`,
        undefined,
        options,
      ),

    listSlackChannels: (workspaceId: string, options?: RequestOptions) =>
      request<SlackChannelList>(
        "GET",
        `/v1/workspaces/${workspaceId}/integrations/slack/channels`,
        undefined,
        options,
      ),

    setSlackChannels: (workspaceId: string, channelIds: string[], options?: RequestOptions) =>
      request<SlackChannelSelection>(
        "PUT",
        `/v1/workspaces/${workspaceId}/integrations/slack/channels`,
        { channelIds },
        options,
      ),

    disconnectSlack: (workspaceId: string, options?: RequestOptions) =>
      request<SlackDisconnect>(
        "POST",
        `/v1/workspaces/${workspaceId}/integrations/slack/disconnect`,
        undefined,
        options,
      ),

    startGoogleChatInstall: (workspaceId: string, options?: RequestOptions) =>
      request<GoogleChatInstall>(
        "POST",
        `/v1/workspaces/${workspaceId}/integrations/google-chat/install`,
        undefined,
        options,
      ),

    listGoogleChatSpaces: (workspaceId: string, options?: RequestOptions) =>
      request<GoogleChatSpaceList>(
        "GET",
        `/v1/workspaces/${workspaceId}/integrations/google-chat/spaces`,
        undefined,
        options,
      ),

    setGoogleChatSpaces: (workspaceId: string, spaceNames: string[], options?: RequestOptions) =>
      request<GoogleChatSpaceSelection>(
        "PUT",
        `/v1/workspaces/${workspaceId}/integrations/google-chat/spaces`,
        { spaceNames },
        options,
      ),

    disconnectGoogleChat: (workspaceId: string, options?: RequestOptions) =>
      request<GoogleChatDisconnect>(
        "POST",
        `/v1/workspaces/${workspaceId}/integrations/google-chat/disconnect`,
        undefined,
        options,
      ),

    getMyIdentities: (workspaceId: string, options?: RequestOptions) =>
      request<MyIdentities>(
        "GET",
        `/v1/workspaces/${workspaceId}/me/identities`,
        undefined,
        options,
      ),

    confirmMyIdentity: (
      workspaceId: string,
      provider: string,
      providerAccountId: string,
      options?: RequestOptions,
    ) =>
      request<ExternalIdentity>(
        "POST",
        `/v1/workspaces/${workspaceId}/me/identities`,
        { provider, providerAccountId },
        options,
      ),

    revokeMyIdentity: (
      workspaceId: string,
      identityId: string,
      disputed: boolean,
      options?: RequestOptions,
    ) =>
      request<ExternalIdentity>(
        "POST",
        `/v1/workspaces/${workspaceId}/me/identities/${identityId}/revoke`,
        { disputed },
        options,
      ),

    getAttributionHealth: (workspaceId: string, options?: RequestOptions) =>
      request<AttributionHealth>(
        "GET",
        `/v1/workspaces/${workspaceId}/attribution-health`,
        undefined,
        options,
      ),

    createMeetingCaptureRequest: (
      workspaceId: string,
      body: MeetingCaptureBody,
      options?: RequestOptions,
    ) =>
      request<MeetingCaptureRequest>(
        "POST",
        `/v1/workspaces/${workspaceId}/meetings/capture-requests`,
        body,
        options,
      ),

    listMeetingCaptureRequests: (workspaceId: string, options?: RequestOptions) =>
      request<MeetingCaptureList>(
        "GET",
        `/v1/workspaces/${workspaceId}/meetings/capture-requests`,
        undefined,
        options,
      ),

    cancelMeetingCaptureRequest: (
      workspaceId: string,
      meetingId: string,
      options?: RequestOptions,
    ) =>
      request<MeetingCaptureRequest>(
        "POST",
        `/v1/workspaces/${workspaceId}/meetings/capture-requests/${meetingId}/cancel`,
        undefined,
        options,
      ),

    listMyMeetingRequests: (workspaceId: string, options?: RequestOptions) =>
      request<MyMeetingRequestList>(
        "GET",
        `/v1/workspaces/${workspaceId}/me/meeting-requests`,
        undefined,
        options,
      ),

    decideMeetingRequest: (
      workspaceId: string,
      meetingId: string,
      decision: MeetingDecision,
      options?: RequestOptions,
    ) =>
      request<MyMeetingRequest>(
        "POST",
        `/v1/workspaces/${workspaceId}/me/meeting-requests/${meetingId}/decision`,
        { decision },
        options,
      ),

    setWorkRole: (workspaceId: string, workRole: string | null, options?: RequestOptions) =>
      request<{ workRole?: string | null }>(
        "PUT",
        `/v1/workspaces/${workspaceId}/me/role`,
        { workRole },
        options,
      ),

    search: (workspaceId: string, query: SearchQuery, options?: RequestOptions) =>
      request<SearchResults>(
        "GET",
        `/v1/workspaces/${workspaceId}/search${searchParams(query)}`,
        undefined,
        options,
      ),

    getOnboarding: (workspaceId: string, options?: RequestOptions) =>
      request<Onboarding>("GET", `/v1/workspaces/${workspaceId}/onboarding`, undefined, options),

    connectGitHub: (workspaceId: string, body: ConnectGitHubBody, options?: RequestOptions) =>
      request<GitHubInstallation>(
        "POST",
        `/v1/workspaces/${workspaceId}/integrations/github`,
        body,
        options,
      ),

    acceptInvitation: (
      body: paths["/v1/invitations/accept"]["post"]["requestBody"]["content"]["application/json"],
      options?: RequestOptions,
    ) => request<Workspace>("POST", "/v1/invitations/accept", body, options),
  };
}

/** Falls back to a synthetic problem when the body is not JSON: a 502 from a
 * load balancer returns HTML, and a `SyntaxError` would hide the outage. */
async function readProblem(response: Response): Promise<Problem> {
  try {
    const parsed = (await response.json()) as Partial<Problem>;
    if (typeof parsed.title === "string" && typeof parsed.status === "number") {
      return parsed as Problem;
    }
  } catch {
    // Fall through to the synthetic problem below.
  }

  const problem: Problem = {
    type: "about:blank",
    title: response.statusText || "Request failed",
    status: response.status,
    detail: `The server returned ${String(response.status)} with an unreadable body.`,
  };
  const requestId = response.headers.get("X-Request-ID");
  if (requestId !== null) problem.requestId = requestId;
  return problem;
}
