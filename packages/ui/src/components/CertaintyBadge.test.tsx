import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CertaintyBadge } from "./CertaintyBadge.js";
import styles from "./CertaintyBadge.module.css";

describe("CertaintyBadge", () => {
  it.each([
    ["verified", "Verified"],
    ["observed", "Observed"],
    ["suggested", "Suggested"],
  ] as const)("renders a readable label for %s", (certainty, label) => {
    render(<CertaintyBadge certainty={certainty} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("explains what the tier means to assistive technology", () => {
    // The badge alone is meaningless to someone who has not been told what the
    // tiers are, so the explanation travels with it.
    render(<CertaintyBadge certainty="suggested" />);

    const badge = screen.getByLabelText(/Suggested:/);
    expect(badge.getAttribute("aria-label")).toContain("meeting transcript");
  });

  /**
   * These three tests guard product constraints rather than implementation.
   * They exist so that a future change which quietly reintroduces numeric
   * confidence or traffic-light colouring fails CI and forces a conversation.
   */
  describe("product constraints", () => {
    it.each(["verified", "observed", "suggested"] as const)(
      "shows no numeric confidence for %s",
      (certainty) => {
        // md/05 §A.2.1 — certainty is categorical, never a percentage.
        const { container } = render(<CertaintyBadge certainty={certainty} />);
        expect(container.textContent).not.toMatch(/\d/);
        expect(container.innerHTML).not.toContain("%");
      },
    );

    it("distinguishes tiers without relying on colour", () => {
      // WCAG 1.4.1 — information must not be conveyed by colour alone. Here the
      // visible text label carries the meaning; styling only reinforces it.
      const { container: verified } = render(<CertaintyBadge certainty="verified" />);
      const { container: suggested } = render(<CertaintyBadge certainty="suggested" />);

      expect(verified.textContent).not.toBe(suggested.textContent);
    });

    it("uses wording that invites correction rather than reporting a defect", () => {
      // "Suggested" invites a check; "Low confidence" reads as an accusation
      // about the person the claim concerns.
      render(<CertaintyBadge certainty="suggested" />);
      const text = screen.getByText("Suggested").getAttribute("aria-label") ?? "";

      expect(text).toContain("Worth checking");
      expect(text.toLowerCase()).not.toContain("error");
      expect(text.toLowerCase()).not.toContain("unreliable");
    });
  });

  it("accepts an additional className", () => {
    render(<CertaintyBadge certainty="verified" className="inline" />);
    expect(screen.getByText("Verified").className).toContain("inline");
  });

  it.each(["verified", "observed", "suggested"] as const)(
    "applies the %s tier class",
    (certainty) => {
      // Certainty is conveyed through weight and border treatment rather than
      // colour, so the tier class is not cosmetic — it is the entire visual
      // distinction between a fact and an inference. Losing it silently would
      // present a guess with the authority of a merged pull request.
      render(<CertaintyBadge certainty={certainty} />);

      const classes = screen.getByRole("img").className.split(" ");
      expect(styles[certainty]).toBeDefined();
      expect(classes).toContain(styles.badge);
      expect(classes).toContain(styles[certainty]);
    },
  );

  it("can be reached and read without a pointer", async () => {
    /**
     * Closes audit finding O15 (WCAG 1.4.13, Content on Hover or Focus).
     *
     * The explanation used to live only in `title`, which appears on hover and
     * nothing else. A screen reader user received it through `aria-label`; a
     * sighted keyboard user could not reach it at all — the group least likely
     * to be represented in a manual test, and the reason this needs an
     * automated one.
     */
    const user = userEvent.setup();
    render(<CertaintyBadge certainty="suggested" />);

    await user.tab();

    const badge = screen.getByRole("img");
    expect(badge).toHaveFocus();
    expect(badge).toHaveAttribute("tabindex", "0");
  });

  it("does not announce its explanation twice", () => {
    // The visible description repeats the words already in the accessible name,
    // so it is aria-hidden. Without that a screen reader reads the whole
    // sentence, then reads it again.
    render(<CertaintyBadge certainty="verified" />);

    const badge = screen.getByRole("img");
    const visible = badge.querySelector("[aria-hidden='true']");

    expect(visible).not.toBeNull();
    expect(visible?.textContent).toBe(badge.getAttribute("aria-label")?.split(": ")[1]);
  });
});
