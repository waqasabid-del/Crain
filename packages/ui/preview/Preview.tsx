import { useEffect, useState } from "react";

import { WCAG_AA, contrastRatio } from "../src/a11y/contrast.js";
import { Button } from "../src/components/Button.js";
import { type Certainty, CertaintyBadge } from "../src/components/CertaintyBadge.js";
import { type Theme, darkTheme, lightTheme } from "../src/tokens/color.js";
import { space } from "../src/tokens/layout.js";
import { type TextStyleName, textStyle } from "../src/tokens/typography.js";
import styles from "./Preview.module.css";

/**
 * The living style guide.
 *
 * Step 2's exit criterion was "renders all base components", and it was marked
 * complete while `vite.config.ts` pointed at a `preview/` directory that did not
 * exist. Every component was tested and contrast-verified and had never been
 * rendered anywhere a person could look at it.
 *
 * That gap matters more here than it would elsewhere. CAIRN's stated priority is
 * that the interface be calm and obvious (md/05 §A.1) — a judgement no unit test
 * can make. This page is where that judgement gets made, in both themes, before
 * a component reaches a screen.
 *
 * It is deliberately not Storybook. Storybook is a build system, a config
 * surface and a dependency tree in exchange for controls and a sidebar; at two
 * components that trade is not worth making, and the Vite dev server already
 * configured here does the job. Revisit when the component count justifies it.
 */

type ThemeName = "light" | "dark";

const CERTAINTIES: readonly Certainty[] = ["verified", "observed", "suggested"];

const SPECIMENS: readonly { style: TextStyleName; sample: string }[] = [
  { style: "heading", sample: "This week in engineering" },
  { style: "subheading", sample: "Authentication and tenant isolation" },
  {
    style: "prose",
    sample:
      "Priya finished the invitation flow and moved on to session revocation. The " +
      "work on rate limiting is waiting on the API layer, which is the next thing " +
      "to land.",
  },
  { style: "body", sample: "The quick brown fox jumps over the lazy dog." },
  { style: "bodySmall", sample: "The quick brown fox jumps over the lazy dog." },
  { style: "label", sample: "Workspace name" },
  { style: "caption", sample: "Updated 4 minutes ago" },
];

/**
 * Contrast pairs that carry a WCAG obligation.
 *
 * Only the pairs the product actually renders. A grid of every combination
 * would look thorough and mean nothing — an unused pair failing is not a defect,
 * and burying the four that matter among thirty that do not is how a real
 * failure goes unnoticed.
 *
 * Each pair is checked against the requirement its token actually carries, not
 * a uniform 4.5:1. `fg.subtle` is deliberately a large-text token: it measures
 * 4.18:1 on the dark background, which is a defect only if something sets small
 * text in it. Holding it to 4.5:1 here would report a failure the design does
 * not have; holding everything to 3:1 would hide four real ones.
 */
const CONTRAST_PAIRS: readonly {
  label: string;
  fg: keyof Theme["fg"] | "borderInteractive" | "accent";
  requirement: keyof typeof WCAG_AA;
}[] = [
  { label: "Body text on background", fg: "default", requirement: "normalText" },
  { label: "Muted text on background", fg: "muted", requirement: "normalText" },
  { label: "Subtle text — large only", fg: "subtle", requirement: "largeText" },
  { label: "Control outline", fg: "borderInteractive", requirement: "nonText" },
  { label: "Focus ring", fg: "accent", requirement: "nonText" },
];

function foregroundFor(theme: Theme, key: string): string {
  if (key === "borderInteractive") return theme.border.interactive;
  if (key === "accent") return theme.accent.default;
  return theme.fg[key as keyof Theme["fg"]];
}

export function Preview(): React.JSX.Element {
  const [theme, setTheme] = useState<ThemeName>("light");

  useEffect(() => {
    // Set on the document element, not a wrapper: the tokens are declared on
    // :root and [data-theme], so scoping it lower would leave `body` — and
    // anything portalled out of the tree — on the other theme.
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const tokens = theme === "light" ? lightTheme : darkTheme;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>CAIRN — Design System</h1>
          <p className={styles.subtitle}>
            Black and white, monochrome by decision rather than by default. Colour carries meaning,
            and meaning about people is what this product refuses to imply — so there is no
            success/warning/danger scale for anything describing someone&rsquo;s work.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            setTheme((current) => (current === "light" ? "dark" : "light"));
          }}
          // The control announces what it switches to, not what is currently
          // shown. "Dark theme" alone is ambiguous — a screen reader user cannot
          // tell whether it reports state or offers an action.
          aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
        >
          {theme === "light" ? "Dark theme" : "Light theme"}
        </Button>
      </header>

      <ContrastSection theme={tokens} />
      <ColourSection theme={tokens} />
      <TypeSection />
      <ButtonSection />
      <CertaintySection />
      <SpacingSection />

      <footer className={styles.footer}>
        Every value on this page comes from <code>src/tokens/</code>. The stylesheet is generated
        from those tokens and checked for drift in CI, so a colour cannot pass its contrast test and
        ship as something else.
      </footer>
    </main>
  );
}

function ContrastSection({ theme }: { theme: Theme }): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Contrast</h2>
      <p className={styles.sectionNote}>
        Measured live from the tokens rendering this page, in the theme you are looking at. WCAG 2.1
        AA is a locked requirement — the European Accessibility Act has been in force since June
        2025 — so these are also asserted in the test suite. Shown here because a table someone can
        read is what makes the guarantee legible to a reviewer.
      </p>

      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Pair</th>
              <th scope="col">Ratio</th>
              <th scope="col">Required</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {CONTRAST_PAIRS.map((pair) => {
              const ratio = contrastRatio(foregroundFor(theme, pair.fg), theme.bg.default);
              const required = WCAG_AA[pair.requirement];
              const passes = ratio >= required;

              return (
                <tr key={pair.label}>
                  <th scope="row">{pair.label}</th>
                  <td className={styles.ratio}>{ratio.toFixed(2)}:1</td>
                  <td className={styles.ratio}>{required}:1</td>
                  {/* The word carries the meaning; the styling only emphasises
                      it. Conveying pass/fail by appearance alone would fail
                      WCAG 1.4.1 on a page whose subject is WCAG compliance. */}
                  <td className={passes ? styles.pass : styles.fail}>
                    {passes ? "Passes AA" : "Fails AA"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ColourSection({ theme }: { theme: Theme }): React.JSX.Element {
  const groups = Object.entries(theme) as [string, Record<string, string>][];
  const swatches = groups.flatMap(([group, roles]) =>
    Object.entries(roles).map(([role, value]) => ({ name: `${group}.${role}`, value })),
  );

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Colour roles</h2>
      <p className={styles.sectionNote}>
        Roles, not colours. Components reference <code>fg.default</code>, never a grey step, so
        changing a theme never means touching a component. Note that <code>border.default</code> is
        deliberately low-contrast: a hairline dividing two sections carries no information, while
        the outline of an input carries essential information — only the latter is held to 3:1.
      </p>

      <div className={styles.grid}>
        {swatches.map((swatch) => (
          <div key={swatch.name} className={styles.swatch}>
            <div className={styles.swatchChip} style={{ background: swatch.value }} />
            <div className={styles.swatchMeta}>
              <span className={styles.swatchName}>{swatch.name}</span>
              <span className={styles.swatchValue}>{swatch.value}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TypeSection(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Typography</h2>
      <p className={styles.sectionNote}>
        CAIRN&rsquo;s primary output is prose someone reads rather than scans, which makes
        typography load-bearing rather than decorative. Sizes are in <code>rem</code> so they
        respect the reader&rsquo;s browser setting; a <code>px</code> scale silently breaks zoom for
        anyone who has increased their default, and looks fine to everyone testing at defaults.
      </p>

      <div className={styles.specimen}>
        {SPECIMENS.map((specimen) => (
          <div key={specimen.style} className={styles.specimenRow}>
            <span className={styles.specimenName}>{specimen.style}</span>
            <span className={styles.specimenText} style={textStyle[specimen.style]}>
              {specimen.sample}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ButtonSection(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Buttons</h2>
      <p className={styles.sectionNote}>
        Three variants. There is no <code>danger</code> variant — destructive actions are
        distinguished by confirmation flow and wording, not by turning a button red, which is the
        only way to keep a palette that carries no semantic colour.
      </p>

      <div className={styles.stack}>
        <div className={styles.specimen}>
          <p className={styles.specimenLabel}>variant</p>
          <div className={styles.row}>
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
          </div>
        </div>

        <div className={styles.specimen}>
          <p className={styles.specimenLabel}>size</p>
          <div className={styles.row}>
            <Button size="sm">Small</Button>
            <Button size="md">Medium</Button>
          </div>
        </div>

        <div className={styles.specimen}>
          <p className={styles.specimenLabel}>state</p>
          <div className={styles.row}>
            <Button variant="primary" disabled>
              Disabled
            </Button>
            <Button variant="primary" loading>
              Saving
            </Button>
            <Button variant="secondary" loading>
              Saving
            </Button>
          </div>
          <p className={styles.subtitle}>
            The loading state sets <code>aria-busy</code> and keeps its label rather than swapping
            in a spinner, so a screen reader user is told the control is working instead of hearing
            its name vanish. Tab to these — the focus ring is the one place this system spends
            colour, because a monochrome interface otherwise fails WCAG 2.4.7.
          </p>
        </div>
      </div>
    </section>
  );
}

function CertaintySection(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Certainty</h2>
      <p className={styles.sectionNote}>
        The most product-specific component here. A GitHub assignment is unambiguous; a commitment
        inferred from a meeting transcript carries roughly 30% speaker-misattribution risk.
        Presenting both with equal authority is the fastest way to lose a user&rsquo;s trust for
        good.
      </p>
      <p className={styles.sectionNote}>
        Traffic-light colouring would be the only colour in the system, drawing the eye to
        uncertainty rather than content — and amber reads as a judgement about the person, not about
        the evidence. Tiers differ by weight and border instead, which survives greyscale and
        colour-blindness with no extra work. There are no percentages: &ldquo;73% confident&rdquo;
        looks rigorous, means nothing to a non-technical reader, and invites false precision.
      </p>

      <div className={styles.specimen}>
        <div className={styles.row}>
          {CERTAINTIES.map((certainty) => (
            <CertaintyBadge key={certainty} certainty={certainty} />
          ))}
        </div>
      </div>
    </section>
  );
}

function SpacingSection(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Spacing</h2>
      <p className={styles.sectionNote}>
        A 4px base, applied consistently. A single rhythm is what makes an interface feel
        considered; arbitrary values are what make it feel improvised.
      </p>

      <div className={styles.specimen}>
        {Object.entries(space)
          .filter(([step]) => step !== "0")
          .map(([step, value]) => (
            <div key={step} className={styles.specimenRow}>
              <span className={styles.specimenName}>
                space.{step} · {value}
              </span>
              <div className={styles.spaceRow}>
                <div className={styles.spaceBar} style={{ width: value }} />
              </div>
            </div>
          ))}
      </div>
    </section>
  );
}
