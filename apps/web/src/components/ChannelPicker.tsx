"use client";

import type { SlackChannelList, SlackChannelSelection } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import type { DescribedError } from "../errors.js";
import utility from "../styles/utility.module.css";
import styles from "./ChannelPicker.module.css";
import { SLACK_NO_HISTORY } from "./ConnectionCard.js";
import { Field } from "./Field.js";
import { headingTag, type HeadingLevel } from "./headings.js";
import { InlineProblem } from "./InlineProblem.js";

/**
 * Which Slack channels CAIRN reads.
 *
 * **A tick here means the backend said so.** Every other selection control in
 * every other product updates optimistically and reconciles later, and that is
 * usually the right trade — a wrong tick on a filter costs nothing. This one is
 * a claim about surveillance. A channel drawn as selected when the save was
 * refused tells somebody CAIRN is reading a room it is not, and a channel drawn
 * as unselected when it was saved tells them the opposite. Both are worse than a
 * moment of latency, so `selected` is read from the last answer the server gave
 * and from nowhere else; a save in flight is announced as *saving*, which is
 * what is actually true, and the checkbox does not move until the answer
 * arrives.
 *
 * The API expresses that per channel — `SlackChannelResponse.selected` — rather
 * than as a parallel array of IDs, so there is no way to render a tick for a
 * channel the server did not describe. `PUT` answers with IDs only, and
 * `reconcileChannels` is the one place that folds those back onto the list.
 *
 * **The names come from the backend too, because Slack does not send them.**
 * Slack's message events carry channel IDs only — no names — so a name on this
 * screen can only ever be one `conversations.list` returned through CAIRN's API.
 * Nothing here derives, formats or guesses one.
 *
 * A disclosure rather than an always-open list: the answer to "what is CAIRN
 * reading" is the summary line, and a workspace with two hundred channels should
 * not make somebody scroll past all of them to find it.
 */

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
  "An Owner or an Admin of this workspace chooses which channels CAIRN reads. This is the same list they see.";

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
   * to choose channels wants to be typing — not at the top of a list of two
   * hundred checkboxes they now have to tab through. Closing returns it to the
   * trigger, looked up live because React has just re-mounted it; without that a
   * keyboard reader is dropped at the top of the document, several sections
   * above where they were working.
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

  const channels = selection.channels ?? [];
  const selected = channels.filter((channel) => channel.selected);
  const filtered = filterChannels(channels, query);

  return (
    <div className={styles.picker}>
      <Heading className={styles.heading}>Channels CAIRN reads</Heading>

      {/*
        The answer to "what is CAIRN reading", before any control. Built only
        from names the backend returned — see `summarise`.
      */}
      <p className={styles.summary}>{summarise(selected)}</p>

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
              {open ? "Done choosing channels" : "Choose channels"}
            </Button>
          </div>

          {open && (
            <div className={styles.panel} id={panelId} ref={panelRef}>
              {/*
                The rule that decides whether any of this works, at the point of
                choosing rather than in a help article — and in the server's own
                words. The API sends this sentence with every channel response
                precisely so the client cannot keep a second copy of it that
                slowly stops matching what the backend actually enforces.
              */}
              <p className={styles.rule}>{selection.notice}</p>
              {/* Not a server field: no endpoint has an opinion about backfill,
                  because there is no backfill to have an opinion about. */}
              <p className={styles.rule}>{SLACK_NO_HISTORY}</p>

              <Field
                label="Search channels"
                hint="Public channels only. CAIRN cannot list private channels or direct messages."
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
                {countLabel(filtered.length, channels.length)}
              </p>

              <fieldset className={styles.group}>
                <legend className={utility.visuallyHidden}>Public channels CAIRN reads</legend>

                {filtered.length === 0 ? (
                  <p className={styles.empty}>
                    {channels.length === 0
                      ? "Slack returned no public channels for this workspace. CAIRN can only list channels Slack shows it."
                      : `No public channel matches “${query}”.`}
                  </p>
                ) : (
                  <ul className={styles.list}>
                    {filtered.map((channel) => (
                      <ChannelRow
                        key={channel.id}
                        idBase={baseId}
                        channel={channel}
                        saving={saving.includes(channel.id)}
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
            Read-only readers get the list itself, not only the count. What CAIRN
            reads from their workspace is a fact about their own messages, and a
            summary they cannot expand is one they have to take on trust.
          */}
          {selected.length > 0 && (
            <ul className={styles.readOnlyList}>
              {selected.map((channel) => (
                <li key={channel.id}>#{channel.name}</li>
              ))}
            </ul>
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
 * One channel, with its state said in words beside it.
 *
 * The checkbox's accessible *name* is the channel and nothing else; the state
 * hangs off `aria-describedby`. Wrapping the note inside the `<label>` would
 * fold "Saving" into the name, so the control would be announced as a different
 * control every time its state changed — and "#general saving" is not what the
 * checkbox is called.
 */
function ChannelRow({
  idBase,
  channel,
  saving,
  onToggle,
}: {
  idBase: string;
  channel: SlackChannel;
  saving: boolean;
  onToggle: ((channelId: string, next: boolean) => void) | undefined;
}): ReactNode {
  const inputId = `${idBase}-${channel.id}`;
  const noteId = `${inputId}-note`;
  const note = statusNote(channel, saving);

  return (
    <li className={styles.row}>
      <input
        className={styles.checkbox}
        id={inputId}
        type="checkbox"
        // Never the reader's last click: the server's last answer. A controlled
        // checkbox React re-renders with the same value snaps back, which is
        // exactly the behaviour wanted here.
        checked={channel.selected}
        disabled={saving}
        aria-busy={saving || undefined}
        aria-describedby={note === null ? undefined : noteId}
        onChange={(event) => {
          onToggle?.(channel.id, event.target.checked);
        }}
      />
      <label className={styles.channelName} htmlFor={inputId}>
        #{channel.name}
      </label>
      {note !== null && (
        <p className={styles.rowNote} id={noteId}>
          {note}
        </p>
      )}
    </li>
  );
}

/**
 * What is true about this row, or nothing.
 *
 * "Saving" wins over everything, because while it is true the tick is out of
 * date by definition.
 *
 * **`botIsMember: false` is the most important line this component draws.**
 * CAIRN does not ask Slack for `channels:join`, so a channel selected while the
 * app is not in it delivers nothing at all, silently and forever. That is the
 * single most common reason somebody connects Slack and concludes the product is
 * broken, and from a screen that does not say so they would be right to.
 */
function statusNote(channel: SlackChannel, saving: boolean): string | null {
  if (saving) return "Saving your choice. Nothing changes until Slack and CAIRN both confirm it.";
  if (!channel.botIsMember) {
    return "The CAIRN app is not in this channel, so nothing arrives from it yet. Run /invite @CAIRN there.";
  }
  if (channel.selected) return "The CAIRN app is in this channel.";
  return null;
}

/** Case-insensitive, and tolerant of the `#` people type out of habit. */
function filterChannels(channels: SlackChannel[], query: string): SlackChannel[] {
  const needle = query.trim().replace(/^#/, "").toLowerCase();
  if (needle === "") return channels;
  return channels.filter((channel) => channel.name.toLowerCase().includes(needle));
}

function countLabel(shown: number, total: number): string {
  if (shown === total) return `${String(total)} ${total === 1 ? "channel" : "channels"}.`;
  return `${String(shown)} of ${String(total)} channels match.`;
}

/**
 * The selection in one sentence.
 *
 * Names every selected channel, which the API makes possible without a lookup:
 * `selected` is a property of the channel, so a chosen channel is by
 * construction one the server also named. There is no counted-but-unnamed case
 * left to round in either direction.
 */
function summarise(selected: SlackChannel[]): string {
  if (selected.length === 0) {
    return "No channels chosen, so CAIRN is reading nothing from Slack.";
  }

  const count = `${String(selected.length)} ${selected.length === 1 ? "channel" : "channels"}`;
  const list = selected.map((channel) => `#${channel.name}`).join(", ");
  return `CAIRN is reading ${count}: ${list}.`;
}

/**
 * A picker-shaped placeholder.
 *
 * Matches the dimensions of the summary and the trigger that replace it, so the
 * card does not jump when the list lands. Silent to assistive technology; the
 * `role="status"` line makes the one announcement.
 */
export function ChannelPickerLoading(): ReactNode {
  return (
    <div className={styles.loading} role="status">
      <span className={utility.visuallyHidden}>Loading the Slack channels.</span>
      <span className={styles.skeletonLine} aria-hidden="true" />
      <span className={styles.skeletonLine} aria-hidden="true" />
    </div>
  );
}
