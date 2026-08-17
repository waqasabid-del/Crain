import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { PageHeader } from "./PageHeader.js";

/**
 * The shared screen header.
 *
 * The assertions that matter here are structural rather than visual: the
 * heading level is what a screen reader user navigates a page by, and a header
 * that silently renders an `<h1>` inside a page that already has one is a
 * defect no rendering shows.
 */
describe("PageHeader", () => {
  it("owns the page's h1 by default", () => {
    render(<PageHeader title="This week" />);

    expect(screen.getByRole("heading", { level: 1, name: "This week" })).toBeVisible();
  });

  it("steps down to h2 when it opens a section inside a page", () => {
    render(<PageHeader title="Connected sources" headingLevel={2} />);

    expect(screen.getByRole("heading", { level: 2, name: "Connected sources" })).toBeVisible();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("shows the eyebrow without folding it into the heading's accessible name", () => {
    // The heading list is how a screen reader user skims; prefixing every entry
    // with its section makes that list harder to read, not easier.
    render(<PageHeader eyebrow="Workspace" title="Overview" />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("Overview");
    expect(screen.getByText("Workspace")).toBeVisible();
  });

  it("renders the description and metadata when given, and nothing when not", () => {
    const { unmount } = render(
      <PageHeader title="Overview" description="What changed across the workspace." meta="Today" />,
    );

    expect(screen.getByText("What changed across the workspace.")).toBeVisible();
    expect(screen.getByText("Today")).toBeVisible();
    unmount();

    render(<PageHeader title="Overview" />);
    expect(screen.getByRole("heading", { level: 1 })).toBeVisible();
    expect(screen.queryByText("Today")).toBeNull();
  });

  it("renders the action slot as real controls in a banner-free header", () => {
    render(
      <PageHeader title="Your record" actions={<button type="button">Correct something</button>} />,
    );

    expect(screen.getByRole("button", { name: "Correct something" })).toBeVisible();
  });

  it("passes an axe audit", async () => {
    const { container } = render(
      <PageHeader
        eyebrow="Workspace"
        title="Overview"
        description="What changed across the workspace this week."
        actions={<button type="button">Refresh</button>}
      />,
    );

    await expect(axe(container)).resolves.toHaveNoViolations();
  });
});
