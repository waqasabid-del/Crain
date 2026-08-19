import type { ReactNode } from "react";

import styles from "./CapacityChip.module.css";

/**
 * A person's self-declared availability, worn as a monochrome chip.
 *
 * **Colour never describes a person** (md/05 §B.2.2): no green-means-available,
 * no amber warning — the chip is the same ink as the rest of the page, because
 * a coloured availability dot is a status board, and a status board of people
 * is monitoring. The words carry everything, including whose words they are:
 * "self-reported" is in the visible label, not a tooltip, so nobody reads the
 * chip as CAIRN's assessment.
 *
 * `not_stated` renders as a plain em dash rather than a chip. The absence of a
 * declaration is not information about a person, and dressing it as a chip
 * would invite reading it as one.
 */
export function CapacityChip({ capacity }: { capacity: string }): ReactNode {
  if (capacity === "open_to_work") {
    return <span className={styles.chip}>Open to new work — self-reported</span>;
  }
  if (capacity === "at_capacity") {
    return <span className={styles.chip}>At capacity — self-reported</span>;
  }
  return (
    <span className={styles.notStated} aria-label="No availability stated">
      —
    </span>
  );
}
