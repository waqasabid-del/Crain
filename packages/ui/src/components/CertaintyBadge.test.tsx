import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  it.each([
    ["verified", "Verified"],
    ["observed", "Observed"],
    ["suggested", "Suggested"],
  ] as const)("names the %s tier before its explanation", (certainty, label) => {
    // The accessible name has to lead with the certainty: it is the part the
    // reader needs, and a screen reader user hears it first or not at all.
    render(<CertaintyBadge certainty={certainty} />);
    expect(screen.getByRole("button", { name: new RegExp(`^${label}: `) })).toBeInTheDocument();
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

      const classes = screen.getByRole("button").className.split(" ");
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

    const badge = screen.getByRole("button");
    expect(badge).toHaveFocus();
    expect(badge).toHaveAttribute("aria-expanded", "true");
  });

  it("is a real control rather than a focusable image", () => {
    /**
     * The dead tab stop this closes.
     *
     * The badge was `role="img"` with `tabIndex={0}` — focusable, announced as
     * a graphic, and doing nothing when activated. Thirty claims on a page is
     * thirty stops that lead nowhere. Either the description is worth a stop,
     * in which case the element is a control, or it is not, in which case it
     * should not be focusable. It is worth a stop.
     */
    render(<CertaintyBadge certainty="verified" />);
    const badge = screen.getByRole("button");

    expect(badge).not.toHaveAttribute("tabindex");
    expect(badge.tagName).toBe("BUTTON");
    expect(badge).toHaveAttribute("type", "button");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("reveals the description on hover", async () => {
    const user = userEvent.setup();
    render(<CertaintyBadge certainty="observed" />);

    await user.hover(screen.getByRole("button"));

    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");
  });

  it("dismisses the description with Escape, without moving focus", async () => {
    // WCAG 2.2 SC 1.4.13. A tooltip that can only be closed by moving the
    // pointer or tabbing away obscures whatever is under it for a magnifier
    // user, who may not be able to see what it is covering to move off it.
    const user = userEvent.setup();
    render(<CertaintyBadge certainty="verified" />);

    const badge = screen.getByRole("button");
    await user.tab();
    expect(badge).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");

    expect(badge).toHaveAttribute("aria-expanded", "false");
    expect(badge).toHaveFocus();
  });

  it("can be reopened after dismissal", async () => {
    // Escape must not be a one-way door: the description is the only place the
    // tier is explained.
    const user = userEvent.setup();
    render(<CertaintyBadge certainty="verified" />);

    const badge = screen.getByRole("button");
    await user.tab();
    await user.keyboard("{Escape}");
    await user.keyboard("{Enter}");

    expect(badge).toHaveAttribute("aria-expanded", "true");
  });

  it("pulls the description back inside a 320px viewport", async () => {
    /**
     * The tooltip is anchored to the badge's left edge, so on the narrowest
     * supported viewport a badge towards the end of a line pushed it off screen
     * — where, being `position: absolute`, it could not be scrolled to.
     */
    const user = userEvent.setup();
    const previousWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { value: 320, configurable: true });

    // jsdom lays nothing out, so the geometry has to be supplied: a 200px-wide
    // panel starting 200px in, on a 320px screen.
    const measure = vi.spyOn(Element.prototype, "getBoundingClientRect");
    measure.mockImplementation(function measurePanel(this: Element): DOMRect {
      return this.hasAttribute("data-open") ? new DOMRect(200, 0, 200, 40) : new DOMRect();
    });

    try {
      render(<CertaintyBadge certainty="verified" />);
      await user.tab();

      // 400 - (320 - 8) = 88px of overflow, and the panel has 192px of room to
      // its left, so the whole overflow is absorbed.
      const panel = screen.getByRole("button").querySelector("[data-open]");
      expect(panel?.getAttribute("style")).toContain("--tooltip-shift: -88px");
    } finally {
      measure.mockRestore();
      Object.defineProperty(window, "innerWidth", { value: previousWidth, configurable: true });
    }
  });

  it("does not announce its explanation twice", () => {
    // The visible description repeats the words already in the accessible name,
    // so it is aria-hidden. Without that a screen reader reads the whole
    // sentence, then reads it again.
    render(<CertaintyBadge certainty="verified" />);

    const badge = screen.getByRole("button");
    const visible = badge.querySelector("[aria-hidden='true']");

    expect(visible).not.toBeNull();
    expect(visible?.textContent).toBe(badge.getAttribute("aria-label")?.split(": ")[1]);
  });
});
