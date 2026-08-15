import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button.js";
import styles from "./Button.module.css";

describe("Button", () => {
  it("renders its label", () => {
    render(<Button>Connect GitHub</Button>);
    expect(screen.getByRole("button", { name: "Connect GitHub" })).toBeInTheDocument();
  });

  it("defaults to type=button so it cannot accidentally submit a form", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  it("allows an explicit submit type", () => {
    render(<Button type="submit">Save</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "submit");
  });

  it("calls its handler on click", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Correct</Button>);

    await userEvent.click(screen.getByRole("button"));

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("is operable by keyboard", async () => {
    // Correcting your own record is the most important repeated action in the
    // product (md/05 §A.3). It must work without a mouse.
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Correct</Button>);

    await userEvent.tab();
    expect(screen.getByRole("button")).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not fire when disabled", async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Correct
      </Button>,
    );

    await userEvent.click(screen.getByRole("button"));

    expect(onClick).not.toHaveBeenCalled();
  });

  describe("loading state", () => {
    it("announces itself as busy rather than hiding its label", () => {
      // Swapping the label for a spinner makes the control's name vanish for
      // screen reader users mid-interaction.
      render(<Button loading>Generating brief</Button>);

      const button = screen.getByRole("button", { name: "Generating brief" });
      expect(button).toHaveAttribute("aria-busy", "true");
    });

    it("blocks interaction while busy", async () => {
      const onClick = vi.fn();
      render(
        <Button loading onClick={onClick}>
          Generating
        </Button>,
      );

      await userEvent.click(screen.getByRole("button"));

      expect(onClick).not.toHaveBeenCalled();
    });

    it("omits aria-busy when idle rather than setting it false", () => {
      render(<Button>Idle</Button>);
      expect(screen.getByRole("button")).not.toHaveAttribute("aria-busy");
    });
  });

  it("merges a caller-supplied className rather than replacing its own", () => {
    render(<Button className="custom">Label</Button>);
    const button = screen.getByRole("button");
    expect(button.className).toContain("custom");
    expect(button.className.split(" ").length).toBeGreaterThan(1);
  });

  it.each(["primary", "secondary", "ghost"] as const)("applies the %s variant class", (variant) => {
    // Asserted against the imported module, not a literal. Two reasons: the
    // processed class names are hashed, and — the point — a renamed or
    // deleted rule makes `styles[variant]` undefined, so this fails instead
    // of quietly comparing two strings that both happen to exist.
    //
    // This is only a real assertion because CSS Modules are now processed
    // rather than stubbed (vitest.config.ts). Under the stub every property
    // resolved to a truthy string and this test would have passed against a
    // stylesheet containing no classes at all.
    render(<Button variant={variant}>Label</Button>);

    const classes = screen.getByRole("button").className.split(" ");
    expect(styles[variant]).toBeDefined();
    expect(classes).toContain(styles.button);
    expect(classes).toContain(styles[variant]);
  });

  it("applies the size class", () => {
    render(<Button size="sm">Label</Button>);

    expect(styles.sm).toBeDefined();
    expect(screen.getByRole("button").className.split(" ")).toContain(styles.sm);
  });
});

describe("asChild", () => {
  it("renders the child element with the button's appearance", () => {
    // The case this exists for: a control that is a navigation. Rendering it as
    // a `<button>` with an `onClick` breaks middle-click, open-in-new-tab,
    // copy-link and the destination preview on hover.
    render(
      <Button asChild variant="primary">
        <a href="https://github.com/apps/cairn">Connect GitHub</a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "Connect GitHub" });
    expect(link).toHaveAttribute("href", "https://github.com/apps/cairn");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps the child's own classes", () => {
    render(
      <Button asChild className="from-button">
        <a href="/somewhere" className="from-child">
          Go
        </a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "Go" });
    expect(link.className).toContain("from-button");
    expect(link.className).toContain("from-child");
  });

  it("refuses a child that is not an element", () => {
    // A silent fallback to `<button>` would render something that looks right
    // and is not a link — the reported bug, one step later and much harder to
    // find.
    expect(() => render(<Button asChild>plain text</Button>)).toThrow(/single element child/);
  });
});
