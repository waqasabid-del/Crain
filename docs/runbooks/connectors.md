# Runbook: a source has stopped delivering

**Read this first: you may not read the customer's messages to debug ingestion.**

Not "prefer not to", not "only if you have to". Reading a workspace's activity requires an
approved, time-boxed, customer-visible support session (md/15 §5.2) that no staff role can grant
itself, and integration debugging is not a reason to open one — a support session defaults to
configuration and diagnostic data, and reaching actual work content needs a separate escalation and
a separate approval.

Everything in this runbook is answerable from counts, states and categories. If you find yourself
needing a channel name, a message, a repository name or a person's handle to make progress, you
have not run out of diagnostics — you have reached the boundary the product is sold on. Escalate to
the connector owner instead.

---

## Where the numbers are

`cairn_api.ops.connectors.connector_health` — a read model over `source_connections`, one row per
provider. It needs the `engineering` or `security` staff role, the same as every other
`/v1/internal/operations/*` surface. Support and Billing Ops cannot read it, deliberately: least
privilege applies internally too.

| Field                                                       | What it counts                                                                     |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `workspacesConnected`                                       | Workspaces with a live authorisation for this provider                             |
| `workspacesEverSynced`                                      | Workspaces this provider has ever successfully delivered to                        |
| `workspacesByState`                                         | Every connection by `pending` / `connected` / `disconnected` / `revoked` / `error` |
| `workspacesByHealth`                                        | Live connections by `unknown` / `healthy` / `degraded` / `failing`                 |
| `errorsByCategory`                                          | Live connections by `lastErrorCategory`                                            |
| `oldestUnsuccessfulSyncMinutes`                             | How long the worst live connection has gone without a successful sync              |
| `deliveriesLastHour`, `failuresLastHour`, `deliveriesTotal` | Inbound events, **GitHub only** — `null` elsewhere                                 |
| `inboundVerified`                                           | Whether anything has ever actually arrived from this provider                      |

There is no field for a message, a channel, a space, an account label, a repository or a person,
and a test asserts that over the model's fields so one cannot be added quietly.

---

## The three causes that look identical

A source that has stopped delivering shows the same thing on every dashboard: zero events. The
cause is one of three, they need **completely different responses**, and getting it wrong is
expensive in both directions — re-issuing credentials for a connection a customer deliberately
removed is an attempt to restore access that was withdrawn.

| Cause                            | What you see                                                                                          | What to do                                                                                                                                                                                       |
| -------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **The customer disconnected it** | `workspacesByState` shows `disconnected` or `revoked` rising; no error category                       | Nothing technical. `disconnected` is our side turned off — reconnecting is a click for them. `revoked` is their side — reconnecting needs a fresh authorisation. **Never re-issue credentials.** |
| **Our credentials expired**      | `errorsByCategory` shows `authentication_expired` or `permission_revoked`, `state` = `error`          | Ours to fix. `authentication_expired` is a rotation we missed; `permission_revoked` is a scope an admin removed and needs the customer to re-authorise with the scope granted.                   |
| **The provider is down**         | `errorsByCategory` shows `provider_unavailable` or `rate_limited`, across **many** workspaces at once | Nothing to fix here. Check the provider's status page, back off, and say so. Time fixes `rate_limited`; nothing else does.                                                                       |

**The tell is the spread.** One workspace is about that workspace. Every workspace on one provider,
starting within the same few minutes, is the provider or a credential of ours — and a credential of
ours would usually be all workspaces on one _app_, which today is the same thing. Count the
workspaces before deciding.

**`configuration_invalid` is a fourth answer**, and it means the connection itself no longer makes
sense: a workspace that was deleted, a space we were removed from. It looks like our problem and is
usually the customer's, so confirm the account still exists before touching anything.

**`unknown` is honest, not lazy.** It means the failure did not match a category. Treat a rising
`unknown` count as a gap in the classifier and report it — a category that has to be guessed at is
still better than an error message that quotes a customer's data, which is why the raw provider
error is never stored.

---

## Reading an error state

`state` and `health` answer different questions and both matter.

- **`state` is about permission.** `connected` means we are authorised. `error` means we are
  authorised and something we cannot retry our way out of went wrong.
- **`health` is about whether data is arriving.** A connection can be perfectly authorised and
  rate-limited into uselessness, and `connected` + `failing` is exactly that. This is the worst
  combination to miss, because a customer looking at a green "connected" while nothing ingests is
  the situation md/05 calls out as worse than an honest failure.
- **`unknown` health is not healthy.** It means nothing has been attempted yet. A connection that
  has never synced has not proved anything, and it is the one most likely to be silently broken —
  which is why `oldestUnsuccessfulSyncMinutes` counts it, aged from when it was authorised.

---

## When a source stops delivering

1. **Is anything connected at all?** `workspacesConnected` at zero for a provider that had
   connections is a disconnect event, not an outage. Check `workspacesByState`.
2. **Is it one workspace or all of them?** See "the tell is the spread" above. This decides which
   of the three causes you are in, and everything after it depends on getting this right.
3. **Has it ever worked?** `inboundVerified` false means this provider has never delivered
   anything, anywhere. That is not an incident — it is an unfinished installation, and the release
   gate has been saying so (`uv run python -m cairn_api.ops.gates_cli`, the `connectors` gate).
4. **How far behind?** `oldestUnsuccessfulSyncMinutes`. Compare against the queue backlog
   thresholds in `docs/OPERATIONS.md`; a source that is behind because the queue is behind is a
   queue incident wearing a connector's clothes.
5. **For GitHub, check the delivery counts.** `failuresLastHour` against `deliveriesLastHour`
   separates "nothing is arriving" from "everything arriving is failing" — different problems, and
   the second one is ours.
6. **Read the logs and the spans, not the payloads.** `cairn.connector.deliveries` and
   `cairn.connector.errors` carry `source`, `outcome` and `error_category` and nothing else. That
   is deliberate: the telemetry allow-list in `telemetry/attributes.py` is closed, and a channel
   name will never be on it.

---

## GitHub

GitHub is the source every other one is measured against, and the only one with a durable inbound
record. It is also the one where the gap between "installed" and "working" is a single database row
that nothing tells you is missing.

### Setup, and what each permission buys

Create a GitHub App on the account that owns the repositories. **Read-only throughout — no write
permission of any kind is ever required, and widening one to make something work is a product
invariant broken, not a fix.**

| Step                      | Exactly                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------- |
| Webhook URL               | `https://<host>/v1/webhooks/github` — the `/v1` prefix is not optional                            |
| Webhook secret            | 256 bits of randomness, into `CAIRN_GITHUB_WEBHOOK_SECRET`                                        |
| Repository permissions    | Contents: **Read-only**; Pull requests: **Read-only**; Issues: **Read-only**; Metadata: Read-only |
| Subscribe to events       | Push, Pull request, Issues, Issue comment                                                         |
| Where it can be installed | Only on this account, until there is a reason otherwise                                           |

- **Contents** is what backfill reads. `github/client.py` asks GraphQL for
  `repository.defaultBranchRef.target.history`, and without this permission the query returns a null
  repository rather than an error — an empty history that looks like a quiet quarter.
- **Pull requests** and **Issues** are what `pipeline/jobs.py::_read_evidence` turns into evidence a
  fact can cite. Their author becomes a `ProviderActor` from `user.id` — GitHub's stable numeric id,
  never the login, which the account holder can change at any time.
- **Metadata** is mandatory and granted automatically.
- **No account permissions, and no organisation permissions.** Nothing in the codebase calls an
  endpoint that needs one.

Installation lifecycle events (`installation`, `installation_repositories`) are delivered to an App
without being subscribed to, and are handled inline rather than queued: they decide whether _future_
deliveries are processed, and deferring them would leave a window in which a suspended
installation's activity is still captured.

### Installing the App does not connect it

**This is the first thing to check when a correctly configured App produces nothing.** Installing
grants access; it does not tell CAIRN whose workspace the activity belongs to. That mapping lives in
`github_installations`, and the only thing that writes it is an authenticated call to
`POST /v1/workspaces/{workspace_id}/integrations/github` behind the `INTEGRATIONS_CONNECT`
permission.

That is deliberate and worth not "fixing". An inbound webhook that could create the mapping would
bind whoever installed the App to a workspace nobody chose — `_apply_lifecycle` ignores an
`installation.created` for an installation it has never seen, for exactly this reason.

Until the row exists, every delivery is answered `202 {"status":"unclaimed"}` and is **not**
enqueued: capturing activity for an integration nobody connected is a consent problem, not a
backlog. Nothing about the response says "misconfigured", because from the endpoint's side it is
not.

### What actually produces an attributed fact

| Event          | Becomes evidence         | Who it credits                                                               |
| -------------- | ------------------------ | ---------------------------------------------------------------------------- |
| `push`         | One item per commit      | The author named in the message header, plus every `Co-authored-by:` trailer |
| `pull_request` | The PR title and body    | A `ProviderActor` from `user.id`                                             |
| `issues`       | The issue title and body | A `ProviderActor` from `user.id`                                             |

A push commit deliberately carries **no** actor. A push payload names the pusher, and attributing
somebody's commit to whoever pushed it is precisely the wrong-person failure the product exists to
avoid. The author reaches the fact by being named in the evidence text instead, which keeps it a
claim the payload made — one a person can correct — rather than provenance the system asserts.

### The queue is not optional

The API and the worker are separate processes. On the default in-memory broker they do not share a
queue, so a delivery is accepted, enqueued into the API's own process, and never runs: an
acknowledged webhook, a `webhook_deliveries` row that stays `PENDING`, and no fact. Set
`CAIRN_QUEUE_BACKEND=postgres` before expecting anything to be understood, and treat the `queue`
release gate as a prerequisite for the GitHub one rather than an unrelated item.

### The ten-second budget

**GitHub expects a 2xx within ten seconds** or it retries. The handler verifies, records and
enqueues, and does nothing else — normalisation, attribution and every model call happen on the
worker. `ProviderLimits.ack_deadline_seconds` in `ops/connectors.py` holds the same number so a
threshold and this page cannot drift apart.

Delivery is not exactly-once: GitHub documents duplicates and gaps as normal. The delivery id is
written under a unique constraint **before** the job is enqueued, and committed before the
acknowledgement, because acknowledging first would let a rollback erase work GitHub believes we
already hold. A redelivery of something already held is answered `200 {"status":"duplicate"}` and
not re-enqueued.

### Troubleshooting, in this order

1. **Did the delivery arrive?** GitHub's App settings show every delivery with its response. A 401
   is the signature: the secret in `.env` is not the secret registered on the App, or a proxy
   rewrote the body. The signature is checked against the raw bytes, so anything that re-encodes
   them invalidates it.
2. **Was it claimed?** `{"status":"unclaimed"}` means no `github_installations` row — see above. It
   is the single most common cause of "installed and nothing happens".
3. **Is the row there but the delivery still pending?** Read `status` and `error` from the most
   recent `webhook_deliveries` rows through a tenant-scoped session. `PENDING` with no error is a
   queue that nothing is draining — check the worker and `CAIRN_QUEUE_BACKEND`.
4. **Did understanding run?** One `pipeline.understand` job follows each processed delivery. Without
   a queue bound to the delivery handler it is never published, and the handler logs
   `github.understanding_not_published` loudly rather than returning quietly.
5. **Facts but no people?** Extraction names people from the evidence text. A commit whose message
   has no author header and no trailers names nobody, and an empty `people` is the correct answer
   there — a wrong name is worse than a missing one.

### Backfill

`github/backfill.py` walks the last ninety days of the default branch through the same attribution
path live webhooks use, at `BULK` priority so a new customer's history cannot starve the activity
arriving now. It needs `CAIRN_GITHUB_APP_ID` and `CAIRN_GITHUB_PRIVATE_KEY` — the webhook path needs
neither, which is why an App can receive deliveries perfectly while backfill is unconfigured.

The cursor is committed only after a page's contents are in the session, so a crash re-reads a page
rather than skipping one. Re-reading is safe: evidence ids are the commit SHA, and both the evidence
check and `graph.build`'s `ON CONFLICT DO NOTHING` make a second pass idempotent. Exhausting the
rate budget parks the run as `THROTTLED` rather than failing it.

---

## Slack

Slack is the first chat source, and the one where the difference between "configured" and "working"
is widest. Everything below is answerable from counts, states and categories. None of it requires
looking at a channel, a message or a person, and none of it ever will.

### Setup, and what each scope buys

Create a Slack app, then:

| Step                    | Exactly                                                                  |
| ----------------------- | ------------------------------------------------------------------------ |
| Bot Token Scopes        | `channels:history`, `channels:read`, `users:read` — these three, no more |
| Events API              | Set the Request URL and wait for it to verify                            |
| Subscribe to bot events | `message.channels`                                                       |
| Subscribe to app events | `app_uninstalled`, `tokens_revoked`                                      |

- **`channels:history`** is the connector. Without it no message is ever delivered, and a missing
  capability then reads as an empty feed rather than as a permission problem — which is why
  `source_connections.scopes` stores what was actually granted rather than what was asked for.
- **`channels:read`** resolves channel metadata, so a channel can be identified without calling the
  Web API once per message.
- **`users:read`** resolves an author to a person **once**, for identity resolution. It is not
  called per message — see the Web API limits below.
- **`channels:join` is deliberately not requested.** CAIRN does not add itself to channels. A
  customer decides what CAIRN sees by inviting the bot, and that consent is the product working as
  sold. It is also the single most common cause of "no events arrive", which is why it is the first
  thing this runbook checks.

`app_uninstalled` and `tokens_revoked` need no scopes at all. Subscribe to both.

### Request URL verification

Slack POSTs `{"type": "url_verification", "challenge": ...}` to the Request URL. That request **is
signed**, and CAIRN verifies the signature before answering it — a challenge endpoint that echoes
without verifying will answer anybody.

Two things go wrong here and both look like "verification failed" with no further detail:

- **Request URLs are case-sensitive.** A path that differs by one letter fails, and the app is
  configured, credentialled and completely inert.
- **Slack retries verification if the first attempt times out.** A cold start that exceeded the
  budget below can show as a failure that then succeeds on its own; do not change anything between
  the two attempts or you will not know which change worked.

### The 3-second budget

**Slack requires an HTTP 2xx within 3 seconds.** That is the whole budget, including TLS, cold
start and anything the handler does before it answers. Nothing that talks to a model, a queue
broker on another host, or a third party belongs before the acknowledgement. Acknowledge, then work.

`ProviderLimits.ack_deadline_seconds` in `ops/connectors.py` is the same number, recorded once so a
threshold and this page cannot drift apart.

### Retries, and how to stop them

Slack retries a failed delivery **3 times in total: immediately, after 1 minute, then after 5
minutes.**

| Header                 | What it carries                                     |
| ---------------------- | --------------------------------------------------- |
| `x-slack-retry-num`    | Which attempt this is                               |
| `x-slack-retry-reason` | `http_timeout`, `connection_failed`, `ssl_error`, … |

A rising `http_timeout` count is the 3-second budget being missed, not a Slack fault. `ssl_error`
is a certificate or chain problem at our edge.

To refuse a delivery **permanently** — a payload CAIRN will never accept, however many times it is
resent — respond non-200 with `x-slack-no-retry: 1`. Use it only for permanent rejections. Sending
it for a transient failure discards an event that a retry would have delivered, and Slack will not
offer it again.

### The rate limit, and the data it destroys

**Event deliveries max out at 30,000 per workspace, per app, per 60 minutes.** Past that, Slack
emits an `app_rate_limited` event and **drops the rest of that window's events. They are not
queued, and they are not redelivered.**

**Those events are gone permanently.** CAIRN requests no history scope, so there is no API call
that can go back for them. This is not a backlog to wait out and not something a redeploy fixes —
it is a hole in that customer's record, and the honest response is to tell them, not to look for a
recovery path that does not exist.

`app_rate_limited` is **not** an `event_callback`: it arrives with a top-level `type`, a `team_id`
and a `minute_rate_limited`, and has no nested `event` and no `event_id`. A handler that reaches
for `payload["event"]["type"]` will fail on exactly the event that matters most.

Operationally:

- **Alert well before 30,000.** `ConnectorHealth.event_budget_alert_at` is 24,000 — 80% of the
  ceiling. An alert that fires at the ceiling is a notification that data was lost, not a chance to
  prevent it.
- **CAIRN cannot currently measure how close a workspace is.** Slack's ceiling is per workspace per
  hour; every count in the read model is platform-wide, and Slack has no durable inbound record at
  all. `ConnectorHealth.event_budget_per_hour` is a number to compare against by hand. Nothing here
  estimates the fraction, because a platform-wide gauge would read 3% while one workspace sat at
  100%.
- **Both are on the Python read model, not on the API response yet.** `ConnectorHealthView` in
  `api/schemas.py` does not carry them, so today they are read from `SLACK_LIMITS` in
  `ops/connectors.py` rather than from `/v1/internal/operations/connectors`.
- **What you can see today is `cairn.connector.rate_limit_windows`** and a `rate_limited` count in
  `errorsByCategory`. Both are lagging: they say events were already dropped.

### Uninstall and revocation

`app_uninstalled` and `tokens_revoked` both exist, both need no scopes, and **their order is not
guaranteed** — either can arrive first, both can arrive, and one can arrive twice.

So teardown is **idempotent and keyed on `team_id`**. Tearing down twice must be a no-op, and the
second event must not resurrect or re-error a connection the first one closed. Both are the
customer's decision: they land as `revoked`, they are not incidents, and **no credential is
re-issued in response to either.**

### Troubleshooting, in this order

The order is not arbitrary. Each step rules out a cause that would make the next step's evidence
meaningless, and the first one is first because it is the answer most of the time.

1. **Has the bot been invited to the channel?** CAIRN never requests `channels:join`, so a bot that
   has not been invited receives **nothing at all** — no error, no failed delivery, no rate limit.
   Every scope check, credential check and signature check passes in this state, which is exactly
   why it is mistaken for a platform fault. "The scopes look right but no events arrive" is this,
   almost every time. Ask the customer to `/invite` the app to one channel and post a message.
2. **Did the Request URL ever verify?** An unverified URL means Slack has never delivered anything
   here. Check the case of the path first.
3. **What does the connection say?** `workspacesByState` and `errorsByCategory` for the Slack row.
   This is where the three causes below separate.
4. **Are the granted scopes the ones we asked for?** `source_connections.scopes` records what Slack
   actually granted. An app reinstalled with fewer scopes is `permission_revoked`, not an outage.
5. **Are we timing out?** A rising `http_timeout` retry reason means the 3-second budget is being
   missed, and Slack is discarding after the third attempt.
6. **Are we being throttled?** `rate_limited` in `errorsByCategory`, or
   `cairn.connector.rate_limit_windows` above zero. If so, events have already been lost — go to
   the rate-limit section and disclose rather than investigate.
7. **Escalate.** If none of the above explains it, escalate to the connector owner. Reading the
   customer's messages is not the next step, and it is not a later step either.

### The three causes, in Slack's terms

Same three as above, and they are genuinely indistinguishable from "zero events" alone. Slack gives
each a different signature:

| Cause                            | Slack's signature                                                                                 | Response                                                                                      |
| -------------------------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **The customer disconnected it** | `app_uninstalled` or `tokens_revoked` was received; `workspacesByState` shows `revoked`           | Nothing technical. **Never re-issue credentials.** They removed us on purpose.                |
| **Our credentials were revoked** | `errorsByCategory` shows `authentication_expired` or `permission_revoked` with no uninstall event | Ours, or a scope an admin removed. A rotation we missed is ours; a scope needs their re-auth. |
| **Slack is down**                | `provider_unavailable` or `rate_limited` across **many** workspaces starting within minutes       | Nothing to fix. Check Slack's status page and back off.                                       |

**Count the workspaces before deciding.** One workspace is about that workspace. All of them at
once is Slack or a credential of ours.

**A fourth, enterprise-specific answer:** workspace admins can require app approval. Installation is
then blocked by policy regardless of Marketplace status, and it looks like a customer who "keeps
failing to install". It is not a bug and no amount of retrying fixes it — the customer's Slack admin
has to approve the app.

### Web API limits are separate

`conversations.list` and `users.info` are Web API calls with their own tiered limits and their own
`Retry-After` on 429 — entirely separate from the 30,000 event budget. Exhausting them does not
drop events, but it does stall enrichment.

**Never call `users.info` per message.** Cache identity aggressively; a per-message identity lookup
is both a rate-limit incident waiting to happen and the shape of a per-person query.

### Manual live validation

The `connectors` release gate is `MANUAL` while Slack is configured and unproven, and structurally
cannot be anything better. To close it:

1. Install the app on a real workspace.
2. **`/invite` the bot to one channel.** Nothing arrives without this.
3. Post one message in that channel.
4. `GET /v1/internal/operations/connectors` and confirm the Slack row reports `inboundVerified`
   true.
5. Re-run `uv run python -m cairn_api.ops.gates_cli` and record who validated it and when.

`deliveriesLastHour` stays `null` for Slack — there is no durable inbound record for it — so
`inboundVerified` is the field to read. Waiting for a delivery count to rise is waiting for a number
that cannot exist.

---

## Google Chat

Google Chat is the connector where the gap between "the code works" and "this can be sold" is
widest, and the gap is not technical. Read the scope section first: it is the reason a finished
connector may still not be able to launch for months.

**Google Chat is not live, and nothing in this section says it is.** What has landed is the
plumbing: the migration `20260817_0300_google_chat.py` (`c5a92f7e4d18`) creating
`google_chat_oauth_states`, `google_chat_space_selections` and `google_chat_subscriptions`; the
seven `CAIRN_GOOGLE_CHAT_*` settings in `config.py`; `gchat/oauth.py`, `gchat/pubsub.py`,
`gchat/events.py` and `gchat/subscriptions.py`; the Pub/Sub push route
(`api/routers/gchat_push.py`); a renewal sweep the worker actually calls
(`jobs/main.py::run_maintenance` → `renew_expiring_subscriptions`); and the customer-facing half —
`api/routers/gchat.py` and a Google Chat card with a Connect button on the Workspace screen. What
has **not** happened is everything Google has to approve, and the connector stops dead there: the
button is pressable and the authorisation behind it cannot succeed. Two operational readings are
also still missing — see "What is wired, and what is not" below, and the release gate at the end of
this section. Do not read a wired connect flow as a shippable connector.

Everything below is answerable from counts, states and categories. None of it requires reading a
space, a message or a person, and none of it ever will.

### The scopes, and what they actually cost

| Scope                    | Tier           | What that means                                                                                                                                           |
| ------------------------ | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `chat.messages.readonly` | **RESTRICTED** | OAuth verification **plus** an independent third-party security assessment (CASA) ending in a Letter of Assessment, **re-taken at least every 12 months** |
| `chat.spaces.readonly`   | SENSITIVE      | OAuth verification by Google. No third party, no assessment.                                                                                              |

**This is the largest blocker in the connector programme.** There is no read-only Chat message scope
in a lower tier — reading messages at all puts CAIRN in the restricted tier. Assessments run **weeks
to months**, they are re-taken annually forever, and no amount of finished, reviewed, tested code
shortens one. A deployment that has not _started_ the assessment cannot ship this connector, which
is why the `connectors` release gate says so before it says anything about installing the app.

**Start it before the code, not after it.** The two facts that make this urgent are linked: until
the app is published and verified, the OAuth consent screen stays in "Testing" with external user
type — and there, **refresh tokens expire after 7 days**. Every customer connection breaks weekly,
forever, until verification completes. A connector that works on Monday and is dead by the following
Monday is indistinguishable from an unstable product, and the fix is a calendar, not a patch.

Also: Google allows **100 refresh tokens per account per client id**, and the 101st silently
invalidates the oldest. A reconnect loop quietly logs out the connection that was working, with no
error anywhere.

`GOOGLE_CHAT_SCOPES` and `GOOGLE_CHAT_SUBSCRIPTION` in `ops/connectors.py` hold these numbers, and
tests assert them, so this page and the code cannot drift apart.

### Setup

| Step                      | Exactly                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cloud project             | One project. The `spaces.messages.get` read ceiling below is **per project**, shared by every tenant in it.                                                                                                                                                                                                                                                                |
| Google Chat API           | Enable it and configure the app.                                                                                                                                                                                                                                                                                                                                           |
| Workspace Events API      | Enable it. This is what issues subscriptions; the Chat API alone delivers nothing.                                                                                                                                                                                                                                                                                         |
| Pub/Sub topic             | Create it, and grant `roles/pubsub.publisher` to Google's publisher principal — **see the warning below**.                                                                                                                                                                                                                                                                 |
| Pub/Sub push subscription | Push to CAIRN's endpoint with **authenticated (OIDC JWT) delivery**. Verify the token against an **explicit `aud`** (`CAIRN_GOOGLE_CHAT_PUSH_AUDIENCE`) and a **named service-account email** (`CAIRN_GOOGLE_CHAT_SERVICE_ACCOUNT`); an unauthenticated push endpoint accepts anybody's events, and a token verified without an audience accepts anybody's Google project. |
| OAuth consent screen      | Published and verified, with the assessment complete, before any real customer connects.                                                                                                                                                                                                                                                                                   |

**The publisher principal is not confirmed.** Google's documentation names
`chat-api-push@system.gserviceaccount.com` for Chat _interaction_ events and does **not** state
whether Workspace-Events-for-Chat publishes as the same principal. Granting the wrong one does not
fail loudly — it appears later as an `ENDPOINT_PERMISSION_DENIED` **suspension**, hours after
setup looked fine. Verify it empirically in a real project and write down what you observed;
`SubscriptionLimits.publisher_principal_confirmed` is `False` until somebody does.

**The authorising user must belong to a Google Workspace organisation.** A personal Gmail account
cannot authorise this connector at all, and every configuration check passes in that state. It is
the Chat equivalent of Slack's uninvited bot, and it belongs in onboarding qualification rather than
in a support queue.

### Subscriptions: a four-hour lease, per space, forever

CAIRN subscribes **per space**, and each subscription is a lease with an expiry, not a registration.

| Fact                     | Value                                                                              |
| ------------------------ | ---------------------------------------------------------------------------------- |
| Lease length             | **4 hours** (`includeResource: true`, no domain-wide delegation)                   |
| Renew at                 | 2 hours — half the lease                                                           |
| Renewals per space       | **12 per day**, every day, for every selected space in every customer              |
| Alternative lease        | 7 days with `includeResource: false`                                               |
| Cost of that alternative | one `spaces.messages.get` per message, against **3,000 reads per project per 60s** |

**The 24-hour lease requires domain-wide delegation and is out of scope.** Domain-wide delegation is
an admin granting one application the right to impersonate every user in the organisation — a far
larger grant than this product needs, and not one to ask for to halve a renewal loop's frequency.

**CAIRN took the four-hour lease deliberately.** The seven-day lease looks like the easy win and is
not: without the resource on the event, every message costs a read against a ceiling that is **per
Cloud project**, shared by every tenant. One busy customer would throttle all of them, and a
per-project wall is harder to route around than a renewal loop. Do not "simplify" this without
re-reading that number.

**Do not build the renewal loop on Google's expiration reminder.** The documented reminder fires 12
hours before expiry; the lease is 4 hours long, so the reminder would have to precede the
subscription. It is structurally impossible here. Google's own guidance is to track `expireTime` and
renew, which is what `expire_time` on `google_chat_subscriptions` is for.

**Stagger renewals.** Workspace Events publishes **no** request-rate limits. With N spaces renewing
several times a day, a single cron sweep is a thundering herd aimed at a limit nobody can look up.
This one is done: `_stagger()` in `gchat/subscriptions.py` sleeps a **uniform random** interval
between leases in a pass, random rather than fixed because a fixed delay keeps two workers that
started together in lockstep. The pass also claims its rows `FOR UPDATE SKIP LOCKED`, so running the
sweep from every worker renews nothing twice.

**An expired subscription is deleted, permanently, and cannot be renewed.** It has to be _created_
again — a different code path from renewal, and one a renewal loop does not have. Everything
published for that space while no subscription existed was never delivered anywhere and there is no
backfill. That is a gap in the customer's record, like Slack's dropped events: disclose it rather
than look for a recovery path that does not exist.

### Subscription health

`cairn_api.ops.connectors.subscription_health` — counts, one age, and nothing else.

**Readable from the back-office.** `GET /v1/internal/operations/connectors` carries it as
`subscriptions`, for the Engineering and Security staff roles only; a customer session gets a 404,
because the existence of a back-office is not something an ordinary session should confirm.
`gchat/subscriptions.fleet_subscription_records` reduces every lease, fleet-wide, to a state, a
category and an expiry — **no space, no connection, no tenant** — so the aggregate has nowhere to put
an identifier and no grouping choice downstream can reintroduce one.

The read is fleet-wide and deliberately never per workspace: which customer is connected to what is a
support session's question, and a dashboard answers it for everybody at once with nobody's consent.
An unconfigured deployment reports `observable: false` with a reason instead of zeros.

| Reading                        | What it counts                                                                      |
| ------------------------------ | ----------------------------------------------------------------------------------- |
| `subscriptionsByState`         | Every lease by `pending` / `active` / `suspended` / `expired` / `deleted` / `error` |
| `subscriptionsLive`            | Leases Google is delivering on                                                      |
| `subscriptionsSuspended`       | Reactivatable — act promptly, the window is undocumented                            |
| `subscriptionsExpired`         | Not reactivatable. Recreate.                                                        |
| `subscriptionsMissing`         | Selected spaces with no live lease. **The number that matters.**                    |
| `subscriptionsByErrorCategory` | Non-delivering leases by `ConnectorErrorCategory`                                   |
| `nearestExpiryMinutes`         | Minutes until the nearest live lease lapses. Negative means one already has.        |

**`subscriptionsMissing` is the one to watch.** Because an expired lease is deleted, the live count
falls below the number of selected spaces while the connection still reads `connected`, the
credentials still validate and no error category is set. Nothing else in this product moves when
that happens.

There is no per-space breakdown and no space identifier anywhere in this aggregate — the input type
`SubscriptionRecord` has three fields (`state`, `suspension_category`, `expires_at`) and a test pins
that list, because the caller building those records is holding the space name while it does so.

### Suspension reasons, and how to tell them apart

Google suspends a subscription rather than deleting it, and the reason decides the response. They
fall into three families with nothing in common but the word "suspended".

| Reason                        | Whose problem   | Response                                                                                                        |
| ----------------------------- | --------------- | --------------------------------------------------------------------------------------------------------------- |
| `USER_SCOPE_REVOKED`          | The customer's  | A scope was withdrawn. They must re-authorise. **Do not re-issue anything.**                                    |
| `APP_SCOPE_REVOKED`           | The customer's  | An admin removed the app's grant org-wide. Contact them.                                                        |
| `RESOURCE_DELETED`            | Nobody's        | The space is gone. Deselect it; there is nothing to reconnect to.                                               |
| `USER_AUTHORIZATION_FAILURE`  | Possibly ours   | The user's credential failed. If it is the 7-day Testing-mode expiry, it is ours and it will recur weekly.      |
| `APP_AUTHORIZATION_FAILURE`   | Ours            | Our own credential. Rotate and reconnect.                                                                       |
| `ENDPOINT_PERMISSION_DENIED`  | **Ours, setup** | Google cannot publish to the topic. Check the publisher principal first — it is the fact that is not confirmed. |
| `ENDPOINT_NOT_FOUND`          | Ours, setup     | Wrong topic, or right topic in the wrong project.                                                               |
| `ENDPOINT_RESOURCE_EXHAUSTED` | Ours, capacity  | Our topic or endpoint is over quota. Back-pressure, not permission.                                             |
| `OTHER`                       | Unknown         | Google will not say. Treat as a gap in this table and report it.                                                |

Recovery is `subscriptions.reactivate`. **How long a suspended subscription stays reactivatable is
not documented** — so reactivate promptly rather than queueing it behind other work, and if
reactivation fails, recreate.

The reason itself is reduced to a `ConnectorErrorCategory` before it is stored or exported
(`SUSPENSION_REASON_CATEGORY`, total over Google's published set). That is why there is no
`suspension_reason` telemetry attribute and why none is needed: Google's suspension messages quote
the resource that failed, which here means space display names and the authorising person's address.

### The ack deadline

Chat arrives over a **Pub/Sub push** subscription, and the acknowledgement deadline **doubles as the
request timeout**.

- Default **10 seconds**, raisable to **600** — and raising it raises how long a push endpoint may
  block, which is a decision rather than a free win.
- **It cannot be extended for one message.** Push has no `modifyAckDeadline`; there is no
  per-message reprieve.
- A non-2xx **nacks**, and Pub/Sub redelivers with backoff between **100ms and 60s**. There is no
  fixed retry count — it redelivers until message retention expires.
- Delivery is **at-least-once**. Exactly-once is **pull-only**, and CAIRN receives by push, so every
  handler must be idempotent. A duplicated Chat message is a duplicated fact in someone's brief.

Acknowledge, then work — the same discipline as Slack's three seconds, with more room.

### Troubleshooting, in this order

The order is not arbitrary. Each step rules out a cause that would make the next step's evidence
meaningless, and the first two are first because they are cheap and they are the answer most of the
time.

1. **Is the authorising account a Workspace account?** A personal Gmail account cannot authorise
   this connector at all, and every credential, scope and endpoint check passes in that state. It
   costs one question and it is the Chat equivalent of "was the bot invited".
2. **Is the refresh token less than 7 days old, and is the app still in "Testing"?** If the consent
   screen is unpublished, the token expired on a schedule and will do so again next week. This is
   not an incident, it is the verification work not being finished — check it before you check
   anything that looks technical, because it explains a weekly pattern that otherwise reads as
   instability.
3. **Are the subscriptions alive?** `subscriptionsMissing` and `subscriptionsExpired` first, then
   `subscriptionsByState`. A lapsed lease is the failure mode unique to this connector: the
   connection reads `connected`, nothing errors, and no events arrive.
4. **How long until the next one lapses?** `nearestExpiryMinutes`. Under 120 minutes means the
   renewal loop has already missed its window; a negative number means a lease has gone and the
   space needs a **new** subscription, not a renewal.
5. **If they are suspended, which reason?** Use the table above. This decides whether the response
   is "contact the customer", "rotate our credential" or "fix our Pub/Sub setup", and the three have
   nothing in common.
6. **If the reason is an endpoint one, check the publisher principal.** It is the one fact in this
   connector that Google's documentation does not settle, and a wrong principal presents as a
   permission suspension rather than as a setup error.
7. **Is the push endpoint answering inside the ack deadline?** Repeated redelivery of the same
   events is the signature. Duplicates are expected at-least-once behaviour; a rising rate of them
   is a timeout.
8. **What does the connection say?** `workspacesByState` and `errorsByCategory` for the Google Chat
   row — the three causes at the top of this runbook, unchanged.
9. **Escalate.** Reading the customer's Chat messages is not the next step, and it is not a later
   step either.

### What is wired, and what is not

Kept as a table because the honest answer is neither "done" nor "not started", and every previous
version of this page rounded to one of the two.

| Piece                             | State                | Evidence                                                                                                                                                |
| --------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tables and row-level security     | **Wired**            | `migrations/versions/20260817_0300_google_chat.py`, revision `c5a92f7e4d18` on `e7b41c8d0392`; RLS + policy on all three tables                         |
| Configuration                     | **Wired**            | seven `google_chat_*` settings in `config.py`, with the redirect-URI HTTPS check                                                                        |
| Renewal sweep                     | **Wired and called** | `gchat/subscriptions.renew_expiring_subscriptions`, invoked from `jobs/main.py::run_maintenance`; covered by `test_gchat_subscriptions.py`              |
| Renewal staggering                | **Wired**            | `_stagger()` sleeps a uniform random interval between leases, so two workers that started together do not stay in lockstep                              |
| Recreate-vs-renew                 | **Wired**            | `_needs_creation()` takes the create path for a lapsed lease, including the case nothing marked expired                                                 |
| Pub/Sub push receiver             | **Wired**            | `api/routers/gchat_push.py`                                                                                                                             |
| Connector + subscription health   | Readable             | `GET /v1/internal/operations/connectors` carries `subscriptions`; Engineering and Security roles only, 404 for a customer session                       |
| Renewal telemetry                 | Wired                | `gchat/subscriptions.py` calls `record_subscription_renewal` per lease, and once per tenant whose pass raises; pinned by `test_gchat_subscriptions.py`  |
| Customer-facing connect flow      | **Wired, unusable**  | `api/routers/gchat.py` (install, callback, spaces, disconnect) and a Google Chat card on the Workspace screen. It cannot complete: see the release gate |
| Space picker in the app           | **Wired**            | `GoogleChatSpaces` in `routes/AdminPage.tsx` renders `SpacePicker`, but only once the connection is `connected`                                         |
| Google approvals and live traffic | **Not started here** | see the release gate below. Nothing in this repository can change this row                                                                              |

`apps/web/e2e/google-chat.e2e.ts` holds the customer-facing half to the code in a real browser: both
scope strings verbatim and **no third**, the Workspace-account sentence, the connect control present
for an Owner and absent for a Member, and — with nothing authorised at Google — no space named,
chosen or shown as delivering. It performs **no** OAuth round trip: everything past the Connect
button needs the approvals below, so the suite stops there rather than mocking a state the product
cannot reach.

### The manual release gate

**Google Chat cannot be released from this repository, and no amount of merged code changes that.**
The `connectors` release gate is `MANUAL` and structurally cannot be anything better. Every item
below is external, most have lead times measured in weeks, and the first is measured in months.

| Gate                                  | Why it blocks, and what it costs                                                                                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Restricted-scope OAuth verification   | `chat.messages.readonly` is RESTRICTED. Google's own verification, before anything else.                                                                                                               |
| CASA / Letter of Assessment           | An independent third-party security assessment ending in a Letter of Assessment, **re-taken at least every 12 months, forever**. Weeks to months of lead time. Start it before the code, not after it. |
| Google Cloud project                  | One project. The `spaces.messages.get` ceiling is **per project**, shared by every tenant in it.                                                                                                       |
| Google Chat API                       | Enabled, with the app configured.                                                                                                                                                                      |
| Workspace Events API                  | Enabled. This is what issues subscriptions; the Chat API alone delivers nothing.                                                                                                                       |
| Pub/Sub topic with authenticated push | Push to CAIRN's endpoint with an OIDC JWT, an explicit `aud` and a **verified service-account email**. An unauthenticated push endpoint accepts anybody's events.                                      |
| A real Google **Workspace** account   | For testing and for every customer. **A personal Gmail account cannot authorise this connector at all**, and every configuration check passes in that state.                                           |
| Real selected-space validation        | One real space, one real message, delivered end to end. Nothing short of this distinguishes "configured" from "working".                                                                               |

Until the app is published and verified the consent screen stays in **Testing**, and there refresh
tokens expire after **7 days** — so every customer connection breaks weekly until verification
completes. That is the launch blocker restated as an operational one.

To close the gate, in this order:

1. Confirm the restricted-scope security assessment is **started** — this gates the launch, not the
   merge.
2. Confirm the authorising account belongs to a Workspace organisation.
3. Confirm the Pub/Sub push subscription authenticates, with an explicit `aud` and a verified
   service-account email.
4. Add the app to one space and create the subscription.
5. Post one message in that space.
6. `GET /v1/internal/operations/connectors` and confirm the Google Chat row reports `inboundVerified`
   true.
7. Record what the Pub/Sub publisher principal turned out to be — the one fact Google's
   documentation does not settle. See the warning in Setup.
8. Re-run `uv run python -m cairn_api.ops.gates_cli` and record who validated it and when.

`deliveriesLastHour` stays `null` for Google Chat — there is no durable inbound record for it — so
`inboundVerified` is the field to read.

---

## What an operator must never do

- **Never read a customer's messages, channels or repositories to debug ingestion.** There is a
  consent-gated, time-boxed, customer-visible support session for reaching customer data
  (md/15 §5.2), it is approved by the customer's own Owner or Admin, and _even then_ it defaults to
  configuration and diagnostics — activity content needs a further, separate escalation. Debugging
  a connector is never a sufficient reason.
- **Never read a customer's Slack messages to debug ingestion.** Not one channel, not one message,
  not "just to see whether the text arrived intact". CAIRN holds `channels:history` for a
  workspace, which makes this technically trivial and is exactly why it is stated separately: the
  capability exists, the authorisation does not. If confirming what a message contained is genuinely
  the only way forward, that is a consent-gated, time-boxed, customer-visible support session
  (md/15 §5.2) with a further escalation for activity content — not a decision an operator makes
  during an incident.
- **Never read a customer's Google Chat messages to debug ingestion.** Not one space, not one
  message, not "just to confirm the event arrived intact". CAIRN holds `chat.messages.readonly`, so
  this is technically trivial — which is exactly why it is stated separately from the Slack line
  above. The capability exists; the authorisation does not. If confirming what a message contained is
  genuinely the only way forward, that is a consent-gated, time-boxed, customer-visible support
  session (md/15 §5.2) with a further escalation for activity content, approved by the customer's
  own Owner or Admin — never a decision an operator makes during an incident. A Chat space's display
  name is frequently the most sensitive string a customer holds ("Acme × Northwind diligence",
  "redundancy planning"), which is why CAIRN stores space resource names and never display names.
- **Never re-issue or rotate credentials in response to `disconnected` or `revoked`.** That is a
  customer decision. Contact them. For Slack, `app_uninstalled` and `tokens_revoked` both mean this,
  and either can arrive first.
- **Never send `x-slack-no-retry: 1` for a transient failure.** It tells Slack the rejection is
  permanent, and the event is never offered again.
- **Never add a per-channel, per-space or per-account count to make this easier to diagnose.** A
  per-channel count is a per-team productivity metric with a different label, and md/05 §B.2
  forbids the shape. A structural test rejects it.
- **Never put a provider's error text into telemetry, a log line, or the read model.** Provider
  errors quote the request that failed, which for Slack and Chat means channel names, user handles
  and sometimes message fragments. Reduce to a `ConnectorErrorCategory` at the point of failure.
- **Never read the credential.** `SourceConnection._secret_ciphertext` is private by name and there
  is no property that returns it. Reading plaintext is `connectors.credentials.read_secret`, which
  is an import, a call and a line in a diff somebody can review — that visibility is the point.

---

## What this runbook cannot tell you yet

- **No provider writes `health` or `last_successful_sync_at`.** GitHub's rows are projected from
  `github_installations` by a migration trigger, and that table never recorded either, so every
  GitHub connection reads as never-synced with `unknown` health. For GitHub, the delivery counts
  are the real signal. The health and sync-age columns become meaningful per provider as Step 32's
  connectors start writing them.
- **Only GitHub has a durable inbound record.** Slack and Google Chat report `null` delivery counts
  with a reason rather than zero, because a zero here would read as "connected and quiet".
- **How close a Slack workspace is to its 30,000-event ceiling.** The ceiling is per workspace per
  hour; these counts are platform-wide, and Slack has no inbound record here to count at all. The
  published number is on the Python read model (`event_budget_per_hour`, warn at
  `event_budget_alert_at`) and not yet on the API response, and the comparison is manual either
  way. Closing it needs a per-workspace inbound event count —
  `record_connector_delivery` already accepts a `tenant_id`, which is on the telemetry allow-list;
  the Slack connector has to pass it.
- **Whether a Slack delivery was acknowledged inside 3 seconds.** No latency is recorded at the
  webhook boundary yet, so a workspace losing every event to `http_timeout` is visible only as a
  silence. `x-slack-retry-reason` is the evidence, and it is in the provider's request rather than
  in anything CAIRN stores.
- **Google Chat's subscription counts are readable.** Closed.
  `/v1/internal/operations/connectors` carries `subscriptions`, so `subscriptionsMissing` — the
  number this connector's worst failure mode moves — can be read by the staff who would be paged for
  it. Proven by tests over real rows: fleet-wide counts across two workspaces, the empty case, the
  unconfigured case reporting unobservable rather than zero, and an assertion that no space resource
  name, tenant id or connection id appears anywhere in the response body.
- **Whether a Chat renewal actually ran is now measured.** Closed. `gchat/subscriptions.py` calls
  `ops/connectors.record_subscription_renewal` at the per-lease site, carrying the bounded
  `RenewalAction` word as `outcome`, and once with `failed` for a tenant whose entire pass raises —
  without that second call the worst failure, a whole workspace renewing nothing, was the only one
  absent from the counter. The sweep itself was already wired: `jobs/main.py::run_maintenance`
  invokes `renew_expiring_subscriptions` every maintenance pass. `cairn.connector.subscription_renewals`
  therefore distinguishes a sweep that is failing from a sweep that stopped.
- **Whether a Chat connection can be _completed_.** The connect flow exists end to end in the
  product — a card, an install route, a callback, a space picker — and it stops at Google. Without
  restricted-scope verification, the assessment and a Workspace account, no authorisation succeeds,
  so every subscription reading above still describes rows that only a test or a manual insert
  creates today. A wired connect button is not a connected connector.
- **Whether the Pub/Sub publisher principal is the one Google documents for Chat interaction
  events.** Unconfirmed, and a wrong guess presents as `ENDPOINT_PERMISSION_DENIED` rather than as a
  setup error. Verify it in a real project and record what you saw.
- **How long a suspended Chat subscription stays reactivatable.** Not documented by Google. Act
  promptly rather than relying on a window nobody has published.
- **Nothing is alerting on any of this.** The thresholds in `docs/OPERATIONS.md` have no
  destination and nobody is paged. Somebody has to open the screen.
