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

/**
 * One source, and whether this deployment could connect it at all.
 *
 * Read before the Connect button is offered rather than after it is pressed.
 * A deployment with no OAuth credentials for a provider answers its install
 * route with a 503, and a 5xx is rendered everywhere as "something on CAIRN's
 * side failed" — an apology, with a reference id, for a fault that did not
 * happen. This is the field that lets the screen say "Not set up" instead.
 */
export type IntegrationProvider =
  paths["/v1/workspaces/{workspace_id}/integrations/providers"]["get"]["responses"][200]["content"]["application/json"][number];

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
 * Google Meet
 * ---------------------------------------------------------------------------
 *
 * Two methods, and deliberately only two.
 *
 * The API publishes three Google Meet routes. `/v1/integrations/google-meet/
 * callback` is the third, and it is not here: Google's consent screen sends the
 * *browser* there and it answers with a 303 back to the workspace screen, so a
 * `fetch` wrapper around it would follow the redirect inside the XHR and the
 * customer would never arrive. The outcome reaches the interface as the
 * `?googleMeet=` parameter that redirect carries, which `AdminPage` reads.
 *
 * The push receiver (`webhooks/google-meet`) is not here either, and is excluded
 * on purpose rather than overlooked: it is unauthenticated, it is called by
 * Google Pub/Sub and never by a signed-in person, and a browser-side method for
 * it would be a method whose only possible use is forging a delivery.
 *
 * Both types are indexed out of `paths[...]`, like Slack's and Chat's above. The
 * Chat block records what a hand-written shape costs; nothing here repeats it.
 */

/** Where to send a customer to authorise Google Meet, and when the link lapses.
 *
 * `notice` is the server's own sentence about what connecting does and does not
 * do — the interface renders it rather than paraphrasing it, because the claim
 * is about what the backend does and a copy in a React component is a claim
 * nothing keeps true.
 */
export type GoogleMeetInstall =
  paths["/v1/workspaces/{workspace_id}/integrations/google-meet/install"]["post"]["responses"][200]["content"]["application/json"];

/**
 * What disconnecting Google Meet actually did.
 *
 * Carries `subscriptionsRemoved` as well as `credentialCleared`, which Chat's
 * does not: stopping the event subscriptions and destroying the refresh token
 * are two different things, and a disconnect that did only one of them is a
 * disconnect the reader is entitled to be told about.
 */
export type GoogleMeetDisconnect =
  paths["/v1/workspaces/{workspace_id}/integrations/google-meet/disconnect"]["post"]["responses"][200]["content"]["application/json"];

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
export type ProjectList =
  paths["/v1/workspaces/{workspace_id}/projects"]["get"]["responses"]["200"]["content"]["application/json"];
export type ProjectSummary = NonNullable<ProjectList["projects"]>[number];
export type ProjectDetail =
  paths["/v1/workspaces/{workspace_id}/projects/{project_id}"]["get"]["responses"]["200"]["content"]["application/json"];
export type ProjectState = ProjectSummary["state"];
export type ProjectCreateBody =
  paths["/v1/workspaces/{workspace_id}/projects"]["post"]["requestBody"]["content"]["application/json"];
export type ProjectUpdateBody =
  paths["/v1/workspaces/{workspace_id}/projects/{project_id}"]["patch"]["requestBody"]["content"]["application/json"];

export type TaskList =
  paths["/v1/workspaces/{workspace_id}/projects/{project_id}/tasks"]["get"]["responses"]["200"]["content"]["application/json"];
export type TaskSummary = NonNullable<TaskList["tasks"]>[number];
export type TaskDetail =
  paths["/v1/workspaces/{workspace_id}/tasks/{task_id}"]["get"]["responses"]["200"]["content"]["application/json"];
export type TaskState = NonNullable<TaskSummary["state"]>;
export type TaskCreateBody =
  paths["/v1/workspaces/{workspace_id}/projects/{project_id}/tasks"]["post"]["requestBody"]["content"]["application/json"];
export type TaskUpdateBody =
  paths["/v1/workspaces/{workspace_id}/tasks/{task_id}"]["patch"]["requestBody"]["content"]["application/json"];
export type MyTasks =
  paths["/v1/workspaces/{workspace_id}/me/tasks"]["get"]["responses"]["200"]["content"]["application/json"];

export type Capacity = "open_to_work" | "at_capacity" | "not_stated";
export type RelatedWork =
  paths["/v1/workspaces/{workspace_id}/related-work"]["get"]["responses"]["200"]["content"]["application/json"];
export type CapacityState =
  paths["/v1/workspaces/{workspace_id}/me/capacity"]["put"]["responses"]["200"]["content"]["application/json"];

type ForgotPasswordBody =
  paths["/v1/auth/forgot-password"]["post"]["requestBody"]["content"]["application/json"];
type ResetPasswordBody =
  paths["/v1/auth/reset-password"]["post"]["requestBody"]["content"]["application/json"];
type VerifyEmailBody =
  paths["/v1/auth/verify-email"]["post"]["requestBody"]["content"]["application/json"];
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

export type InvitationPreview =
  paths["/v1/invitations/preview"]["get"]["responses"][200]["content"]["application/json"];

/** Declared rather than inferred from the object literal, so an accidental
 * signature change is a compile error rather than a widened type. */
export interface CairnClient {
  /** Create an account and its first workspace. Signs the caller in. */
  signUp(body: SignUpBody, options?: RequestOptions): Promise<Session>;
  logIn(body: LogInBody, options?: RequestOptions): Promise<Session>;
  /** The workspace's projects, alphabetically. Ordering is deliberate: any
   * activity-derived order would rank the work, and through it the people
   * doing it. Archived projects are excluded unless asked for. */
  listProjects(
    workspaceId: string,
    query?: { state?: ProjectState; q?: string; includeArchived?: boolean },
    options?: RequestOptions,
  ): Promise<ProjectList>;
  /** One project: its claimed citation strings, its membership history, and a
   * rollup grouped from live facts (delivered / blockers / open questions /
   * decisions), each cited and newest first. Symmetric - every role receives
   * identical bytes. There is no remaining-work field, deliberately: CAIRN
   * holds no planned-work model and will not invent one. */
  getProject(
    workspaceId: string,
    projectId: string,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  createProject(
    workspaceId: string,
    body: ProjectCreateBody,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  /** Declare a state or reword the purpose. A state is stamped with who
   * declared it and when - it is never inferred from activity. */
  updateProject(
    workspaceId: string,
    projectId: string,
    body: ProjectUpdateBody,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  archiveProject(
    workspaceId: string,
    projectId: string,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  restoreProject(
    workspaceId: string,
    projectId: string,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  claimProjectSource(
    workspaceId: string,
    projectId: string,
    value: string,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  releaseProjectSource(
    workspaceId: string,
    projectId: string,
    value: string,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  /** Add a person to the project's context. Context, never assignment - and
   * never silent: the row records who added them and when, and every member
   * can see it. */
  addProjectMember(
    workspaceId: string,
    projectId: string,
    body: { personId: string; projectRole?: string },
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  /** Remove a person from the context. History-preserving: the entry stays in
   * the list, closed, with who removed them. */
  removeProjectMember(
    workspaceId: string,
    projectId: string,
    personId: string,
    options?: RequestOptions,
  ): Promise<ProjectDetail>;
  /** Create a task on a project's board. Title is the only requirement; an
   * assignee must be an active member of the project. */
  createTask(
    workspaceId: string,
    projectId: string,
    body: TaskCreateBody,
    options?: RequestOptions,
  ): Promise<TaskDetail>;
  /** One project's board, in creation order - never ordered by activity.
   * Archived tasks are excluded unless asked for. */
  listTasks(
    workspaceId: string,
    projectId: string,
    query?: { state?: TaskState; includeArchived?: boolean },
    options?: RequestOptions,
  ): Promise<TaskList>;
  /** One task with its audit trail rendered as neutral sentences. Symmetric -
   * every role receives identical bytes. */
  getTask(workspaceId: string, taskId: string, options?: RequestOptions): Promise<TaskDetail>;
  /** Edit a task's descriptive fields. Each changed field leaves its own
   * categorical audit event; state moves through setTaskState instead. */
  updateTask(
    workspaceId: string,
    taskId: string,
    body: TaskUpdateBody,
    options?: RequestOptions,
  ): Promise<TaskDetail>;
  /** Move a task along the closed workflow. Illegal moves 409; approving a
   * review requires a different user from the one who requested it. */
  setTaskState(
    workspaceId: string,
    taskId: string,
    state: TaskState,
    options?: RequestOptions,
  ): Promise<TaskDetail>;
  /** Archive a task - close it, never delete it. Owner, admin, or the task's
   * creator. */
  archiveTask(workspaceId: string, taskId: string, options?: RequestOptions): Promise<TaskDetail>;
  restoreTask(workspaceId: string, taskId: string, options?: RequestOptions): Promise<TaskDetail>;
  /** The caller's own tasks, grouped by workflow column. Self-scoped by
   * construction; empty groups when no Person is linked yet. */
  listMyTasks(workspaceId: string, options?: RequestOptions): Promise<MyTasks>;
  /** Evidence of who has worked on related things. Deterministic retrieval
   * over facts - no score, no rank, no model call; groups order by most recent
   * related fact and every fact carries its citations. People appear only
   * through facts that cite them, so opt-outs are inherited structurally. */
  findRelatedWork(
    workspaceId: string,
    topic: string,
    options?: RequestOptions,
  ): Promise<RelatedWork>;
  /** State the caller's own availability. Self only - the person is resolved
   * from the session, and no parameter can name anybody else. */
  setMyCapacity(
    workspaceId: string,
    capacity: Capacity,
    options?: RequestOptions,
  ): Promise<CapacityState>;
  /** Redeem the link from a verification email.
   *
   * Unauthenticated, deliberately: somebody clicking a link in their inbox may
   * have no session in that browser, and requiring one would send them to a
   * sign-in screen that discards the token they arrived with. The token is the
   * credential - 256 bits delivered only to the address it proves. */
  verifyEmail(body: VerifyEmailBody, options?: RequestOptions): Promise<Session>;

  /** Issue a reset link if the address has an account. Same response either
   * way — see the route's own docstring for why. */
  forgotPassword(
    body: ForgotPasswordBody,
    options?: RequestOptions,
  ): Promise<Record<string, string>>;
  /** Redeem a reset link. Does not sign the caller in — continuing to
   * `/login` is a separate, explicit step, same as accepting an invitation. */
  resetPassword(body: ResetPasswordBody, options?: RequestOptions): Promise<Record<string, string>>;
  /** Issue a fresh verification link for the signed-in caller. Requires a
   * session — there is no unauthenticated resend, unlike `forgotPassword`. */
  resendVerification(options?: RequestOptions): Promise<Record<string, string>>;
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
  /** Who is inviting whom, to where, as what — read-only, before anyone
   * decides to accept. Deliberately unauthenticated, same as
   * `acceptInvitation`: the reader may not have an account yet. */
  previewInvitation(token: string, options?: RequestOptions): Promise<InvitationPreview>;
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
  /** Which sources this deployment holds credentials for. Read-only, and the
   * same answer for every workspace: it describes the deployment, not the team. */
  listIntegrationProviders(
    workspaceId: string,
    options?: RequestOptions,
  ): Promise<IntegrationProvider[]>;
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

  /** Begin connecting Google Meet. Returns where to send the customer.
   *
   * Same shape as Chat's and for the same reason: the API answers with the
   * authorise URL rather than a 302, so the caller moves the window itself.
   *
   * There is no corresponding `finishGoogleMeetInstall`. The callback is a
   * browser navigation that ends in a 303 back to the workspace screen; calling
   * it with `fetch` would consume the single-use `state` and land the customer
   * nowhere.
   */
  startGoogleMeetInstall(workspaceId: string, options?: RequestOptions): Promise<GoogleMeetInstall>;

  /** Stop watching, tear down the event subscriptions, and clear the stored
   * credential — all three, because a disconnect that leaves the credential
   * behind keeps CAIRN holding a standing grant after somebody asked it to
   * stop. The response says which of the three happened. */
  disconnectGoogleMeet(
    workspaceId: string,
    options?: RequestOptions,
  ): Promise<GoogleMeetDisconnect>;

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

    listProjects: (
      workspaceId: string,
      query?: { state?: ProjectState; q?: string; includeArchived?: boolean },
      options?: RequestOptions,
    ) => {
      const search = new URLSearchParams();
      if (query?.state) search.set("state", query.state);
      if (query?.q) search.set("q", query.q);
      if (query?.includeArchived) search.set("include_archived", "true");
      const suffix = search.toString() === "" ? "" : `?${search.toString()}`;
      return request<ProjectList>(
        "GET",
        `/v1/workspaces/${workspaceId}/projects${suffix}`,
        undefined,
        options,
      );
    },

    getProject: (workspaceId: string, projectId: string, options?: RequestOptions) =>
      request<ProjectDetail>(
        "GET",
        `/v1/workspaces/${workspaceId}/projects/${projectId}`,
        undefined,
        options,
      ),

    createProject: (workspaceId: string, body: ProjectCreateBody, options?: RequestOptions) =>
      request<ProjectDetail>("POST", `/v1/workspaces/${workspaceId}/projects`, body, options),

    updateProject: (
      workspaceId: string,
      projectId: string,
      body: ProjectUpdateBody,
      options?: RequestOptions,
    ) =>
      request<ProjectDetail>(
        "PATCH",
        `/v1/workspaces/${workspaceId}/projects/${projectId}`,
        body,
        options,
      ),

    archiveProject: (workspaceId: string, projectId: string, options?: RequestOptions) =>
      request<ProjectDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/archive`,
        undefined,
        options,
      ),

    restoreProject: (workspaceId: string, projectId: string, options?: RequestOptions) =>
      request<ProjectDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/restore`,
        undefined,
        options,
      ),

    claimProjectSource: (
      workspaceId: string,
      projectId: string,
      value: string,
      options?: RequestOptions,
    ) =>
      request<ProjectDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/sources`,
        { value },
        options,
      ),

    releaseProjectSource: (
      workspaceId: string,
      projectId: string,
      value: string,
      options?: RequestOptions,
    ) =>
      request<ProjectDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/sources/release`,
        { value },
        options,
      ),

    addProjectMember: (
      workspaceId: string,
      projectId: string,
      body: { personId: string; projectRole?: string },
      options?: RequestOptions,
    ) =>
      request<ProjectDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/members`,
        body,
        options,
      ),

    removeProjectMember: (
      workspaceId: string,
      projectId: string,
      personId: string,
      options?: RequestOptions,
    ) =>
      request<ProjectDetail>(
        "DELETE",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/members/${personId}`,
        undefined,
        options,
      ),

    createTask: (
      workspaceId: string,
      projectId: string,
      body: TaskCreateBody,
      options?: RequestOptions,
    ) =>
      request<TaskDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/tasks`,
        body,
        options,
      ),

    listTasks: (
      workspaceId: string,
      projectId: string,
      query?: { state?: TaskState; includeArchived?: boolean },
      options?: RequestOptions,
    ) => {
      const search = new URLSearchParams();
      if (query?.state) search.set("state", query.state);
      if (query?.includeArchived) search.set("include_archived", "true");
      const suffix = search.toString() === "" ? "" : `?${search.toString()}`;
      return request<TaskList>(
        "GET",
        `/v1/workspaces/${workspaceId}/projects/${projectId}/tasks${suffix}`,
        undefined,
        options,
      );
    },

    getTask: (workspaceId: string, taskId: string, options?: RequestOptions) =>
      request<TaskDetail>(
        "GET",
        `/v1/workspaces/${workspaceId}/tasks/${taskId}`,
        undefined,
        options,
      ),

    updateTask: (
      workspaceId: string,
      taskId: string,
      body: TaskUpdateBody,
      options?: RequestOptions,
    ) =>
      request<TaskDetail>("PATCH", `/v1/workspaces/${workspaceId}/tasks/${taskId}`, body, options),

    setTaskState: (
      workspaceId: string,
      taskId: string,
      state: TaskState,
      options?: RequestOptions,
    ) =>
      request<TaskDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/tasks/${taskId}/state`,
        { state },
        options,
      ),

    archiveTask: (workspaceId: string, taskId: string, options?: RequestOptions) =>
      request<TaskDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/tasks/${taskId}/archive`,
        undefined,
        options,
      ),

    restoreTask: (workspaceId: string, taskId: string, options?: RequestOptions) =>
      request<TaskDetail>(
        "POST",
        `/v1/workspaces/${workspaceId}/tasks/${taskId}/restore`,
        undefined,
        options,
      ),

    listMyTasks: (workspaceId: string, options?: RequestOptions) =>
      request<MyTasks>("GET", `/v1/workspaces/${workspaceId}/me/tasks`, undefined, options),

    findRelatedWork: (workspaceId: string, topic: string, options?: RequestOptions) =>
      request<RelatedWork>(
        "GET",
        `/v1/workspaces/${workspaceId}/related-work?topic=${encodeURIComponent(topic)}`,
        undefined,
        options,
      ),

    setMyCapacity: (workspaceId: string, capacity: Capacity, options?: RequestOptions) =>
      request<CapacityState>(
        "PUT",
        `/v1/workspaces/${workspaceId}/me/capacity`,
        { capacity },
        options,
      ),

    verifyEmail: (
      body: paths["/v1/auth/verify-email"]["post"]["requestBody"]["content"]["application/json"],
      options?: RequestOptions,
    ) => request<Session>("POST", "/v1/auth/verify-email", body, options),

    forgotPassword: (body: ForgotPasswordBody, options?: RequestOptions) =>
      request<Record<string, string>>("POST", "/v1/auth/forgot-password", body, options),

    resetPassword: (body: ResetPasswordBody, options?: RequestOptions) =>
      request<Record<string, string>>("POST", "/v1/auth/reset-password", body, options),

    resendVerification: (options?: RequestOptions) =>
      request<Record<string, string>>("POST", "/v1/auth/resend-verification", undefined, options),

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

    listIntegrationProviders: (workspaceId: string, options?: RequestOptions) =>
      request<IntegrationProvider[]>(
        "GET",
        `/v1/workspaces/${workspaceId}/integrations/providers`,
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

    startGoogleMeetInstall: (workspaceId: string, options?: RequestOptions) =>
      request<GoogleMeetInstall>(
        "POST",
        `/v1/workspaces/${workspaceId}/integrations/google-meet/install`,
        undefined,
        options,
      ),

    disconnectGoogleMeet: (workspaceId: string, options?: RequestOptions) =>
      request<GoogleMeetDisconnect>(
        "POST",
        `/v1/workspaces/${workspaceId}/integrations/google-meet/disconnect`,
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

    previewInvitation: (token: string, options?: RequestOptions) =>
      request<InvitationPreview>(
        "GET",
        `/v1/invitations/preview${searchParams({ token })}`,
        undefined,
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
