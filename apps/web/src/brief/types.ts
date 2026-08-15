import type { Brief as ApiBrief, FactPage } from "@cairn/api-client";

/**
 * The brief's shapes, from the generated client.
 *
 * **These used to be hand-written**, because the endpoints did not exist and the
 * screens had to be built against something. The file that held them said its
 * job was to be deleted when the real types arrived. They have.
 *
 * Re-exported through this module rather than imported directly by each screen,
 * for one reason: the generated names are positional
 * (`paths["/v1/..."]["get"]["responses"][200]...`) and a component importing
 * that is a component nobody can read. The indirection is a vocabulary, not an
 * abstraction — nothing here changes a shape.
 *
 * **Every field the API marks optional stays optional.** Flattening `claims?:
 * Claim[]` into `Claim[]` here would move the missing-data branch from the type
 * system into a runtime crash on the one screen a founder opens every morning.
 */

export type Brief = ApiBrief;

/** One sentence of a brief, with everything needed to check it. */
export type Claim = NonNullable<ApiBrief["claims"]>[number];

/**
 * Where a claim came from.
 *
 * `url` is optional because some evidence has no permalink — a meeting
 * transcript, most obviously. The interface handles a citation it cannot link
 * by naming the source rather than by hiding the citation: an unlinked citation
 * is still provenance a person can go and check, whereas a hidden one silently
 * breaks the product's central promise.
 */
export type SourceRef = NonNullable<Claim["citations"]>[number];

export type Fact = NonNullable<FactPage["items"]>[number];

/** The taxonomy, as the API sends it. A string there, so a client that gains a
 * new kind renders it rather than refusing to deserialise the page. */
export type FactKind = string;
