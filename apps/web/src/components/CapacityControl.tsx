"use client";

import { useId, useState, type ReactNode, type SyntheticEvent } from "react";

import type { Capacity } from "@cairn/api-client";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import styles from "./CapacityControl.module.css";

/**
 * The person's own availability, stated by them and nobody else.
 *
 * The copy carries the whole contract in plain English: everyone in the
 * workspace can see it, only the person themselves can set it, and CAIRN never
 * computes it from anything. An explicit save rather than save-on-select — a
 * statement about yourself deserves a deliberate act, and a radio that saves
 * on focus travel is a misclick published to the whole team.
 *
 * There is no history behind this control. Current state and when you said it;
 * changing your answer replaces it. (`PersonCapacity`'s docstring on the API
 * side records why a capacity timeline will not be added.)
 */
export function CapacityControl({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const groupId = useId();
  const [choice, setChoice] = useState<Capacity>("not_stated");
  const [state, setState] = useState<
    | { status: "idle" }
    | { status: "saving" }
    | { status: "saved" }
    | { status: "failed"; error: DescribedError }
  >({ status: "idle" });

  async function save(): Promise<void> {
    setState({ status: "saving" });
    try {
      await client.setMyCapacity(workspaceId, choice);
      setState({ status: "saved" });
    } catch (error: unknown) {
      setState({ status: "failed", error: describeError(error, "save your availability") });
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    void save();
  }

  const options: { value: Capacity; label: string }[] = [
    { value: "open_to_work", label: "Open to new work" },
    { value: "at_capacity", label: "At capacity" },
    { value: "not_stated", label: "Prefer not to say" },
  ];

  return (
    <form className={styles.control} onSubmit={handleSubmit}>
      <fieldset className={styles.fieldset}>
        <legend className={styles.legend}>Your availability</legend>
        <p className={styles.copy}>
          Everyone in this workspace can see what you choose here, shown as
          &ldquo;self-reported&rdquo;. Only you can set it — no role can change it for you, and
          CAIRN never fills it in from your activity.
        </p>
        <div className={styles.options} role="radiogroup" aria-labelledby={`${groupId}-legend`}>
          <span id={`${groupId}-legend`} className={styles.srOnly}>
            Availability options
          </span>
          {options.map((option) => (
            <label key={option.value} className={styles.option}>
              <input
                type="radio"
                name={`${groupId}-capacity`}
                value={option.value}
                checked={choice === option.value}
                onChange={() => {
                  setChoice(option.value);
                  setState({ status: "idle" });
                }}
              />
              {option.label}
            </label>
          ))}
        </div>
        <div className={styles.actions}>
          <button className={styles.save} type="submit" disabled={state.status === "saving"}>
            {state.status === "saving" ? "Saving…" : "Save"}
          </button>
          <span aria-live="polite" className={styles.outcome}>
            {state.status === "saved" && "Saved. Visible to your workspace as self-reported."}
            {state.status === "failed" && state.error.message}
          </span>
        </div>
      </fieldset>
    </form>
  );
}
