import type { Brief, Fact } from "./types.js";

/**
 * Example content for reviewing the Brief and Feed screens. Only reachable when
 * `CONTENT_SOURCE=sample`, and every screen using it shows an undismissable
 * banner: sample data that can appear unasked is how a product promising "every
 * claim links to its source" shows a source that was never read.
 *
 * Chosen to exercise the hard cases — all three certainty tiers, several sources
 * on one claim, a citation with no URL, and hedged wording per `hedging.py`.
 */
export const SAMPLE_BRIEF: Brief = {
  // The full response shape, including fields no screen reads: a subset would
  // let a screen be designed against data that cannot occur.
  periodStart: "2026-08-12T06:00:00Z",
  periodEnd: "2026-08-13T06:00:00Z",
  generatedAt: "2026-08-13T06:00:00Z",
  stored: true,
  suppressedCount: 0,
  truncated: false,
  narrative:
    "Most of yesterday went on the invitation flow, which is now merged. The " +
    "billing spike is still blocked on the sandbox credentials, and that has " +
    "been the case for three days. One thing worth checking: it sounded like " +
    "the meeting settled on deferring SAML, but nobody wrote it down anywhere.",
  abstained: false,
  claims: [
    {
      text: "The invitation acceptance flow was merged into main.",
      certainty: "verified",
      hedgedBySystem: false,
      resolvedActors: 0,
      unresolvedActors: 0,
      citations: [
        {
          evidenceId: "pr-482",
          source: "github",
          url: "https://github.com/example/cairn/pull/482",
        },
      ],
      credits: ["Ali Rahman"],
    },
    {
      text: "Work on billing appears to be waiting on sandbox credentials from the provider.",
      certainty: "observed",
      hedgedBySystem: false,
      resolvedActors: 0,
      unresolvedActors: 0,
      citations: [
        {
          evidenceId: "msg-91733",
          source: "chat",
          quote: "still no sandbox keys, can't test the webhook end to end",
          url: "https://chat.example.com/archives/C01/p91733",
        },
        {
          evidenceId: "issue-118",
          source: "github",
          url: "https://github.com/example/cairn/issues/118",
        },
      ],
      credits: ["Jo Meyer"],
    },
    {
      text: "It sounded like the team agreed to defer SAML support to next quarter.",
      certainty: "suggested",
      hedgedBySystem: false,
      resolvedActors: 0,
      unresolvedActors: 0,
      citations: [
        {
          evidenceId: "meeting-2026-08-12",
          source: "meeting",
          quote: "let's push SAML, nobody's asked for it yet",
          // Deliberately no URL: the case the citation component must render
          // without dropping the provenance.
        },
      ],
      credits: ["Sam Okonkwo", "Jo Meyer"],
    },
  ],
};

export const SAMPLE_FACTS: Fact[] = [
  {
    id: "fact-1",
    kind: "delivery",
    statement: "Pull request 482, invitation acceptance, was merged.",
    certainty: "verified",
    people: [{ mention: "Ali Rahman" }],
    // One account behind it, and CAIRN knows whose.
    resolvedActors: 1,
    unresolvedActors: 0,
    occurredAt: "2026-08-12T16:22:00Z",
    validFrom: "2026-08-14T09:00:00Z",
    origin: "extracted",
    sources: [
      { evidenceId: "pr-482", source: "github", url: "https://github.com/example/cairn/pull/482" },
    ],
  },
  {
    id: "fact-2",
    kind: "blocker",
    statement: "Billing work is waiting on sandbox credentials from the payment provider.",
    certainty: "observed",
    people: [{ mention: "Jo Meyer" }],
    // A second account CAIRN cannot place: the case the screens have to say
    // out loud without naming anybody.
    resolvedActors: 1,
    unresolvedActors: 1,
    occurredAt: "2026-08-12T11:05:00Z",
    validFrom: "2026-08-14T09:00:00Z",
    origin: "extracted",
    sources: [
      {
        evidenceId: "msg-91733",
        source: "chat",
        quote: "still no sandbox keys, can't test the webhook end to end",
        url: "https://chat.example.com/archives/C01/p91733",
      },
    ],
  },
  {
    id: "fact-3",
    kind: "open_question",
    statement: "It is not clear who is writing up the SAML decision.",
    certainty: "suggested",
    people: [],
    // Nothing to attribute at all — the state the screens stay silent about.
    resolvedActors: 0,
    unresolvedActors: 0,
    occurredAt: "2026-08-12T09:40:00Z",
    validFrom: "2026-08-14T09:00:00Z",
    origin: "extracted",
    sources: [{ evidenceId: "meeting-2026-08-12", source: "meeting" }],
  },
];
