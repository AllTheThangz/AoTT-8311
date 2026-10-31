"""Release identity drift and offline path-safety regression tests."""
from pathlib import Path
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "release_identity_tests", ROOT / "tools/release_identity.py")
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)

CANONICAL = {
    "schema": 1, "product": "AoTT-8311", "version": "v2", "revision": "r2",
    "variant": "basic", "target": "WAS-110",
    "hardware_profile": "potron-prx126-aott-v1", "status": "offline-candidate",
}
CONTROL = (
    "FW_VER=AoTT-8311-v2r2\nFW_VERSION=AoTT-8311-v2r2\n"
    "FW_LONG_VERSION=AoTT-8311-v2r2_basic\nFW_REV=r2\nFW_REVISION=r2\n"
    "FW_VARIANT=basic\nFW_SUFFIX=\nFW_TARGET=WAS-110\n"
    "FW_PROFILE=potron-prx126-aott-v1\n"
)
PROFILE = "profile potron-prx126-aott-v1\ntarget WAS-110\nvariant basic\n"


class ReleaseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.base = Path(self.workspace.name)
        self.source = self.base / "source"
        (self.source / "overlay").mkdir(parents=True)
        (self.source / "MANIFEST.json").write_text("{}\n")
        self.metadata = self.source / "release.json"
        self.metadata.write_text(json.dumps(CANONICAL))
        self.spec = identity.write_source(self.source)
        self.rootfs = self.base / "rootfs"
        shutil.copytree(self.source / "overlay", self.rootfs)
        (self.rootfs / "lib").mkdir()
        self.profile = self.rootfs / "lib/8311-release-profile"
        self.profile.write_text(PROFILE)
        self.control = self.base / "control"
        self.control.write_text(CONTROL)

    def test_current_source_has_consistent_generated_identity(self):
        identity.check_files(ROOT / "overlay", identity.load_release(ROOT))

    def test_machine_and_display_identity_are_distinct_and_consistent(self):
        fields = identity.parse_assignments(self.rootfs / "etc/8311_version")
        self.assertEqual(fields["FW_VERSION"], "AoTT-8311-v2r2")
        self.assertEqual(fields["FW_LONG_VERSION"], "AoTT-8311-v2r2_basic")
        self.assertEqual(fields["FW_REVISION"], "r2")
        self.assertIn("AoTT-8311-v2 r2", (self.rootfs / "etc/banner").read_text())
        self.assertIn('display = "AoTT-8311-v2 r2"',
                      (self.rootfs / "usr/lib/lua/8311/version.lua").read_text())
        result = identity.check_rootfs(self.rootfs, self.source, self.control)
        self.assertEqual(result["runtime_identity"], "passed")
        self.assertEqual(result["control_identity"], "passed")
        self.assertFalse(result["hardware_qualified"])

    def test_verification_is_read_only(self):
        paths = [p for p in self.rootfs.rglob("*") if p.is_file()]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
        identity.check_rootfs(self.rootfs, self.source, self.control)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths})

    def test_missing_generated_metadata_rejected(self):
        for relative in ("etc/8311_version", "etc/aott_release", "etc/banner",
                         "usr/lib/lua/8311/version.lua"):
            with self.subTest(path=relative):
                path = self.rootfs / relative
                original = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, "Release identity mismatch"):
                    identity.check_rootfs(self.rootfs, self.source)
                path.write_bytes(original)

    def test_stale_metadata_rejected_independently(self):
        changes = {
            "etc/8311_version": (b"v2r2", b"v2r1"),
            "etc/aott_release": (b"AOTT_REVISION=r2", b"AOTT_REVISION=r1"),
            "etc/banner": (b"v2 r2", b"v2 r1"),
            "usr/lib/lua/8311/version.lua": (b'revision = "r2"', b'revision = "r1"'),
        }
        for relative, (old, new) in changes.items():
            with self.subTest(path=relative):
                path = self.rootfs / relative
                original = path.read_bytes()
                path.write_bytes(original.replace(old, new))
                with self.assertRaisesRegex(ValueError, "Release identity mismatch"):
                    identity.check_rootfs(self.rootfs, self.source)
                path.write_bytes(original)

    def test_duplicate_embedded_version_rejected(self):
        path = self.rootfs / "etc/8311_version"
        path.write_text(path.read_text() + "FW_VERSION=AoTT-8311-v2r2\n")
        with self.assertRaisesRegex(ValueError, "Release identity mismatch"):
            identity.check_rootfs(self.rootfs, self.source)

    def test_control_identity_and_alias_mismatches_rejected(self):
        replacements = (
            ("FW_VERSION=AoTT-8311-v2r2", "FW_VERSION=AoTT-8311-v2r1"),
            ("FW_REVISION=r2", "FW_REVISION=r1"),
            ("FW_VER=AoTT-8311-v2r2", "FW_VER=AoTT-8311-v2r1"),
            ("FW_LONG_VERSION=AoTT-8311-v2r2_basic", "FW_LONG_VERSION=stale"),
            ("FW_TARGET=WAS-110", "FW_TARGET=other-board"),
            ("FW_PROFILE=potron-prx126-aott-v1", "FW_PROFILE=other-profile"),
        )
        for old, new in replacements:
            with self.subTest(field=old.split("=")[0]):
                self.control.write_text(CONTROL.replace(old, new))
                with self.assertRaisesRegex(ValueError, "control disagrees"):
                    identity.check_rootfs(self.rootfs, self.source, self.control)

    def test_missing_or_duplicate_control_revision_rejected(self):
        for content in (CONTROL.replace("FW_REVISION=r2\n", ""),
                        CONTROL + "FW_REVISION=r2\n"):
            with self.subTest(content=content):
                self.control.write_text(content)
                with self.assertRaises(ValueError):
                    identity.check_rootfs(self.rootfs, self.source, self.control)

    def test_control_text_matches_runtime_constraints(self):
        for content in (CONTROL.replace("\n", "\r\n"), CONTROL + "X=\x00\n"):
            with self.subTest(content=repr(content)):
                self.control.write_bytes(content.encode())
                with self.assertRaisesRegex(ValueError, "Unsupported identity control text"):
                    identity.check_rootfs(self.rootfs, self.source, self.control)

    def test_runtime_profile_mismatch_or_duplicate_rejected(self):
        variants = (PROFILE.replace("WAS-110", "other-board"),
                    PROFILE.replace("potron-prx126-aott-v1", "other-profile"),
                    PROFILE.replace("basic", "other"),
                    PROFILE + "profile potron-prx126-aott-v1\n")
        for text in variants:
            with self.subTest(profile=text):
                self.profile.write_text(text)
                with self.assertRaisesRegex(ValueError, "Runtime hardware profile"):
                    identity.check_rootfs(self.rootfs, self.source)

    def test_symlinked_rootfs_or_overlay_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.rootfs, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "offline extracted rootfs"):
            identity.check_rootfs(alias, self.source)
        with self.assertRaisesRegex(ValueError, "Identity root"):
            identity.check_files(alias, self.spec)

    def test_symlinked_generated_file_rejected_without_following(self):
        path = self.rootfs / "etc/banner"
        external = self.base / "external-banner"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "Symlink in identity path"):
            identity.check_rootfs(self.rootfs, self.source)
        self.assertEqual(external.read_text(), identity.generated_files(self.spec)["etc/banner"])

    def test_symlinked_control_rejected(self):
        alias = self.base / "control-link"
        alias.symlink_to(self.control)
        with self.assertRaisesRegex(ValueError, "bounded regular file"):
            identity.check_rootfs(self.rootfs, self.source, alias)

    def test_generation_preflights_all_destination_paths(self):
        first = self.source / "overlay/etc/8311_version"
        first.write_text("previous-identity\n")
        lua = self.source / "overlay/usr/lib/lua/8311/version.lua"
        external = self.base / "external-version.lua"
        external.write_text("untouched\n")
        lua.unlink()
        lua.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "Symlink in identity path"):
            identity.write_source(self.source)
        self.assertEqual(first.read_text(), "previous-identity\n")
        self.assertEqual(external.read_text(), "untouched\n")

    def test_generation_rejects_nonregular_destination_before_updates(self):
        first = self.source / "overlay/etc/8311_version"
        first.write_text("previous-identity\n")
        last = self.source / "overlay/usr/lib/lua/8311/version.lua"
        last.unlink()
        last.mkdir()
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            identity.write_source(self.source)
        self.assertEqual(first.read_text(), "previous-identity\n")

    def test_symlinked_source_and_metadata_rejected(self):
        alias = self.base / "source-link"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Source checkout cannot be a symlink"):
            identity.write_source(alias)
        external = self.base / "external-release.json"
        external.write_bytes(self.metadata.read_bytes())
        self.metadata.unlink()
        self.metadata.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "Symlink in identity path"):
            identity.load_release(self.source)

    def test_malformed_spec_types_and_schema_rejected(self):
        values = [None, [], 1, "release", {**CANONICAL, "schema": True},
                  {**CANONICAL, "schema": 1.0}, {**CANONICAL, "revision": 2},
                  {**CANONICAL, "version": "v02"}, {**CANONICAL, "revision": "r0"},
                  {**CANONICAL, "revision": "r2;invalid"},
                  {**CANONICAL, "status": "released"}]
        for value in values:
            with self.subTest(value=value):
                self.metadata.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    identity.load_release(self.source)

    def test_unknown_missing_or_wrong_hardware_spec_rejected(self):
        missing = {key: value for key, value in CANONICAL.items() if key != "target"}
        for value in ({**CANONICAL, "extra": "field"}, missing,
                      {**CANONICAL, "hardware_profile": "other-profile"}):
            with self.subTest(value=value):
                self.metadata.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    identity.load_release(self.source)

    def test_duplicate_canonical_json_fields_rejected(self):
        content = json.dumps(CANONICAL)
        self.metadata.write_text(content[:-1] + ', "revision": "r2"}')
        with self.assertRaisesRegex(ValueError, "Duplicate canonical release field"):
            identity.load_release(self.source)

    def test_cli_reports_malformed_spec_without_traceback(self):
        self.metadata.write_text("null\n")
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/release_identity.py"),
             "--source", str(self.source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
