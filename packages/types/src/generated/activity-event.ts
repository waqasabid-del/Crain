/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source of truth: apps/api/src/cairn_api/events/schema.py
 * Regenerate with: make schema
 *
 * A test fails if this file is out of date, so drift between the Python model
 * and these types cannot reach production.
 */

/**
 * Resolved person, mirrored onto the envelope for cheap filtering.
 */
export type Actorid = string | null;
/**
 * Source-specific verb: merged, sent, decided.
 */
export type Action = string;
/**
 * The four capture pillars every source normalizes into.
 */
export type ActivityCategory = "code" | "conversation" | "meeting" | "document";
export type ProjectRef = string | null;
/**
 * One-line human-readable description. Embedded for retrieval rather than the raw content — summarising before embedding cuts retrieval failures substantially (md/09 §4.4).
 */
export type Summary = string;
/**
 * Additional contributors, first-class rather than an afterthought. Squash merges collapse a branch into one commit, so pair and mob work is systematically erased unless co-authorship is modelled explicitly (md/01 §5.1).
 */
export type CoActors = string[];
export type DisplayName = string | null;
/**
 * Bot activity is retained as project context but excluded from human attribution. Dependabot can out-commit every human on a team, so filtering at the schema level means the rule cannot be forgotten by one consumer downstream.
 */
export type IsBot = boolean;
/**
 * Identity as the source reported it — an email, handle or user ID.
 */
export type RawIdentity = string;
/**
 * CAIRN person this resolves to. Null before identity resolution runs. One human may appear under several raw identities — a work email, a personal email, a GitHub handle — and treating those as different people would fragment their contribution record.
 */
export type ResolvedPersonId = string | null;
export type Text = string | null;
/**
 * How much CAIRN trusts a claim.
 *
 * Categorical, never numeric. A "73% confident" badge looks rigorous, means
 * nothing to a non-technical reader, and invites false precision. Internal
 * numeric confidence exists for thresholds and evaluation, but it never
 * reaches this field or the interface (md/05 §A.2.1).
 */
export type Certainty = "verified" | "observed" | "suggested";
/**
 * Transcript offset for meeting-derived events, enabling one-click verification (md/03 §6). Null for other sources.
 */
export type SourceTimestampRef = string | null;
/**
 * Something a human can open. Provenance is a product feature, not a debug aid.
 */
export type SourceUrl = string | null;
export type Datacontenttype = "application/json";
export type Dataschema = string | null;
/**
 * Unique per event. Combined with `source`, this is the idempotency key — webhook redelivery is normal, so duplicates must upsert rather than create a second record (md/01 §4.1).
 */
export type Id = string;
/**
 * When CAIRN received the event. Diverges from `time` routinely — backfill imports 90 days in minutes. Operational views order by this; user-facing views never do.
 */
export type Ingestedat = string;
/**
 * Producer URI-reference, e.g. /github/12345 or /slack/T0001.
 */
export type Source = string;
export type Specversion = "1.0";
/**
 * Entity acted upon — repository, channel or meeting identifier.
 */
export type Subject = string | null;
/**
 * Owning workspace. Mandatory on every event, no exceptions. This lives on the envelope rather than inside the payload so that a background job cannot lose tenant context — the context is structurally inseparable from the event (md/06 §4.3).
 */
export type Tenantid = string;
/**
 * When the activity **happened**, not when CAIRN received it. Every user-facing view orders by this. Conflating it with ingestion time produces a brief claiming today's work that actually happened in March (md/12 §3.2).
 */
export type Time = string;
/**
 * W3C trace context, correlating this event with its cause (md/10 §7).
 */
export type Traceparent = string | null;
/**
 * Reverse-DNS with a version suffix, per the CloudEvents convention: ai.cairn.github.pull_request.merged.v1. The version lives in the type so a breaking change produces a new type rather than silently altering the meaning of an existing one (md/12 §4).
 */
export type Type = string;

/**
 * A CloudEvents 1.0 envelope carrying a CAIRN activity payload. Generated from apps/api/src/cairn_api/events/schema.py — edit that, not this.
 */
export interface ActivityEvent {
  actorid?: Actorid;
  data: ActivityPayload;
  datacontenttype?: Datacontenttype;
  dataschema?: Dataschema;
  id: Id;
  ingestedat?: Ingestedat;
  source: Source;
  specversion?: Specversion;
  subject?: Subject;
  tenantid: Tenantid;
  time: Time;
  traceparent?: Traceparent;
  type: Type;
}
/**
 * The CAIRN-defined ``data`` section of the CloudEvent.
 */
export interface ActivityPayload {
  activity: Activity;
  actor: Actor;
  content?: Content;
  provenance: Provenance;
}
/**
 * What happened.
 */
export interface Activity {
  action: Action;
  category: ActivityCategory;
  project_ref?: ProjectRef;
  summary: Summary;
}
/**
 * Who did the thing.
 */
export interface Actor {
  co_actors?: CoActors;
  display_name?: DisplayName;
  is_bot?: IsBot;
  raw_identity: RawIdentity;
  resolved_person_id?: ResolvedPersonId;
}
/**
 * Optional payload detail.
 *
 * Frequently absent by design. Raw diffs stay out of the pipeline by default
 * (md/01 §6.3) and non-work-relevant chat is excluded entirely (md/02 §7.1),
 * so **missing content is the normal case, not a degraded one.**
 */
export interface Content {
  metadata?: Metadata;
  text?: Text;
}
export interface Metadata {
  [k: string]: unknown;
}
/**
 * Where the claim came from, and how much to trust it.
 */
export interface Provenance {
  certainty: Certainty;
  source_timestamp_ref?: SourceTimestampRef;
  source_url?: SourceUrl;
}
