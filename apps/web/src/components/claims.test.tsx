import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { ClaimList, type ClaimEntry } from "./ClaimList.js";
import { renderRoute } from "../test/harness.js";

/**
 * The claim card, and the four things it may say about who is behind a claim.
 *
 * These are unit tests because the wording is the feature. The counts reach the
 * interface precisely so that a reader can tell *nobody else was involved* from
 * *somebody was, and CAIRN cannot yet say who* — and every way of getting that
 * second sentence wrong is a way of making the product less trustworthy than
 * saying nothing would have been. So the assertions are about vocabulary: not
 * an error, not an accusation, not a number pretending to be a confidence.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

const CLAIM: ClaimEntry = {
  text: "The invitation acceptance flow was merged into main.",
  certainty: "verified",
  hedgedBySystem: false,
  resolvedActors: 0,
  unresolvedActors: 0,
  citations: [
    { evidenceId: "pr-482", source: "github", url: "https://github.com/example/cairn/pull/482" },
  ],
  credits: ["Ali Rahman"],
};

function renderClaims(claims: ClaimEntry[]): ReturnType<typeof renderRoute> {
  return renderRoute(<ClaimList claims={claims} label="Claims" />, { route: "/feed" });
}

function withAttribution(resolvedActors: number, unresolvedActors: number): ClaimEntry {
  return { ...CLAIM, attribution: { resolvedActors, unresolvedActors } };
}

describe("a claim card", () => {
  it("keeps the named credit and the citation disclosure it already had", () => {
    // State one, unchanged: a mention the identity graph placed is still shown
    // by name, and the evidence is still one disclosure away.
    renderClaims([CLAIM]);

    expect(screen.getByText("Ali Rahman")).toBeVisible();
    expect(screen.getByRole("link", { name: /pr-482/ })).toHaveAttribute(
      "href",
      "https://github.com/example/cairn/pull/482",
    );
  });
});

describe("the four states of attribution", () => {
  it("says nothing when a claim carries no attribution at all", () => {
    // State four. There is no such thing as "no connected accounts" in this
    // product, and rendering one would be inventing a status to fill a gap.
    const { container } = renderClaims([CLAIM]);

    expect(container.textContent).not.toMatch(/connected account/i);
    expect(container.textContent).not.toMatch(/has not connected/i);
  });

  it("says nothing when both counts are zero", () => {
    const { container } = renderClaims([withAttribution(0, 0)]);

    expect(container.textContent).not.toMatch(/connected account/i);
  });

  it("says a connected identity is behind it, in words, without naming it", () => {
    // State two. "Attributed through a connected account" is the whole of what
    // may be said: the link underneath holds a Slack or Google Chat handle,
    // which is a private identifier for a colleague and not a credit.
    renderClaims([withAttribution(1, 0)]);

    expect(screen.getByText(/attributed through a connected account/i)).toBeVisible();
  });

  it("counts more than one in words rather than as a figure", () => {
    renderClaims([withAttribution(4, 0)]);

    expect(screen.getByText(/attributed through four connected accounts/i)).toBeVisible();
  });

  it("falls back to a numeral only where a word would be worse", () => {
    renderClaims([withAttribution(14, 0)]);

    expect(screen.getByText(/attributed through 14 connected accounts/i)).toBeVisible();
  });

  it("states an unresolved identity neutrally, and offers no blame in either direction", () => {
    // State three, and the sentence this whole feature turns on.
    renderClaims([withAttribution(0, 1)]);

    const note = screen.getByText(/one contributor here has not connected their account/i);
    const text = note.textContent;

    // Not the reader's fault, and not a fault at all.
    expect(text).not.toMatch(/error|failed|failure|problem|invalid|unable|broken|denied|missing/i);
    // Not a colleague concealing anything, either.
    expect(text).not.toMatch(/hidden|hiding|anonymous|withheld|refused|unknown person/i);
    // And it is temporary, which is the word that makes it neutral.
    expect(text).toMatch(/\byet\b/);
  });

  it("says both when both are true", () => {
    renderClaims([withAttribution(2, 1)]);

    expect(screen.getByText(/attributed through two connected accounts/i)).toBeVisible();
    expect(screen.getByText(/one contributor here has not connected their account/i)).toBeVisible();
  });

  it("never renders a provider handle, address or credential state", () => {
    const { container } = renderClaims([withAttribution(3, 3)]);
    const html = container.innerHTML;

    expect(html).not.toMatch(/\bU[A-Z0-9]{6,}\b/);
    expect(html).not.toMatch(/users\/\d+/);
    expect(html).not.toMatch(/[\w.+-]+@[\w-]+\.[\w.]+/);
    expect(html).not.toMatch(/oauth|access[_ ]token|refresh[_ ]token|scope[s]?=/i);
  });

  it("keeps attribution categorical rather than numeric", () => {
    // md/05 §A.2.1. A count of accounts on one statement is not a confidence,
    // and must never be dressed as one.
    const { container } = renderClaims([withAttribution(1, 1)]);

    expect(container.textContent).not.toMatch(/\d+\s?%|\bconfidence\b|\blikelihood\b/i);
  });

  it("is not announced as a live region", () => {
    // It is on screen from first paint, describing content already there. A
    // status role here interrupts a screen reader for nothing.
    renderClaims([withAttribution(0, 1)]);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("passes an axe audit with attribution on every card", async () => {
    const { container } = renderClaims([withAttribution(1, 1), withAttribution(0, 2)]);

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

/**
 * The attribution note used to end in a link to Preferences — "Connect your own
 * accounts". Preferences has been removed from the product, and with it the only
 * screen where somebody could connect an account, so the note now states the
 * fact and offers no remedy.
 */
