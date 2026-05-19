#!/usr/bin/env python3
"""
scripts/get-rosa-version.py

Auto-detect the latest ROSA version supported by both Classic and HCP cluster types.

Usage:
    python3 scripts/get-rosa-version.py          # prints resolved version to stdout
    python3 scripts/get-rosa-version.py --verify 4.17.3  # validates a specific version

Exit codes:
    0 — success (version printed to stdout)
    1 — no common version found or ROSA CLI error
"""

import json
import re
import subprocess
import sys
from typing import NamedTuple


class Version(NamedTuple):
    major: int
    minor: int
    patch: int
    pre: str  # e.g. "" for stable, "-rc.1" for release candidates

    @classmethod
    def parse(cls, raw: str) -> "Version":
        # Strip leading "openshift-v" prefix that rosa sometimes emits
        raw = re.sub(r"^openshift-v", "", raw)
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)?$", raw)
        if not m:
            raise ValueError(f"Cannot parse version string: {raw!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or "")

    def is_stable(self) -> bool:
        return self.pre == ""

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}{self.pre}"


def list_rosa_versions(hosted_cp: bool) -> list[str]:
    """Return a list of raw version strings from `rosa list versions`.

    For Classic clusters, no variant flag is needed — the command returns all
    versions, which are Classic-compatible by definition.
    For HCP clusters, pass hosted_cp=True to add --hosted-cp.

    Note: `rosa list versions --classic` is NOT a valid flag (rosa 1.2.x).
    """
    cmd = ["rosa", "list", "versions", "-o", "json"]
    if hosted_cp:
        cmd.append("--hosted-cp")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: `{' '.join(cmd)}` failed: {exc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("ERROR: `rosa` CLI not found. Install it from https://github.com/openshift/rosa", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"ERROR: Could not parse JSON from rosa list versions output:\n{result.stdout}", file=sys.stderr)
        sys.exit(1)

    # The rosa CLI returns a list of objects; extract the 'raw_id' or 'id' field.
    versions = []
    for item in data:
        raw_id = item.get("raw_id") or item.get("id") or ""
        if raw_id:
            versions.append(raw_id)
    return versions


def find_latest_common_version(classic_raw: list[str], hcp_raw: list[str]) -> str:
    """
    Find the highest stable version present in both Classic and HCP version lists.
    Falls back to release candidates if no stable common version exists.
    """
    def parse_safe(v: str) -> Version | None:
        try:
            return Version.parse(v)
        except ValueError:
            return None

    classic_versions = {str(v): v for raw in classic_raw if (v := parse_safe(raw)) is not None}
    hcp_versions = {str(v): v for raw in hcp_raw if (v := parse_safe(raw)) is not None}

    common_keys = set(classic_versions) & set(hcp_versions)
    if not common_keys:
        print("ERROR: No common ROSA versions found between Classic and HCP.", file=sys.stderr)
        sys.exit(1)

    common = [classic_versions[k] for k in common_keys]
    # Prefer stable (no pre-release suffix), then sort descending
    stable = [v for v in common if v.is_stable()]
    candidates = stable if stable else common
    candidates.sort(reverse=True)
    return str(candidates[0])


def verify_version(target: str, classic_raw: list[str], hcp_raw: list[str]) -> None:
    """Verify that a given version exists in both Classic and HCP lists."""
    try:
        target_v = Version.parse(target)
    except ValueError:
        print(f"ERROR: Cannot parse target version: {target!r}", file=sys.stderr)
        sys.exit(1)

    def parse_safe(v: str) -> "Version | None":
        try:
            return Version.parse(v)
        except ValueError:
            return None

    classic_strs = {str(v) for raw in classic_raw if (v := parse_safe(raw)) is not None}
    hcp_strs = {str(v) for raw in hcp_raw if (v := parse_safe(raw)) is not None}

    target_str = str(target_v)
    in_classic = target_str in classic_strs
    in_hcp = target_str in hcp_strs

    if in_classic and in_hcp:
        print(f"OK: {target_str} is available on both Classic and HCP.", file=sys.stderr)
        print(target_str)
    else:
        if not in_classic:
            print(f"ERROR: {target_str} is NOT available for ROSA Classic.", file=sys.stderr)
        if not in_hcp:
            print(f"ERROR: {target_str} is NOT available for ROSA HCP.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    verify_target: str | None = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--verify" and i + 1 < len(sys.argv) - 1:
            verify_target = sys.argv[i + 2]
            break

    print("Fetching available ROSA versions for Classic...", file=sys.stderr)
    classic_raw = list_rosa_versions(hosted_cp=False)

    print("Fetching available ROSA versions for HCP...", file=sys.stderr)
    hcp_raw = list_rosa_versions(hosted_cp=True)

    if verify_target:
        verify_version(verify_target, classic_raw, hcp_raw)
    else:
        version = find_latest_common_version(classic_raw, hcp_raw)
        print(version)


if __name__ == "__main__":
    main()
