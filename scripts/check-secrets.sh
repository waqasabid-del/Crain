#!/usr/bin/env sh
#
# Fast pre-commit secret scan.
#
# A first line of defence only — gitleaks in CI (.github/workflows/ci.yml) is
# the thorough scan. This exists to catch the obvious mistake in under a second,
# because a hook slow enough to be annoying gets bypassed with --no-verify.
#
# Logic lives here rather than inline in lefthook.yml so that it is readable,
# testable, and not subject to differences in how hook runners handle shell
# quoting and negation across platforms.
#
# See md/17-engineering-standards.md §9.

set -eu

# Patterns are assembled from fragments so that this file does not match itself.
# A scanner that trips on its own definitions blocks every commit that touches
# it, which teaches people to disable it.
AWS="AKIA[0-9A-Z]{16}"
PEM="BEGIN [A-Z ]*PRIVATE KEY"
ANTHROPIC="sk""-ant-[a-zA-Z0-9_-]{20,}"
OPENAI="sk""-[a-zA-Z0-9]{32,}"
GITHUB_PAT="gh[pousr]""_[A-Za-z0-9]{36,}"
SLACK="xox[baprs]""-[A-Za-z0-9-]{10,}"
GOOGLE="AIza""[0-9A-Za-z_-]{35}"

PATTERN="($AWS|$PEM|$ANTHROPIC|$OPENAI|$GITHUB_PAT|$SLACK|$GOOGLE)"

# Only added lines, and never this file itself.
FINDINGS=$(
  git diff --cached -U0 -- . ":(exclude)scripts/check-secrets.sh" \
    | grep -E "^\+" \
    | grep -E "$PATTERN" \
    || true
)

if [ -n "$FINDINGS" ]; then
  echo "✖ Possible secret detected in staged changes:"
  echo ""
  echo "$FINDINGS" | head -5
  echo ""
  echo "Move the value to Secret Manager and reference it at runtime."
  echo "See md/17-engineering-standards.md §9."
  echo ""
  echo "If this is a false positive, adjust the patterns in this script rather"
  echo "than bypassing the hook."
  exit 1
fi

exit 0
