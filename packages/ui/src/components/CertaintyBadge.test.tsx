import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CertaintyBadge } from "./CertaintyBadge.js";

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
});
