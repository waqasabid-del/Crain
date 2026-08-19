/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source of truth: apps/api/src/cairn_api/api/ (FastAPI routes and Pydantic models)
 * Regenerate with: make schema
 *
 * A test fails if this file is out of date, so drift between the API and these
 * types cannot reach production.
 */

export interface paths {
  "/healthz": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Liveness probe
     * @description Report that the process is running. Never touches the database.
     */
    get: operations["liveness_healthz_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/readyz": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Readiness probe
     * @description Report whether this instance can serve traffic.
     *
     *     Returns 503 rather than raising, so the body is a plain health document in
     *     both cases — a probe parsing two different shapes is a probe that eventually
     *     misreads one.
     */
    get: operations["readiness_readyz_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/forgot-password": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Request a password reset link
     * @description Issue a reset link, if the address has an account.
     *
     *     **The response is identical whether or not it does.** Saying otherwise
     *     would let anyone use this form to enumerate registered addresses — this
     *     is the unauthenticated case `login` avoids by being deliberately vague
     *     about which of two things failed; here there is only one thing to hide,
     *     the account's existence, and it stays hidden.
     */
    post: operations["forgot_password_v1_auth_forgot_password_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/login": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Exchange credentials for a session
     * @description Verify credentials and issue a session.
     */
    post: operations["login_v1_auth_login_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/logout": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * End the current session
     * @description Revoke this session and clear the cookie.
     *
     *     Both, in that order. Clearing the cookie alone leaves a token that still
     *     works if it was captured; revoking alone leaves a browser presenting a dead
     *     credential on every request.
     */
    post: operations["logout_v1_auth_logout_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/logout-everywhere": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * End every other session for this user
     * @description Revoke every session except the one making the request.
     *
     *     The account-recovery path. Until this existed, the only way to end a session
     *     was to present its token — which is precisely what someone reporting a
     *     compromised account does not have, and what the attacker does.
     *
     *     The current session survives so that "sign out everywhere else" does not sign
     *     the user out of the device they are asking from, which reads as the button
     *     having failed.
     */
    post: operations["logout_everywhere_v1_auth_logout_everywhere_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/resend-verification": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Send a fresh verification link
     * @description Issue a new verification token, invalidating any outstanding one.
     *
     *     Returns the same response whether or not the account is already verified.
     *     Saying "already verified" would confirm account state to whoever holds the
     *     session, and there is no useful action either answer enables.
     */
    post: operations["resend_verification_v1_auth_resend_verification_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/reset-password": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Redeem a password reset link
     * @description Set a new password from a reset token.
     *
     *     Deliberately unauthenticated, and deliberately does not sign the caller
     *     in: the token proves control of the address, not that this browser
     *     should now hold a session — the reader continues to `/login` explicitly,
     *     the same way accepting an invitation does.
     */
    post: operations["reset_password_endpoint_v1_auth_reset_password_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/session": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Identify the current caller
     * @description Return the signed-in user and their workspaces.
     *
     *     The request a frontend makes before rendering anything, which is why it
     *     returns workspaces in the same round trip rather than requiring a second
     *     call to decide what to draw.
     */
    get: operations["current_session_v1_auth_session_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/signup": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Create an account and its first workspace
     * @description Create a user, a workspace and the owner membership joining them.
     *
     *     All three or none — the transaction is the caller's, and a partial signup
     *     leaves an account that cannot do anything and cannot be recovered without
     *     manual intervention.
     *
     *     Signing in immediately is deliberate: making someone who just chose a
     *     password type it again is friction with no security benefit, on the one
     *     screen where abandonment costs the most.
     */
    post: operations["signup_v1_auth_signup_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/auth/verify-email": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Prove control of an email address
     * @description Redeem a verification link.
     *
     *     Deliberately unauthenticated: someone clicking a link from their inbox may
     *     not have a session in that browser, and requiring one would send them to a
     *     login screen that discards the token they arrived with.
     *
     *     The token is the credential. It is 256 bits of entropy delivered only to the
     *     address it proves, which is a stronger claim about that address than a
     *     session is.
     */
    post: operations["verify_email_endpoint_v1_auth_verify_email_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/audit": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What staff have done
     * @description The log, newest first, optionally for one workspace.
     */
    get: operations["read_audit_log_v1_internal_audit_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/audit/verify": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Check the audit chain end to end
     * @description Walk every link and report the first break.
     *
     *     Exposed as an endpoint rather than left to a script because the question it
     *     answers — "has this record been altered" — is one a customer may ask, and an
     *     answer that requires database access is one only staff can produce.
     */
    get: operations["verify_audit_log_v1_internal_audit_verify_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/operations/evaluation": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * The last recorded evaluation run
     * @description Scores and failure modes from the committed baseline.
     *
     *     The cases stay in the repository. A dashboard that showed the golden cases
     *     would be exporting the customer corrections they were built from.
     */
    get: operations["evaluation_summary_v1_internal_operations_evaluation_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/operations/pipeline": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Ingestion health across every workspace
     * @description Counts and ages, no tenant named.
     *
     *     Deliberately platform-wide: a per-workspace view of what a customer is
     *     producing is a support session's business, not a dashboard's.
     */
    get: operations["pipeline_health_v1_internal_operations_pipeline_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/operations/queue": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Queue and backfill state
     * @description Read from the durable record.
     *
     *     Queue depth from the broker would be per-instance and momentary; the rows
     *     waiting in PostgreSQL are the same on every replica.
     */
    get: operations["queue_health_v1_internal_operations_queue_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/operations/slo": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Each service level objective, its target, and what it currently reads
     * @description The objectives, measured where the infrastructure allows it.
     *
     *     An objective this deployment cannot measure reports `measurable: false` and
     *     says why. Nothing here substitutes the target for a missing measurement:
     *     an operator who reads a fabricated number acts on it, and the action is
     *     always "nothing is wrong".
     */
    get: operations["slo_status_v1_internal_operations_slo_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/operations/spend": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What the model boundary cost this process, and how close it is to the ceiling
     * @description The process's own spend counters, and the ceiling signals.
     *
     *     In-process, so this is one replica's view — stated rather than implied,
     *     because a spend figure that looks global and is not is how a cost incident
     *     gets missed. The durable version arrives with the metrics exporter.
     *
     *     Read from `SPEND_SIGNALS` rather than from a ledger. A ledger belongs to one
     *     unit of work and is discarded with it, so building a fresh one here — which
     *     is what this endpoint used to do — reported zero however much the process
     *     had spent, and the screen could not have shown a cost incident if one had
     *     been happening while it was open.
     */
    get: operations["model_spend_v1_internal_operations_spend_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/staff/{user_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Grant back-office access
     * @description Make somebody staff.
     *
     *     The first staff member is created by a migration or by hand — deliberately,
     *     since an endpoint that can bootstrap the first one is an endpoint that can
     *     bootstrap an attacker.
     */
    post: operations["grant_staff_v1_internal_staff__user_id__post"];
    /**
     * Revoke back-office access
     * @description Revoke access, keeping the row.
     *
     *     "Was this person staff in March" is a question an audit asks, and a deleted
     *     row cannot answer it.
     */
    delete: operations["revoke_staff_v1_internal_staff__user_id__delete"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/support-sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * The caller's own support requests and their status
     * @description Only the caller's own requests.
     *
     *     The minimum needed to act: whether the workspace said yes, and until when. A
     *     staff member has no reason to read what a colleague asked another customer
     *     for — that is the security role's view, through the audit log.
     */
    get: operations["my_support_sessions_v1_internal_support_sessions_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/tenants": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Every workspace, with its configuration and health
     * @description List workspaces by name or slug.
     *
     *     Reads are not audited. An audit log that records every list view fills with
     *     noise and buries the entries that matter — and a read of configuration is
     *     not the thing md/15 §5 exists to constrain. Reading a customer's *work*
     *     requires a support session, which is audited, approved and time-boxed.
     */
    get: operations["list_tenants_v1_internal_tenants_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/tenants/{tenant_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * One workspace: configuration, integrations, and ingestion health
     * @description Everything an operator needs to diagnose a workspace, and nothing more.
     *
     *     Counts, timestamps and connection state — no statement, no brief, no
     *     person's activity. The distinction is the product's central claim, so it is
     *     enforced by what this response model can hold rather than by care.
     */
    get: operations["get_tenant_v1_internal_tenants__tenant_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/tenants/{tenant_id}/subscription": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Billing state, read without touching the payment provider
     * @description What CAIRN believes about this workspace's plan.
     *
     *     md/15 screen 31 exists so an operator answering "why were we charged this"
     *     does not open Stripe and act on what they see there. Billing is not
     *     implemented (Step 31), so this reports what is known — seats and the plan
     *     CAIRN holds — and says plainly that no provider is connected, rather than
     *     inventing a subscription to fill the screen.
     */
    get: operations["inspect_subscription_v1_internal_tenants__tenant_id__subscription_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/tenants/{tenant_id}/support-sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Ask a workspace for permission to look at it
     * @description Request access. Grants nothing.
     *
     *     The session is created `pending`. Only an Owner or Admin of that workspace
     *     can make it live, which is the whole model: staff ask, customers decide
     *     (md/15 §5.2).
     */
    post: operations["request_support_session_v1_internal_tenants__tenant_id__support_sessions_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/internal/tenants/{tenant_id}/support/activity": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Read a workspace's activity under an approved content session
     * @description The only path from staff to customer content, and it records itself.
     *
     *     The read happens through a tenant-scoped session, so row-level security
     *     still decides what is visible — the approval decides whether the door opens,
     *     not whether isolation applies.
     */
    get: operations["read_activity_under_support_v1_internal_tenants__tenant_id__support_activity_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/invitations/accept": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Redeem an invitation
     * @description Join the workspace an invitation names.
     *
     *     **The invited person joins the existing workspace.** No workspace is created
     *     — that is the entire point of this endpoint and the mistake it exists to
     *     prevent. A signup path that creates a workspace for every new account turns
     *     one team into several isolated single-person workspaces, each showing an
     *     empty brief. Everyone can sign in, so it looks like it works.
     *
     *     Runs on the platform connection because there is no membership yet, and so
     *     no tenant context to scope to. This is one of three routes that legitimately
     *     do.
     *
     *     Note that redeeming does **not** issue a session. The caller proves control
     *     of the address by holding the token, which is not the same as proving they
     *     know the password; signing them in here would let anyone who intercepts an
     *     invitation link take over an existing account.
     */
    post: operations["accept_v1_invitations_accept_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/invitations/preview": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * See who is inviting you, and where, before accepting
     * @description Read-only. Nothing is created, changed, or consumed by looking.
     *
     *     Deliberately unauthenticated, same as `accept` below: the reader may not
     *     have an account yet, so there is no session to require.
     */
    get: operations["preview_v1_invitations_preview_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Read a workspace
     * @description Return the workspace the caller is a member of.
     *
     *     Read through the tenant-scoped session rather than the platform one, even
     *     though membership is already proven. Two reasons: privileged connections
     *     should stay rare enough that `grep platform_db` remains reviewable, and it
     *     means row-level security is exercised on the ordinary read path, where a
     *     policy regression would show up immediately rather than in the one endpoint
     *     that happens to be scoped.
     */
    get: operations["get_workspace_v1_workspaces__workspace_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/brief": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Generate a brief for a period
     * @description Serve the period's brief: from the archive if it is a record, else fresh.
     *
     *     A finished period is generated once and kept; the current one is generated
     *     live, never stored, and reused from `briefs.BriefCache` for a few minutes so
     *     a morning's readers share one model call. Every claim carries the facts and
     *     the evidence it rests on, and claims failing synthesis' four gates are
     *     dropped rather than caveated — the count is reported instead.
     *
     *     The rate limit is applied only when something is actually generated, so
     *     neither reading the archive nor reading a cached brief is rationed: reading
     *     is not what costs money.
     */
    get: operations["get_brief_v1_workspaces__workspace_id__brief_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/briefs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Past briefs, newest first
     * @description The archive.
     *
     *     Summaries, not whole briefs: an archive is a list to scan, and sending every
     *     claim of every period to render a list of dates is the request that makes
     *     this screen slow exactly as a workspace accumulates history.
     *
     *     Keyset pagination on `period_end`, matching `/facts`. Offset pagination on a
     *     list that grows at the newest end shifts every row down as briefs are
     *     written, so a reader paging backwards sees one period twice and never sees
     *     another.
     */
    get: operations["list_briefs_v1_workspaces__workspace_id__briefs_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/briefs/{brief_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * One brief from the archive
     * @description A stored brief by id — the permalink the archive links to.
     *
     *     A stable address matters more here than it looks: "you told us on Tuesday
     *     that payments had shipped" needs something a person can send to somebody
     *     else. A URL that reconstructs the period as query parameters would be that
     *     address only until the period boundaries were computed differently.
     *
     *     Reads only stored briefs. There is deliberately no fallback that generates
     *     one for a missing id: an archive entry that appears when it is asked for is
     *     not a record of anything.
     */
    get: operations["get_archived_brief_v1_workspaces__workspace_id__briefs__brief_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/facets": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What this workspace can be filtered by
     * @description The people, projects and sources that appear in this workspace's facts.
     *
     *     Read from the facts, not from a list of what CAIRN can hold. A filter menu is
     *     a description of what is there — offering a value that matches nothing
     *     teaches a reader that the filters are broken, and they are right to conclude
     *     it.
     */
    get: operations["get_facets_v1_workspaces__workspace_id__facets_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/facts": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List the facts CAIRN holds for this workspace
     * @description Return a page of facts, newest activity first.
     *
     *     **Keyset pagination, not limit/offset**, and the choice is forced by what
     *     this list is. Facts arrive continuously — every webhook can insert into the
     *     middle of the ordering, because a fact is ordered by when the activity
     *     *happened*, not by when it was stored. Under `OFFSET 50` a fact inserted
     *     while someone reads page one is a fact that shifts every later page by a
     *     row: the reader sees one item twice and never sees another at all, with
     *     nothing in the response to indicate it. A keyset cursor names the last row
     *     of the previous page, so an insertion behind the cursor is simply invisible
     *     and an insertion ahead of it appears on a later page. It is also the version
     *     that stays fast: `OFFSET 10000` reads and discards ten thousand rows, on a
     *     table that only grows.
     *
     *     The cursor is opaque on purpose. It encodes `(occurred_at, id)`, and a
     *     client that parsed it would be depending on the sort key — which is exactly
     *     the thing a later "sort by relevance" would change.
     *
     *     **Undated facts sort last and page consistently.** `occurred_at` is nullable
     *     — some sources do not timestamp reliably — so the ordering is
     *     `occurred_at DESC NULLS LAST, id DESC`, and the cursor predicate has a
     *     matching branch for a null. Dropping undated facts from the list instead
     *     would silently hide whole sources.
     */
    get: operations["list_facts_v1_workspaces__workspace_id__facts_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/facts/{fact_id}/correction": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Correct something CAIRN said about you
     * @description Record a correction, superseding the fact it corrects.
     *
     *     **The check is subject, not seniority.** A caller may correct a fact that
     *     concerns them and no other, whatever their role. An Owner rewriting what
     *     CAIRN said about somebody else would be the product taking a person's record
     *     away from them at exactly the moment it matters most.
     */
    post: operations["correct_v1_workspaces__workspace_id__facts__fact_id__correction_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What this workspace has connected
     * @description Every integration, connected or not, and its state.
     *
     *     Readable by every member rather than by administrators only. What is
     *     connected decides what CAIRN can see about the person reading — the same
     *     reasoning that puts the source list on the notification screen. Hiding it
     *     behind a role would mean a Viewer had to ask permission to find out what was
     *     being read about them.
     *
     *     Disconnected installations are listed, not omitted: a gap in the feed is
     *     explained by "GitHub was disconnected on the 4th" and unexplained by silence.
     *
     *     Read through the tenant-scoped connection even though the write below is
     *     platform-side. The application role has `SELECT` on this table behind a
     *     row-level-security policy, so the isolation is enforced by the database
     *     rather than by the `WHERE` clause being remembered.
     */
    get: operations["list_integrations_v1_workspaces__workspace_id__integrations_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/github": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Connect a GitHub App installation to this workspace
     * @description Bind an installation to this workspace and start its backfill.
     *
     *     **The only way an installation is ever created**, and deliberately so. An
     *     audit found the webhook path could resolve an installation and nothing could
     *     create one, which made Steps 11 to 13 unreachable end to end — but the fix
     *     is not to let the webhook create it. An inbound webhook creating the mapping
     *     would mean whoever installed the app has their activity bound to a workspace
     *     nobody chose. This runs behind a session, a membership and a permission
     *     check, which is the point at which we know who asked.
     *
     *     Runs on the platform connection because the installation table is read
     *     before tenant context exists on the webhook path, so its writes live
     *     platform-side too.
     */
    post: operations["connect_github_v1_workspaces__workspace_id__integrations_github_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/github/{installation_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    /**
     * Stop capturing activity from a GitHub installation
     * @description Stop capture from one installation.
     *
     *     **Marked, not deleted**, and the two differ in what they promise. Marking
     *     stops every future delivery being processed — the ingestion path checks this
     *     already, because a suspended installation that kept delivering was treated as
     *     a consent problem rather than a bug. Deleting the row would additionally
     *     erase the record that the integration ever existed, which turns the months of
     *     activity it produced into facts with no explanation of where they came from.
     *
     *     **What was already captured stays**, and the interface says so rather than
     *     letting an administrator discover it. Disconnecting is "stop reading", not
     *     "forget what you read": the second is a deletion request, it applies to
     *     everyone's shared history, and it is not a side effect of a button labelled
     *     *Disconnect*.
     *
     *     This does not uninstall the GitHub App. CAIRN cannot revoke somebody else's
     *     installation, and pretending otherwise would leave an administrator believing
     *     they had removed an access grant that is still live on GitHub's side.
     */
    delete: operations["disconnect_github_v1_workspaces__workspace_id__integrations_github__installation_id__delete"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/invitations": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List outstanding invitations
     * @description List invitations that are still redeemable.
     *
     *     Gated on the permission to *invite* rather than a separate read permission.
     *     Who has been invited but not yet joined is administrative information, and a
     *     Viewer having it serves no purpose while disclosing hiring intent.
     *
     *     Superseded and accepted invitations are excluded — an admin asking "who is
     *     still outstanding" means exactly the rows a new invitation would conflict
     *     with.
     */
    get: operations["list_invitations_v1_workspaces__workspace_id__invitations_get"];
    put?: never;
    /**
     * Invite someone to the workspace
     * @description Issue an invitation.
     *
     *     Two escalation paths are closed in the service layer and worth restating,
     *     because the route is where someone would be tempted to re-implement them:
     *     a Member cannot invite at all, and nobody — including an Admin — can invite
     *     at a role above their own. Ownership moves by explicit transfer.
     *
     *     The caller's `Membership` is passed rather than a tenant ID and a user ID,
     *     so the three facts cannot disagree.
     *
     *     **The token is not returned.** It goes to the invited address and nowhere
     *     else. Returning it would let anyone who can invite also redeem, collapsing
     *     "invite an address" into "prove control of it".
     */
    post: operations["create_invitation_v1_workspaces__workspace_id__invitations_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/invitations/{invitation_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    /**
     * Withdraw an invitation
     * @description Withdraw an invitation that has not been accepted.
     *
     *     Marks it superseded rather than deleting it. "We invited this person and
     *     then withdrew it" is exactly the sort of question an audit trail is kept to
     *     answer, and the partial unique index treats superseded rows as free, so the
     *     address can be invited again immediately.
     */
    delete: operations["revoke_invitation_v1_workspaces__workspace_id__invitations__invitation_id__delete"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/me/role": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What the caller says they do
     * @description The caller's own work role.
     *
     *     Also on the session, which is where every screen reads it from. This exists
     *     for the one case the session does not cover: confirming what was saved
     *     without re-authenticating.
     */
    get: operations["my_role_v1_workspaces__workspace_id__me_role_get"];
    /**
     * Say what you do, or withdraw the answer
     * @description Record what the caller does.
     *
     *     **Self only, by construction rather than by a check.** The membership being
     *     written is the one the caller's own session resolved to; there is no path
     *     through this API that sets anybody else's. That absence is the design: an
     *     administrator who could label a colleague's role would be storing a
     *     management classification on their record, in a product whose position is
     *     that it does not do that (md/05 §B.2).
     *
     *     **It changes emphasis and never access.** What CAIRN opens on, and how a
     *     person's own record is framed. Every role sees the same facts, and
     *     `test_roles.py` asserts it rather than trusting that nobody will wire a
     *     filter to this field later.
     *
     *     **Null is accepted**, because withdrawing the answer has to be as easy as
     *     giving it — otherwise the only way out of a wrong guess is a different wrong
     *     guess.
     *
     *     No permission is declared. Every role including Viewer may answer a question
     *     about themselves, and requiring one would mean a person's own description of
     *     their work was something the workspace granted them.
     */
    put: operations["set_my_role_v1_workspaces__workspace_id__me_role_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/me/sources": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What CAIRN may attribute to you, and what it never does
     * @description Every source, whether the caller has opted out, and the refusals.
     *
     *     **Every source is listed, not only the connected ones.** md/11 §4.1 requires
     *     the notification to reach a person *before* any of their activity is
     *     captured, which means before their workspace has necessarily connected
     *     anything. An opt-out for a source nobody has connected yet is not pointless
     *     — it is a person deciding in advance, which is the strongest form the choice
     *     can take.
     *
     *     **Serving this is what "notified" means**, and it is recorded here. Worker
     *     notification is a legal obligation before first capture with no regional
     *     exception, and an obligation nobody can evidence is one an Owner has to take
     *     on trust at the moment a works council asks them not to. This response *is*
     *     the notification — what is read, and the control for switching it off — so
     *     the moment it is delivered is the honest moment to stamp. Deliberately
     *     narrower than "they read it", which no software knows.
     */
    get: operations["my_sources_v1_workspaces__workspace_id__me_sources_get"];
    /**
     * Opt out of a source, or back in
     * @description Record the caller's choice about one source.
     *
     *     **A `PUT` of the desired state rather than two verbs.** The interface is a
     *     toggle, and a toggle that has to choose between `POST` and `DELETE` based on
     *     what it believes the current state to be is a toggle that gets it wrong
     *     after a stale page — turning "opt me out" into "opt me back in" at the worst
     *     possible moment.
     *
     *     Only ever the caller's own consent. There is no workspace-level version of
     *     this endpoint, and there should not be: an Owner opting somebody else back
     *     in would be the product overriding a privacy decision on the person's
     *     behalf.
     */
    put: operations["set_source_consent_v1_workspaces__workspace_id__me_sources_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/me/week": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What CAIRN believes about you
     * @description The caller's own record.
     *
     *     **Scoped in the query, not in the response.** Filtering the team's facts down
     *     to the reader in the interface would mean one forgotten condition shows a
     *     person somebody else's record — the failure that turns a trust product into
     *     a surveillance complaint. Scoping the query means the same bug shows nothing.
     *
     *     Superseded facts are excluded, so a correction takes effect the moment it is
     *     made. That is the point of the screen: a person who fixes something should
     *     see it fixed, not see their correction queued behind a nightly job.
     */
    get: operations["my_week_v1_workspaces__workspace_id__me_week_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/members": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List workspace members
     * @description List everyone in the workspace, with their roles.
     *
     *     Available to every member, including Viewers, and identical for all of them.
     *     That symmetry is deliberate and load-bearing: an Owner sees exactly what a
     *     Member sees. Adding a field here that only Admins receive would be the first
     *     step towards the visibility hierarchy this product exists not to have.
     */
    get: operations["list_members_v1_workspaces__workspace_id__members_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/members/{user_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    /**
     * Remove somebody from this workspace
     * @description Remove a member's access.
     *
     *     **Their record is not deleted with them.** The facts stay, still attributed,
     *     and this is the decision worth arguing with rather than the one it looks
     *     like. A leaver's work is the team's history — the decision they made in March
     *     is why the system is shaped as it is, and removing it on their last day
     *     rewrites the record for everyone still there.
     *
     *     What ends is *access*: the membership row goes, the session it depends on
     *     stops resolving, and no new activity is captured because nothing links them
     *     to the workspace any more. Somebody who wants their record removed as well is
     *     exercising a different right (GDPR Article 17) through a different path,
     *     which is deliberately not an administrator's button.
     */
    delete: operations["remove_member_v1_workspaces__workspace_id__members__user_id__delete"];
    options?: never;
    head?: never;
    /**
     * Change what somebody may configure
     * @description Change one member's role.
     *
     *     **A role is about configuration, not about what they can see.** Moving
     *     somebody from Admin to Viewer takes away their ability to connect an
     *     integration; it takes away nothing about their colleagues' work, because
     *     there was never anything extra to take.
     *
     *     Two refusals, both structural:
     *
     *     - **Nobody changes their own role.** The realistic version of this is an
     *       Owner demoting themselves while tidying up and locking themselves out of
     *       billing on a Friday. There is a transfer flow for handing the workspace
     *       over; this is not it.
     *     - **The last Owner stays an Owner.** A workspace with no Owner cannot be
     *       given one from inside, so the recovery path is a support ticket — the exact
     *       thing this module exists to remove.
     */
    patch: operations["change_role_v1_workspaces__workspace_id__members__user_id__patch"];
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/notifications": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Who has been told their activity may be captured
     * @description Notification per person; opt-outs only as a number.
     *
     *     **This is the asymmetry, and it is the most considered decision in the
     *     module.** md/15 §4.2 describes one screen showing "who has been notified, who
     *     has opted out". The first half is named per person and the second is not, and
     *     the two halves are different kinds of fact:
     *
     *     - **Notification is the employer's obligation**, owed to each person
     *       individually before capture begins, with no regional exception. An Owner
     *       who cannot see that Priya has not been notified cannot discharge it, and
     *       cannot evidence it when a works council asks. So it is named.
     *     - **An opt-out is the person's own decision about their own record.** A list
     *       of names beside "opted out" is a list of employees who declined to be
     *       recorded, handed to the person who writes their review. It does not matter
     *       that no reasonable manager would misuse it; what matters is that a person
     *       deciding whether to opt out would have to weigh that possibility, which
     *       turns a privacy control into a career calculation and produces a low
     *       opt-out rate that means nothing.
     *
     *     So the rate is reported and the names are not. That is also the number
     *     md/11 §7 makes the product's trust barometer and md/13 makes a phase gate —
     *     and a rate is exactly what a gate needs, where a list is not.
     *
     *     The permission is `WORKSPACE_SETTINGS` rather than `CONTENT_READ`: whether a
     *     colleague has been notified is compliance administration rather than
     *     something everyone needs, and this endpoint names people.
     */
    get: operations["notification_status_v1_workspaces__workspace_id__notifications_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/onboarding": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * How far this workspace has got, for the onboarding screen
     * @description Assemble the state of the workspace's first ten minutes.
     *
     *     Cheap enough to poll. The three queries are a count, a small indexed select
     *     and one lookup on a unique column; the screen refreshes every few seconds
     *     while an import runs, and a query that grew with the workspace would turn
     *     onboarding into the most expensive page in the product.
     */
    get: operations["get_onboarding_v1_workspaces__workspace_id__onboarding_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/privacy": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Retention and region
     * @description How long raw activity is kept, and where it lives.
     *
     *     Readable by everybody for the same reason the integration list is: these are
     *     facts about what happens to the reader's own activity, and a person should
     *     not need a role to learn them.
     */
    get: operations["get_privacy_v1_workspaces__workspace_id__privacy_get"];
    /**
     * Change how long raw activity is kept
     * @description Set the retention period.
     *
     *     **The setting is enforced by a sweep that deletes**, not by a filter that
     *     hides — see `retention.py`. A retention period nothing acts on is the worst
     *     kind of claim this product could make, because it is stated in the Trust &
     *     Privacy Center to an audience deciding whether to believe the rest of it.
     *
     *     **Region is not changeable here**, and is returned so the interface can show
     *     it. Moving a workspace between regions is a data migration under compliance
     *     pressure (md/06 §6.3), not a dropdown — and a control that silently did
     *     nothing would be worse than its absence.
     *
     *     Shortening the window takes effect on the next sweep, which will delete what
     *     has just fallen outside it. That is the honest consequence and the interface
     *     states it before the change, because "we deleted three months of raw activity
     *     because you typed 30" is not a thing to learn afterwards.
     */
    put: operations["set_privacy_v1_workspaces__workspace_id__privacy_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/search": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Search the facts CAIRN holds
     * @description Facts matching a query, most relevant first, each with its evidence.
     *
     *     **Results are stored facts and nothing else.** No model is called on this
     *     path, and the response has no field for prose. That is what "grounded" means
     *     here: the reader is looking at what CAIRN recorded, with the citation
     *     attached, rather than at a summary of it. A generated answer with sources
     *     listed underneath is the failure md/09 §5 exists to prevent — the prose is
     *     what gets believed and the citations are what nobody opens.
     *
     *     **The same filters as the feed**, from the same object, so narrowing the
     *     screen and then searching cannot widen it again.
     *
     *     Rate limited per workspace because a query with vector search enabled embeds
     *     the text, which is a model call. Far above a person typing and far below a
     *     script.
     */
    get: operations["search_facts_v1_workspaces__workspace_id__search_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/support-sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Every time CAIRN staff asked to look at this workspace
     * @description The workspace's own support history, newest first.
     *
     *     Readable by every member. Row-level security scopes it to this workspace, so
     *     the isolation is the database's rather than this query's to remember.
     */
    get: operations["list_support_sessions_v1_workspaces__workspace_id__support_sessions_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/support-sessions/{session_id}/decision": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Approve or reject a support request
     * @description Let CAIRN staff in, or refuse.
     *
     *     The expiry is set here from the server clock, using the minutes the request
     *     asked for. Nothing a caller sends decides how long access lasts.
     */
    post: operations["decide_support_session_v1_workspaces__workspace_id__support_sessions__session_id__decision_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/support-sessions/{session_id}/revoke": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * End support access now
     * @description Withdraw access before it expires.
     *
     *     Idempotent, and available whatever the state: somebody ending access under
     *     pressure should not have to read a status first.
     */
    post: operations["revoke_support_session_v1_workspaces__workspace_id__support_sessions__session_id__revoke_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/trust": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What CAIRN reads, what it refuses to do, and what happens to it
     * @description The Trust & Privacy Center for this workspace.
     *
     *     **Every member, no permission check beyond membership.** An engineer should
     *     not need their manager's role to find out what is read about them — and a
     *     page about trust that some of the team cannot open has answered the question
     *     it was written to address.
     *
     *     Sources are listed exhaustively with a connected flag rather than filtered to
     *     the connected ones. "What could CAIRN read here if somebody switched it on"
     *     is the question a person joining a workspace is actually asking, and a list
     *     that grows silently as integrations are added answers it only in hindsight.
     */
    get: operations["trust_center_v1_workspaces__workspace_id__trust_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /** AcceptInvitationRequest */
    AcceptInvitationRequest: {
      /** Displayname */
      displayName?: string | null;
      /**
       * Email
       * Format: email
       */
      email: string;
      /** Password */
      password?: string | null;
      /** Token */
      token: string;
    };
    /**
     * AuditEntryResponse
     * @description One recorded staff action.
     *
     *     `entryHash` is returned so a reader can verify the chain independently
     *     rather than trusting the server's own verdict on itself.
     */
    AuditEntryResponse: {
      /** Action */
      action: string;
      /**
       * Actoruserid
       * Format: uuid
       */
      actorUserId: string;
      /** Checksum */
      checksum: string;
      /** Detail */
      detail?: {
        [key: string]: unknown;
      };
      /**
       * Occurredat
       * Format: date-time
       */
      occurredAt: string;
      /** Reason */
      reason: string;
      /** Sequence */
      sequence: number;
      /** Tenantid */
      tenantId?: string | null;
    };
    /**
     * AuditVerification
     * @description Whether the audit chain is intact.
     */
    AuditVerification: {
      /** Brokenat */
      brokenAt?: number | null;
      /** Entries */
      entries: number;
      /** Intact */
      intact: boolean;
      /** Reason */
      reason?: string | null;
    };
    /**
     * BriefArchive
     * @description A page of past briefs, newest first.
     */
    BriefArchive: {
      /** Items */
      items?: components["schemas"]["BriefSummary"][];
      /** Nextcursor */
      nextCursor?: string | null;
    };
    /**
     * BriefClaimResponse
     * @description One sentence of a brief, with everything needed to check it.
     */
    BriefClaimResponse: {
      certainty: components["schemas"]["Certainty"];
      /** Citations */
      citations?: components["schemas"]["CitationResponse"][];
      /** Credits */
      credits?: string[];
      /** Factids */
      factIds?: string[];
      /**
       * Hedgedbysystem
       * @default false
       */
      hedgedBySystem: boolean;
      /** Text */
      text: string;
    };
    /**
     * BriefResponse
     * @description A period's brief: prose, and the claims behind it.
     */
    BriefResponse: {
      /**
       * Abstained
       * @default false
       */
      abstained: boolean;
      /** Claims */
      claims?: components["schemas"]["BriefClaimResponse"][];
      /** Generatedat */
      generatedAt?: string | null;
      /** Id */
      id?: string | null;
      /** Narrative */
      narrative: string;
      /**
       * Periodend
       * Format: date-time
       */
      periodEnd: string;
      /**
       * Periodstart
       * Format: date-time
       */
      periodStart: string;
      /**
       * Stored
       * @default false
       */
      stored: boolean;
      /**
       * Suppressedcount
       * @default 0
       */
      suppressedCount: number;
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
    };
    /**
     * BriefSummary
     * @description One entry in the archive.
     *
     *     Deliberately not the whole brief. An archive is a list to scan, and sending
     *     every claim of every period to render a list of dates is the request that
     *     makes the screen slow exactly as a workspace accumulates history.
     */
    BriefSummary: {
      /** Abstained */
      abstained: boolean;
      /** Claimcount */
      claimCount: number;
      /** Excerpt */
      excerpt: string;
      /**
       * Generatedat
       * Format: date-time
       */
      generatedAt: string;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /**
       * Periodend
       * Format: date-time
       */
      periodEnd: string;
      /**
       * Periodstart
       * Format: date-time
       */
      periodStart: string;
    };
    /**
     * Certainty
     * @description How much CAIRN trusts a claim.
     *
     *     Categorical, never numeric. A "73% confident" badge looks rigorous, means
     *     nothing to a non-technical reader, and invites false precision. Internal
     *     numeric confidence exists for thresholds and evaluation, but it never
     *     reaches this type or the interface.
     *
     *     See md/05-ux-design-privacy.md §A.2.1.
     * @enum {string}
     */
    Certainty: "verified" | "observed" | "suggested";
    /**
     * CitationResponse
     * @description Where a claim came from, resolvable in one click.
     *
     *     **The URL is the whole point of this type.** Citations used to be bare
     *     evidence identifiers — `ev-pr-482` — which satisfies "every claim carries a
     *     citation" and fails the thing the citation is *for*: a reader cannot check
     *     `ev-pr-482`. Step 21's criterion is that every claim links to its source in
     *     one click, and a string that only means something inside this database is
     *     not a link.
     *
     *     `url` is optional because some evidence genuinely has no permalink — a
     *     meeting transcript, most obviously. The interface names the source rather
     *     than hiding the citation: an unlinked citation is still provenance a person
     *     can go and check, whereas a hidden one silently breaks the promise.
     */
    CitationResponse: {
      /** Evidenceid */
      evidenceId: string;
      /** Quote */
      quote?: string | null;
      /** Source */
      source: string;
      /** Url */
      url?: string | null;
    };
    /**
     * ConnectGitHubRequest
     * @description Bind a GitHub App installation to this workspace.
     *
     *     The `installation_id` arrives as a query parameter on GitHub's post-install
     *     redirect. The caller must be an authenticated member with permission to
     *     connect integrations, which is the whole point: an inbound webhook must
     *     never be able to create this mapping, or whoever installed the app would
     *     have their activity bound to a workspace nobody chose.
     */
    ConnectGitHubRequest: {
      /** Accountlogin */
      accountLogin: string;
      /**
       * Accounttype
       * @default Organization
       */
      accountType: string;
      /** Installationid */
      installationId: number;
      /** Repositories */
      repositories?: string[];
    };
    /**
     * ConsentResponse
     * @description What CAIRN may attribute to the caller, and what it never does.
     *
     *     The refusals travel with the choices deliberately. md/05 §B.3.4 requires the
     *     contractual refusals to be stated in-product, and the moment a person is
     *     deciding whether to opt out is the moment they are most entitled to read
     *     them — not a policy page they would have to go looking for.
     */
    ConsentResponse: {
      /** Refusals */
      refusals?: string[];
      /** Sources */
      sources?: components["schemas"]["SourceConsent"][];
    };
    /**
     * ConsentUpdate
     * @description A person changing what CAIRN may attribute to them.
     */
    ConsentUpdate: {
      /** Optedout */
      optedOut: boolean;
      /** Source */
      source: string;
    };
    /**
     * ConsentUpdateResponse
     * @description The result of one choice.
     */
    ConsentUpdateResponse: {
      /** Optedout */
      optedOut: boolean;
      /** Source */
      source: string;
      /**
       * Unlinked
       * @default 0
       */
      unlinked: number;
    };
    /**
     * CorrectionRequest
     * @description A person saying what CAIRN got wrong about them.
     *
     *     A closed set of kinds rather than a free-text box, because free text is the
     *     worse input on both sides: it asks somebody to explain a defect in a product
     *     they did not build, and it hands evaluation an unlabelled string instead of
     *     a failure mode. `note` exists for the detail a kind cannot carry, and
     *     nothing depends on it being filled in.
     */
    CorrectionRequest: {
      /** Kind */
      kind: string;
      /** Note */
      note?: string | null;
      /** Statement */
      statement?: string | null;
    };
    /**
     * CorrectionResponse
     * @description What the correction did.
     */
    CorrectionResponse: {
      /**
       * Correctedfactid
       * Format: uuid
       */
      correctedFactId: string;
      replacement?: components["schemas"]["FactResponse"] | null;
    };
    /**
     * EvaluationSummary
     * @description The last recorded evaluation run.
     *
     *     Scores and failure modes. The cases themselves stay in the repository, where
     *     they are reviewed by a person rather than exported to a dashboard.
     */
    EvaluationSummary: {
      /** Available */
      available: boolean;
      /**
       * Cases
       * @default 0
       */
      cases: number;
      /**
       * Failed
       * @default 0
       */
      failed: number;
      /** Failuremodes */
      failureModes?: {
        [key: string]: number;
      };
      /** Note */
      note?: string | null;
      /**
       * Passed
       * @default 0
       */
      passed: number;
    };
    /**
     * FacetPerson
     * @description Somebody at least one current fact is about.
     */
    FacetPerson: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Name */
      name: string;
    };
    /**
     * FacetsResponse
     * @description What this workspace can actually be filtered by.
     *
     *     Every value here is one that at least one currently-valid fact would match,
     *     read from the facts rather than from a list of what CAIRN could hold. A menu
     *     offering "Meetings" to a workspace that never connected one produces an empty
     *     result the reader blames on the product.
     *
     *     **No counts anywhere.** A number beside a person's name is a productivity
     *     metric wearing a filter's clothes (md/05 §B.1), and it would be the first
     *     thing on this screen anyone screenshotted.
     */
    FacetsResponse: {
      /** People */
      people?: components["schemas"]["FacetPerson"][];
      /** Projects */
      projects?: string[];
      /** Sources */
      sources?: string[];
    };
    /**
     * FactKind
     * @description What sort of statement this is. Deliberately few and glossary-free.
     * @enum {string}
     */
    FactKind: "delivery" | "decision" | "blocker" | "in_progress" | "open_question";
    /**
     * FactOrigin
     * @description Who asserted this — a human correction outranks an extracted fact.
     * @enum {string}
     */
    FactOrigin: "extracted" | "correction";
    /**
     * FactPage
     * @description One page of facts, and how to ask for the next.
     *
     *     No total count. Counting rows a reader has not asked for costs a second
     *     query on every page, and the number would be read as "how much did this team
     *     do" — a measurement this product does not make (md/09 §10).
     */
    FactPage: {
      /** Items */
      items?: components["schemas"]["FactResponse"][];
      /** Nextcursor */
      nextCursor?: string | null;
    };
    /**
     * FactPersonResponse
     * @description A person a fact concerns, resolved or not.
     *
     *     `personId` is null for a mention the identity graph could not place
     *     unambiguously, and the raw mention is returned anyway. A name the system
     *     could not resolve is a question the workspace can answer; dropping it makes
     *     "who is Sam?" unanswerable.
     */
    FactPersonResponse: {
      /** Mention */
      mention: string;
      /** Personid */
      personId?: string | null;
    };
    /**
     * FactResponse
     * @description One statement the pipeline asserts, with its validity interval.
     */
    FactResponse: {
      certainty: components["schemas"]["Certainty"];
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Kind */
      kind: string;
      /** Occurredat */
      occurredAt?: string | null;
      origin: components["schemas"]["FactOrigin"];
      /** People */
      people?: components["schemas"]["FactPersonResponse"][];
      /** Sources */
      sources?: components["schemas"]["FactSourceResponse"][];
      /** Statement */
      statement: string;
      /** Supersededbyid */
      supersededById?: string | null;
      /** Supersessionreason */
      supersessionReason?: string | null;
      /**
       * Validfrom
       * Format: date-time
       */
      validFrom: string;
      /** Validuntil */
      validUntil?: string | null;
    };
    /**
     * FactSourceResponse
     * @description Where a fact came from, precisely enough to open.
     */
    FactSourceResponse: {
      /** Evidenceid */
      evidenceId: string;
      /** Project */
      project?: string | null;
      /** Quote */
      quote?: string | null;
      /** Source */
      source: string;
      /** Url */
      url?: string | null;
    };
    /** ForgotPasswordRequest */
    ForgotPasswordRequest: {
      /**
       * Email
       * Format: email
       */
      email: string;
    };
    /**
     * GitHubInstallationResponse
     * @description A connected installation.
     */
    GitHubInstallationResponse: {
      /** Accountlogin */
      accountLogin: string;
      /** Accounttype */
      accountType: string;
      /** Active */
      active: boolean;
      /** Backfillruns */
      backfillRuns: number;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Installationid */
      installationId: number;
    };
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components["schemas"]["ValidationError"][];
    };
    /** HealthResponse */
    HealthResponse: {
      /** Environment */
      environment: string;
      /** Status */
      status: string;
    };
    /**
     * IntegrationResponse
     * @description One source, and whether it is currently reading.
     *
     *     Disconnected integrations are returned rather than filtered out: a gap in the
     *     feed is explained by "GitHub was disconnected on the 4th" and unexplained by
     *     silence.
     */
    IntegrationResponse: {
      /** Account */
      account: string;
      /**
       * Connectedat
       * Format: date-time
       */
      connectedAt: string;
      /** Disconnectedat */
      disconnectedAt?: string | null;
      /** Installationid */
      installationId: number;
      /** Source */
      source: string;
      /**
       * Suspended
       * @default false
       */
      suspended: boolean;
    };
    /**
     * InvitationPreviewResponse
     * @description What the invitee sees before accepting anything — no token, no
     *     membership row created, nothing mutated by looking.
     */
    InvitationPreviewResponse: {
      /**
       * Email
       * Format: email
       */
      email: string;
      /** Invitedbyname */
      invitedByName: string;
      role: components["schemas"]["TenantRole"];
      /** Workspacename */
      workspaceName: string;
    };
    /**
     * InvitationResponse
     * @description An issued invitation.
     *
     *     **The token is not here.** It reaches the invitee by email and nowhere else.
     *     Returning it would let anyone who can issue an invitation also redeem it,
     *     collapsing the distinction between inviting an address and proving control
     *     of it — and would write a working credential into the API logs of every
     *     intermediary.
     */
    InvitationResponse: {
      /**
       * Email
       * Format: email
       */
      email: string;
      /**
       * Expiresat
       * Format: date-time
       */
      expiresAt: string;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      role: components["schemas"]["TenantRole"];
    };
    /** InviteRequest */
    InviteRequest: {
      /**
       * Email
       * Format: email
       */
      email: string;
      /** @default member */
      role: components["schemas"]["TenantRole"];
    };
    /** LoginRequest */
    LoginRequest: {
      /**
       * Email
       * Format: email
       */
      email: string;
      /** Password */
      password: string;
    };
    /**
     * MembershipResponse
     * @description A person's place in a workspace.
     *
     *     Carries role and join date and nothing else — no activity counts, no last
     *     seen, no "engagement". Roles govern configuration; they do not govern how
     *     much is visible about a person (md/15 §2.2), and a members list is exactly
     *     where a visibility field would first appear.
     */
    MembershipResponse: {
      /** Displayname */
      displayName: string | null;
      /**
       * Email
       * Format: email
       */
      email: string;
      /**
       * Joinedat
       * Format: date-time
       */
      joinedAt: string;
      role: components["schemas"]["TenantRole"];
      /**
       * Userid
       * Format: uuid
       */
      userId: string;
    };
    /**
     * ModelSpend
     * @description What the model boundary cost, and whether the ceiling is being hit.
     *
     *     Read from the same counters the pipeline records against, so this screen and
     *     the bill cannot disagree.
     *
     *     Capping without signalling is how a ceiling that refuses work every day goes
     *     unnoticed until a customer asks why their briefs stopped. `warnings` and
     *     `refusals` are the two numbers OPERATIONS.md's cost row alerts on.
     */
    ModelSpend: {
      /** Backend */
      backend: string;
      /** Bystage */
      byStage?: components["schemas"]["ModelSpendLine"][];
      /** Ceilingcalls */
      ceilingCalls?: number | null;
      /** Ceilingtokens */
      ceilingTokens?: number | null;
      /** Live */
      live: boolean;
      /** Note */
      note?: string | null;
      /**
       * Refusals
       * @default 0
       */
      refusals: number;
      /** Totalcalls */
      totalCalls: number;
      /** Totaltokens */
      totalTokens: number;
      /**
       * Warnings
       * @default 0
       */
      warnings: number;
      /**
       * Workspacesrefused
       * @default 0
       */
      workspacesRefused: number;
    };
    /**
     * ModelSpendLine
     * @description Spend for one stage, and how close it came to the ceiling.
     *
     *     Tokens, calls and ratios. Never content, and never a workspace: which stage
     *     is running out of budget is an operations question, which workspace it
     *     belongs to is a support session's.
     */
    ModelSpendLine: {
      /** Calls */
      calls: number;
      /** Closestapproach */
      closestApproach?: number | null;
      /**
       * Refusals
       * @default 0
       */
      refusals: number;
      /** Stage */
      stage: string;
      /** Tokens */
      tokens: number;
      /**
       * Warnings
       * @default 0
       */
      warnings: number;
    };
    /**
     * NotificationStatus
     * @description Worker notification across the workspace.
     */
    NotificationStatus: {
      /** Membercount */
      memberCount: number;
      /** Optedoutcount */
      optedOutCount: number;
      /** People */
      people?: components["schemas"]["PersonNotification"][];
      /** Sources */
      sources?: string[];
    };
    /**
     * OnboardingResponse
     * @description How far a workspace has got through its first ten minutes.
     *
     *     Counters rather than a percentage. GitHub does not say how many commits a
     *     repository holds before it is walked, so a percentage would be invented —
     *     and an invented one always stalls near the end, which reads as broken rather
     *     than as unknown. A number that climbs is honest and, on the screen where
     *     abandonment costs most, more reassuring.
     */
    OnboardingResponse: {
      /** Accountlogin */
      accountLogin?: string | null;
      /**
       * Commitsimported
       * @default 0
       */
      commitsImported: number;
      /** Connected */
      connected: boolean;
      /**
       * Factsavailable
       * @default 0
       */
      factsAvailable: number;
      /**
       * Importing
       * @default false
       */
      importing: boolean;
      /** Repositories */
      repositories?: components["schemas"]["RepositoryProgress"][];
      /** Stage */
      stage: string;
    };
    /**
     * PersonNotification
     * @description Whether one member has been served the worker notification.
     *
     *     Named per person deliberately. Notification is an obligation the employer
     *     owes each individual before capture begins, and an Owner who cannot see who
     *     is outstanding cannot discharge it.
     *
     *     Note what is **not** here: whether they opted out. That is the person's own
     *     decision about their own record, and a list of names beside "opted out" is a
     *     list of employees who declined to be recorded, handed to whoever writes their
     *     review — see `NotificationStatus`.
     */
    PersonNotification: {
      /** Displayname */
      displayName?: string | null;
      /**
       * Email
       * Format: email
       */
      email: string;
      /** Notifiedat */
      notifiedAt?: string | null;
      /**
       * Userid
       * Format: uuid
       */
      userId: string;
    };
    /**
     * PipelineHealth
     * @description How ingestion is going, in counts and ages.
     *
     *     Every field is a number or a timestamp. There is nowhere here to put a
     *     statement, a brief or a payload, which is the point: operations data leaves
     *     the product for dashboards and exporters that md/05's promises do not cover.
     */
    PipelineHealth: {
      /** Deliverieslasthour */
      deliveriesLastHour: number;
      /** Deliveriesunprocessed */
      deliveriesUnprocessed: number;
      /** Factslasthour */
      factsLastHour: number;
      /** Oldestunprocessedminutes */
      oldestUnprocessedMinutes?: number | null;
      /** Workspacesingesting */
      workspacesIngesting: number;
    };
    /**
     * PrivacySettings
     * @description What happens to this workspace's raw activity.
     *
     *     The bounds are returned with the value so the interface states the range it
     *     will accept before somebody is refused for typing outside it.
     */
    PrivacySettings: {
      /** Maxretentiondays */
      maxRetentionDays: number;
      /** Minretentiondays */
      minRetentionDays: number;
      region: components["schemas"]["Region"];
      /** Retentiondays */
      retentionDays: number;
    };
    /**
     * PrivacyUpdate
     * @description How long to keep raw activity.
     */
    PrivacyUpdate: {
      /** Retentiondays */
      retentionDays: number;
    };
    /**
     * QueueHealth
     * @description Queue state, from the durable record rather than from memory.
     */
    QueueHealth: {
      /** Backfillrunsactive */
      backfillRunsActive: number;
      /** Backfillrunsfailed */
      backfillRunsFailed: number;
      /** Deliveriesawaitingprocessing */
      deliveriesAwaitingProcessing: number;
      /** Inmemorybroker */
      inMemoryBroker: boolean;
      /** Longestwaitminutes */
      longestWaitMinutes?: number | null;
      /**
       * Scheduledrunning
       * @default 0
       */
      scheduledRunning: number;
      /**
       * Scheduledwaiting
       * @default 0
       */
      scheduledWaiting: number;
      /**
       * Tenantswaiting
       * @default 0
       */
      tenantsWaiting: number;
    };
    /**
     * Region
     * @description Where a tenant's data is stored (only ``US_CENTRAL1`` is live so far,
     *     md/06 §6.3).
     * @enum {string}
     */
    Region: "us-central1" | "europe-west1";
    /**
     * RepositoryProgress
     * @description One repository's import, as the onboarding screen shows it.
     */
    RepositoryProgress: {
      /** Commitsimported */
      commitsImported: number;
      /** Finished */
      finished: boolean;
      /** Repository */
      repository: string;
      /** State */
      state: string;
    };
    /** ResetPasswordRequest */
    ResetPasswordRequest: {
      /** Password */
      password: string;
      /** Token */
      token: string;
    };
    /**
     * RoleUpdate
     * @description A member's new role.
     *
     *     A role, and nothing else. A body that also carried, say, `email` would make
     *     this endpoint a general-purpose member editor, and the next field added to it
     *     would be added without anybody deciding an administrator should be able to
     *     change it.
     */
    RoleUpdate: {
      role: components["schemas"]["TenantRole"];
    };
    /**
     * SearchHit
     * @description One search result: a stored fact, and how it was found.
     */
    SearchHit: {
      fact: components["schemas"]["FactResponse"];
      /**
       * Matchedon
       * @enum {string}
       */
      matchedOn: "words" | "meaning";
    };
    /**
     * SearchResults
     * @description What a search found.
     *
     *     **No cursor, deliberately.** Keyset pagination needs a stable total order,
     *     and relevance is not one — it is recomputed per query and would reorder under
     *     a cursor. A ranked list is an answer rather than a stream, so this returns
     *     the best `limit` results and says when it stopped short of everything.
     *
     *     **Results are stored facts.** Nothing on this path calls a model to compose a
     *     reply, which is what "grounded" is being used to mean: the reader is looking
     *     at what CAIRN recorded, with the evidence attached, not at prose about it.
     */
    SearchResults: {
      /** Items */
      items?: components["schemas"]["SearchHit"][];
      /**
       * Semantic
       * @default true
       */
      semantic: boolean;
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
    };
    /**
     * SessionResponse
     * @description Who the caller is, and where they can go.
     */
    SessionResponse: {
      user: components["schemas"]["UserResponse"];
      /** Workspaces */
      workspaces: components["schemas"]["WorkspaceMembershipResponse"][];
    };
    /** SignupRequest */
    SignupRequest: {
      /** Displayname */
      displayName?: string | null;
      /**
       * Email
       * Format: email
       */
      email: string;
      /** Password */
      password: string;
      /** Workspacename */
      workspaceName: string;
      /** Workspaceslug */
      workspaceSlug: string;
    };
    /**
     * SloObjective
     * @description One service level objective, its target, and what it currently reads.
     *
     *     `measured` is nullable and that is the point: an objective the current
     *     infrastructure cannot measure reports `measurable: false` with the reason,
     *     rather than a number nobody can defend.
     */
    SloObjective: {
      /** Direction */
      direction: string;
      /** Key */
      key: string;
      /** Measurable */
      measurable: boolean;
      /** Measured */
      measured?: number | null;
      /** Measuredfrom */
      measuredFrom: string;
      /** Met */
      met?: boolean | null;
      /** Note */
      note?: string | null;
      /** Rationale */
      rationale: string;
      /** Target */
      target: number;
      /** Title */
      title: string;
      /** Unit */
      unit: string;
      /** Windowminutes */
      windowMinutes: number;
    };
    /**
     * SloStatus
     * @description Every objective, as of one moment.
     *
     *     Counts of machine work only. There is deliberately no objective here about
     *     how quickly a person replies to anything — see md/05 §B.2.
     */
    SloStatus: {
      /**
       * Breaching
       * @default 0
       */
      breaching: number;
      /**
       * Measuredat
       * Format: date-time
       */
      measuredAt: string;
      /** Objectives */
      objectives?: components["schemas"]["SloObjective"][];
      /**
       * Unmeasurable
       * @default 0
       */
      unmeasurable: number;
    };
    /**
     * SourceConsent
     * @description One source, and whether this person has opted out of it.
     */
    SourceConsent: {
      /** Label */
      label: string;
      /** Optedout */
      optedOut: boolean;
      /** Reads */
      reads: string;
      /** Source */
      source: string;
    };
    /**
     * StaffRole
     * @description What a member of CAIRN staff may do in the back-office.
     *
     *     The four roles md/15 §6 defines, and no catch-all: least privilege applies
     *     internally too, so a billing operator has no route to product data and a
     *     support engineer has none to the audit log. None of them reaches customer
     *     content — that needs an approved support session (Step 28), which no role
     *     can grant itself.
     * @enum {string}
     */
    StaffRole: "support" | "billing" | "engineering" | "security";
    /**
     * StaffTenantDetail
     * @description One workspace in enough detail to diagnose it.
     *
     *     Ingestion health is reported as counts and timestamps. An operator can see
     *     that deliveries stopped four days ago without seeing what any of them said.
     */
    StaffTenantDetail: {
      /**
       * Createdat
       * Format: date-time
       */
      createdAt: string;
      /** Githubconnected */
      githubConnected: number;
      /** Githubdisconnected */
      githubDisconnected: number;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Ingestionstale */
      ingestionStale: boolean;
      /** Lastdeliveryat */
      lastDeliveryAt?: string | null;
      /** Membercount */
      memberCount: number;
      /** Name */
      name: string;
      region: components["schemas"]["Region"];
      /** Retentiondays */
      retentionDays: number;
      /** Runningbackfills */
      runningBackfills: number;
      /** Slug */
      slug: string;
      /** Unprocesseddeliveries */
      unprocessedDeliveries: number;
    };
    /**
     * StaffTenantSummary
     * @description One workspace as the back-office lists it.
     *
     *     Configuration and size. No activity, no counts of work, nothing about a
     *     person — the fields this model does not have are what keeps staff out of
     *     customer content (md/15 §5.2).
     */
    StaffTenantSummary: {
      /**
       * Createdat
       * Format: date-time
       */
      createdAt: string;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Membercount */
      memberCount: number;
      /** Name */
      name: string;
      region: components["schemas"]["Region"];
      /** Slug */
      slug: string;
    };
    /**
     * SubscriptionInspection
     * @description Billing state as CAIRN holds it.
     *
     *     md/15 screen 31: an operator answering "why were we charged this" should not
     *     have to open the payment provider and act on what they see there. Billing is
     *     not implemented, so this says so rather than inventing a subscription.
     */
    SubscriptionInspection: {
      /** Note */
      note: string;
      /** Plan */
      plan: string;
      /** Providerconnected */
      providerConnected: boolean;
      /** Seatsinuse */
      seatsInUse: number;
      /**
       * Tenantid
       * Format: uuid
       */
      tenantId: string;
    };
    /**
     * SupportAccessEventResponse
     * @description One thing CAIRN staff actually opened during a session.
     */
    SupportAccessEventResponse: {
      /** Description */
      description: string;
      /**
       * Occurredat
       * Format: date-time
       */
      occurredAt: string;
      scope: components["schemas"]["SupportScope"];
    };
    /**
     * SupportDecision
     * @description A workspace's answer to a support request.
     */
    SupportDecision: {
      /** Approve */
      approve: boolean;
    };
    /**
     * SupportScope
     * @description How far a support session reaches.
     *
     *     A closed set, never a free string: a scope the database would accept but
     *     nobody decided on is an access level nobody approved.
     * @enum {string}
     */
    SupportScope: "configuration_diagnostics" | "activity_content";
    /**
     * SupportSessionRequest
     * @description What CAIRN staff are asking for.
     *
     *     No expiry field: the duration is a number of minutes bounded server-side,
     *     because an expiry supplied by the person requesting access is one they chose.
     */
    SupportSessionRequest: {
      /**
       * Minutes
       * @default 60
       */
      minutes: number;
      /** Reason */
      reason: string;
      /** @default configuration_diagnostics */
      scope: components["schemas"]["SupportScope"];
    };
    /**
     * SupportSessionResponse
     * @description A request by CAIRN staff to look at this workspace.
     *
     *     Everything md/15 §5.2 requires the customer to be able to see: who asked,
     *     for what, why, who decided, when it started, when it ends, whether it was
     *     break-glass, and what was actually opened.
     *
     *     Staff are identified by their email rather than an opaque id: "approved
     *     access for someone" is not an answer a person can act on.
     */
    SupportSessionResponse: {
      /** Active */
      active: boolean;
      approvedScope?: components["schemas"]["SupportScope"] | null;
      /**
       * Breakglass
       * @default false
       */
      breakGlass: boolean;
      /** Decidedat */
      decidedAt?: string | null;
      /** Decidedby */
      decidedBy?: string | null;
      /** Events */
      events?: components["schemas"]["SupportAccessEventResponse"][];
      /** Expiresat */
      expiresAt?: string | null;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Reason */
      reason: string;
      /**
       * Requestedat
       * Format: date-time
       */
      requestedAt: string;
      /**
       * Requestedby
       * Format: email
       */
      requestedBy: string;
      /** Requestedminutes */
      requestedMinutes: number;
      requestedScope: components["schemas"]["SupportScope"];
      /** Revokedat */
      revokedAt?: string | null;
      /** Revokedby */
      revokedBy?: string | null;
      status: components["schemas"]["SupportSessionStatus"];
    };
    /**
     * SupportSessionStatus
     * @description Where a request has got to.
     *
     *     There is deliberately no `expired` value. Expiry is a fact about the clock,
     *     and a stored status would be wrong between the moment a session lapses and
     *     whatever job got around to updating it — during which `status == 'approved'`
     *     would read as live access. `SupportSession.is_active` computes it instead.
     * @enum {string}
     */
    SupportSessionStatus: "pending" | "approved" | "rejected" | "revoked";
    /**
     * TenantRole
     * @description A person's role within one workspace. Deliberately four (md/15 §2.2).
     *     ``ADMIN`` governs configuration, never visibility depth.
     * @enum {string}
     */
    TenantRole: "owner" | "admin" | "member" | "viewer";
    /**
     * TrustCenter
     * @description The Trust & Privacy Center (md/05 §B.6).
     *
     *     **In-product and readable by every member**, not an administrator's page and
     *     not a PDF. Two audiences and identical content: employees deciding whether to
     *     trust it daily, and buyers evaluating it.
     *
     *     Every number here is read from this workspace rather than written into the
     *     copy. A trust page that states a retention period the system does not apply
     *     is the most damaging sentence this product could publish, because it is read
     *     by the audience deciding whether the rest is true.
     */
    TrustCenter: {
      /** Awaitingnotification */
      awaitingNotification: number;
      /** Commitments */
      commitments?: components["schemas"]["TrustCommitment"][];
      /** Refusals */
      refusals?: string[];
      region: components["schemas"]["Region"];
      /** Retentiondays */
      retentionDays: number;
      /** Sources */
      sources?: components["schemas"]["TrustSource"][];
      /** Subprocessors */
      subprocessors?: components["schemas"]["TrustCommitment"][];
    };
    /**
     * TrustCommitment
     * @description One thing CAIRN does, or refuses to do, in plain language.
     */
    TrustCommitment: {
      /** Detail */
      detail: string;
      /** Title */
      title: string;
    };
    /**
     * TrustSource
     * @description One source, what it reads, and whether it is switched on here.
     */
    TrustSource: {
      /** Connected */
      connected: boolean;
      /** Label */
      label: string;
      /** Reads */
      reads: string;
      /** Source */
      source: string;
    };
    /** UserResponse */
    UserResponse: {
      /** Displayname */
      displayName: string | null;
      /**
       * Email
       * Format: email
       */
      email: string;
      /**
       * Emailverified
       * @default false
       */
      emailVerified: boolean;
      /**
       * Id
       * Format: uuid
       */
      id: string;
    };
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, unknown>;
      /** Input */
      input?: unknown;
      /** Location */
      loc: (string | number)[];
      /** Message */
      msg: string;
      /** Error Type */
      type: string;
    };
    /** VerifyEmailRequest */
    VerifyEmailRequest: {
      /** Token */
      token: string;
    };
    /**
     * WorkRole
     * @description What somebody does, self-described. Not a permission — decides what
     *     CAIRN opens on (md/08 §A, md/11 §6).
     * @enum {string}
     */
    WorkRole: "founder" | "developer" | "designer" | "product" | "operations";
    /** WorkRoleResponse */
    WorkRoleResponse: {
      workRole?: components["schemas"]["WorkRole"] | null;
    };
    /**
     * WorkRoleUpdate
     * @description What the reader says they do.
     *
     *     Nullable, because withdrawing the answer has to be as easy as giving it. A
     *     person who decides they would rather not say should not have to pick
     *     something inaccurate instead.
     */
    WorkRoleUpdate: {
      workRole?: components["schemas"]["WorkRole"] | null;
    };
    /** WorkspaceMembershipResponse */
    WorkspaceMembershipResponse: {
      role: components["schemas"]["TenantRole"];
      workRole?: components["schemas"]["WorkRole"] | null;
      workspace: components["schemas"]["WorkspaceResponse"];
    };
    /** WorkspaceResponse */
    WorkspaceResponse: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Name */
      name: string;
      /** Slug */
      slug: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  liveness_healthz_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HealthResponse"];
        };
      };
    };
  };
  readiness_readyz_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HealthResponse"];
        };
      };
      /** @description A dependency is unavailable. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  forgot_password_v1_auth_forgot_password_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ForgotPasswordRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            [key: string]: string;
          };
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
      /** @description Too many requests from this address. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  login_v1_auth_login_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["LoginRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionResponse"];
        };
      };
      /** @description Unknown address or wrong password — deliberately indistinguishable. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
      /** @description Too many attempts. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  logout_v1_auth_logout_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  logout_everywhere_v1_auth_logout_everywhere_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  resend_verification_v1_auth_resend_verification_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            [key: string]: string;
          };
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  reset_password_endpoint_v1_auth_reset_password_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ResetPasswordRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            [key: string]: string;
          };
        };
      };
      /** @description Unknown, expired, or already-used link. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The password is too short, or a field is malformed. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  current_session_v1_auth_session_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionResponse"];
        };
      };
      /** @description No valid session. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  signup_v1_auth_signup_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SignupRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionResponse"];
        };
      };
      /** @description The email address already has an account. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The password is too short, or a field is malformed. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Too many signups from this address. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  verify_email_endpoint_v1_auth_verify_email_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["VerifyEmailRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionResponse"];
        };
      };
      /** @description Unknown, expired, already-used or superseded link. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  read_audit_log_v1_internal_audit_get: {
    parameters: {
      query?: {
        tenant_id?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AuditEntryResponse"][];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  verify_audit_log_v1_internal_audit_verify_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AuditVerification"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  evaluation_summary_v1_internal_operations_evaluation_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EvaluationSummary"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  pipeline_health_v1_internal_operations_pipeline_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PipelineHealth"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  queue_health_v1_internal_operations_queue_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["QueueHealth"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  slo_status_v1_internal_operations_slo_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SloStatus"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  model_spend_v1_internal_operations_spend_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ModelSpend"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  grant_staff_v1_internal_staff__user_id__post: {
    parameters: {
      query: {
        role: components["schemas"]["StaffRole"];
        /** @description Why this action is being taken. Recorded permanently. */
        reason: string;
      };
      header?: never;
      path: {
        user_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Requires the admin staff role. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  revoke_staff_v1_internal_staff__user_id__delete: {
    parameters: {
      query: {
        /** @description Why this action is being taken. Recorded permanently. */
        reason: string;
      };
      header?: never;
      path: {
        user_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Requires the admin staff role. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Not a staff member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  my_support_sessions_v1_internal_support_sessions_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SupportSessionResponse"][];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_tenants_v1_internal_tenants_get: {
    parameters: {
      query?: {
        search?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["StaffTenantSummary"][];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_tenant_v1_internal_tenants__tenant_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        tenant_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["StaffTenantDetail"];
        };
      };
      /** @description No such workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  inspect_subscription_v1_internal_tenants__tenant_id__subscription_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        tenant_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SubscriptionInspection"];
        };
      };
      /** @description No such workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  request_support_session_v1_internal_tenants__tenant_id__support_sessions_post: {
    parameters: {
      query: {
        /** @description Why this action is being taken. Recorded permanently. */
        reason: string;
      };
      header?: never;
      path: {
        tenant_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SupportSessionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SupportSessionResponse"];
        };
      };
      /** @description Requires a support or engineering role. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The requested duration is out of range. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  read_activity_under_support_v1_internal_tenants__tenant_id__support_activity_get: {
    parameters: {
      query?: {
        limit?: number;
      };
      header?: never;
      path: {
        tenant_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FactResponse"][];
        };
      };
      /** @description No approved, unexpired content session. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  accept_v1_invitations_accept_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AcceptInvitationRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["WorkspaceResponse"];
        };
      };
      /** @description Unknown, expired, superseded, or already-accepted invitation. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description A new account was required and the password is too short. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Too many attempts from this address. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  preview_v1_invitations_preview_get: {
    parameters: {
      query: {
        token: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["InvitationPreviewResponse"];
        };
      };
      /** @description Unknown, expired, superseded, or already-accepted invitation. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_workspace_v1_workspaces__workspace_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["WorkspaceResponse"];
        };
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_brief_v1_workspaces__workspace_id__brief_get: {
    parameters: {
      query?: {
        /** @description Start of the period. Defaults to 7 days ago. */
        since?: string | null;
        /** @description End of the period. Defaults to now. */
        until?: string | null;
      };
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BriefResponse"];
        };
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The requested period is inverted or too long. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Too many briefs generated for this workspace. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  list_briefs_v1_workspaces__workspace_id__briefs_get: {
    parameters: {
      query?: {
        limit?: number;
        /** @description The `nextCursor` from a previous page. */
        cursor?: string | null;
      };
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BriefArchive"];
        };
      };
      /** @description The pagination cursor could not be read. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_archived_brief_v1_workspaces__workspace_id__briefs__brief_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        brief_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BriefResponse"];
        };
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such brief in this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_facets_v1_workspaces__workspace_id__facets_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FacetsResponse"];
        };
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_facts_v1_workspaces__workspace_id__facts_get: {
    parameters: {
      query?: {
        /** @description Restrict to these fact kinds. Repeat the parameter to pass several. */
        kind?: components["schemas"]["FactKind"][] | null;
        /** @description Only facts concerning these people. Repeat to pass several. */
        person?: string[] | null;
        /** @description Only facts whose evidence names these projects. */
        project?: string[] | null;
        /** @description Only facts with evidence from these sources. */
        source?: string[] | null;
        /** @description Only activity that happened at or after this time. */
        since?: string | null;
        /** @description Only activity that happened at or before this time. */
        until?: string | null;
        /** @description Include facts that have been replaced. Off by default. */
        includeSuperseded?: boolean;
        limit?: number;
        /** @description The `nextCursor` from a previous page. */
        cursor?: string | null;
      };
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FactPage"];
        };
      };
      /** @description The pagination cursor could not be read. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  correct_v1_workspaces__workspace_id__facts__fact_id__correction_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        fact_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CorrectionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["CorrectionResponse"];
        };
      };
      /** @description That fact is not about you. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such fact in this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description That fact has already been superseded. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description A reworded correction needs the corrected sentence. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  list_integrations_v1_workspaces__workspace_id__integrations_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["IntegrationResponse"][];
        };
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  connect_github_v1_workspaces__workspace_id__integrations_github_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ConnectGitHubRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["GitHubInstallationResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description That installation is already connected elsewhere. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  disconnect_github_v1_workspaces__workspace_id__integrations_github__installation_id__delete: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        installation_id: number;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Requires permission to disconnect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such installation in this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_invitations_v1_workspaces__workspace_id__invitations_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["InvitationResponse"][];
        };
      };
      /** @description Requires permission to invite. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  create_invitation_v1_workspaces__workspace_id__invitations_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["InviteRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["InvitationResponse"];
        };
      };
      /** @description Requires permission to invite, or the role outranks yours. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description That address is already a member. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  revoke_invitation_v1_workspaces__workspace_id__invitations__invitation_id__delete: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        invitation_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Requires permission to invite. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such outstanding invitation. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  my_role_v1_workspaces__workspace_id__me_role_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["WorkRoleResponse"];
        };
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  set_my_role_v1_workspaces__workspace_id__me_role_put: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["WorkRoleUpdate"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["WorkRoleResponse"];
        };
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Not a role CAIRN knows. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  my_sources_v1_workspaces__workspace_id__me_sources_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ConsentResponse"];
        };
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  set_source_consent_v1_workspaces__workspace_id__me_sources_put: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ConsentUpdate"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ConsentUpdateResponse"];
        };
      };
      /** @description CAIRN has not linked any activity to your account yet. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Unknown source. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  my_week_v1_workspaces__workspace_id__me_week_get: {
    parameters: {
      query?: {
        /** @description Defaults to seven days ago. */
        since?: string | null;
        /** @description Defaults to now. */
        until?: string | null;
      };
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FactPage"];
        };
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_members_v1_workspaces__workspace_id__members_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MembershipResponse"][];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  remove_member_v1_workspaces__workspace_id__members__user_id__delete: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        user_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Requires permission to remove members. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such member of this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The removal would leave the workspace with no Owner. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  change_role_v1_workspaces__workspace_id__members__user_id__patch: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        user_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RoleUpdate"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MembershipResponse"];
        };
      };
      /** @description Requires permission to change roles. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such member of this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The change would leave no Owner, or is a self-demotion. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  notification_status_v1_workspaces__workspace_id__notifications_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["NotificationStatus"];
        };
      };
      /** @description Requires permission to change workspace settings. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_onboarding_v1_workspaces__workspace_id__onboarding_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["OnboardingResponse"];
        };
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_privacy_v1_workspaces__workspace_id__privacy_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PrivacySettings"];
        };
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  set_privacy_v1_workspaces__workspace_id__privacy_put: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["PrivacyUpdate"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PrivacySettings"];
        };
      };
      /** @description Requires permission to change workspace settings. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The retention period is outside the permitted range. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  search_facts_v1_workspaces__workspace_id__search_get: {
    parameters: {
      query: {
        /** @description What to look for. */
        q: string;
        kind?: components["schemas"]["FactKind"][] | null;
        person?: string[] | null;
        project?: string[] | null;
        source?: string[] | null;
        since?: string | null;
        until?: string | null;
        limit?: number;
      };
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SearchResults"];
        };
      };
      /** @description Requires permission to read content. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
      /** @description Too many searches for this workspace. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  list_support_sessions_v1_workspaces__workspace_id__support_sessions_get: {
    parameters: {
      query?: {
        limit?: number;
      };
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SupportSessionResponse"][];
        };
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  decide_support_session_v1_workspaces__workspace_id__support_sessions__session_id__decision_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SupportDecision"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SupportSessionResponse"];
        };
      };
      /** @description Requires permission to decide support access. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such request in this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The request has already been decided. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  revoke_support_session_v1_workspaces__workspace_id__support_sessions__session_id__revoke_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SupportSessionResponse"];
        };
      };
      /** @description Requires permission to decide support access. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such request in this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  trust_center_v1_workspaces__workspace_id__trust_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TrustCenter"];
        };
      };
      /** @description No such workspace, or you are not a member. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
}
