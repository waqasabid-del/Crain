import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button.js";

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
});
