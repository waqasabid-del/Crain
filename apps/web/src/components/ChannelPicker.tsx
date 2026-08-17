"use client";

import type {
  GoogleChatSpace,
  GoogleChatSpaceList,
  GoogleChatSpaceSelection,
  SlackChannelList,
  SlackChannelSelection,
} from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import type { DescribedError } from "../errors.js";
import utility from "../styles/utility.module.css";
import styles from "./ChannelPicker.module.css";
import { GOOGLE_CHAT_NO_HISTORY, SLACK_NO_HISTORY } from "./ConnectionCard.js";
import { formatDayAndTime } from "./dates.js";
import { Field } from "./Field.js";
import { headingTag, type HeadingLevel } from "./headings.js";
import { InlineProblem } from "./InlineProblem.js";

/**
 * Which rooms CAIRN reads — Slack channels, and Google Chat spaces.
 *
 * **A tick here means the backend said so.** Every other selection control in
 * every other product updates optimistically and reconciles later, and that is
 * usually the right trade — a wrong tick on a filter costs nothing. This one is
 * a claim about surveillance. A room drawn as selected when the save was refused
 * tells somebody CAIRN is reading a place it is not, and a room drawn as
 * unselected when it was saved tells them the opposite. Both are worse than a
 * moment of latency, so `selected` is read from the last answer the server gave
 * and from nowhere else; a save in flight is announced as *saving*, which is
 * what is actually true, and the checkbox does not move until the answer
 * arrives.
 *
 * The API expresses that per room — `SlackChannelResponse.selected`, and the
 * same shape for a space — rather than as a parallel array of IDs, so there is
 * no way to render a tick for a room the server did not describe. `PUT` answers
 * with IDs only, and `reconcileChannels` / `reconcileSpaces` are the one place
 * that folds those back onto the list.
 *
 * **The names come from the backend too.** Slack's message events carry channel
 * IDs and no names, and a Google Chat space's `displayName` is Google's to give,
 * so a name on this screen can only ever be one the API returned. Nothing here
 * derives, formats or guesses one.
 *
 * **One picker, two providers.** `SourcePicker` below is the whole control — the
 * disclosure, the search, the checkboxes, the focus handling, the honesty rule —
 * and `ChannelPicker` and `SpacePicker` are the two vocabularies it is dressed
 * in. Slack and Google Chat differ in what a row can be *wrong* about (an
 * uninvited bot; an expired subscription) and in nothing else, so they must not
 * differ in how a reader operates them.
 *
 * A disclosure rather than an always-open list: the answer to "what is CAIRN
 * reading" is the summary line, and a workspace with two hundred channels should
 * not make somebody scroll past all of them to find it.
 */

// --------------------------------------------------------------------------
// The picker itself, in the terms both providers share
// --------------------------------------------------------------------------

/**
 * One row, already reduced to what the control needs to draw.
 *
 * `note` is what is *true* about the row, in words — never a colour, never an
 * icon on its own (WCAG 1.4.1). The wrapper decides it, because "the app has not
 * been invited here" and "this subscription expired" are the same kind of fact
 * about two different systems.
 */
interface PickerItem {
  id: string;
  /** Exactly as the reader sees it — `#general`, or a space's display name. */
  label: string;
  /** The server's last answer, and never the reader's last click. */
  selected: boolean;
  note: ReactNode | null;
  /**
   * The row is shown but cannot be chosen — an ineligible Google Chat space.
   *
   * Disabled rather than omitted, and never without a `note` saying why: a room
   * missing from the list is indistinguishable from one that does not exist, and
   * a control that refuses without explaining reads as a fault.
   */
  disabled?: boolean;
  /** Something to *do* about the row, when the note says it is broken. A note
   * that reports a failure and offers nothing is a dead end. */
  action?: { label: string; onClick: () => void };
}

/** Everything the two providers say differently. */
interface PickerCopy {
  heading: string;
  /** The disclosure's two labels. Different words, because "Done" alone does not
   * say what it is done with. */
  open: string;
  close: string;
  searchLabel: string;
  searchHint: string;
  /** Names the `<fieldset>`, which is otherwise an unlabelled group of
   * checkboxes to a screen reader. */
  groupLabel: string;
  /**
   * Heads the read-only list — "Selected channels", "Selected spaces".
   *
   * The same two words on both providers, because a reader moving between the
   * Slack card and the Google Chat card is looking at one product. It also
   * names the list for a screen reader, which otherwise meets an unlabelled
   * `<ul>` immediately after a summary sentence and has to infer the relation.
   */
  selectedLabel: string;
  /** One room, then many. Used for the count and nothing else. */
  unit: [string, string];
  /** Said while a save is in flight, in place of whatever the row said before —
   * because while it is in flight the row's state is out of date by definition. */
  savingNote: string;
  noMatch: (query: string) => string;
  /** The provider listed nothing at all. Not the same as "nothing matched". */
  none: string;
}

interface SourcePickerProps {
  copy: PickerCopy;
  items: PickerItem[];
  /** The whole selection in one sentence, decided by the wrapper. */
  summary: string;
  /** Standing rules, shown where the choosing happens. Empty when the server has
   * not sent one — a rule this client invented would be a rule nothing
   * enforces. */
  rules: ReactNode[];
  canManage: boolean;
  onToggle?: (id: string, next: boolean) => void;
  saving: readonly string[];
  readOnlyNote: ReactNode;
  problem?: DescribedError;
  headingLevel: HeadingLevel;
}

function SourcePicker({
  copy,
  items,
  summary,
  rules,
  canManage,
  onToggle,
  saving,
  readOnlyNote,
  problem,
  headingLevel,
}: SourcePickerProps): ReactNode {
  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const Heading = headingTag(headingLevel);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const triggerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);

  const editable = canManage && onToggle !== undefined;

  /*
   * Focus follows the disclosure and comes back when it closes.
   *
   * Opening moves it to the search box, which is where somebody who just asked
   * to choose rooms wants to be typing — not at the top of a list of two hundred
   * checkboxes they now have to tab through. Closing returns it to the trigger,
   * looked up live because React has just re-mounted it; without that a keyboard
   * reader is dropped at the top of the document, several sections above where
   * they were working.
   */
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      panelRef.current?.querySelector<HTMLInputElement>("input[type='search']")?.focus();
      return;
    }
    if (wasOpen.current) {
      wasOpen.current = false;
      triggerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    }
  }, [open]);

  const selected = items.filter((item) => item.selected);
  const filtered = filterItems(items, query);

  return (
    <div className={styles.picker}>
      <Heading className={styles.heading}>{copy.heading}</Heading>

      {/*
        The answer to "what is CAIRN reading", before any control. Built only
        from names the backend returned.
      */}
      <p className={styles.summary}>{summary}</p>

      {editable ? (
        <>
          <div className={styles.trigger} ref={triggerRef}>
            <Button
              size="sm"
              variant="secondary"
              aria-expanded={open}
              // Only while the panel exists. `aria-controls` pointing at an id
              // that is not in the document is an invalid attribute value, and
              // some screen readers offer a "go to controlled element" command
              // that then goes nowhere. `aria-expanded` carries the state on its
              // own when the panel is closed.
              aria-controls={open ? panelId : undefined}
              onClick={() => {
                setOpen((was) => !was);
              }}
            >
              {open ? copy.close : copy.open}
            </Button>
          </div>

          {open && (
            <div className={styles.panel} id={panelId} ref={panelRef}>
              {/*
                The rules that decide whether any of this works, at the point of
                choosing rather than in a help article. The server's own sentence
                comes first wherever there is one, precisely so the client cannot
                keep a second copy of it that slowly stops matching what the
                backend actually enforces.
              */}
              {rules.map((rule, index) => (
                // Index keys: a fixed, ordered list of sentences with no
                // identity of their own and no reordering.
                <p className={styles.rule} key={index}>
                  {rule}
                </p>
              ))}

              <Field
                label={copy.searchLabel}
                hint={copy.searchHint}
                type="search"
                value={query}
                autoComplete="off"
                onChange={(event) => {
                  setQuery(event.target.value);
                }}
              />

              {/* Polite, and the only announcement the filtering makes: the list
                  itself re-rendering says nothing to a screen reader. */}
              <p className={styles.count} role="status">
                {countLabel(filtered.length, items.length, copy.unit)}
              </p>

              <fieldset className={styles.group}>
                <legend className={utility.visuallyHidden}>{copy.groupLabel}</legend>

                {filtered.length === 0 ? (
                  <p className={styles.empty}>
                    {items.length === 0 ? copy.none : copy.noMatch(query)}
                  </p>
                ) : (
                  <ul className={styles.list}>
                    {filtered.map((item) => (
                      <PickerRow
                        key={item.id}
                        idBase={baseId}
                        item={item}
                        saving={saving.includes(item.id)}
                        savingNote={copy.savingNote}
                        onToggle={onToggle}
                      />
                    ))}
                  </ul>
                )}
              </fieldset>
            </div>
          )}
        </>
      ) : (
        <>
          {/*
            Read-only readers get the list itself, not only the count — and each
            row's note with it. What CAIRN reads from their workspace is a fact
            about their own messages, and a summary they cannot expand is one
            they have to take on trust. The note is the half that matters most
            here: a space listed as selected whose subscription has expired is
            not delivering, and a list that omits that says the opposite.
          */}
          {selected.length > 0 && (
            <>
              <p className={styles.readOnlyHeading} id={`${baseId}-selected`}>
                {copy.selectedLabel}
              </p>
              <ul className={styles.readOnlyList} aria-labelledby={`${baseId}-selected`}>
                {selected.map((item) => (
                  <li key={item.id}>
                    {item.label}
                    {item.note !== null && <p className={styles.rowNote}>{item.note}</p>}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className={styles.readOnly}>{readOnlyNote}</p>
        </>
      )}

      {problem !== undefined && (
        <div className={styles.problem}>
          <InlineProblem error={problem} />
        </div>
      )}
    </div>
  );
}

/**
 * One row, with its state said in words beside it.
 *
 * The checkbox's accessible *name* is the room and nothing else; the state hangs
 * off `aria-describedby`. Wrapping the note inside the `<label>` would fold
 * "Saving" into the name, so the control would be announced as a different
 * control every time its state changed — and "#general saving" is not what the
 * checkbox is called.
 */
function PickerRow({
  idBase,
  item,
  saving,
  savingNote,
  onToggle,
}: {
  idBase: string;
  item: PickerItem;
  saving: boolean;
  savingNote: string;
  onToggle: ((id: string, next: boolean) => void) | undefined;
}): ReactNode {
  const inputId = `${idBase}-${item.id}`;
  const noteId = `${inputId}-note`;
  // "Saving" wins over everything, because while it is true the tick is out of
  // date by definition.
  const note = saving ? savingNote : item.note;

  return (
    <li className={styles.row}>
      <input
        className={styles.checkbox}
        id={inputId}
        type="checkbox"
        // Never the reader's last click: the server's last answer. A controlled
        // checkbox React re-renders with the same value snaps back, which is
        // exactly the behaviour wanted here.
        checked={item.selected}
        // Disabled while saving, and permanently for a row the provider will not
        // let CAIRN read. Both keep the tick honest: one because the answer is
        // not back yet, the other because there is no answer to be had.
        disabled={saving || item.disabled === true}
        aria-busy={saving || undefined}
        aria-describedby={note === null ? undefined : noteId}
        onChange={(event) => {
          onToggle?.(item.id, event.target.checked);
        }}
      />
      <label className={styles.channelName} htmlFor={inputId}>
        {item.label}
      </label>
      {note !== null && (
        <p className={styles.rowNote} id={noteId}>
          {note}
        </p>
      )}
      {/* Offered only while the row is idle: a retry pressed against a save
          already in flight would ask for the same thing twice. */}
      {item.action !== undefined && !saving && (
        <div className={styles.rowAction}>
          <Button size="sm" variant="secondary" onClick={item.action.onClick}>
            {item.action.label}
          </Button>
        </div>
      )}
    </li>
  );
}

/** Case-insensitive, and tolerant of the `#` people type out of habit. */
function filterItems(items: PickerItem[], query: string): PickerItem[] {
  const needle = query.trim().replace(/^#/, "").toLowerCase();
  if (needle === "") return items;
  return items.filter((item) => item.label.toLowerCase().includes(needle));
}

function countLabel(shown: number, total: number, [one, many]: [string, string]): string {
  if (shown === total) return `${String(total)} ${total === 1 ? one : many}.`;
  return `${String(shown)} of ${String(total)} ${many} match.`;
}

/**
 * The selection in one sentence.
 *
 * Names every selected room, which the API makes possible without a lookup:
 * `selected` is a property of the room, so a chosen one is by construction one
 * the server also named. There is no counted-but-unnamed case left to round in
 * either direction.
 */
function summarise(selected: PickerItem[], [one, many]: [string, string], nothing: string): string {
  if (selected.length === 0) return nothing;

  const count = `${String(selected.length)} ${selected.length === 1 ? one : many}`;
  const list = selected.map((item) => item.label).join(", ");
  return `CAIRN is reading ${count}: ${list}.`;
}

/**
 * A picker-shaped placeholder.
 *
 * Matches the dimensions of the summary and the trigger that replace it, so the
 * card does not jump when the list lands. Silent to assistive technology; the
 * `role="status"` line makes the one announcement.
 */
function PickerLoading({ label }: { label: string }): ReactNode {
  return (
    <div className={styles.loading} role="status">
      <span className={utility.visuallyHidden}>Loading {label}.</span>
      <span className={styles.skeletonLine} aria-hidden="true" />
      <span className={styles.skeletonLine} aria-hidden="true" />
    </div>
  );
}

// --------------------------------------------------------------------------
// Slack channels
// --------------------------------------------------------------------------

/**
 * One channel, exactly as the API describes it.
 *
 * Derived from the generated response rather than restated, so a field added or
 * renamed on the server is a compile error here rather than a row that quietly
 * stops rendering.
 */
type SlackChannel = NonNullable<SlackChannelList["channels"]>[number];

export interface ChannelPickerProps {
  /** The list the server returned, with `selected` already decided on it. */
  selection: SlackChannelList;
  /** Owners and Admins. Everybody else gets the same record, read-only. */
  canManage: boolean;
  /** Called with the channel and the value the reader asked for. The caller
   * saves it and passes back whatever the server confirmed. */
  onToggle?: (channelId: string, next: boolean) => void;
  /** Channels with a save in flight. Announced, never ticked. */
  saving?: readonly string[];
  /** Named, because absence is not an explanation. */
  readOnlyNote?: ReactNode;
  /** A refused save, said next to the control that was pressed. */
  problem?: DescribedError;
  /** Where this sits under the page's `<h1>`. Default 4 — it lives inside a
   * connection card, which is itself an `<h3>`. */
  headingLevel?: HeadingLevel;
}

/** Said to a reader whose role may not change the selection. */
export const CHANNEL_READ_ONLY_NOTE =
  "An Owner or an Admin of this workspace chooses which channels CAIRN reads, in Workspace settings. This is the same list they see.";

const CHANNEL_COPY: PickerCopy = {
  heading: "Channels CAIRN reads",
  open: "Choose channels",
  close: "Done choosing channels",
  searchLabel: "Search channels",
  searchHint: "Public channels only. CAIRN cannot list private channels or direct messages.",
  groupLabel: "Public channels CAIRN reads",
  selectedLabel: "Selected channels",
  unit: ["channel", "channels"],
  savingNote: "Saving your choice. Nothing changes until Slack and CAIRN both confirm it.",
  noMatch: (query) => `No public channel matches “${query}”.`,
  none: "Slack returned no public channels for this workspace. CAIRN can only list channels Slack shows it.",
};

/**
 * The list, with the selection the server just confirmed written onto it.
 *
 * `PUT /channels` answers with `channelIds` and no names — deliberately, since
 * the names are `conversations.list`'s to give and not a write endpoint's. This
 * is the single place that folds that answer back onto the channels the `GET`
 * described, so the tick still comes from server-confirmed state and from
 * nowhere else. Anything absent from `channelIds` is unselected: the request was
 * the full state of the checkboxes, so a missing ID is a channel the server
 * declined to keep, not a channel it forgot to mention.
 */
export function reconcileChannels(
  list: SlackChannelList,
  confirmed: SlackChannelSelection,
): SlackChannelList {
  const chosen = new Set(confirmed.channelIds ?? []);

  return {
    channels: (list.channels ?? []).map((channel) => ({
      ...channel,
      selected: chosen.has(channel.id),
    })),
    // The server's own copy, from the response that is now current. Keeping the
    // older list's sentence here would be the one place the two could drift.
    notice: confirmed.notice,
  };
}

export function ChannelPicker({
  selection,
  canManage,
  onToggle,
  saving = [],
  readOnlyNote = CHANNEL_READ_ONLY_NOTE,
  problem,
  headingLevel = 4,
}: ChannelPickerProps): ReactNode {
  const items = (selection.channels ?? []).map(channelItem);

  return (
    <SourcePicker
      copy={CHANNEL_COPY}
      items={items}
      summary={summarise(
        items.filter((item) => item.selected),
        CHANNEL_COPY.unit,
        "No channels chosen, so CAIRN is reading nothing from Slack.",
      )}
      rules={[
        // The API sends this sentence with every channel response precisely so
        // the client cannot keep a second copy that stops matching what the
        // backend enforces.
        selection.notice,
        // Not a server field: no endpoint has an opinion about backfill, because
        // there is no backfill to have an opinion about.
        SLACK_NO_HISTORY,
      ]}
      canManage={canManage}
      {...(onToggle === undefined ? {} : { onToggle })}
      saving={saving}
      readOnlyNote={readOnlyNote}
      {...(problem === undefined ? {} : { problem })}
      headingLevel={headingLevel}
    />
  );
}

function channelItem(channel: SlackChannel): PickerItem {
  return {
    id: channel.id,
    label: `#${channel.name}`,
    selected: channel.selected,
    note: channelNote(channel),
  };
}

/**
 * What is true about this channel, or nothing.
 *
 * **`botIsMember: false` is the most important line this component draws.**
 * CAIRN does not ask Slack for `channels:join`, so a channel selected while the
 * app is not in it delivers nothing at all, silently and forever. That is the
 * single most common reason somebody connects Slack and concludes the product is
 * broken, and from a screen that does not say so they would be right to.
 */
function channelNote(channel: SlackChannel): string | null {
  if (!channel.botIsMember) {
    return "The CAIRN app is not in this channel, so nothing arrives from it yet. Run /invite @CAIRN there.";
  }
  if (channel.selected) return "The CAIRN app is in this channel.";
  return null;
}

export function ChannelPickerLoading(): ReactNode {
  return <PickerLoading label="the Slack channels" />;
}

// --------------------------------------------------------------------------
// Google Chat spaces
// --------------------------------------------------------------------------

/** Said to a reader whose role may not change the selection. */
export const SPACE_READ_ONLY_NOTE =
  "An Owner or an Admin of this workspace chooses which Google Chat spaces CAIRN reads, in Workspace settings. This is the same list they see.";

const SPACE_COPY: PickerCopy = {
  heading: "Spaces CAIRN reads",
  open: "Choose spaces",
  close: "Done choosing spaces",
  searchLabel: "Search spaces",
  searchHint:
    "The spaces the Google Workspace account that authorised CAIRN can already see. CAIRN cannot list direct messages, and does not ask Google for them.",
  groupLabel: "Google Chat spaces CAIRN reads",
  selectedLabel: "Selected spaces",
  unit: ["space", "spaces"],
  savingNote: "Saving your choice. Nothing changes until Google and CAIRN both confirm it.",
  noMatch: (query) => `No space matches “${query}”.`,
  none: "Google returned no spaces for this account. CAIRN can only list spaces the account that authorised it can see.",
};

export interface SpacePickerProps {
  /** The list the server returned, with `selected` already decided on it. */
  spaces: GoogleChatSpaceList;
  canManage: boolean;
  /** Called with Google's resource name — `spaces/AAAA…` — and the value the
   * reader asked for. Never the display name: two spaces may share one. */
  onToggle?: (spaceName: string, next: boolean) => void;
  /** Spaces with a save in flight. Announced, never ticked. */
  saving?: readonly string[];
  readOnlyNote?: ReactNode;
  problem?: DescribedError;
  headingLevel?: HeadingLevel;
}

/**
 * The list, with the selection the server just confirmed written onto it.
 *
 * The same rule as Slack's, for the same reason: `PUT` answers with resource
 * names, and this is the one place that turns those back into ticks. A name
 * missing from the answer is a space the server declined to keep, not one it
 * forgot to mention — the request was the full state of the checkboxes.
 *
 * `notice` is taken from the confirmation rather than carried over from the
 * older list, because the confirmation is the response that is now current and
 * keeping both would be the one place the two could drift.
 */
export function reconcileSpaces(
  list: GoogleChatSpaceList,
  confirmed: GoogleChatSpaceSelection,
): GoogleChatSpaceList {
  const chosen = new Set(confirmed.spaceNames);

  return {
    spaces: (list.spaces ?? []).map((space) => ({ ...space, selected: chosen.has(space.name) })),
    notice: confirmed.notice,
  };
}

export function SpacePicker({
  spaces,
  canManage,
  onToggle,
  saving = [],
  readOnlyNote = SPACE_READ_ONLY_NOTE,
  problem,
  headingLevel = 4,
}: SpacePickerProps): ReactNode {
  const items = (spaces.spaces ?? []).map(spaceItem);

  return (
    <SourcePicker
      copy={SPACE_COPY}
      items={items}
      summary={summarise(
        items.filter((item) => item.selected),
        SPACE_COPY.unit,
        "No spaces chosen, so CAIRN is reading nothing from Google Chat.",
      )}
      rules={[
        // The API sends its own sentence with every space response, precisely so
        // the client cannot keep a second copy that stops matching what the
        // backend enforces.
        spaces.notice,
        // Not a server field: no endpoint has an opinion about backfill, because
        // there is no backfill to have an opinion about.
        GOOGLE_CHAT_NO_HISTORY,
      ]}
      canManage={canManage}
      {...(onToggle === undefined ? {} : { onToggle })}
      saving={saving}
      readOnlyNote={readOnlyNote}
      {...(problem === undefined ? {} : { problem })}
      headingLevel={headingLevel}
    />
  );
}

/**
 * One space as the control needs it.
 *
 * The id is Google's resource name and the label is the display name Google
 * gave, never derived from one another: a resource name is not a name, and
 * putting `spaces/AAAAQ_x1` in front of somebody does not identify the room.
 *
 * `selected` is copied straight from the server's answer even when the space is
 * ineligible. A space CAIRN was reading and can no longer read is a fact the
 * reader needs; quietly drawing it as unselected would be this component telling
 * a comfortable lie about what the backend actually holds.
 */
function spaceItem(space: GoogleChatSpace): PickerItem {
  const item: PickerItem = {
    id: space.name,
    label: space.displayName,
    selected: space.selected,
    note: spaceNote(space),
  };
  // Ineligible spaces are shown, not hidden: a space missing from the list is
  // indistinguishable from one that does not exist, and "why is Incidents not
  // here" is a question the screen should answer rather than raise.
  if (!space.eligible) item.disabled = true;
  return item;
}

/**
 * What is true about this space, in words.
 *
 * **Selected is not the same as delivering.** Google Chat carries events through
 * subscriptions that expire on Google's schedule and are renewed automatically,
 * and a renewal fails whenever the authorising account loses access to the space
 * or the grant is withdrawn. When that happens the space stops delivering,
 * silently. So the subscription state is carried per space and said as a word —
 * never as a colour, and never rounded up to "healthy" when the server has not
 * said so.
 *
 * An unselected, eligible space says nothing at all: a subscription note against
 * a space nobody chose sends somebody to fix a problem they do not have.
 */
function spaceNote(space: GoogleChatSpace): ReactNode | null {
  if (!space.eligible) return ineligibleReason(space.errorCategory);
  if (!space.selected) return null;

  switch (normaliseState(space.subscriptionState)) {
    case "active":
      return (
        <>
          Selected, and the subscription is active, so messages from this space are reaching CAIRN.
          {expiry(space.expireTime, "Renews by")}
        </>
      );
    case "renewing":
      return (
        <>
          Selected, and the subscription is renewing. CAIRN renews it automatically; if the renewal
          fails — usually because the account that authorised Google Chat lost access to this space
          — the space stops delivering.
          {expiry(space.expireTime, "Renews by")}
        </>
      );
    case "expired":
      return (
        <>
          Selected, but the subscription expired and was not renewed, so nothing is arriving from
          this space. Reconnecting Google Chat starts a new one.
          {expiry(space.expireTime, "Expired on")}
        </>
      );
    case "suspended":
      return (
        <>
          Selected, but the subscription is suspended, so nothing is arriving from this space.
          Google suspends a subscription when it can no longer deliver to it.
          {expiry(space.expireTime, "Lapses on")}
          {failureReason(space.errorCategory)}
        </>
      );
    case "failed":
      return (
        <>
          Selected, but the subscription failed, so nothing is arriving from this space.
          {expiry(space.expireTime, "Lapses on")}
          {failureReason(space.errorCategory)}
        </>
      );
    case "pending":
      // "We have not asked Google yet" and "we asked and Google has not
      // answered" are different things to be looking at while a feed is empty,
      // and the API distinguishes them deliberately. So does this.
      return (
        <>
          Selected, and CAIRN has asked Google to start delivering from this space. Nothing arrives
          until Google confirms it.
        </>
      );
    case "deleted":
      return (
        <>
          Selected, but the subscription has been deleted at Google, so nothing is arriving from
          this space. Reconnecting Google Chat starts a new one.
          {failureReason(space.errorCategory)}
        </>
      );
    default:
      // No subscription state from the server is not a healthy space. It is a
      // space CAIRN cannot yet say anything about, which is what it says.
      return (
        <>
          Selected. CAIRN has not recorded a subscription for this space, so it cannot say that
          anything is arriving from it.
        </>
      );
  }
}

/**
 * The states this client knows how to say, and nothing else.
 *
 * The keys are the server's vocabulary — `GoogleChatSubscriptionState` — and the
 * values are the words a reader is shown. `error` is said as *failed* because
 * "error" describes the system's experience and "nothing is arriving from this
 * space" describes theirs.
 *
 * An unrecognised word from the server falls through to the "not recorded"
 * sentence rather than being printed raw: `SUBSCRIPTION_STATE_UNSPECIFIED` on a
 * privacy screen is a string nobody can act on, and rounding it up to active is
 * the lie this component exists to prevent.
 */
type SubscriptionWord =
  "active" | "renewing" | "expired" | "suspended" | "failed" | "pending" | "deleted";

const SUBSCRIPTION_WORDS: Record<string, SubscriptionWord> = {
  active: "active",
  renewing: "renewing",
  renewal_warning: "renewing",
  expired: "expired",
  suspended: "suspended",
  failed: "failed",
  error: "failed",
  pending: "pending",
  deleted: "deleted",
};

function normaliseState(value: string | null | undefined): SubscriptionWord | null {
  if (value == null) return null;
  return SUBSCRIPTION_WORDS[value.trim().toLowerCase()] ?? null;
}

/**
 * Why CAIRN cannot read this space, and what to do about it.
 *
 * Always a sentence, because "unselectable" with no reason is the screen
 * refusing to explain itself — the reader is left to guess whether it is their
 * permissions, CAIRN's, or a fault. A category this client has no wording for is
 * reported as exactly that, rather than printed raw or paraphrased into a guess.
 */
function ineligibleReason(errorCategory: string | null | undefined): ReactNode {
  const known = lookup(INELIGIBLE_REASONS, errorCategory);
  return (
    <>
      CAIRN cannot read this space, so it cannot be chosen.{" "}
      {known ??
        "Google did not give a reason CAIRN has wording for, so none is shown rather than guessed at."}
    </>
  );
}

/** Keyed by the server's `ConnectorErrorCategory`, which is a closed set on the
 * API side precisely so a client can say each one in words. */
const INELIGIBLE_REASONS: Record<string, string> = {
  permission_revoked:
    "The Google Workspace account that authorised CAIRN cannot see this space, so CAIRN cannot either.",
  authentication_expired:
    "CAIRN's authorisation has lapsed. Reconnecting Google Chat is what restores it.",
  configuration_invalid:
    "Google Chat does not deliver events for this kind of space — direct messages and group chats among them, which CAIRN does not ask for.",
  provider_unavailable: "Google could not answer for this space when CAIRN last asked.",
  rate_limited: "Google is rate-limiting CAIRN, so it could not check this space.",
  // Named as unknown by the server, and repeated as unknown here rather than
  // dressed up: "unknown" is a real answer and a guess is not.
  unknown: "Google gave no reason CAIRN could record.",
};

/** The reason a subscription is failing, when it is one CAIRN has wording for.
 * Silence otherwise — a raw category token beside a broken space is a second
 * thing to be confused about rather than an explanation. */
function failureReason(errorCategory: string | null | undefined): ReactNode {
  const known = lookup(FAILURE_REASONS, errorCategory);
  if (known === undefined) return null;
  return <> {known}</>;
}

const FAILURE_REASONS: Record<string, string> = {
  permission_revoked:
    "The Google Workspace account that authorised CAIRN lost access to this space. Reconnecting with an account that can see it starts delivery again.",
  authentication_expired:
    "CAIRN's authorisation has lapsed, so it could not renew this subscription. Reconnecting Google Chat restores it.",
  rate_limited: "Google is rate-limiting CAIRN's subscription for this space.",
  provider_unavailable:
    "Google was not answering when CAIRN last tried to renew this subscription.",
  configuration_invalid: "Google refused CAIRN's subscription for this space.",
};

/** A table read by a key the server chose, so the miss is expressed rather than
 * asserted away. */
function lookup(table: Record<string, string>, key: string | null | undefined): string | undefined {
  if (key == null) return undefined;
  return table[key.trim().toLowerCase()];
}

/**
 * The instant, rendered only when the server sent it.
 *
 * Never "unknown", never a dash: an absent time means CAIRN has not recorded
 * one, and a placeholder in its slot is a claim that it asked and got no answer.
 */
function expiry(at: string | null | undefined, term: string): ReactNode {
  if (at == null) return null;
  return (
    <>
      {" "}
      {term} <time dateTime={at}>{formatDayAndTime(at)}</time>.
    </>
  );
}

export function SpacePickerLoading(): ReactNode {
  return <PickerLoading label="the Google Chat spaces" />;
}
