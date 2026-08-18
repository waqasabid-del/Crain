"use client";

import {
  ApiError,
  type MeetingCaptureList,
  type MeetingCaptureRequest,
  type MeetingCaptureState,
  type MeetingDecision,
  type MyMeetingRequest,
  type MyMeetingRequestList,
} from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import { formatDayAndTime } from "./dates.js";
import { InlineProblem } from "./InlineProblem.js";
import { Section } from "./Section.js";
import { EmptyState, ErrorState, LoadingState } from "./States.js";
import { StatusNote } from "./StatusNote.js";
import styles from "./MeetingConsent.module.css";

/**
 * Asking whether CAIRN may ever receive a meeting's transcript.
 *
 * **Nothing on this screen records a meeting.** CAIRN never joins one as a bot
 * or as a participant, it produces no recording and no transcript, and no
 * provider integration exists behind any of it. What these two sections show is
 * the permission a future connector would have to hold before it could ask a
 * platform for an artifact that platform made under its own settings. Every
 * label here is written so that a reader who assumed "capture" meant "recording"
 * is corrected in the first sentence they read.
 *
 * **Nobody ever learns who declined or who is silent.** That is the constraint
 * the whole file is shaped around, and it is enforced in three places at once:
 *
 * - The participant's view carries only the reader's own answer. There is no
 *   field on it that could hold anybody else's, and no request that would return
 *   one.
 * - The workspace's view carries counts, and this file renders a count only when
 *   it cannot be read as a statement about a person. `acceptedCount` arrives
 *   `null` once a request is refused precisely because a count of acceptances
 *   printed beside a refusal names the refuser by subtraction — so when it is
 *   absent, **no number at all is rendered for that row**, not even the number of
 *   people invited.
 * - A partial acceptance count is never rendered either, in any state. "4 of 5
 *   have agreed" is the same subtraction one step earlier, and it also hands an
 *   administrator a reason to go and chase whoever is left, which is how a free
 *   choice stops being free. The count appears only where every person invited
 *   has agreed, where it discloses nothing.
 *
 * **No dark patterns, checked rather than intended.** Agreeing and declining are
 * the same size, the same variant and one click each, side by side. Nothing
 * counts down, nothing is pre-selected, there is no bulk "agree to everything",
 * and declining is stated as costing nothing because it costs nothing.
 *
 * **Agreement here is an operating safeguard, not a lawful basis.** md/03 §3.3
 * records that consent cannot carry employment-context processing in the EU —
 * the basis is legitimate interest with a documented assessment — so no sentence
 * in this file says that anybody's agreement is what makes CAIRN lawful. It says
 * what agreement actually does: without it, nothing is collected.
 *
 * **No per-person meeting analysis exists and none is hinted at** (md/03 §5.4).
 * There is no measure of how much anybody spoke, no comparison between people,
 * no judgement of tone, no per-person figure of any kind — not withheld behind a
 * role, absent from the product.
 *
 * **Three fields are deliberately never rendered.** `externalMeetingRef` is the
 * platform's own handle for the meeting and can be a joining code, so it stays
 * off the screen and out of every attribute; there is no meeting title stored
 * anywhere to render; and no participant identifier of any kind reaches a
 * client. A `title` or an `aria-label` is not a safer place to put one of these,
 * only a less visible one.
 */

/**
 * The meeting boundary, in one place because it is claimed in three.
 *
 * The Trust Center, the participant's own screen and the workspace's screen all
 * make this promise, and three hand-maintained copies is three chances for the
 * product to promise slightly different things in different rooms.
 */
export const MEETING_BOUNDARY: readonly string[] = [
  "CAIRN never joins a meeting. It does not dial in, it does not appear as a participant or a bot, and it makes no recording and no transcript of its own.",
  "Any recording or transcript is made by the meeting platform, under that platform's own settings. The only thing CAIRN could ever receive is an artifact the platform itself already produced — if it produces none, there is nothing for CAIRN to receive.",
  "Everybody invited has to agree first, each from their own signed-in account. Nobody can answer for somebody else: not an Owner, not an Admin, not CAIRN staff. If one person invited does not agree, nothing from that meeting is collected.",
  "Anybody can take their agreement back at any time before anything is collected, and CAIRN never shows anybody who agreed, who declined, or who has not answered yet.",
  "No meeting platform connector exists in CAIRN yet, so nothing from any meeting is being collected today whatever anybody answers. This is the permission such a connector would have to hold before it could be built.",
];

/**
 * What a meeting could ever contribute, and what it could never produce.
 *
 * The second half is the one that matters: md/03 §5.4 rules out any per-person
 * meeting measure, and the honest way to say so is to describe what CAIRN reads
 * a transcript *for* — the same facts it reads from a pull request or a message.
 */
const WHAT_CAIRN_MAY_RECEIVE =
  "If everybody invited agrees, CAIRN may later receive the text of a transcript the meeting platform produced, and read it for the same things it reads everywhere else: what was decided, what was agreed, and what is now blocked. No audio, no video, and nothing about who was present.";

const WHAT_CAIRN_NEVER_DOES =
  "CAIRN never produces any per-person figure from a meeting. It does not measure how much anybody spoke, compare people with each other, judge anybody's tone, or record any per-person meeting analysis at all. There is no such data in CAIRN and no screen where it could appear.";

const DECLINING_COSTS_NOTHING =
  "Declining costs you nothing. Nobody is told who declined, no Owner or Admin can see or change your answer, and it is not recorded against you anywhere. If you decline, nothing from that meeting is collected from anybody.";

const HOW_TO_WITHDRAW =
  "If you agree and then change your mind, take your agreement back here at any point before anything is collected. Each answer is added to the record rather than replacing the last one, so it can always be shown that withdrawal was possible and was honoured.";

// --------------------------------------------------------------------------
// The participant's own requests
// --------------------------------------------------------------------------

export interface MyMeetingRequestsProps {
  workspaceId: string;
  /** Applied to the section, so a screen with a card treatment keeps it. */
  className?: string;
}

/**
 * The meetings the reader has been asked about, and their own answer to each.
 *
 * Self only by construction rather than by a check: `listMyMeetingRequests`
 * takes no subject, and there is no route anywhere by which a colleague's answer
 * could be read or written. That is why this section lives in Preferences beside
 * the reader's own identities rather than in Workspace settings — putting it
 * where an administrator works would suggest an administrator has a say in it.
 */
export function MyMeetingRequests({ workspaceId, className }: MyMeetingRequestsProps): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<MyMeetingRequestList> =>
      client.listMyMeetingRequests(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load your meeting privacy requests");

  return (
    <Section
      // Spread rather than passed: `exactOptionalPropertyTypes` is on, so an
      // explicit `undefined` is not the same as an absent prop.
      {...(className === undefined ? {} : { className })}
      title="Meeting privacy requests"
      description="When somebody asks whether CAIRN may ever receive the transcript of a meeting you were invited to, the question appears here. Only you can answer it, only for yourself, and you can change your answer until the moment anything is collected."
    >
      <Boundary />

      {state.status === "loading" && (
        <LoadingState label="your meeting privacy requests" shape="rows" lines={2} />
      )}

      {state.status === "failed" && (
        <ErrorState
          title="Your meeting privacy requests could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
          action={
            <Link className={utility.actionLink} href="/trust">
              Read what CAIRN does with meetings
            </Link>
          }
        />
      )}

      {state.status === "ready" && (
        <>
          {/* The server's own promise about this screen. Standing guidance
              rather than a result, so it does not announce itself on every
              paint. */}
          <div className={styles.rule}>
            <StatusNote live={false}>{state.data.notice}</StatusNote>
          </div>

          <MyRequestList
            requests={state.data.requests ?? []}
            workspaceId={workspaceId}
            onChanged={reload}
          />
        </>
      )}
    </Section>
  );
}

function MyRequestList({
  requests,
  workspaceId,
  onChanged,
}: {
  requests: MyMeetingRequest[];
  workspaceId: string;
  onChanged: () => void;
}): ReactNode {
  if (requests.length === 0) {
    return (
      <EmptyState title="Nobody has asked you about a meeting" headingLevel={3}>
        No meeting of yours has been put to you for an answer, and nothing from any meeting you
        attend is being collected. If somebody ever asks, the question appears here and stays
        unanswered until you answer it yourself.
      </EmptyState>
    );
  }

  return (
    <ul className={styles.list} aria-label="Meetings you have been asked about">
      {requests.map((request) => (
        <MyRequestRow
          key={request.id}
          request={request}
          workspaceId={workspaceId}
          onChanged={onChanged}
        />
      ))}
    </ul>
  );
}

/**
 * One request, and the reader's own answer to it.
 *
 * The order is deliberate: when the meeting is, why it was asked about, what
 * CAIRN could receive, what it will never do, what declining costs, how to
 * withdraw — and only then the two buttons. A person answering a question about
 * their own privacy should reach the controls having already read what they do.
 */
function MyRequestRow({
  request,
  workspaceId,
  onChanged,
}: {
  request: MyMeetingRequest;
  workspaceId: string;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  // Which answer is in flight, not merely whether one is. A shared boolean marks
  // two mutually exclusive controls busy at once, which is a lie to anybody
  // listening rather than looking.
  const [busy, setBusy] = useState<MeetingDecision | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function answer(decision: MeetingDecision): Promise<void> {
    setBusy(decision);
    setProblem(null);
    try {
      await client.decideMeetingRequest(workspaceId, request.id, decision);
      setSaved(SAVED[decision]);
      onChanged();
    } catch (error: unknown) {
      setProblem(describeError(error, "record your answer"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className={styles.row}>
      {/* No meeting title: none is stored, and inventing one from the purpose
          would put the requester's words in the position of a fact. No joining
          link and no platform reference either — see the file docstring. */}
      <h3 className={styles.rowTitle}>
        Meeting on{" "}
        <time dateTime={request.scheduledStart}>{formatDayAndTime(request.scheduledStart)}</time>
      </h3>
      <p className={styles.when}>
        Ends <time dateTime={request.scheduledEnd}>{formatDayAndTime(request.scheduledEnd)}</time>
      </p>

      {/* Attributed to whoever wrote it, so that it is read as a request rather
          than as CAIRN's own description of the meeting. */}
      <p className={styles.purpose}>
        <span className={styles.label}>Why it was asked, in the requester&rsquo;s words:</span>{" "}
        {request.purpose}
      </p>

      <p className={styles.answer}>{selfAnswerLabel(request)}</p>

      {/* The shared explanation, from the server, which is written to name
          nobody. Composing one here would be a second author, and the second
          author is always the one who eventually says "waiting for two people". */}
      <p className={styles.shared}>{request.message}</p>

      <dl className={styles.terms}>
        <dt>What CAIRN may receive</dt>
        <dd>{WHAT_CAIRN_MAY_RECEIVE}</dd>
        <dt>What CAIRN will never do</dt>
        <dd>{WHAT_CAIRN_NEVER_DOES}</dd>
        <dt>Who makes the transcript</dt>
        <dd>{MEETING_BOUNDARY[1]}</dd>
        <dt>If you decline</dt>
        <dd>{DECLINING_COSTS_NOTHING}</dd>
        <dt>If you change your mind</dt>
        <dd>{HOW_TO_WITHDRAW}</dd>
      </dl>

      {saved !== null && (
        <div className={styles.rule}>
          <StatusNote>{saved}</StatusNote>
        </div>
      )}

      {problem !== null && (
        <div className={styles.problem}>
          <InlineProblem error={problem} />
        </div>
      )}

      <Answers request={request} busy={busy} onAnswer={answer} />
    </li>
  );
}

/**
 * The controls, weighted equally on purpose.
 *
 * Both buttons are the same variant and the same size, side by side, one click
 * each, with no confirmation step in front of either — because a confirmation in
 * front of only one of two answers is a thumb on the scale, and a confirmation in
 * front of both is friction on a question people should be free to answer
 * quickly. Nothing here is pre-selected and nothing counts down.
 */
function Answers({
  request,
  busy,
  onAnswer,
}: {
  request: MyMeetingRequest;
  busy: MeetingDecision | null;
  onAnswer: (decision: MeetingDecision) => Promise<void>;
}): ReactNode {
  if (!request.canDecide) {
    return (
      <p className={styles.closed}>
        This request is closed, so there is nothing left to answer. Your answer stays in the record
        as you gave it.
      </p>
    );
  }

  const answered = request.myDecision;
  const offer: MeetingDecision[] =
    answered === "accepted"
      ? ["withdrawn"]
      : answered === "declined"
        ? ["accepted"]
        : ["accepted", "declined"];

  return (
    <div className={styles.actions}>
      {offer.map((decision) => (
        <Button
          key={decision}
          // Identical weight for every answer this row offers. `secondary`
          // rather than a primary beside a ghost: a primary button is the
          // product recommending an answer, and CAIRN has no view on how
          // somebody should answer a question about their own privacy.
          variant="secondary"
          size="md"
          loading={busy === decision}
          disabled={busy !== null}
          onClick={() => {
            void onAnswer(decision);
          }}
        >
          {ANSWER_LABELS[decision]}
        </Button>
      ))}
    </div>
  );
}

/**
 * The three answers, in the words of what they do.
 *
 * "Agree" and "Decline" rather than "Yes" and "No, thanks": the second reads as
 * a decline the product is disappointed by, which is the smallest possible dark
 * pattern and still one.
 */
const ANSWER_LABELS: Record<MeetingDecision, string> = {
  accepted: "Agree that CAIRN may receive this transcript",
  declined: "Decline — nothing is collected from this meeting",
  withdrawn: "Take my agreement back",
};

const SAVED: Record<MeetingDecision, string> = {
  accepted:
    "Your agreement is recorded. Nothing is collected unless everybody invited agrees, and you can take it back at any time before anything is.",
  declined:
    "Your answer is recorded. Nothing will be collected from this meeting, from you or from anybody else, and nobody is told who declined.",
  withdrawn:
    "Your agreement is withdrawn. Nothing will be collected from this meeting, and nobody is told who withdrew.",
};

/** The reader's own answer, in words, and never anybody else's. */
export function selfAnswerLabel(request: MyMeetingRequest): string {
  const decided = request.myDecidedAt == null ? "" : ` on ${formatDayAndTime(request.myDecidedAt)}`;

  switch (request.myDecision) {
    case "accepted":
      return `You agreed${decided}.`;
    case "declined":
      return `You declined${decided}. Nothing from this meeting is collected.`;
    case "withdrawn":
      return `You took your agreement back${decided}. Nothing from this meeting is collected.`;
    case "expired":
      return "Your answer expired when this request closed. Nothing from this meeting was collected.";
    default:
      // `pending`, `null`, and anything a future server adds. Silence is not an
      // answer, and it is never described as one.
      return "You have not answered yet. Nothing is collected until you do.";
  }
}

// --------------------------------------------------------------------------
// The workspace's requests
// --------------------------------------------------------------------------

/**
 * What the workspace view is allowed to load.
 *
 * A refusal is folded into the data rather than thrown, because the two failures
 * need different screens: a permission refusal will be refused identically
 * forever, and a "Try again" button in front of one teaches the reader not to
 * believe the next thing the product says.
 */
type CaptureView = { denied: true } | { denied: false; list: MeetingCaptureList };

/**
 * Meeting capture requests across the workspace, for an Owner or an Admin.
 *
 * **This asks. It does not record.** The heading, the description and the first
 * sentence of every state say so, because "capture request" read quickly looks
 * like a recording control, and an administrator who believes they have started
 * a recording will tell their team they have.
 *
 * The caller gates this on `administers`. That gate is courtesy: the API refuses
 * a member independently, and nothing here is the only thing standing in front
 * of the request.
 */
export function MeetingCaptureRequests({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    async (signal: AbortSignal): Promise<CaptureView> => {
      try {
        return {
          denied: false,
          list: await client.listMeetingCaptureRequests(workspaceId, { signal }),
        };
      } catch (error: unknown) {
        if (error instanceof ApiError && error.status === 403) return { denied: true };
        throw error;
      }
    },
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the meeting capture requests");

  return (
    <Section
      variant="eyebrow"
      title="Meeting capture requests"
      description="Asking permission, and nothing else. Creating a request starts no recording: CAIRN never joins a meeting and makes no recording and no transcript. Each person invited answers for themselves, from their own account, and you cannot answer for them or see how they answered."
    >
      <Boundary />

      {state.status === "loading" && (
        <LoadingState label="the meeting capture requests" shape="rows" lines={2} />
      )}

      {state.status === "failed" && (
        <ErrorState
          title="The meeting capture requests could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
          action={
            <Link className={utility.actionLink} href="/trust">
              Read what CAIRN does with meetings
            </Link>
          }
        />
      )}

      {state.status === "ready" && state.data.denied && (
        <ErrorState
          title="This account cannot see the workspace's requests"
          error={{
            message:
              "An Owner or an Admin of this workspace sees these. Your own meeting requests are yours whatever your role — they are in Preferences, and nobody else can answer them for you.",
          }}
          retryable={false}
          headingLevel={3}
          action={
            <Link className={utility.actionLink} href="/settings">
              Your own meeting privacy requests
            </Link>
          }
        />
      )}

      {state.status === "ready" && !state.data.denied && (
        <CaptureList list={state.data.list} workspaceId={workspaceId} onChanged={reload} />
      )}
    </Section>
  );
}

function CaptureList({
  list,
  workspaceId,
  onChanged,
}: {
  list: MeetingCaptureList;
  workspaceId: string;
  onChanged: () => void;
}): ReactNode {
  const requests = list.requests ?? [];

  return (
    <>
      {/* The server's own statement of what this view cannot answer, rendered
          rather than paraphrased. */}
      <div className={styles.rule}>
        <StatusNote live={false}>{list.notice}</StatusNote>
      </div>

      {requests.length === 0 ? (
        <EmptyState title="No meeting has been asked about" headingLevel={3}>
          Nobody in this workspace has asked whether CAIRN may receive a meeting&rsquo;s transcript,
          and no meeting platform connector exists yet, so nothing from any meeting is being
          collected. Asking would put the question to every person invited, and each of them would
          answer for themselves.
        </EmptyState>
      ) : (
        <ul className={styles.list} aria-label="Meeting capture requests">
          {requests.map((request) => (
            <CaptureRow
              key={request.id}
              request={request}
              workspaceId={workspaceId}
              onChanged={onChanged}
            />
          ))}
        </ul>
      )}
    </>
  );
}

function CaptureRow({
  request,
  workspaceId,
  onChanged,
}: {
  request: MeetingCaptureRequest;
  workspaceId: string;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const open = request.state === "pending" || request.state === "eligible";

  async function callOff(): Promise<void> {
    setBusy(true);
    setProblem(null);
    try {
      await client.cancelMeetingCaptureRequest(workspaceId, request.id);
      setConfirming(false);
      onChanged();
    } catch (error: unknown) {
      setProblem(describeError(error, "call off this request"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={styles.row}>
      <h3 className={styles.rowTitle}>
        Meeting on{" "}
        <time dateTime={request.scheduledStart}>{formatDayAndTime(request.scheduledStart)}</time>
      </h3>
      <p className={styles.when}>
        Ends <time dateTime={request.scheduledEnd}>{formatDayAndTime(request.scheduledEnd)}</time>
      </p>

      <p className={styles.purpose}>
        <span className={styles.label}>Why it was asked:</span> {request.purpose}
      </p>

      <p className={styles.answer}>{captureStateLabel(request.state)}</p>

      {/* The server's shared explanation, which names nobody by design. */}
      <p className={styles.shared}>{request.message}</p>

      <Invited request={request} />

      {problem !== null && (
        <div className={styles.problem}>
          <InlineProblem error={problem} />
        </div>
      )}

      {open &&
        (confirming ? (
          // States the effect rather than asking "are you sure?". Nothing is
          // deleted and nothing was ever collected, and the wording must not
          // imply either.
          <div className={styles.confirm} role="group" aria-label="Call off this request">
            <p className={styles.confirmBody}>
              The question is withdrawn and nobody is asked again. Answers already given stay in the
              record exactly as they were given — nothing was collected, and nothing is deleted.
            </p>
            <div className={styles.actions}>
              <Button
                size="sm"
                variant="secondary"
                loading={busy}
                onClick={() => {
                  void callOff();
                }}
              >
                Call off the request
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  setConfirming(false);
                }}
              >
                Leave the question open
              </Button>
            </div>
          </div>
        ) : (
          <div className={styles.actions}>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setConfirming(true);
              }}
            >
              Call off this request
            </Button>
          </div>
        ))}
    </li>
  );
}

/**
 * How many people were asked — and only where a number says nothing about a
 * person.
 *
 * `acceptedCount` is `null` on a refused request, because a count of acceptances
 * beside a refusal identifies the refuser by arithmetic. When it is absent this
 * renders **no number at all**, including the number of people invited: on a
 * two-person meeting that number and the state are enough between them.
 *
 * A partial count is never rendered in any state either. "4 of 5" is the same
 * subtraction with the arithmetic left to the reader, and it invites an
 * administrator to work out who is left and go and ask them — which is how a
 * free choice quietly stops being free.
 */
function Invited({ request }: { request: MeetingCaptureRequest }): ReactNode {
  if (request.acceptedCount == null) {
    return (
      <p className={styles.invited}>
        CAIRN does not show how many people answered, or how. Whether anything is collected is the
        line above; who decided it is not this screen&rsquo;s to say.
      </p>
    );
  }

  const people = `${String(request.participantCount)} ${request.participantCount === 1 ? "person was" : "people were"}`;

  return (
    <p className={styles.invited}>
      {request.state === "eligible"
        ? `${people} invited to answer, and everybody invited agreed.`
        : `${people} invited to answer. CAIRN does not show you who has answered, or how.`}
    </p>
  );
}

/**
 * Where a request stands, in words a reader can act on.
 *
 * A switch rather than a chain of ternaries, so a state added on the server is a
 * compile error here instead of an unfamiliar word on a privacy screen. The
 * default returns something honest rather than throwing: a blank section during
 * a privacy review is worse than a plain sentence.
 */
export function captureStateLabel(state: MeetingCaptureState): string {
  switch (state) {
    case "pending":
      return "Waiting for everybody invited to answer.";
    case "eligible":
      return "Everybody invited agreed. Nothing has been collected — no meeting platform connector exists yet.";
    case "refused":
      return "Not eligible. Nothing from this meeting is collected.";
    case "cancelled":
      return "Called off. The question was withdrawn and nothing was collected.";
    case "expired":
      return "Expired. The meeting finished without everybody agreeing, so nothing was collected.";
    case "completed":
      return "Closed. Nothing further will be collected.";
    default:
      return "Closed. Nothing further will be collected.";
  }
}

// --------------------------------------------------------------------------
// Shared
// --------------------------------------------------------------------------

/** The boundary, stated on both screens before anything else on them. */
function Boundary(): ReactNode {
  return (
    <ul className={styles.boundary}>
      {MEETING_BOUNDARY.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}
