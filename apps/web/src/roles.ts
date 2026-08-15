import type { WorkRole } from "./auth/context.js";

/** All five roles get the same data through different lenses (md/08 §A.6), so
 * this decides emphasis only, never what anybody can see — one careless rename
 * from the visibility hierarchy md/05 §B.2 refuses. First screens: md/11 §6. */
export interface RoleProfile {
  value: WorkRole;

  label: string;
  detail: string;
  /** Where CAIRN opens for them (md/11 §6). */
  home: string;
  homeLabel: string;
  /** One sentence at the top of their own record. For the designer this is the
   * md/08 §A.4 mitigation itself, not decoration. */
  recordLead: string;
}

export const ROLE_PROFILES: readonly RoleProfile[] = [
  {
    value: "founder",
    label: "Founder or team lead",
    detail: "You want to know what shipped, what stalled, and what needs you.",
    home: "/",
    homeLabel: "the team brief",
    recordLead:
      "Your own week, on the same terms as everybody else's — the team can see this about you exactly as you can see it about them.",
  },
  {
    value: "developer",
    label: "Engineer",
    detail: "You want no status reports, and no sense of being watched.",
    home: "/me",
    homeLabel: "your record",
    recordLead:
      "What CAIRN believes about your work, and where it got it. Nothing here is a count, a score, or a comparison — and if any of it is wrong, correcting it takes one action.",
  },
  {
    value: "designer",
    label: "Designer",
    detail: "You want the work that never lands in a repository to count.",
    home: "/me",
    homeLabel: "your record",
    recordLead:
      "Reviews, decisions and the conversations that set direction count here exactly as much as merged code. If something you did is missing, say so — that is how CAIRN learns to see it.",
  },
  {
    value: "product",
    label: "Product",
    detail: "You want one initiative followed across code, chat and meetings.",
    home: "/feed",
    homeLabel: "the team feed",
    recordLead:
      "What CAIRN believes about your work. Decisions and the questions you opened are recorded the same way delivery is.",
  },
  {
    value: "operations",
    label: "Marketing, sales or operations",
    detail: "You want to read what happened without needing the technical detail.",
    home: "/",
    homeLabel: "the team brief",
    recordLead:
      "What CAIRN believes about your work, in the same plain language it uses for everyone else's.",
  },
] as const;

export function homeFor(role: WorkRole | null | undefined): string {
  return profileFor(role)?.home ?? "/";
}

export function homeLabelFor(role: WorkRole | null | undefined): string {
  return profileFor(role)?.homeLabel ?? "the team brief";
}

/** The default mentions neither code nor design: assuming engineering would be
 * the md/08 §A.4 invisible-work problem, one screen earlier. */
export function recordLeadFor(role: WorkRole | null | undefined): string {
  return (
    profileFor(role)?.recordLead ??
    "What CAIRN believes about your work, and where it got that from. If any of it is wrong, say so — it is your record."
  );
}

function profileFor(role: WorkRole | null | undefined): RoleProfile | undefined {
  return role == null ? undefined : ROLE_PROFILES.find((profile) => profile.value === role);
}
