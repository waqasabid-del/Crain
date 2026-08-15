"use client";

import { useId, type ChangeEvent, type ReactNode } from "react";

import { useAuth } from "../auth/context.js";
import styles from "./WorkspaceSwitcher.module.css";

/** A native `<select>`, not a custom menu: keyboard support, screen-reader
 * announcement, mobile behaviour and typeahead come free and correct. Collapses
 * to a plain name when there is only one workspace. */
export function WorkspaceSwitcher(): ReactNode {
  const { workspaces, activeWorkspace, switchWorkspace } = useAuth();
  const labelId = useId();

  if (activeWorkspace === null) return null;

  if (workspaces.length < 2) {
    return <div className={styles.single}>{activeWorkspace.name}</div>;
  }

  function handleChange(event: ChangeEvent<HTMLSelectElement>): void {
    switchWorkspace(event.target.value);
  }

  return (
    <div className={styles.switcher}>
      {/* A hidden label, not a placeholder option: a first option reading
        "Choose a workspace" is announced as the current value. */}
      <label className={styles.label} htmlFor={labelId}>
        Workspace
      </label>
      <select
        id={labelId}
        className={styles.select}
        value={activeWorkspace.id}
        onChange={handleChange}
      >
        {workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </select>
    </div>
  );
}
