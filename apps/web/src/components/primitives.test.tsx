import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { DescribedError } from "../errors.js";
import { AuthCard } from "./AuthCard.js";
import { formatDay, formatDayAndTime, formatGeneratedAt } from "./dates.js";
import { Field } from "./Field.js";
import { InlineProblem } from "./InlineProblem.js";
import { Section } from "./Section.js";
import { EmptyState, ErrorState, LoadingState } from "./States.js";
import { StatusNote } from "./StatusNote.js";

/**
 * The shared primitives, and specifically the accessibility contracts they
 * exist to guarantee.
 *
 * The audit these replace found **zero** uses of `aria-invalid` and **zero**
 * `aria-describedby` pointing at an error message anywhere in the app, and no
 * axe run with an error message on screen. So the assertions below are mostly
 * about wiring rather than rendering: a `<p>` appearing near an input is the
 * part that already worked, and the part that is announced to somebody who
 * cannot see the `<p>` is the part that did not.
 *
 * Rendered with bare `render` rather than the route harness: none of these
 * touches a client, a session or a route, and pulling in the provider tree would
 * make a failure here ambiguous.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx` for why this is honest rather
  // than a dodge.
  rules: { "color-contrast": { enabled: false } },
} as const;

const PROBLEM: DescribedError = {
  message: "CAIRN could not reach the server, so it could not save your choice.",
};

describe("Field", () => {
  it("binds its label to its control", () => {
    render(<Field label="Email address" type="email" />);

    expect(screen.getByLabelText("Email address")).toBeVisible();
  });

  it("describes the control with its hint, so a rule is heard before it is broken", () => {
    render(<Field label="Choose a password" hint="At least 12 characters." />);

    // `toHaveAccessibleDescription` resolves `aria-describedby` the way a
    // screen reader does. Asserting the attribute string instead would pass
    // against an id that points at nothing.
    expect(screen.getByLabelText("Choose a password")).toHaveAccessibleDescription(
      "At least 12 characters.",
    );
  });

  it("marks the control invalid and describes it with the error", () => {
    render(<Field label="Email address" error="Enter the address the invitation was sent to." />);

    const input = screen.getByLabelText("Email address");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter the address the invitation was sent to.");
  });

  it("describes the control with the error and the hint together, error first", () => {
    // Both, not one replacing the other: the rule is still true while the field
    // is wrong, and dropping it leaves the reader knowing they failed without
    // knowing what would pass.
    render(
      <Field
        label="Choose a password"
        hint="At least 12 characters."
        error="That password is too short."
      />,
    );

    expect(screen.getByLabelText("Choose a password")).toHaveAccessibleDescription(
      "That password is too short. At least 12 characters.",
    );
  });

  it("leaves aria-invalid and aria-describedby off entirely when there is nothing to say", () => {
    // Absent, not `aria-invalid="false"` and not an empty `aria-describedby`:
    // an empty description is a dangling reference, and some screen readers
    // announce the field as having one.
    render(<Field label="Your name" />);

    const input = screen.getByLabelText("Your name");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(input).not.toHaveAttribute("aria-describedby");
    expect(input).not.toHaveAccessibleDescription();
  });

  it("announces the error as well as describing it", () => {
    // The description is heard on focus, which does not reach a reader whose
    // focus is still on the submit button they just pressed.
    render(<Field label="Email address" error="That address is not in this workspace." />);

    expect(screen.getByRole("alert")).toHaveTextContent("not in this workspace");
  });

  it("gives two instances of the same field distinct ids", () => {
    render(
      <>
        <Field label="Email address" />
        <Field label="Email address" />
      </>,
    );

    const [first, second] = screen.getAllByLabelText("Email address");
    expect(first).toHaveAttribute("id");
    expect(first?.id).not.toBe(second?.id);
  });

  it("passes the caller's input attributes through", () => {
    render(<Field label="Email address" type="email" autoComplete="username" required disabled />);

    const input = screen.getByLabelText("Email address");
    expect(input).toHaveAttribute("type", "email");
    expect(input).toHaveAttribute("autocomplete", "username");
    expect(input).toBeRequired();
    expect(input).toBeDisabled();
  });

  it("passes an axe audit in its error state", async () => {
    const { container } = render(
      <Field
        label="Choose a password"
        type="password"
        hint="At least 12 characters."
        error="That password is too short."
      />,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("InlineProblem", () => {
  it("announces the failure without waiting for a focus move", () => {
    render(<InlineProblem error={PROBLEM} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/could not reach the server/i);
  });

  it("offers a way forward when the action can be repeated", async () => {
    const onRetry = vi.fn();
    render(<InlineProblem error={PROBLEM} onRetry={onRetry} />);

    await userEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("offers no retry when the caller has nothing to retry", () => {
    render(<InlineProblem error={PROBLEM} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the request ID quietly rather than in the message", () => {
    render(<InlineProblem error={{ ...PROBLEM, requestId: "req_01H9" }} />);

    expect(screen.getByText(/req_01H9/)).toBeVisible();
  });

  it("describes a field with only the message, not the retry button", () => {
    // The whole point of `id` landing on the paragraph: pointing at the wrapper
    // would append "Try again" and the reference to the field's description,
    // read out on every single focus.
    render(
      <>
        <InlineProblem
          id="problem"
          error={{ ...PROBLEM, requestId: "req_01H9" }}
          onRetry={vi.fn()}
        />
        <label htmlFor="email">Email address</label>
        <input id="email" aria-describedby="problem" />
      </>,
    );

    const description = screen.getByLabelText("Email address").getAttribute("aria-describedby");
    expect(description).toBe("problem");
    expect(screen.getByLabelText("Email address")).toHaveAccessibleDescription(PROBLEM.message);
  });

  it("passes an axe audit with a message on screen", async () => {
    const { container } = render(
      <InlineProblem error={{ ...PROBLEM, requestId: "req_01H9" }} onRetry={vi.fn()} />,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("StatusNote", () => {
  it("announces politely, so a confirmation does not interrupt", () => {
    render(<StatusNote>3 things are no longer attributed to you.</StatusNote>);

    expect(screen.getByRole("status")).toHaveTextContent("no longer attributed");
  });

  it("stays silent when it is standing guidance rather than a result", () => {
    render(<StatusNote live={false}>CAIRN never scores or ranks people.</StatusNote>);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText(/never scores or ranks/i)).toBeVisible();
  });
});

describe("Section", () => {
  it("labels its region with its own heading", () => {
    render(
      <Section title="What CAIRN never does">
        <p>Body.</p>
      </Section>,
    );

    // Found *by* its accessible name, which only resolves if `aria-labelledby`
    // points at an element that exists.
    const region = screen.getByRole("region", { name: "What CAIRN never does" });
    expect(within(region).getByText("Body.")).toBeVisible();
  });

  it("generates a distinct id for every instance", () => {
    // Two routes both hardcoded `id="never"`. A duplicate id makes
    // `aria-labelledby` resolve to whichever comes first, silently.
    render(
      <>
        <Section title="What CAIRN never does">
          <p>One.</p>
        </Section>
        <Section title="What CAIRN never does">
          <p>Two.</p>
        </Section>
      </>,
    );

    const [first, second] = screen.getAllByRole("heading", { name: "What CAIRN never does" });
    expect(first?.id).not.toBe("");
    expect(first?.id).not.toBe(second?.id);
  });

  it("renders h2 by default", () => {
    render(
      <Section title="Appearance">
        <p>Body.</p>
      </Section>,
    );

    expect(screen.getByRole("heading", { level: 2, name: "Appearance" })).toBeVisible();
  });

  it("renders the level the caller asks for", () => {
    render(
      <Section title="Outer">
        <Section title="Inner" headingLevel={3}>
          <p>Body.</p>
        </Section>
      </Section>,
    );

    expect(screen.getByRole("heading", { level: 2, name: "Outer" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 3, name: "Inner" })).toBeVisible();
  });

  it("renders an optional description above its content", () => {
    render(
      <Section title="Retention" description="How long CAIRN keeps what it reads.">
        <p>Body.</p>
      </Section>,
    );

    expect(screen.getByText("How long CAIRN keeps what it reads.")).toBeVisible();
  });

  it("passes an axe audit", async () => {
    const { container } = render(
      <Section title="What CAIRN never does" variant="eyebrow">
        <p>Body.</p>
      </Section>,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("States", () => {
  it("announces what is loading, since a skeleton says nothing", () => {
    render(<LoadingState label="today's brief" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading today's brief.");
  });

  it("renders EmptyState at h2 by default", () => {
    render(<EmptyState title="Nothing yet">CAIRN has not read anything.</EmptyState>);

    expect(screen.getByRole("heading", { level: 2, name: "Nothing yet" })).toBeVisible();
  });

  it("renders EmptyState at the level a surrounding section needs", () => {
    // The defect this fixes: two `<h2>`s as siblings, at six call sites.
    render(
      <Section title="This week">
        <EmptyState title="Nothing yet" headingLevel={3}>
          CAIRN has not read anything.
        </EmptyState>
      </Section>,
    );

    expect(screen.getByRole("heading", { level: 2, name: "This week" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 3, name: "Nothing yet" })).toBeVisible();
  });

  it("renders ErrorState at h2 by default and at the requested level otherwise", () => {
    const { rerender } = render(<ErrorState title="Could not load" error={PROBLEM} />);
    expect(screen.getByRole("heading", { level: 2, name: "Could not load" })).toBeVisible();

    rerender(<ErrorState title="Could not load" error={PROBLEM} headingLevel={4} />);
    expect(screen.getByRole("heading", { level: 4, name: "Could not load" })).toBeVisible();
  });

  it("still announces and still retries after the heading change", async () => {
    const onRetry = vi.fn();
    render(
      <ErrorState title="Could not load" error={PROBLEM} onRetry={onRetry} headingLevel={3} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/could not reach the server/i);
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not offer to retry a failure that will be refused identically forever", () => {
    // A permission or configuration refusal is not an outage. "Try again" in
    // front of one is a promise the product cannot keep, and the reader clicks
    // it three times before thinking to ask somebody.
    render(
      <ErrorState
        title="You do not have access to that"
        error={PROBLEM}
        onRetry={vi.fn()}
        retryable={false}
        action={<a href="/trust">Trust Center</a>}
      />,
    );

    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
    // Still somewhere to go: a dead end is what the retry button was covering.
    expect(screen.getByRole("link", { name: "Trust Center" })).toBeVisible();
  });

  it("gives an empty state somewhere to go, not just an explanation", () => {
    render(
      <EmptyState title="Nothing recorded yet" action={<a href="/trust">See what is connected</a>}>
        Nothing is read until a source is connected.
      </EmptyState>,
    );

    expect(screen.getByRole("link", { name: "See what is connected" })).toBeVisible();
  });

  it("shapes the skeleton like the content it stands in for", () => {
    // The point of a skeleton is that nothing moves when the content lands, so
    // the number of placeholders has to match the rows that are coming.
    const { container, rerender } = render(
      <LoadingState label="the team feed" shape="rows" lines={4} />,
    );
    expect(container.querySelectorAll("[aria-hidden='true']")).toHaveLength(4);

    rerender(<LoadingState label="the people in this workspace" shape="table" lines={2} />);
    expect(container.querySelectorAll("[aria-hidden='true']")).toHaveLength(2);
    // Whatever the shape, the announcement is the only thing a screen reader
    // gets from any of it.
    expect(screen.getByRole("status")).toHaveTextContent("Loading the people in this workspace.");
  });
});

describe("AuthCard", () => {
  it("owns the single h1 on a screen that has no page header", () => {
    render(
      <AuthCard title="Sign in" subtitle="CAIRN records what your team is working on.">
        <p>Form.</p>
      </AuthCard>,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    expect(screen.getByText(/records what your team is working on/i)).toBeVisible();
    expect(screen.getByText("Form.")).toBeVisible();
  });

  it("can drop the brand mark for a continuation rather than an arrival", () => {
    const { rerender } = render(
      <AuthCard title="Sign in">
        <p>Form.</p>
      </AuthCard>,
    );
    expect(screen.getByText("Cairn")).toBeVisible();

    rerender(
      <AuthCard title="This link is incomplete" brand={false}>
        <p>Form.</p>
      </AuthCard>,
    );
    expect(screen.queryByText("Cairn")).not.toBeInTheDocument();
  });

  it("passes an axe audit with a field in error inside it", async () => {
    const { container } = render(
      <AuthCard title="Sign in" subtitle="Welcome back." footer={<span>New here?</span>}>
        <Field label="Email address" type="email" error="That address did not match an account." />
      </AuthCard>,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("date formatting", () => {
  it("formats a day without a time, and a day with one", () => {
    // Asserted loosely: the locale is the machine's, and pinning the exact
    // string would fail in CI for a reason unrelated to the code.
    const iso = "2026-01-04T09:00:00Z";

    expect(formatDay(iso)).toMatch(/2026/);
    expect(formatDay(iso)).not.toMatch(/\d\d:\d\d/);
    expect(formatDayAndTime(iso)).toMatch(/\d?\d[:.]\d\d/);
  });

  it("says what a generated-at timestamp is, since a bare one reads as the subject", () => {
    expect(formatGeneratedAt("2026-01-04T09:00:00Z")).toMatch(/^Written /);
  });

  it("degrades to something deliberate rather than 'Invalid Date'", () => {
    expect(formatDay("not a date")).toBe("—");
    expect(formatDayAndTime("not a date")).toBe("—");
    expect(formatDay("not a date", "Not shown yet")).toBe("Not shown yet");
    // Empty for the brief: a dash under a title reads as a missing heading.
    expect(formatGeneratedAt("not a date")).toBe("");
  });
});
