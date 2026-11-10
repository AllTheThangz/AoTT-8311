"""P0 version-aware candidate qualification: isolated host-shell negative tests.

These tests only create temporary regular files and source shell functions
from this repository. They never mount, flash or contact a live device.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/"overlay/lib/8311-upgrade-lib.sh"
UPGRADE=ROOT/"overlay/usr/sbin/8311-firmware-upgrade.sh"

def digest(data):
    return hashlib.sha256(data).hexdigest()

class VersionAwareRootfsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.trusted=self.base/"trusted"
        self.target=self.base/"candidate"
        self.scratch=self.base/"scratch"
        for d in (self.trusted,self.target,self.scratch,self.target/"lib"):
            d.mkdir()
        self.common=b"trusted immutable runtime\n"
        self.old=b"old candidate value\n"
        self.new=b"new candidate value\n"
        (self.target/"etc").mkdir()
        (self.target/"etc/immutable").write_bytes(self.common)
        (self.target/"etc/current").write_bytes(self.new)
        self.header=[
            "profile potron-prx126-aott-v1",
            "target WAS-110",
            "variant basic",
            "component kernel 2274800 "+"a"*64,
            "component bootcore 5426656 "+"b"*64,
            "file common etc/immutable "+str(len(self.common))+" "+digest(self.common),
        ]
        for i in range(12):
            data=("trusted-runtime-record-"+str(i)+"\n").encode()
            path="etc/vendor"+str(i)
            (self.target/path).write_bytes(data)
            self.header.append("file common "+path+" "+str(len(data))+" "+digest(data))
        self.oldfile="file candidate etc/current "+str(len(self.old))+" "+digest(self.old)
        self.newfile="file candidate etc/current "+str(len(self.new))+" "+digest(self.new)
        self.write_profile(self.trusted/"8311-release-profile",self.header+[self.oldfile])
        self.write_profile(self.target/"lib/8311-release-profile",self.header+[self.newfile])

    def write_profile(self,path,lines):
        path.write_text("\n".join(lines)+"\n")

    def run_check(self,reviewed=True):
        profile=self.target/"lib/8311-release-profile"
        sha=digest(profile.read_bytes())
        script=(
            'set -eu; MAINT_LIBDIR="$1"; WORKDIR="$2"; . "$3"; '
            'check_reviewed_candidate_profile "$4" "$5" "$2"; '
            + ('check_runtime_profile "$4" candidate "$4/lib/8311-release-profile"; '
               if reviewed else 'check_runtime_profile "$4" candidate; ')
            + 'echo VERIFIED'
        )
        return subprocess.run(["bash","-c",script,"_",
                    str(self.trusted),str(self.scratch),str(LIB),
                    str(self.target),sha],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10)

    def test_exact_independent_review_accepts_changed_candidate(self):
        p=self.run_check()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("VERIFIED",p.stdout)

    def test_legacy_unreviewed_profile_rejects_changed_candidate(self):
        p=self.run_check(False)
        self.assertNotEqual(p.returncode,0)
        self.assertIn("Runtime profile mismatch",p.stderr)

    def test_wrong_reviewed_digest_rejected(self):
        p=self.target/"lib/8311-release-profile"
        script='set -eu; MAINT_LIBDIR="$1"; WORKDIR="$2"; . "$3"; check_reviewed_candidate_profile "$4" "$5" "$2"'
        r=subprocess.run(["bash","-c",script,"_",str(self.trusted),str(self.scratch),
                          str(LIB),str(self.target),"0"*64],
                         capture_output=True,text=True,timeout=10)
        self.assertNotEqual(r.returncode,0)
        self.assertIn("independently reviewed SHA-256",r.stderr)

    def test_protected_common_pins_rejected_even_when_hash_is_reviewed(self):
        self.header[3]="component kernel 2274800 "+"f"*64
        self.write_profile(self.target/"lib/8311-release-profile",self.header+[self.newfile])
        p=self.run_check()
        self.assertNotEqual(p.returncode,0)
        self.assertIn("protected board or common",p.stderr)

    def test_missing_previously_required_candidate_path_rejected(self):
        self.write_profile(self.target/"lib/8311-release-profile",
                           self.header+["file candidate etc/other 4 "+digest(b"test")])
        p=self.run_check()
        self.assertNotEqual(p.returncode,0)
        self.assertIn("missing a required runtime path",p.stderr)

    def test_duplicate_runtime_record_rejected(self):
        self.write_profile(self.target/"lib/8311-release-profile",
                           self.header+[self.newfile,self.newfile])
        p=self.run_check()
        self.assertNotEqual(p.returncode,0)
        self.assertIn("Invalid runtime profile record structure",p.stderr)

    def test_missing_or_modified_content_rejected(self):
        (self.target/"etc/current").write_bytes(b"X"*len(self.new))
        p=self.run_check()
        self.assertNotEqual(p.returncode,0)
        self.assertIn("Runtime profile mismatch",p.stderr)

    def test_symlinked_candidate_profile_rejected(self):
        p=self.target/"lib/8311-release-profile"
        p.rename(self.target/"lib/original")
        p.symlink_to("original")
        result=self.run_check()
        self.assertNotEqual(result.returncode,0)

    def test_guarded_installer_requires_exact_bank_and_fresh_state(self):
        text=UPGRADE.read_text()
        self.assertIn("--expect-candidate-profile-sha",text)
        self.assertIn("Reviewed candidate profiles require a guarded, exact-bank install",text)
        self.assertIn("check_reviewed_candidate_profile",LIB.read_text())
        self.assertIn('qualify_rootfs "$INSTALL_BANK" candidate "$EXPECT_CANDIDATE_PROFILE_SHA"',text)
        self.assertLess(text.index("if [ -n \"$EXPECT_CANDIDATE_PROFILE_SHA\" ]; then"),
                        text.index('lock_upgrade'))

    def test_shell_parser_accepts_both_new_source_files(self):
        for p in (LIB,UPGRADE):
            with self.subTest(path=p):
                result=subprocess.run(["sh","-n",str(p)],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)

if __name__=="__main__":
    unittest.main()
