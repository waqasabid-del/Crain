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
  "/v1/integrations/google-chat/callback": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Finish connecting a Google Chat account
     * @description Where Google sends the customer back.
     *
     *     **Any ``error`` parameter is a failed install.** The callback branches on the
     *     *presence* of the parameter, never on the literal ``access_denied``: an
     *     equality check that missed would fall through to "exchange the code" with no
     *     code, and the customer would see a parse failure instead of "you declined".
     *     The value is read only to choose between "denied" and "error", and is then
     *     discarded.
     *
     *     The order of the checks is the security property. The state is claimed —
     *     atomically, single-use — *before* anything is exchanged, so a replayed
     *     callback fails on the second attempt whether or not the first one worked.
     *     Then the caller is proved to **still** be a member of the state's workspace
     *     **with permission to connect**: minutes passed, and in those minutes the
     *     person may have been removed or demoted, and an install that completes on a
     *     permission that no longer exists is one nobody currently authorised. Only
     *     then is the code sent to Google.
     *
     *     Redirects rather than returning JSON, because the thing following this URL is
     *     a browser mid-navigation, and the destination is built from
     *     ``public_app_url`` rather than from the request — the same rule as
     *     verification links, for the same reason.
     */
    get: operations["finish_install_v1_integrations_google_chat_callback_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/integrations/google-meet/callback": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Finish connecting a Google Meet account
     * @description Where Google sends the customer back.
     *
     *     **Any ``error`` parameter is a failed install.** The callback branches on the
     *     *presence* of the parameter, never on the literal ``access_denied``: an
     *     equality check that missed would fall through to "exchange the code" with no
     *     code, and the customer would see a parse failure instead of "you declined".
     *
     *     The order of the checks is the security property. The state is claimed —
     *     atomically, single-use — *before* anything is exchanged, so a replayed
     *     callback fails on the second attempt whether or not the first one worked.
     *
     *     **The workspace comes off the stored row and never from the request.** There
     *     is no ``workspace_id`` parameter on this route to trust, and adding one would
     *     let anybody who obtained a state bind an authorisation to a workspace of their
     *     choosing.
     *
     *     Then the caller is proved to **still** be a member of that workspace **with
     *     permission to connect**: minutes passed, and in those minutes the person may
     *     have been removed or demoted, and an install that completes on a permission
     *     that no longer exists is one nobody currently authorised. Only then is the
     *     code sent to Google.
     */
    get: operations["finish_install_v1_integrations_google_meet_callback_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/integrations/google-meet/transcript-callback": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Finish granting access to Google Meet transcripts
     * @description Where Google sends the customer back from the transcript consent screen.
     *
     *     **A separate path on a separate OAuth client**, so the two flows cannot
     *     redeem each other's authorisation codes — Google matches the redirect URI
     *     exactly, and a shared one would make the distinction depend on a branch rather
     *     than on the registration.
     *
     *     The same order as the connection callback, for the same reasons: any ``error``
     *     parameter is a refusal, the state is claimed atomically and single-use before
     *     anything is exchanged, the workspace comes off the stored row and never from
     *     the request, and the caller is proved to *still* be a member with permission
     *     before the code is sent to Google. `consume_state` is passed the transcript
     *     grant kind, so a state issued for "connect Google Meet" cannot be redeemed
     *     here.
     */
    get: operations["finish_transcript_access_v1_integrations_google_meet_transcript_callback_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/integrations/slack/callback": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Finish connecting a Slack workspace
     * @description Where Slack sends the customer back.
     *
     *     **Any ``error`` parameter is a failed install.** Slack's documentation does
     *     not state verbatim which value comes back when somebody presses Cancel, so
     *     this does not compare against the literal ``access_denied`` — an equality
     *     check that missed would fall through to "exchange the code" with no code, and
     *     the customer would see a parse failure instead of "you declined". Presence is
     *     the condition; the value is read for categorisation and then discarded.
     *
     *     The order of the checks is the security property. The state is claimed —
     *     atomically, single-use — *before* anything is exchanged, so a replayed
     *     callback fails on the second attempt whether or not the first one worked.
     *     Then the caller is proved to still be a member of the state's workspace with
     *     permission to connect, so a leaked state cannot be redeemed by anyone else.
     *     Only then is the code sent to Slack.
     *
     *     Redirects rather than returning JSON, because the thing following this URL is
     *     a browser mid-navigation, and the destination is built from
     *     ``public_app_url`` rather than from the request — the same rule as
     *     verification links, for the same reason.
     */
    get: operations["finish_install_v1_integrations_slack_callback_get"];
    put?: never;
    post?: never;
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
  "/v1/internal/operations/connectors": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Whether each source is delivering
     * @description Per-source health, answered without reading anything a source delivered.
     *
     *     Step 32 adds Slack and Google Chat, at which point "is ingestion working"
     *     stops being one number and becomes a per-provider question. The tempting way
     *     to answer it is to look at what came in; that is the one thing an operator
     *     may never do, so every figure here is a count, an age or a category from a
     *     closed set.
     *
     *     Platform-wide and naming no workspace, like the other operations surfaces.
     *     A per-workspace view of what a customer is producing is a support session's
     *     business, not a dashboard's.
     */
    get: operations["connector_health_v1_internal_operations_connectors_get"];
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
  "/v1/workspaces/{workspace_id}/attribution-health": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Whether attribution is working in this workspace
     * @description Counts, so an Owner can tell whether to ask members to confirm accounts.
     *
     *     **Owner and Admin, and counts only.** The gate is `WORKSPACE_SETTINGS`
     *     rather than a new permission because this is a fact about the workspace's
     *     configuration — how many source accounts have an owner — and inventing an
     *     `identities.view` permission would make *how much is visible about people* a
     *     function of role, which md/05 §B.3.3 and `permissions.py` both refuse.
     *
     *     The gate is therefore doing much less work than it looks like it is. What
     *     actually protects members is the return type: `attribution_health` groups by
     *     provider and state and never by person, so there is no name, no id, no
     *     address and no activity volume to withhold. An Admin reading this learns
     *     exactly one thing a member could not — a count — and md/15 §2.3's rule that
     *     an Admin may not see more *about a member* than the member sees is intact
     *     because nothing here is about a member at all.
     */
    get: operations["workspace_attribution_health_v1_workspaces__workspace_id__attribution_health_get"];
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
  "/v1/workspaces/{workspace_id}/integrations/google-chat/disconnect": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Disconnect Google Chat and destroy the stored credential
     * @description Stop collecting, tear the leases down, and drop the refresh token.
     *
     *     All three, in one call, with no option to do only the first. A disconnect
     *     that leaves the credential behind keeps CAIRN holding a standing grant to
     *     read a customer's conversations after they asked it to stop — and from
     *     outside there is no way to tell the two apart, which is exactly why the
     *     response says which happened.
     *
     *     The subscriptions are removed **before** the credential is destroyed, because
     *     deleting a lease at Google needs a token. Every space is blocked locally
     *     whether or not that succeeds: `remove_all_subscriptions` marks each row before
     *     it calls Google and does not stop on an error, and the connection state this
     *     handler then sets is itself what `spaces.is_space_permitted` refuses on. A
     *     lease that survives at Google therefore delivers into a workspace that will
     *     not read it, and lapses on its own inside four hours.
     *
     *     **The response tells the truth about retention.** Disconnecting stops new
     *     collection; it does not delete what was already recorded. Saying otherwise
     *     would be the shorter sentence and a false one.
     */
    post: operations["disconnect_google_chat_v1_workspaces__workspace_id__integrations_google_chat_disconnect_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-chat/install": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Begin connecting a Google Chat account
     * @description Issue a one-time state with its PKCE verifier, and return the authorise URL.
     *
     *     Returns the URL rather than redirecting. The caller is a browser application
     *     doing this from an admin screen, and a 302 out of an XHR is either followed
     *     invisibly or blocked — neither of which lets the interface warn about the
     *     "add the app to the space" step before the customer is standing on Google's
     *     consent screen.
     *
     *     Runs on the platform connection because ``google_chat_oauth_states`` is
     *     deliberately unreachable from the application role: the callback has to read
     *     the row with no tenant context to scope to, so every statement against that
     *     table is platform-side and the grant set says so.
     */
    post: operations["begin_install_v1_workspaces__workspace_id__integrations_google_chat_install_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-chat/spaces": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List the Google Chat spaces CAIRN could read
     * @description The picker's contents: every eligible named space, and the state of its feed.
     *
     *     Gated on `INTEGRATIONS_CONNECT` — Owner and Admin — rather than on plain
     *     membership. This is the one endpoint in the API that returns Google Chat
     *     space **display names**, and the people who may see the list are the people
     *     who may change what CAIRN reads. A Member gains nothing from a list they
     *     cannot act on, and a space name is frequently the most sensitive string a
     *     customer holds.
     *
     *     Direct messages, one-to-one app conversations and unnamed spaces never reach
     *     this response: `spaces.eligible_spaces` removes them, in addition to the
     *     server-side filter Google is asked for. Two filters rather than one, because
     *     a picker that offered a direct message would not be noticed until somebody
     *     selected it.
     */
    get: operations["list_spaces_v1_workspaces__workspace_id__integrations_google_chat_spaces_get"];
    /**
     * Choose which Google Chat spaces CAIRN may process
     * @description Replace the selection with exactly these spaces, and move the subscriptions.
     *
     *     ``PUT`` rather than ``POST``, and a replace rather than a merge, because the
     *     body is the full state of a set of checkboxes. A merge would make unchecking
     *     a box do nothing — and the box being unchecked is somebody withdrawing
     *     permission for CAIRN to read a conversation, which is the single operation on
     *     this endpoint that must not silently fail.
     *
     *     An empty list is valid and means "process nothing", which is also the state a
     *     freshly connected account is in.
     *
     *     **This is where the subscription lifecycle is driven from.** Selecting a space
     *     creates a Workspace Events lease; deselecting deletes the selection row —
     *     which blocks ingestion the moment it lands — and then tears the lease down.
     *     The commit happens after both, so a caller that receives 200 has had every
     *     removal persisted.
     */
    put: operations["save_spaces_v1_workspaces__workspace_id__integrations_google_chat_spaces_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-meet/disconnect": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Disconnect Google Meet and destroy the stored credential
     * @description Stop watching, tear the leases down, and drop the refresh token.
     *
     *     All three, in one call, with no option to do only the first. A disconnect that
     *     leaves the credential behind keeps CAIRN holding a standing grant after the
     *     customer asked it to stop, and from outside there is no way to tell the two
     *     apart — which is exactly why the response says which happened.
     *
     *     The subscriptions are removed **before** the credential is destroyed, because
     *     deleting a lease at Google needs a token. Every meeting is blocked locally
     *     whether or not that succeeds: `remove_all_subscriptions` marks each row before
     *     it calls Google and does not stop on an error, and the receiver refuses a
     *     delivery whose connection is not active. A lease that survives at Google
     *     therefore delivers into a workspace that will not record it, and lapses on its
     *     own because nothing renews it.
     *
     *     **The response tells the truth about retention.** Disconnecting stops new
     *     collection; it does not delete what was already recorded.
     */
    post: operations["disconnect_google_meet_v1_workspaces__workspace_id__integrations_google_meet_disconnect_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-meet/install": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Begin connecting a Google Meet account
     * @description Issue a one-time state with its PKCE verifier, and return the authorise URL.
     *
     *     Returns the URL rather than redirecting. The caller is a browser application
     *     doing this from an admin screen, and a 302 out of an XHR is either followed
     *     invisibly or blocked — neither of which lets the interface state
     *     :data:`CONNECT_NOTICE` before the customer is standing on Google's consent
     *     screen.
     *
     *     Runs on the platform connection because ``google_meet_oauth_states`` is
     *     deliberately unreachable from the application role: the callback has to read
     *     the row with no tenant context to scope to, so every statement against that
     *     table is platform-side and the grant set says so.
     */
    post: operations["begin_install_v1_workspaces__workspace_id__integrations_google_meet_install_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-meet/status": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Whether Meet is connected, and what its subscriptions are doing
     * @description The one word a screen shows, decided here rather than in a browser.
     *
     *     **200 with `connected: false` rather than a 404.** "Not connected" is the
     *     ordinary state of this connector in almost every workspace, and a screen that
     *     has to catch an error to render its most common case will eventually render
     *     an error instead.
     *
     *     The status word is composed server-side on purpose. A client that derived
     *     "expiring" from a date would be deciding what the renewal window is, and two
     *     clients would eventually decide differently — the window belongs to the code
     *     that does the renewing.
     *
     *     Carries no meeting reference (for Meet that is the joining code), no title —
     *     none is stored — and no participant.
     */
    get: operations["meet_status_v1_workspaces__workspace_id__integrations_google_meet_status_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-meet/transcript-access": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Begin granting CAIRN access to Google Meet transcripts
     * @description Issue a state for the **transcript** grant, and return its authorise URL.
     *
     *     A separate route rather than a parameter on the install route, and that is the
     *     design rather than an accident of layout. ``drive.meet.readonly`` is a
     *     restricted scope that lets CAIRN read the file the platform produced; folding
     *     it into "connect Google Meet" would mean a workspace acquiring artifact access
     *     by pressing a button labelled something else. Connecting and granting
     *     transcript access are two decisions, so they are two clicks, two OAuth
     *     clients, two consent screens and two rows.
     *
     *     Requires an existing, live Meet connection: transcript access with nothing to
     *     apply it to is a restricted-scope grant held for no reason.
     */
    post: operations["begin_transcript_access_v1_workspaces__workspace_id__integrations_google_meet_transcript_access_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-meet/transcript-access/revoke": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Withdraw CAIRN's access to Google Meet transcripts
     * @description Stop retrieving transcripts, and destroy the credential that could.
     *
     *     **Narrower than disconnecting, deliberately.** The Meet connection keeps
     *     working, the subscriptions keep running, and CAIRN goes back to recording only
     *     that a transcript exists. Somebody who decides transcript retrieval was a step
     *     too far should not have to tear down the whole connector to undo it.
     *
     *     Idempotent: revoking access nobody granted answers the same way, because from
     *     the caller's side "we do not have it" is one fact.
     */
    post: operations["revoke_transcript_access_v1_workspaces__workspace_id__integrations_google_meet_transcript_access_revoke_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/google-meet/transcripts": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Which meetings produced a transcript, and what happened to it
     * @description Availability and status. **There is no route that returns a transcript.**
     *
     *     What a workspace can see here: that a meeting they all consented to produced a
     *     transcript, whether CAIRN retrieved it, how large it was, when it will be
     *     deleted, and — when it was refused — a reason from a vocabulary CAIRN wrote
     *     that names nobody.
     *
     *     What it cannot see: a line of it. Making transcripts readable is a product
     *     decision with its own consent conversation, and shipping it as a side effect
     *     of shipping retrieval would be making that decision on everybody's behalf.
     */
    get: operations["list_transcripts_v1_workspaces__workspace_id__integrations_google_meet_transcripts_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/slack/channels": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List public channels CAIRN could read
     * @description The picker's contents: every non-archived public channel, and its state.
     *
     *     Gated on `INTEGRATIONS_CONNECT` — Owner and Admin — rather than on plain
     *     membership. This is the one endpoint in the API that returns Slack channel
     *     names, and the people who may see the list are the people who may change what
     *     CAIRN reads. A Member gains nothing from a list they cannot act on.
     *
     *     ``bot_is_member`` is carried through untouched because it is the field that
     *     makes the screen honest: selecting a channel the app has not been invited to
     *     produces a permission that delivers nothing, forever, with no error anywhere.
     */
    get: operations["list_channels_v1_workspaces__workspace_id__integrations_slack_channels_get"];
    /**
     * Choose which public channels CAIRN may process
     * @description Replace the selection with exactly these channels.
     *
     *     ``PUT`` rather than ``POST``, and a replace rather than a merge, because the
     *     body is the full state of a set of checkboxes. A merge would make unchecking
     *     a box do nothing — and the box being unchecked is somebody withdrawing
     *     permission for CAIRN to read a conversation, which is the single operation on
     *     this endpoint that must not silently fail.
     *
     *     An empty list is valid and means "process nothing", which is also the state a
     *     freshly connected workspace is in.
     *
     *     Runs on the tenant-scoped session: the application role holds SELECT, INSERT
     *     and DELETE here precisely because these writes happen from inside a
     *     workspace, where the policy's WITH CHECK stops a row being written for
     *     anybody else.
     */
    put: operations["save_channels_v1_workspaces__workspace_id__integrations_slack_channels_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/slack/disconnect": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Disconnect Slack and destroy the stored credential
     * @description Stop collecting, and drop the bot token.
     *
     *     Both, in one call, with no option to do only the first. A disconnect that
     *     leaves the credential behind keeps CAIRN holding a live grant to read a
     *     customer's conversations after they asked it to stop — and from outside there
     *     is no way to tell the two apart, which is exactly why the response says which
     *     happened.
     *
     *     Runs on the platform connection because the application role holds SELECT
     *     only on ``source_connections``.
     *
     *     **The response tells the truth about retention.** Disconnecting stops new
     *     collection; it does not delete what was already recorded. Saying otherwise
     *     would be the shorter sentence and a false one, and a product whose deletion
     *     claims are approximate is one whose deletion claims are worthless.
     */
    post: operations["disconnect_slack_v1_workspaces__workspace_id__integrations_slack_disconnect_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/integrations/slack/install": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Begin connecting a Slack workspace
     * @description Issue a one-time state and return the authorise URL.
     *
     *     Returns the URL rather than redirecting. The caller is a browser application
     *     doing this from a settings screen, and a 302 out of an XHR is either followed
     *     invisibly or blocked — neither of which lets the interface warn about the
     *     ``/invite`` step before the customer is standing on Slack's consent screen.
     *
     *     Runs on the platform connection because ``slack_oauth_states`` is
     *     deliberately unreachable from the application role: the callback has to read
     *     the row with no tenant context to scope to, so every statement against that
     *     table is platform-side and the grant set says so.
     */
    post: operations["begin_install_v1_workspaces__workspace_id__integrations_slack_install_post"];
    delete?: never;
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
  "/v1/workspaces/{workspace_id}/me/capacity": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /**
     * State your own availability, or withdraw the statement
     * @description Self-declared capacity: the person states it, everybody sees it.
     *
     *     **Self only, by construction rather than by a check** - the same shape as
     *     the work-role endpoint above. The person is resolved from the caller's own
     *     session; no parameter exists through which a target could be named, so an
     *     Owner with every permission still cannot set a colleague's capacity.
     *     Nothing anywhere computes this value: availability inferred from activity
     *     would be monitoring wearing a helpful face, and `PersonCapacity`'s
     *     docstring records why there is no history table either.
     */
    put: operations["set_my_capacity_v1_workspaces__workspace_id__me_capacity_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/me/identities": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Which source accounts CAIRN believes are yours
     * @description The caller's own links, the caller's own proposals, and the rule.
     *
     *     **`proposals` is not a menu of unclaimed accounts, and must never become
     *     one.** It returns only the `PROPOSED` rows of the existing `identities`
     *     table that are *already attached to the caller's own `Person`* — identifiers
     *     CAIRN inferred were theirs and is showing them so they can correct it.
     *
     *     Listing the workspace's *unresolved* provider accounts here is the thing
     *     this whole step exists to prevent. Handing every member a list of
     *     colleagues' unclaimed accounts next to a "that's me" button is the
     *     claim-a-colleague attack served as a feature: the second person to look at
     *     the list takes whatever the first has not claimed, the link is recorded as
     *     `SELF_CONFIRMED`, and from then on somebody else's work is in their record
     *     with CAIRN's own evidence field vouching for it. The exclusive index would
     *     not stop it — it only decides who gets there first. So the query is scoped
     *     to `Person.user_id == caller` and there is no parameter, no filter and no
     *     flag that widens it.
     *
     *     **Ended links are shown.** A person is entitled to see that an account was
     *     once attributed to them and no longer is — hiding it makes the record less
     *     checkable at exactly the moment somebody is checking it.
     */
    get: operations["my_identities_v1_workspaces__workspace_id__me_identities_get"];
    put?: never;
    /**
     * Confirm a source account is yours
     * @description Record that the caller owns a provider account.
     *
     *     **Self only, by construction rather than by a check.** The `Person` written
     *     is the one the caller's own session resolved to; the request body has no
     *     subject field, and there is no second route that takes one. That absence is
     *     the design — an Owner who could confirm a colleague's account would be
     *     writing evidence, in CAIRN's own words, that a member's work belongs to
     *     whoever the Owner chose.
     *
     *     **No permission is declared**, and requiring one would be the wrong axis.
     *     Every role including Viewer may answer a question about themselves, and
     *     making that a grant would mean a person's own account was something the
     *     workspace let them have.
     *
     *     Idempotent when the account is already theirs: confirming twice is a
     *     double-click, not a second claim.
     *
     *     Refused with 409 when somebody else holds the account, and the refusal names
     *     nobody. Which colleague holds an account is not the asker's to know — saying
     *     so would turn this endpoint into an oracle for mapping accounts to people.
     */
    post: operations["confirm_identity_v1_workspaces__workspace_id__me_identities_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/me/identities/{identity_id}/revoke": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Stop attributing one of your source accounts to you
     * @description End a link, keeping the row and its evidence.
     *
     *     **Only the caller's own links.** The lookup is filtered by the caller's
     *     `Person`, so another member's link is a 404 rather than a permission error —
     *     from outside, a link that is not yours is indistinguishable from one that
     *     does not exist, which is also what row-level security gives us across
     *     workspaces.
     *
     *     Nothing is deleted. The row, its verification method, when it was linked and
     *     why it ended all survive, and so does every fact the link ever produced —
     *     facts carry the provider actor id recorded at ingestion, which was never
     *     derived from this table and is not rewritten now.
     *
     *     Idempotent: an already-ended link is returned unchanged rather than
     *     erroring. Re-stamping the timestamp would move the moment attribution
     *     actually stopped, which is the one thing the row exists to record.
     */
    post: operations["revoke_identity_v1_workspaces__workspace_id__me_identities__identity_id__revoke_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/me/meeting-requests": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Meetings you have been asked about
     * @description The caller's own invitations to answer, and nobody else's.
     *
     *     **Self only by construction rather than by a check.** The person is resolved
     *     from the caller's session; there is no subject parameter, no filter and no
     *     flag that widens it, so no role has a route through which to read what a
     *     colleague was asked or how they answered.
     *
     *     **No permission is declared**, and requiring one would be the wrong axis.
     *     Every role including Viewer may answer a question about their own presence in
     *     a meeting, and making that a grant would mean a person's own consent was
     *     something the workspace let them have.
     */
    get: operations["my_meeting_requests_v1_workspaces__workspace_id__me_meeting_requests_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/me/meeting-requests/{meeting_id}/decision": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Agree, refuse, or take your agreement back
     * @description Record the caller's own answer, and recompute what it makes possible.
     *
     *     **The only route in the product that writes a consent decision.** The user id
     *     stored in `decided_by_user_id` is the one the session cookie resolved to, and
     *     the body has no field that could name anybody else — so an administrator
     *     calling this records their own answer to their own invitation, or gets a 404.
     *
     *     **404, not 403, for a decision that is not the caller's.** Whether a meeting
     *     exists is not a non-participant's to confirm, and a 403 would confirm it —
     *     turning this into a way of discovering which colleagues are in a meeting
     *     somebody asked to capture.
     *
     *     **Append-only.** Changing your mind supersedes the previous row and inserts a
     *     new one; nothing is updated in place and nothing is deleted, because the
     *     history is the product's only evidence that withdrawal was possible and
     *     honoured.
     */
    post: operations["decide_meeting_request_v1_workspaces__workspace_id__me_meeting_requests__meeting_id__decision_post"];
    delete?: never;
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
  "/v1/workspaces/{workspace_id}/meetings/capture-requests": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Capture requests in this workspace, and where they stand
     * @description The list and the totals, with no per-person answer anywhere in either.
     *
     *     Read-only, including the eligibility it reports: the gate is consulted for
     *     display and nothing is written, so opening this screen cannot change what
     *     CAIRN believes it is allowed to do.
     */
    get: operations["list_capture_requests_v1_workspaces__workspace_id__meetings_capture_requests_get"];
    put?: never;
    /**
     * Ask everybody in a meeting whether CAIRN may collect it
     * @description Create the question. It grants nothing.
     *
     *     The request lands `pending` with no consent rows at all, and stays there
     *     until every expected participant has affirmatively agreed from their own
     *     session. Silence never ages into agreement, so a request created and then
     *     forgotten collects nothing, forever.
     *
     *     Gated on `WORKSPACE_SETTINGS` (Owner and Admin) because *asking* is a
     *     configuration action. What that gate emphatically does not confer is any
     *     ability to answer — see the module docstring.
     */
    post: operations["create_capture_request_v1_workspaces__workspace_id__meetings_capture_requests_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/workspaces/{workspace_id}/meetings/capture-requests/{meeting_id}/cancel": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Call off a capture request
     * @description Withdraw the question.
     *
     *     Only an open request can be cancelled. A refused one is already closed, and
     *     cancelling it would replace "somebody said no" with a tidier word — the
     *     record has to keep saying refused, because that is what the product may later
     *     have to demonstrate it honoured.
     */
    post: operations["cancel_capture_request_v1_workspaces__workspace_id__meetings_capture_requests__meeting_id__cancel_post"];
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
  "/v1/workspaces/{workspace_id}/related-work": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Find who has worked on related things, with evidence
     * @description See the module docstring for everything this refuses to be.
     *
     *     The topic is deliberately not logged: it is free text about somebody's
     *     work, and the telemetry allow-list has no slot for it. The count is
     *     observable; the words are not.
     */
    get: operations["find_related_work_v1_workspaces__workspace_id__related_work_get"];
    put?: never;
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
     * AttributionHealthResponse
     * @description Whether attribution is working here, in counts and nothing else.
     *
     *     **No per-person figures, by construction.** There is no field here that
     *     could carry a name, an id, an address or a volume of activity. md/05 §B.3.3
     *     makes a per-person breakdown a product-reclassifying feature, and md/15
     *     §2.3 says an Admin may not see more about a member than the member sees —
     *     so an "unresolved by person" list is a leaderboard with the ranking left as
     *     an exercise for the reader.
     */
    AttributionHealthResponse: {
      /** Disputed */
      disputed: number;
      /** Notice */
      notice: string;
      /** Resolvedbyprovider */
      resolvedByProvider?: {
        [key: string]: number;
      };
      /** Revoked */
      revoked: number;
      /** Unresolvedbyprovider */
      unresolvedByProvider?: {
        [key: string]: number;
      };
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
      /**
       * Resolvedactors
       * @default 0
       */
      resolvedActors: number;
      /** Text */
      text: string;
      /**
       * Unresolvedactors
       * @default 0
       */
      unresolvedActors: number;
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
    /** CapacityResponse */
    CapacityResponse: {
      /** Capacity */
      capacity: string;
      /** Capacitystatedat */
      capacityStatedAt?: string | null;
    };
    /**
     * CapacityUpdate
     * @description The person's own statement about their availability. Only theirs.
     */
    CapacityUpdate: {
      /** Capacity */
      capacity: string;
    };
    /**
     * CaptureState
     * @description Where a capture request stands.
     *
     *     `ELIGIBLE` is computed, never asserted: it is written only by the gate, and
     *     only when every currently expected participant holds a live acceptance for
     *     the current policy version. Nothing else in the product may set it.
     * @enum {string}
     */
    CaptureState: "pending" | "eligible" | "refused" | "expired" | "cancelled" | "completed";
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
     * ConfirmIdentityRequest
     * @description A person saying an account is theirs, from an authenticated session.
     *
     *     **No subject field, deliberately.** The person is resolved from the session,
     *     so there is nothing here for an administrator to point at a colleague. An
     *     Owner claiming a member's account would override the one thing md/05 §B.2.3
     *     says cannot be overridden — that the record is the person's own.
     */
    ConfirmIdentityRequest: {
      provider: components["schemas"]["ConnectorProvider"];
      /** Provideraccountid */
      providerAccountId: string;
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
     * ConnectorFleetView
     * @description Every source at one moment, and the numbers worth alerting on.
     */
    ConnectorFleetView: {
      /**
       * Measuredat
       * Format: date-time
       */
      measuredAt: string;
      /** Oldestunsuccessfulsyncminutes */
      oldestUnsuccessfulSyncMinutes?: number | null;
      /** Providers */
      providers?: components["schemas"]["ConnectorHealthView"][];
      /**
       * Providersconfiguredbutunverified
       * @default 0
       */
      providersConfiguredButUnverified: number;
      subscriptions?: components["schemas"]["SubscriptionHealthView"] | null;
      /**
       * Workspacesfailing
       * @default 0
       */
      workspacesFailing: number;
      /**
       * Workspacesinerror
       * @default 0
       */
      workspacesInError: number;
    };
    /**
     * ConnectorHealthView
     * @description One source, as far as it can be seen without reading what it carried.
     *
     *     Every field is a count, an age, a flag, or a mapping keyed by a closed enum.
     *     There is nowhere here to put a channel name, a message, a repository or a
     *     person — reaching any of those needs the consent-gated support session in
     *     md/15 §5.2, never an operations screen.
     */
    ConnectorHealthView: {
      /** Credentialsconfigured */
      credentialsConfigured: boolean;
      /** Deliverieslasthour */
      deliveriesLastHour?: number | null;
      /** Deliveriestotal */
      deliveriesTotal?: number | null;
      /** Deliveriesunobservablereason */
      deliveriesUnobservableReason?: string | null;
      /** Errorsbycategory */
      errorsByCategory?: {
        [key: string]: number;
      };
      /** Failureslasthour */
      failuresLastHour?: number | null;
      /**
       * Inboundverified
       * @default false
       */
      inboundVerified: boolean;
      /** Oldestunsuccessfulsyncminutes */
      oldestUnsuccessfulSyncMinutes?: number | null;
      /** Provider */
      provider: string;
      /** Workspacesbyhealth */
      workspacesByHealth?: {
        [key: string]: number;
      };
      /** Workspacesbystate */
      workspacesByState?: {
        [key: string]: number;
      };
      /** Workspacesconnected */
      workspacesConnected: number;
      /** Workspaceseversynced */
      workspacesEverSynced: number;
    };
    /**
     * ConnectorProvider
     * @description Which system a connection reaches.
     *
     *     Closed, because a provider is not a label: each value implies a webhook
     *     verifier, an identity resolver and a retention rule. A free string would let
     *     a typo create a connection nothing on the ingestion side can service, and it
     *     would look connected in the UI.
     * @enum {string}
     */
    ConnectorProvider: "github" | "slack" | "google_chat" | "google_meet";
    /**
     * ConsentDecision
     * @description One person's answer.
     *
     *     There is no `assumed`, `implied`, `inherited` or `default` member, and no
     *     boolean that could be initialised to true. Silence is `PENDING` forever —
     *     it never ages into agreement.
     * @enum {string}
     */
    ConsentDecision: "pending" | "accepted" | "declined" | "withdrawn" | "expired";
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
     * ExternalIdentityResponse
     * @description One provider account bound to the reader, with how CAIRN knows.
     *
     *     Returned only for the caller's own person. There is no variant of this model
     *     carrying somebody else's link, and no route that would produce one.
     */
    ExternalIdentityResponse: {
      /** Explanation */
      explanation: string;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /**
       * Linkedat
       * Format: date-time
       */
      linkedAt: string;
      provider: components["schemas"]["ConnectorProvider"];
      /** Provideraccountid */
      providerAccountId: string;
      /** Revokedat */
      revokedAt?: string | null;
      /** Revokedreason */
      revokedReason?: string | null;
      state: components["schemas"]["IdentityLinkState"];
      verification: components["schemas"]["IdentityVerification"];
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
      /**
       * Resolvedactors
       * @default 0
       */
      resolvedActors: number;
      /** Sources */
      sources?: components["schemas"]["FactSourceResponse"][];
      /** Statement */
      statement: string;
      /** Supersededbyid */
      supersededById?: string | null;
      /** Supersessionreason */
      supersessionReason?: string | null;
      /**
       * Unresolvedactors
       * @default 0
       */
      unresolvedActors: number;
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
    /**
     * GoogleChatDisconnectResponse
     * @description What disconnecting did, stated precisely enough to be trusted.
     */
    GoogleChatDisconnectResponse: {
      /** Credentialcleared */
      credentialCleared: boolean;
      /**
       * Disconnectedat
       * Format: date-time
       */
      disconnectedAt: string;
      /** Retentionnotice */
      retentionNotice: string;
      /** State */
      state: string;
    };
    /**
     * GoogleChatInstallResponse
     * @description Where to send the customer, and what they need to know first.
     */
    GoogleChatInstallResponse: {
      /** Authorizeurl */
      authorizeUrl: string;
      /**
       * Expiresat
       * Format: date-time
       */
      expiresAt: string;
      /** Notice */
      notice: string;
    };
    /**
     * GoogleChatSpaceListResponse
     * @description The picker's contents. Eligible spaces only.
     */
    GoogleChatSpaceListResponse: {
      /** Notice */
      notice: string;
      /** Spaces */
      spaces?: components["schemas"]["GoogleChatSpaceResponse"][];
    };
    /**
     * GoogleChatSpaceResponse
     * @description One space the workspace could select, and the state of its feed.
     */
    GoogleChatSpaceResponse: {
      /** Displayname */
      displayName: string;
      /** Eligible */
      eligible: boolean;
      /** Errorcategory */
      errorCategory?: string | null;
      /** Expiretime */
      expireTime?: string | null;
      /** Name */
      name: string;
      /** Selected */
      selected: boolean;
      /** Subscriptionstate */
      subscriptionState?: string | null;
    };
    /**
     * GoogleChatSpaceSelectionRequest
     * @description The full state of the picker, not a delta.
     *
     *     A replace rather than a merge: unchecking a box has to mean something, and
     *     the something it means is withdrawing permission to read a conversation.
     */
    GoogleChatSpaceSelectionRequest: {
      /** Spacenames */
      spaceNames?: string[];
    };
    /**
     * GoogleChatSpaceSelectionResponse
     * @description What CAIRN may now process. Resource names only — deliberately no names.
     */
    GoogleChatSpaceSelectionResponse: {
      /** Notice */
      notice: string;
      /** Spacenames */
      spaceNames?: string[];
    };
    /**
     * GoogleMeetDisconnectResponse
     * @description What disconnecting did, stated precisely enough to be trusted.
     */
    GoogleMeetDisconnectResponse: {
      /** Credentialcleared */
      credentialCleared: boolean;
      /**
       * Disconnectedat
       * Format: date-time
       */
      disconnectedAt: string;
      /** Retentionnotice */
      retentionNotice: string;
      /** State */
      state: string;
      /** Subscriptionsremoved */
      subscriptionsRemoved: number;
    };
    /**
     * GoogleMeetInstallResponse
     * @description Where to send the customer, and what connecting does and does not do.
     */
    GoogleMeetInstallResponse: {
      /** Authorizeurl */
      authorizeUrl: string;
      /**
       * Expiresat
       * Format: date-time
       */
      expiresAt: string;
      /** Notice */
      notice: string;
    };
    /**
     * GoogleMeetStatusResponse
     * @description Whether Meet is connected, and what its subscriptions are doing.
     *
     *     **Counts and states only.** There is no meeting reference here (for Meet that
     *     is the joining code, and a joining code is a credential), no meeting title —
     *     none is stored — and no participant. A workspace screen answering "is this
     *     working?" needs a shape and a date; it does not need to name a conversation.
     *
     *     Every field is optional-by-absence rather than defaulted: a connector that
     *     cannot say something omits it, and the screen renders nothing. A zero here
     *     would read as "no subscriptions are expiring", which is a different claim
     *     from "CAIRN cannot tell you".
     */
    GoogleMeetStatusResponse: {
      /** Connected */
      connected: boolean;
      /** Nearestexpiry */
      nearestExpiry?: string | null;
      /** Status */
      status: string;
      /** Subscriptionsbystate */
      subscriptionsByState?: {
        [key: string]: number;
      };
      /**
       * Transcriptaccessgranted
       * @default false
       */
      transcriptAccessGranted: boolean;
    };
    /**
     * GoogleMeetTranscriptAccessResponse
     * @description Where to send the customer for the **separate** transcript permission.
     */
    GoogleMeetTranscriptAccessResponse: {
      /** Authorizeurl */
      authorizeUrl: string;
      /**
       * Expiresat
       * Format: date-time
       */
      expiresAt: string;
      /** Notice */
      notice: string;
    };
    /**
     * GoogleMeetTranscriptAccessStateResponse
     * @description Whether this workspace has granted transcript access, and what that means.
     */
    GoogleMeetTranscriptAccessStateResponse: {
      /** Granted */
      granted: boolean;
      /** Grantedat */
      grantedAt?: string | null;
      /** Notice */
      notice: string;
      /** Revokedat */
      revokedAt?: string | null;
    };
    /**
     * GoogleMeetTranscriptListResponse
     * @description This workspace's transcript availability. Status only, by construction.
     */
    GoogleMeetTranscriptListResponse: {
      /** Notice */
      notice: string;
      /** Transcriptaccessgranted */
      transcriptAccessGranted: boolean;
      /** Transcripts */
      transcripts: components["schemas"]["GoogleMeetTranscriptStatus"][];
    };
    /**
     * GoogleMeetTranscriptStatus
     * @description One announced transcript, as far as a customer may see it.
     */
    GoogleMeetTranscriptStatus: {
      /**
       * Announcedat
       * Format: date-time
       */
      announcedAt: string;
      /**
       * Artifactid
       * Format: uuid
       */
      artifactId: string;
      /** Contentbytes */
      contentBytes?: number | null;
      /** Contentheld */
      contentHeld: boolean;
      /** Errorcategory */
      errorCategory?: string | null;
      /** Generatedat */
      generatedAt?: string | null;
      /**
       * Meetingid
       * Format: uuid
       */
      meetingId: string;
      /** Refusalreason */
      refusalReason?: string | null;
      /** Retentionexpiresat */
      retentionExpiresAt?: string | null;
      /** Retrievedat */
      retrievedAt?: string | null;
      /** State */
      state: string;
      /** Withdrawnat */
      withdrawnAt?: string | null;
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
     * IdentityKind
     * @description What sort of identifier a claim carries.
     * @enum {string}
     */
    IdentityKind: "email" | "github_login";
    /**
     * IdentityLinkState
     * @description Where this link stands now.
     *
     *     Deliberately not a boolean. "Linked / not linked" cannot distinguish an
     *     account nobody has claimed from one somebody withdrew, and those need
     *     different words on screen and different behaviour in the pipeline.
     * @enum {string}
     */
    IdentityLinkState: "active" | "revoked" | "disputed";
    /**
     * IdentityProposalResponse
     * @description An identifier CAIRN already attached to the reader by inference.
     *
     *     The reader's own `identities` rows in `PROPOSED` state, and nothing else.
     *     This is deliberately *not* a list of unclaimed accounts in the workspace —
     *     see the route docstring for why that list must never exist.
     */
    IdentityProposalResponse: {
      kind: components["schemas"]["IdentityKind"];
      /** Value */
      value: string;
    };
    /**
     * IdentityVerification
     * @description How CAIRN came to believe this account belongs to this person.
     *
     *     Stored rather than inferred, because "how do you know?" is the question the
     *     Trust Center has to answer in the person's own words, and reconstructing it
     *     later from timestamps would be a guess about a guess.
     * @enum {string}
     */
    IdentityVerification: "verified_email_match" | "self_confirmed";
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
      /** Authorisedby */
      authorisedBy?: string | null;
      /**
       * Connectedat
       * Format: date-time
       */
      connectedAt: string;
      /** Disconnectedat */
      disconnectedAt?: string | null;
      /** Health */
      health?: string | null;
      /** Installationid */
      installationId: number;
      /** Lastsuccessfulsyncat */
      lastSuccessfulSyncAt?: string | null;
      /** Revokedat */
      revokedAt?: string | null;
      /** Scopes */
      scopes?: string[];
      /** Source */
      source: string;
      /**
       * Suspended
       * @default false
       */
      suspended: boolean;
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
     * MeetingCaptureCreateRequest
     * @description Ask a named set of people whether one meeting may be collected.
     *
     *     **There is no consent field, and there is no route that adds one.** An
     *     administrator names who would be in the meeting; every one of those people
     *     then answers for themselves from their own session. `extra="forbid"` means a
     *     client that invents `consented` or `approvedBy` is rejected rather than
     *     quietly ignored.
     */
    MeetingCaptureCreateRequest: {
      /** Externalmeetingref */
      externalMeetingRef: string;
      /** Participantpersonids */
      participantPersonIds: string[];
      provider: components["schemas"]["MeetingProvider"];
      /** Purpose */
      purpose: string;
      /**
       * Scheduledend
       * Format: date-time
       */
      scheduledEnd: string;
      /**
       * Scheduledstart
       * Format: date-time
       */
      scheduledStart: string;
    };
    /**
     * MeetingCaptureListResponse
     * @description Every capture request in the workspace, plus the totals.
     */
    MeetingCaptureListResponse: {
      /** Notice */
      notice: string;
      /** Requests */
      requests?: components["schemas"]["MeetingCaptureResponse"][];
      totals: components["schemas"]["MeetingStateCounts"];
    };
    /**
     * MeetingCaptureResponse
     * @description One capture request, as the workspace that asked for it may see it.
     */
    MeetingCaptureResponse: {
      /** Acceptedcount */
      acceptedCount?: number | null;
      /** Eligible */
      eligible: boolean;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Message */
      message: string;
      /** Participantcount */
      participantCount: number;
      /** Policyversion */
      policyVersion: string;
      provider: components["schemas"]["MeetingProvider"];
      /** Purpose */
      purpose: string;
      reason: components["schemas"]["ReasonCode"];
      /**
       * Requestedat
       * Format: date-time
       */
      requestedAt: string;
      /**
       * Scheduledend
       * Format: date-time
       */
      scheduledEnd: string;
      /**
       * Scheduledstart
       * Format: date-time
       */
      scheduledStart: string;
      state: components["schemas"]["CaptureState"];
    };
    /**
     * MeetingDecisionChoice
     * @description What a participant may say about their own capture request.
     *
     *     Deliberately not `ConsentDecision`. That enum also has `PENDING`, which is
     *     the *absence* of an answer, and `EXPIRED`, which is a conclusion the
     *     eligibility gate reaches — neither is something a person can assert about
     *     themselves, so neither is on the wire.
     * @enum {string}
     */
    MeetingDecisionChoice: "accepted" | "declined" | "withdrawn";
    /**
     * MeetingDecisionRequest
     * @description One person's own answer. Carries no subject, by design.
     */
    MeetingDecisionRequest: {
      decision: components["schemas"]["MeetingDecisionChoice"];
    };
    /**
     * MeetingProvider
     * @description Which platform produced the meeting.
     *
     *     Declared now and implemented later, so the column, its CHECK constraint and
     *     the eligibility gate exist before any provider code does — the order that
     *     makes it impossible to ship a connector that forgot to ask.
     * @enum {string}
     */
    MeetingProvider: "google_meet" | "zoom";
    /**
     * MeetingStateCounts
     * @description How many requests stand where. The aggregate, and only in totals.
     */
    MeetingStateCounts: {
      /**
       * Cancelled
       * @default 0
       */
      cancelled: number;
      /**
       * Completed
       * @default 0
       */
      completed: number;
      /**
       * Eligible
       * @default 0
       */
      eligible: number;
      /**
       * Expired
       * @default 0
       */
      expired: number;
      /**
       * Pending
       * @default 0
       */
      pending: number;
      /**
       * Refused
       * @default 0
       */
      refused: number;
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
      /**
       * Capacity
       * @default not_stated
       */
      capacity: string;
      /** Capacitystatedat */
      capacityStatedAt?: string | null;
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
     * MyIdentitiesResponse
     * @description Everything CAIRN links to the reader across sources, and how.
     */
    MyIdentitiesResponse: {
      /** Identities */
      identities?: components["schemas"]["ExternalIdentityResponse"][];
      /** Notice */
      notice: string;
      /** Proposals */
      proposals?: components["schemas"]["IdentityProposalResponse"][];
    };
    /**
     * MyMeetingRequestListResponse
     * @description The requests the caller was asked about. Theirs only.
     */
    MyMeetingRequestListResponse: {
      /** Notice */
      notice: string;
      /** Requests */
      requests?: components["schemas"]["MyMeetingRequestResponse"][];
    };
    /**
     * MyMeetingRequestResponse
     * @description One capture request, as the person who was asked sees it.
     *
     *     Carries the caller's own answer and nothing about anybody else's. The
     *     request's standing is shown because a participant is entitled to know
     *     whether anything will be collected; *who* caused that standing is not theirs
     *     to learn, and no field here could tell them.
     */
    MyMeetingRequestResponse: {
      /** Candecide */
      canDecide: boolean;
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Message */
      message: string;
      /** Mydecidedat */
      myDecidedAt?: string | null;
      myDecision?: components["schemas"]["ConsentDecision"] | null;
      /** Participantcount */
      participantCount: number;
      /** Policyversion */
      policyVersion: string;
      provider: components["schemas"]["MeetingProvider"];
      /** Purpose */
      purpose: string;
      /**
       * Scheduledend
       * Format: date-time
       */
      scheduledEnd: string;
      /**
       * Scheduledstart
       * Format: date-time
       */
      scheduledStart: string;
      state: components["schemas"]["CaptureState"];
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
     * ReasonCode
     * @description Why collection is or is not permitted. Internal, precise, never shown raw.
     * @enum {string}
     */
    ReasonCode:
      | "allowed"
      | "awaiting_consent"
      | "refused"
      | "unresolved_participant"
      | "participant_added"
      | "policy_changed"
      | "rescheduled"
      | "not_collectable"
      | "window_passed"
      | "scope_mismatch"
      | "no_participants";
    /**
     * Region
     * @description Where a tenant's data is stored (only ``US_CENTRAL1`` is live so far,
     *     md/06 §6.3).
     * @enum {string}
     */
    Region: "us-central1" | "europe-west1";
    /**
     * RelatedFact
     * @description One piece of evidence: a fact, its certainty tier, its citations.
     */
    RelatedFact: {
      /** Certainty */
      certainty: string;
      /** Occurredat */
      occurredAt?: string | null;
      /** Sources */
      sources: components["schemas"]["RelatedFactSource"][];
      /** Statement */
      statement: string;
    };
    /**
     * RelatedFactSource
     * @description One citation on a related fact, resolvable to the thing itself.
     */
    RelatedFactSource: {
      /** Evidenceid */
      evidenceId: string;
      /** Source */
      source: string;
      /** Url */
      url?: string | null;
    };
    /**
     * RelatedPersonGroup
     * @description One person's related work, as evidence.
     *
     *     **No score, no rank, no relevance - not hidden: absent.** A field that
     *     exists gets displayed eventually, and a number between people is a ranking
     *     whatever the label says (md/05 B.2.2). Groups order by most recent related
     *     fact, a property of the evidence. Capacity is the person's own statement,
     *     carried verbatim with when they said it.
     */
    RelatedPersonGroup: {
      /** Capacity */
      capacity: string;
      /** Capacitystatedat */
      capacityStatedAt?: string | null;
      /** Displayname */
      displayName: string;
      /** Facts */
      facts: components["schemas"]["RelatedFact"][];
      /**
       * Personid
       * Format: uuid
       */
      personId: string;
    };
    /** RelatedWorkResponse */
    RelatedWorkResponse: {
      /** Groups */
      groups: components["schemas"]["RelatedPersonGroup"][];
      /** Topic */
      topic: string;
    };
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
    /**
     * RevokeIdentityRequest
     * @description Ending a link, and whether the link was ever right.
     *
     *     `disputed` separates "this was mine and I am unlinking it" from "this was
     *     never mine". Both stop attribution at once; only the second says the
     *     original link was wrong, and flattening the two would lose the distinction
     *     the person actually made.
     */
    RevokeIdentityRequest: {
      /**
       * Disputed
       * @default false
       */
      disputed: boolean;
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
     * SlackChannelListResponse
     * @description The picker's contents.
     */
    SlackChannelListResponse: {
      /** Channels */
      channels?: components["schemas"]["SlackChannelResponse"][];
      /** Notice */
      notice: string;
    };
    /**
     * SlackChannelResponse
     * @description One public channel the workspace could select.
     */
    SlackChannelResponse: {
      /** Botismember */
      botIsMember: boolean;
      /** Id */
      id: string;
      /** Name */
      name: string;
      /** Selected */
      selected: boolean;
    };
    /**
     * SlackChannelSelectionRequest
     * @description The full state of the picker, not a delta.
     *
     *     A replace rather than a merge: unchecking a box has to mean something, and
     *     the something it means is withdrawing permission to read a channel.
     */
    SlackChannelSelectionRequest: {
      /** Channelids */
      channelIds?: string[];
    };
    /**
     * SlackChannelSelectionResponse
     * @description What CAIRN may now process. IDs only — deliberately no names.
     */
    SlackChannelSelectionResponse: {
      /** Channelids */
      channelIds?: string[];
      /** Notice */
      notice: string;
    };
    /**
     * SlackDisconnectResponse
     * @description What disconnecting did, stated precisely enough to be trusted.
     */
    SlackDisconnectResponse: {
      /** Credentialcleared */
      credentialCleared: boolean;
      /**
       * Disconnectedat
       * Format: date-time
       */
      disconnectedAt: string;
      /** Retentionnotice */
      retentionNotice: string;
      /** State */
      state: string;
    };
    /**
     * SlackInstallResponse
     * @description Where to send the customer, and what they are about to be asked.
     */
    SlackInstallResponse: {
      /** Authorizeurl */
      authorizeUrl: string;
      /**
       * Expiresat
       * Format: date-time
       */
      expiresAt: string;
      /** Notice */
      notice: string;
      /** Requestedscopes */
      requestedScopes?: string[];
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
     * SubscriptionHealthView
     * @description Every Google Chat lease at one moment, as counts and one age.
     *
     *     Answers the three questions an operator has about a renewal loop — how many
     *     leases are alive, how many are broken, how long until the next lapses — and
     *     none of the questions a support session exists for. **Every field is an
     *     integer, an age, a closed-enum mapping or the provider name; there is
     *     nowhere here to put a space, a workspace or a person**, which is a property
     *     of the shape rather than of the care taken filling it in.
     *
     *     Derived from `SubscriptionRecord`, which the reader in
     *     `gchat/subscriptions.py` builds without an identifier of any kind, so no
     *     aggregation choice made downstream can reintroduce one.
     */
    SubscriptionHealthView: {
      /**
       * Expiryispermanentloss
       * @default false
       */
      expiryIsPermanentLoss: boolean;
      /** Nearestexpiryminutes */
      nearestExpiryMinutes?: number | null;
      /**
       * Observable
       * @default true
       */
      observable: boolean;
      /** Provider */
      provider: string;
      /** Renewalduewithinminutes */
      renewalDueWithinMinutes?: number | null;
      /** Subscriptionsbyerrorcategory */
      subscriptionsByErrorCategory?: {
        [key: string]: number;
      };
      /** Subscriptionsbystate */
      subscriptionsByState?: {
        [key: string]: number;
      };
      /** Subscriptionsexpected */
      subscriptionsExpected?: number | null;
      /**
       * Subscriptionsexpired
       * @default 0
       */
      subscriptionsExpired: number;
      /**
       * Subscriptionslive
       * @default 0
       */
      subscriptionsLive: number;
      /** Subscriptionsmissing */
      subscriptionsMissing?: number | null;
      /**
       * Subscriptionssuspended
       * @default 0
       */
      subscriptionsSuspended: number;
      /** Subscriptionsunobservablereason */
      subscriptionsUnobservableReason?: string | null;
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
  finish_install_v1_integrations_google_chat_callback_get: {
    parameters: {
      query?: {
        code?: string | null;
        state?: string | null;
        error?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Back to the workspace's admin screen. */
      303: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Successful Response */
      307: {
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
  finish_install_v1_integrations_google_meet_callback_get: {
    parameters: {
      query?: {
        code?: string | null;
        state?: string | null;
        error?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Back to the workspace's admin screen. */
      303: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Successful Response */
      307: {
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
  finish_transcript_access_v1_integrations_google_meet_transcript_callback_get: {
    parameters: {
      query?: {
        code?: string | null;
        state?: string | null;
        error?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Back to the workspace's admin screen. */
      303: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Successful Response */
      307: {
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
  finish_install_v1_integrations_slack_callback_get: {
    parameters: {
      query?: {
        code?: string | null;
        state?: string | null;
        error?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody?: never;
    responses: {
      /** @description Back to the workspace's integration settings. */
      303: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Successful Response */
      307: {
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
  connector_health_v1_internal_operations_connectors_get: {
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
          "application/json": components["schemas"]["ConnectorFleetView"];
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
  workspace_attribution_health_v1_workspaces__workspace_id__attribution_health_get: {
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
          "application/json": components["schemas"]["AttributionHealthResponse"];
        };
      };
      /** @description Requires permission to manage workspace settings. */
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
  disconnect_google_chat_v1_workspaces__workspace_id__integrations_google_chat_disconnect_post: {
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
          "application/json": components["schemas"]["GoogleChatDisconnectResponse"];
        };
      };
      /** @description Requires permission to disconnect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Google Chat account is connected. */
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
  begin_install_v1_workspaces__workspace_id__integrations_google_chat_install_post: {
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
          "application/json": components["schemas"]["GoogleChatInstallResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
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
      /** @description Google Chat is not configured on this deployment. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  list_spaces_v1_workspaces__workspace_id__integrations_google_chat_spaces_get: {
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
          "application/json": components["schemas"]["GoogleChatSpaceListResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Google Chat account is connected. */
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
      /** @description Google could not be reached. */
      502: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  save_spaces_v1_workspaces__workspace_id__integrations_google_chat_spaces_put: {
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
        "application/json": components["schemas"]["GoogleChatSpaceSelectionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["GoogleChatSpaceSelectionResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Google Chat account is connected. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description A space is already connected to another workspace. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description A value was not a Google Chat space resource name. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  disconnect_google_meet_v1_workspaces__workspace_id__integrations_google_meet_disconnect_post: {
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
          "application/json": components["schemas"]["GoogleMeetDisconnectResponse"];
        };
      };
      /** @description Requires permission to disconnect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Google Meet account is connected. */
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
  begin_install_v1_workspaces__workspace_id__integrations_google_meet_install_post: {
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
          "application/json": components["schemas"]["GoogleMeetInstallResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
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
      /** @description Google Meet is not configured on this deployment. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  meet_status_v1_workspaces__workspace_id__integrations_google_meet_status_get: {
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
          "application/json": components["schemas"]["GoogleMeetStatusResponse"];
        };
      };
      /** @description Requires permission to manage integrations. */
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
  begin_transcript_access_v1_workspaces__workspace_id__integrations_google_meet_transcript_access_post: {
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
          "application/json": components["schemas"]["GoogleMeetTranscriptAccessResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Google Meet account is connected. */
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
      /** @description Transcript retrieval is not configured on this deployment. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  revoke_transcript_access_v1_workspaces__workspace_id__integrations_google_meet_transcript_access_revoke_post: {
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
          "application/json": components["schemas"]["GoogleMeetTranscriptAccessStateResponse"];
        };
      };
      /** @description Requires permission to disconnect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Google Meet account is connected. */
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
  list_transcripts_v1_workspaces__workspace_id__integrations_google_meet_transcripts_get: {
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
          "application/json": components["schemas"]["GoogleMeetTranscriptListResponse"];
        };
      };
      /** @description Requires permission to manage integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Google Meet account is connected. */
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
  list_channels_v1_workspaces__workspace_id__integrations_slack_channels_get: {
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
          "application/json": components["schemas"]["SlackChannelListResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Slack workspace is connected. */
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
      /** @description Slack could not be reached. */
      502: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  save_channels_v1_workspaces__workspace_id__integrations_slack_channels_put: {
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
        "application/json": components["schemas"]["SlackChannelSelectionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SlackChannelSelectionResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Slack workspace is connected. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description A value was not a Slack channel ID. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  disconnect_slack_v1_workspaces__workspace_id__integrations_slack_disconnect_post: {
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
          "application/json": components["schemas"]["SlackDisconnectResponse"];
        };
      };
      /** @description Requires permission to disconnect integrations. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No Slack workspace is connected. */
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
  begin_install_v1_workspaces__workspace_id__integrations_slack_install_post: {
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
          "application/json": components["schemas"]["SlackInstallResponse"];
        };
      };
      /** @description Requires permission to connect integrations. */
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
      /** @description Slack is not configured on this deployment. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
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
  set_my_capacity_v1_workspaces__workspace_id__me_capacity_put: {
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
        "application/json": components["schemas"]["CapacityUpdate"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["CapacityResponse"];
        };
      };
      /** @description No such workspace, or no record to state it on. */
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
  my_identities_v1_workspaces__workspace_id__me_identities_get: {
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
          "application/json": components["schemas"]["MyIdentitiesResponse"];
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
  confirm_identity_v1_workspaces__workspace_id__me_identities_post: {
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
        "application/json": components["schemas"]["ConfirmIdentityRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ExternalIdentityResponse"];
        };
      };
      /** @description CAIRN has not linked any activity to your account yet. */
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
      /** @description That account is already linked to somebody in this workspace. */
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
  revoke_identity_v1_workspaces__workspace_id__me_identities__identity_id__revoke_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        identity_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RevokeIdentityRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ExternalIdentityResponse"];
        };
      };
      /** @description No such link of yours in this workspace. */
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
  my_meeting_requests_v1_workspaces__workspace_id__me_meeting_requests_get: {
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
          "application/json": components["schemas"]["MyMeetingRequestListResponse"];
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
  decide_meeting_request_v1_workspaces__workspace_id__me_meeting_requests__meeting_id__decision_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        meeting_id: string;
        workspace_id: string;
      };
      cookie?: {
        cairn_session?: string | null;
      };
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["MeetingDecisionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MyMeetingRequestResponse"];
        };
      };
      /** @description You have no meeting request with that identifier. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The request is closed, or that answer does not apply. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
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
  list_capture_requests_v1_workspaces__workspace_id__meetings_capture_requests_get: {
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
          "application/json": components["schemas"]["MeetingCaptureListResponse"];
        };
      };
      /** @description Requires permission to manage workspace settings. */
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
  create_capture_request_v1_workspaces__workspace_id__meetings_capture_requests_post: {
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
        "application/json": components["schemas"]["MeetingCaptureCreateRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MeetingCaptureResponse"];
        };
      };
      /** @description Requires permission to manage workspace settings. */
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
      /** @description That meeting already has an open capture request. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The window, or one of the people named, is not usable. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  cancel_capture_request_v1_workspaces__workspace_id__meetings_capture_requests__meeting_id__cancel_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        meeting_id: string;
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
          "application/json": components["schemas"]["MeetingCaptureResponse"];
        };
      };
      /** @description Requires permission to manage workspace settings. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description No such capture request in this workspace. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The request is already closed. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
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
  find_related_work_v1_workspaces__workspace_id__related_work_get: {
    parameters: {
      query: {
        topic: string;
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
          "application/json": components["schemas"]["RelatedWorkResponse"];
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
