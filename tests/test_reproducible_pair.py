"""Synthetic USTAR integrity and provenance rejection tests.

Fixtures are tiny and contain no real firmware or subscriber information.
"""
import importlib.util
import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest
import sys

SOURCE = Path(__file__).resolve().parents[1]
TOOL = SOURCE / "tools/audit_reproducible_pair.py"
sys.path.insert(0, str(TOOL.parent))
spec = importlib.util.spec_from_file_location("repro_pair", TOOL)
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)


class PrivatePairAuditTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.folder = Path(self.workspace.name)
        self.epoch = 1234
        self.content = {
            "upgrade.sh": b"#!/bin/sh\nexit 0\n",
            "control": b"FW_VERSION=synthetic\n",
            "kernel.bin": b"synthetic-kernel",
            "bootcore.bin": b"synthetic-bootcore",
            "rootfs.img": b"synthetic-rootfs",
        }
        self.expected = {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in self.content.items()
        }
        self.archive = self.make_archive()

    def make_archive(self, *, filenames=None, epoch=None, modes=None):
        target = self.folder / ("archive-%d.tar" % len(list(self.folder.glob("*.tar"))))
        names = filenames if filenames is not None else pair.MEMBERS
        with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as out:
            for name in names:
                data = self.content.get(name, b"irrelevant")
                from io import BytesIO
                info = tarfile.TarInfo(name)
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = self.epoch if epoch is None else epoch
                info.mode = (modes or {}).get(
                    name, 0o755 if name == "upgrade.sh" else 0o644)
                info.size = len(data)
                out.addfile(info, BytesIO(data))
        return target

    def verify(self, path):
        return pair.validate_tar(path, self.expected, self.epoch,
                                 hashlib.sha256(path.read_bytes()).hexdigest())

    def test_expected_five_member_archive_passes(self):
        self.assertTrue(self.verify(self.archive))

    def test_wrong_order_is_rejected(self):
        p = self.make_archive(filenames=tuple(reversed(pair.MEMBERS)))
        with self.assertRaisesRegex(pair.ProvenanceError, "reordered"):
            self.verify(p)

    def test_duplicate_archive_member_is_rejected(self):
        p = self.make_archive(filenames=pair.MEMBERS + ("control",))
        with self.assertRaisesRegex(pair.ProvenanceError, "reordered"):
            self.verify(p)

    def test_unexpected_extra_archive_member_is_rejected(self):
        p = self.make_archive(filenames=pair.MEMBERS + ("secret.dat",))
        with self.assertRaisesRegex(pair.ProvenanceError, "reordered"):
            self.verify(p)

    def test_wrong_epoch_rejected(self):
        p = self.make_archive(epoch=self.epoch + 5)
        with self.assertRaisesRegex(pair.ProvenanceError, "metadata"):
            self.verify(p)

    def test_executable_mode_mismatch_rejected(self):
        p = self.make_archive(modes={"upgrade.sh": 0o644})
        with self.assertRaisesRegex(pair.ProvenanceError, "metadata"):
            self.verify(p)

    def test_modified_member_rejected_even_with_new_tar_digest(self):
        p = self.make_archive()
        self.expected["kernel.bin"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(pair.ProvenanceError, "member digest"):
            self.verify(p)

    def test_symlinked_archive_rejected(self):
        link = self.folder / "alias.tar"
        link.symlink_to(self.archive)
        with self.assertRaisesRegex(pair.ProvenanceError, "nonsymlink"):
            self.verify(link)

    def test_same_file_cannot_claim_two_independent_builds(self):
        with self.assertRaisesRegex(pair.ProvenanceError, "not aliases"):
            pair.independent_files(self.archive, self.archive, 134217728)

    def test_hardlinked_archive_cannot_claim_independence(self):
        alias = self.folder / "separate-name.tar"
        alias.hardlink_to(self.archive)
        with self.assertRaisesRegex(pair.ProvenanceError, "not aliases"):
            pair.independent_files(self.archive, alias, 134217728)

    def test_two_distinct_regular_files_pass_independence_check(self):
        second = self.make_archive()
        result = pair.independent_files(self.archive, second, 134217728)
        self.assertEqual(len(result), 2)
        self.assertNotEqual(result[0].stat().st_ino, result[1].stat().st_ino)

    def test_unreviewed_archive_checksum_rejected(self):
        with self.assertRaisesRegex(pair.ProvenanceError, "digest mismatch"):
            pair.validate_tar(self.archive, self.expected, self.epoch, "0" * 64)


if __name__ == "__main__":
    unittest.main()
