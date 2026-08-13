import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { Button } from "../src/components/Button.js";
import { CertaintyBadge } from "../src/components/CertaintyBadge.js";
import { checkContrast } from "../src/a11y/contrast.js";
import { darkTheme, lightTheme, neutral } from "../src/tokens/color.js";
import { fontSize, textStyle } from "../src/tokens/typography.js";
import { space } from "../src/tokens/layout.js";
import "../src/styles/theme.css";
import "./preview.css";

type ThemeName = "light" | "dark";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <section className="section">
      <h2 className="sectionTitle">{title}</h2>
      {children}
    </section>
  );
}

function ColorRamp(): React.JSX.Element {
  return (
    <div className="ramp">
      {Object.entries(neutral).map(([step, hex]) => (
        <div key={step} className="rampItem">
          <div className="swatch" style={{ background: hex }} />
          <code className="rampLabel">{step}</code>
          <code className="rampHex">{hex}</code>
        </div>
      ))}
    </div>
  );
}

/**
 * Live contrast readout.
 *
 * The same calculation the test suite asserts against — shown here so the
 * numbers are visible during design review rather than only in CI output.
 */
function ContrastTable({ theme }: { theme: ThemeName }): React.JSX.Element {
  const t = theme === "light" ? lightTheme : darkTheme;
  const pairs = [
    ["fg.default on bg.default", t.fg.default, t.bg.default, "normalText"],
    ["fg.muted on bg.default", t.fg.muted, t.bg.default, "normalText"],
    ["fg.subtle on bg.default", t.fg.subtle, t.bg.default, "largeText"],
    ["accent on bg.default", t.accent.default, t.bg.default, "normalText"],
    ["focus ring on bg.default", t.border.focus, t.bg.default, "nonText"],
    ["border.interactive on bg.default", t.border.interactive, t.bg.default, "nonText"],
  ] as const;

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Pair</th>
          <th>Ratio</th>
          <th>Required</th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody>
        {pairs.map(([label, fg, bg, req]) => {
          const r = checkContrast(fg, bg, req);
          return (
            <tr key={label}>
              <td>
                <code>{label}</code>
              </td>
              <td>{r.ratio}:1</td>
              <td>{r.required}:1</td>
              <td>{r.passes ? "PASS" : "FAIL"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function App(): React.JSX.Element {
  const [theme, setTheme] = useState<ThemeName>("light");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return (
    <div className="page">
      <header className="header">
        <div>
          <h1 className="title">CAIRN Design System</h1>
          <p className="subtitle">
            Black and white. Minimalist. WCAG 2.1 AA, verified by 39 tests rather than asserted.
          </p>
        </div>
        <Button
          onClick={() => {
            setTheme(theme === "light" ? "dark" : "light");
          }}
        >
          {theme === "light" ? "Dark theme" : "Light theme"}
        </Button>
      </header>

      <Section title="Neutral ramp">
        <p className="note">
          Every value is a true grey with equal RGB channels, so the interface has no colour
          temperature at all.
        </p>
        <ColorRamp />
      </Section>

      <Section title="Contrast — live">
        <p className="note">
          The same calculation CI asserts against. Switch themes and the numbers update.
        </p>
        <ContrastTable theme={theme} />
      </Section>

      <Section title="Typography">
        <p className="note">
          Sized in rem so text respects the browser font-size setting. Prose is capped at 68
          characters per line.
        </p>
        <div className="stack">
          {(Object.keys(textStyle) as (keyof typeof textStyle)[]).map((name) => (
            <div key={name} className="typeRow">
              <code className="typeName">{name}</code>
              <span style={textStyle[name]}>The authentication refactor shipped on Tuesday.</span>
            </div>
          ))}
        </div>
        <div className="stack" style={{ marginTop: space[6] }}>
          {Object.entries(fontSize).map(([name, size]) => (
            <div key={name} className="typeRow">
              <code className="typeName">{name}</code>
              <span style={{ fontSize: size }}>{size}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Prose width">
        <p className="prose">
          Ali merged the authentication refactor on Tuesday after review from two engineers. The
          payments work has not moved since Thursday — the branch is open but the reviewer has been
          unavailable. Sara raised a question in the design channel about the onboarding flow that
          nobody has answered yet.
        </p>
      </Section>

      <Section title="Buttons">
        <div className="row">
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
        </div>
        <div className="row">
          <Button variant="primary" size="sm">
            Small
          </Button>
          <Button variant="secondary" size="sm">
            Small
          </Button>
        </div>
        <div className="row">
          <Button variant="primary" disabled>
            Disabled
          </Button>
          <Button variant="secondary" disabled>
            Disabled
          </Button>
          <Button variant="primary" loading>
            Generating brief
          </Button>
        </div>
        <p className="note">
          Try tabbing through these — the focus ring is the one place colour is used, because a
          monochrome interface otherwise fails WCAG 2.4.7. There is no danger variant: destructive
          actions are distinguished by confirmation flow, not by turning a button red.
        </p>
      </Section>

      <Section title="Certainty tiers">
        <p className="note">
          The most product-specific component. Tiers differ by weight, opacity and border style —
          never colour. Traffic-light styling would be the only colour in the system, drawing the
          eye to uncertainty rather than content, and amber or red reads as a judgement about the
          person rather than about the evidence. Hover each badge for its meaning.
        </p>
        <div className="row">
          <CertaintyBadge certainty="verified" />
          <CertaintyBadge certainty="observed" />
          <CertaintyBadge certainty="suggested" />
        </div>

        <div className="briefDemo">
          <p className="prose">
            Ali merged the authentication refactor on Tuesday.{" "}
            <CertaintyBadge certainty="verified" />
          </p>
          <p className="prose">
            The team decided to defer the billing migration to next sprint.{" "}
            <CertaintyBadge certainty="observed" />
          </p>
          <p className="prose">
            It sounded like Sara agreed to pick up the onboarding copy.{" "}
            <CertaintyBadge certainty="suggested" />
          </p>
        </div>
        <p className="note">
          Notice the language shifts with certainty: &ldquo;merged&rdquo; states a fact, &ldquo;it
          sounded like&rdquo; invites correction. Given meeting transcripts carry roughly 30%
          speaker misattribution, asserting the third line as fact would be a trust failure waiting
          to happen.
        </p>
      </Section>

      <footer className="footer">
        <p className="note">
          Step 2 of 30 — md/16-build-steps.md. Screens arrive in Stage D; this page exists so
          components are reviewed in isolation first.
        </p>
      </footer>
    </div>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
