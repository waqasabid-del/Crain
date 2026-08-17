import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { Preview } from "./Preview.js";

/**
 * The style guide is documentation, and documentation that has quietly stopped
 * working is worse than none — a reviewer trusts it.
 *
 * These do not test appearance, which is the whole point of looking at the page
 * by hand. They test that it still mounts, that the theme toggle reaches the
 * document, and that every contrast pair on display reports a pass. That last
 * one matters: the page reads as evidence of WCAG compliance, so a failing row
 * rendered calmly on a page nobody scrutinises is exactly the false-confidence
 * pattern this project keeps finding.
 */

afterEach(() => {
  delete document.documentElement.dataset.theme;
});

describe("design system preview", () => {
  it("renders every section", () => {
    render(<Preview />);

    for (const heading of [
      "Contrast",
      "Colour roles",
      "Typography",
      "Buttons",
      "Certainty",
      "Spacing",
    ]) {
      expect(screen.getByRole("heading", { name: heading, level: 2 })).toBeInTheDocument();
    }
  });

  it("renders all three button variants and both sizes", () => {
    render(<Preview />);

    for (const name of ["Primary", "Secondary", "Ghost", "Small", "Medium"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("renders every certainty tier", () => {
    render(<Preview />);

    // Queried by accessible name rather than text, so this also asserts the
    // explanation still reaches assistive technology — the property that
    // silently disappears when the badge is a bare span.
    for (const tier of ["Verified", "Observed", "Suggested"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${tier}:`) })).toBeInTheDocument();
    }
  });

  it("puts the theme on the document element, not a wrapper", async () => {
    // The tokens are declared on :root and [data-theme]. Setting the attribute
    // any lower would leave `body` on the other theme, which reads as the toggle
    // being broken.
    const user = userEvent.setup();
    render(<Preview />);

    expect(document.documentElement.dataset.theme).toBe("light");

    await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it.each(["light", "dark"])("reports every contrast pair as passing in %s", async (target) => {
    const user = userEvent.setup();
    render(<Preview />);

    if (target === "dark") {
      await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    }

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1); // drop the header

    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(within(row).getByText(/AA$/).textContent).toBe("Passes AA");
    }
  });
});
