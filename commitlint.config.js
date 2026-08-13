/**
 * Conventional Commits — enforced by tooling, not memory.
 * See md/17-engineering-standards.md §2
 */
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      ["feat", "fix", "refactor", "test", "docs", "chore", "perf", "ci", "revert"],
    ],
    "scope-enum": [
      2,
      "always",
      [
        "web",
        "api",
        "ui",
        "types",
        "config",
        "ingestion",
        "pipeline",
        "infra",
        "ci",
        "deps",
        "spec",
        "repo",
      ],
    ],
    "subject-case": [2, "always", "lower-case"],
    "subject-max-length": [2, "always", 72],
    "body-max-line-length": [0],
  },
};
