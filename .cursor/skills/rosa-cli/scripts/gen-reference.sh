#!/usr/bin/env bash
# Recursively extracts rosa CLI help text for all commands and subcommands,
# producing a structured Markdown reference file at commands-reference.md.
#
# Uses `rosa help <cmd> <sub>` (cobra's help subcommand) rather than
# `rosa <cmd> <sub> --help` to avoid argument-validation errors on commands
# that require positional arguments (e.g. `rosa edit addon ID`).
#
# Usage: ./scripts/gen-reference.sh [rosa-binary]
#   rosa-binary  Path to rosa binary (default: rosa from PATH)
#
# Run this after upgrading rosa to keep the reference current.

set -uo pipefail

ROSA="${1:-rosa}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${SCRIPT_DIR}/../commands-reference.md"

if ! command -v "$ROSA" &>/dev/null; then
  echo "Error: '$ROSA' not found. Install rosa CLI first." >&2
  exit 1
fi

ROSA_VERSION=$("$ROSA" version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Run `rosa help [path...]` and strip WARN/INFO noise lines.
rosa_help() {
  "$ROSA" help "$@" 2>&1 \
    | grep -v '^WARN:' \
    | grep -v '^INFO:' || true
}

# Extract sub-command names from help output.
# Cobra lists them under "Available Commands:" until the next blank/flag line.
extract_subcommands() {
  echo "$1" \
    | awk '
      /^Available Commands:/ { found=1; next }
      found && /^$/ { exit }
      found && /^[A-Z]/ { exit }
      found { print $1 }
    ' \
    | grep -v '^$' || true
}

# Write a markdown section for a command, then recurse into subcommands.
# Args: $@ = command path components (e.g. "create" "cluster")
write_command() {
  local -a cmd_path=("$@")
  local help
  help=$(rosa_help "${cmd_path[@]}")

  [[ -z "$help" ]] && return 0

  # Heading depth = number of path components + 1  (## for top-level, ### for sub, etc.)
  local depth=$(( ${#cmd_path[@]} + 1 ))
  # Cap at 6 hashes (markdown max)
  (( depth > 6 )) && depth=6
  local hashes
  hashes=$(python3 -c "print('#' * $depth)")

  {
    echo ""
    echo "${hashes} rosa ${cmd_path[*]}"
    echo ""
    echo '```'
    echo "$help"
    echo '```'
    echo ""
  } >> "$OUT"

  local subcommands
  subcommands=$(extract_subcommands "$help")

  if [[ -n "$subcommands" ]]; then
    while IFS= read -r sub; do
      [[ -z "$sub" || "$sub" == "help" || "$sub" == "completion" ]] && continue
      write_command "${cmd_path[@]}" "$sub"
    done <<< "$subcommands"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

cat > "$OUT" <<EOF
# ROSA CLI Command Reference

Auto-generated from \`rosa version ${ROSA_VERSION}\` on $(date -u '+%Y-%m-%d').
Re-run \`scripts/gen-reference.sh\` after upgrading the rosa CLI.

This file covers both **ROSA Classic** and **ROSA HCP (Hosted Control Planes)**.
Commands specific to one variant are noted in the relevant help text (look for
\`--hosted-cp\` / \`--classic\` flags or variant-specific subcommands).

EOF

# Write global help
TOP_HELP=$(rosa_help)
{
  echo "## rosa (global flags)"
  echo ""
  echo '```'
  echo "$TOP_HELP"
  echo '```'
  echo ""
} >> "$OUT"

# Get top-level commands and walk each one
TOP_COMMANDS=$(extract_subcommands "$TOP_HELP")

while IFS= read -r cmd; do
  [[ -z "$cmd" || "$cmd" == "help" || "$cmd" == "completion" ]] && continue
  echo "  -> $cmd"
  write_command "$cmd"
done <<< "$TOP_COMMANDS"

LINE_COUNT=$(wc -l < "$OUT")
echo "Generated $OUT  (${LINE_COUNT} lines, rosa ${ROSA_VERSION})"
