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
