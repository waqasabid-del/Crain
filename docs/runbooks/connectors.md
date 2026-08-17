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
- **Nothing is alerting on any of this.** The thresholds in `docs/OPERATIONS.md` have no
  destination and nobody is paged. Somebody has to open the screen.
