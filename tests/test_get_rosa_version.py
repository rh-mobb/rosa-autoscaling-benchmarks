"""
tests/test_get_rosa_version.py — Unit tests for scripts/get-rosa-version.py
"""

import sys
from pathlib import Path

import pytest

# Make the scripts directory importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Import the module under test; rename to avoid the hyphen
import importlib.util

spec = importlib.util.spec_from_file_location(
    "get_rosa_version",
    Path(__file__).parent.parent / "scripts" / "get-rosa-version.py",
)
assert spec is not None
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)  # type: ignore[attr-defined]

Version = mod.Version
find_latest_common_version = mod.find_latest_common_version


class TestVersionParsing:
    def test_parse_stable(self) -> None:
        v = Version.parse("4.17.3")
        assert v == Version(4, 17, 3, "")
        assert v.is_stable()

    def test_parse_prerelease(self) -> None:
        v = Version.parse("4.17.3-rc.1")
        assert v == Version(4, 17, 3, "-rc.1")
        assert not v.is_stable()

    def test_parse_with_prefix(self) -> None:
        v = Version.parse("openshift-v4.16.0")
        assert v == Version(4, 16, 0, "")

    def test_str(self) -> None:
        assert str(Version(4, 17, 3, "")) == "4.17.3"
        assert str(Version(4, 17, 3, "-rc.1")) == "4.17.3-rc.1"

    def test_parse_invalid(self) -> None:
        with pytest.raises(ValueError):
            Version.parse("not-a-version")


class TestFindLatestCommonVersion:
    def test_picks_highest_stable(self) -> None:
        classic = ["4.17.3", "4.17.2", "4.16.10"]
        hcp = ["4.17.3", "4.17.1", "4.16.10"]
        assert find_latest_common_version(classic, hcp) == "4.17.3"

    def test_excludes_non_common(self) -> None:
        classic = ["4.17.3", "4.16.10"]
        hcp = ["4.17.2", "4.16.10"]
        # 4.17.3 not in HCP, 4.17.2 not in Classic; common is 4.16.10
        assert find_latest_common_version(classic, hcp) == "4.16.10"

    def test_prefers_stable_over_rc(self) -> None:
        classic = ["4.17.3-rc.1", "4.16.10"]
        hcp = ["4.17.3-rc.1", "4.16.10"]
        # Both have rc.1 and stable 4.16.10; prefer the stable version
        assert find_latest_common_version(classic, hcp) == "4.16.10"

    def test_falls_back_to_rc_when_no_stable(self) -> None:
        classic = ["4.17.3-rc.1"]
        hcp = ["4.17.3-rc.1"]
        assert find_latest_common_version(classic, hcp) == "4.17.3-rc.1"

    def test_no_common_exits(self) -> None:
        classic = ["4.17.3"]
        hcp = ["4.16.10"]
        with pytest.raises(SystemExit):
            find_latest_common_version(classic, hcp)

    def test_skips_unparseable(self) -> None:
        classic = ["4.17.3", "not-a-version"]
        hcp = ["4.17.3", "also-bad"]
        assert find_latest_common_version(classic, hcp) == "4.17.3"
