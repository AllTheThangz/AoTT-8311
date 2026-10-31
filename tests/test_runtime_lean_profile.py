"""Dependency and recovery guards for the offline runtime-lean image profile."""
from pathlib import Path
import os
import struct
import tempfile
import unittest

from test_rootfs_profiles import fixture, m


def mips_elf(needed=None, embedded=b""):
    """Nonexecutable ELF32 MIPS fixture parsed by the real readelf binary."""
    ident=b"\x7fELF"+bytes([1,2,1,0])+bytes(8)
    if needed is None:
        return ident+struct.pack(">HHIIIIIHHHHHH",3,8,1,0,0,0,0,52,0,0,0,0,0)+embedded
    strings=b"\0"+needed.encode("ascii")+b"\0"
    header=ident+struct.pack(">HHIIIIIHHHHHH",3,8,1,0,52,0,0,52,32,2,0,0,0)
    load=struct.pack(">IIIIIIII",1,0,0,0,148+len(strings),148+len(strings),4,4)
    dynamic=struct.pack(">IIIIIIII",2,116,116,116,32,32,4,4)
    entries=struct.pack(">iIiIiIiI",5,148,10,len(strings),1,1,0,0)
    return header+load+dynamic+entries+strings+embedded


class RuntimeLeanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.root=self.directory/"synthetic-prx126"
        self.root.mkdir()
        fixture(self.root)
        (self.root/"usr/bin/omcid").write_bytes(mips_elf())
        for relative in m.LEAN_REMOVALS:
            path=self.root/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b"optional fixture\n")
        for relative,target in {
            "usr/bin/zstdcat":"zstd",
            "usr/bin/unzstd":"zstd",
            "usr/bin/zstdmt":"zstd",
            "usr/lib/libzstd.so":"libzstd.so.1",
            "usr/lib/libzstd.so.1":"libzstd.so.1.4.5",
            "usr/lib/libncursesw.so.6":"libncursesw.so.6.1",
        }.items():
            path=self.root/relative
            path.unlink()
            path.symlink_to(target)
        (self.root/"usr/bin/zstdless").write_text('#!/bin/sh\nzstdcat "$@" | less\n')
        (self.root/"usr/bin/zstdgrep").write_text('#!/bin/sh\nzcat=${ZCAT:-zstdcat}\n')
        self.login=self.root/m.LEAN_LOGIN_PROFILE
        self.login.parent.mkdir(parents=True)
        self.login.write_text('export PATH=/bin:/usr/bin\n'+m.LEAN_LOGIN_ALIAS+'\n')

    def put(self,relative,data):
        path=self.root/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(data,str):
            path.write_text(data)
        else:
            path.write_bytes(data)
        return path

    def test_stage_preserves_source_recovery_crypto_and_configuration(self):
        original_login=self.login.read_bytes()
        target=self.directory/"lean"
        report=m.stage(self.root,target,"prx126-runtime-lean")
        self.assertTrue(report["staged"])
        self.assertFalse(report["hardware_qualified"])
        self.assertEqual(len(report["pruned"]),47)
        self.assertEqual(self.login.read_bytes(),original_login)
        self.assertEqual((target/m.LEAN_LOGIN_PROFILE).read_text(),
                         'export PATH=/bin:/usr/bin\n')
        self.assertEqual(report["source_edits"][0]["operation"],
                         "remove-audited-mtr-alias")
        self.assertGreater(report["static_dependency_checks"]["elf_objects_scanned"],0)
        for relative in m.PROFILES["prx126-runtime-lean"]:
            self.assertFalse(os.path.lexists(target/relative),relative)
            self.assertTrue(os.path.lexists(self.root/relative),relative)
        for relative in m.PROTECTED:
            self.assertTrue((target/relative).exists(),relative)
        self.assertTrue((target/"usr/lib/libssl.so.1.1").exists())
        self.assertTrue((target/"etc/mibs/prx300_2U.ini").exists())

    def test_retained_elf_needing_pruned_library_rejected(self):
        self.put("usr/bin/recovery",mips_elf("libzstd.so.1"))
        with self.assertRaisesRegex(m.ProfileError,"requires pruned shared library"):
            m.stage(self.root,self.directory/"rejected","prx126-runtime-lean")
        self.assertFalse((self.directory/"rejected").exists())

    def test_retained_elf_embedded_dlopen_name_rejected(self):
        self.put("usr/lib/plugin.so",mips_elf(embedded=b"libncursesw.so.6\0"))
        with self.assertRaisesRegex(m.ProfileError,"embeds a pruned library"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_retained_lua_late_library_load_rejected(self):
        self.put("usr/lib/lua/recovery.lua",
                 'package.loadlib("/usr/lib/libncursesw.so.6", "open")\n')
        with self.assertRaisesRegex(m.ProfileError,"pruned library"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_retained_bin_wrapper_shell_default_rejected(self):
        self.put("usr/bin/compressed-logs",'#!/bin/sh\nzcat=${ZCAT:-zstdcat}\n')
        with self.assertRaisesRegex(m.ProfileError,"pruned utility"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_custom_mtr_login_alias_is_not_silently_removed(self):
        self.login.write_text("alias mtr='/usr/sbin/mtr --report'\n")
        with self.assertRaisesRegex(m.ProfileError,"pruned utility"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_duplicate_stock_alias_rejected(self):
        self.login.write_text((m.LEAN_LOGIN_ALIAS+"\n")*2)
        with self.assertRaisesRegex(m.ProfileError,"Ambiguous MTR"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_short_transfer_command_in_recovery_script_rejected(self):
        self.put("sbin/recover",'#!/bin/sh\nrx /tmp/recovery.bin\n')
        with self.assertRaisesRegex(m.ProfileError,"pruned utility"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_rx_lua_variable_does_not_look_like_a_shell_command(self):
        self.put("usr/lib/lua/counters.lua","rx = 0\ntx = 0\n")
        m.profile_plan(self.root,"prx126-runtime-lean")

    def test_retained_symlink_to_removed_utility_rejected(self):
        for link_target in ("zstd","/usr/bin/zstd"):
            with self.subTest(target=link_target):
                link=self.root/"usr/bin/compression-alias"
                link.symlink_to(link_target)
                try:
                    with self.assertRaisesRegex(m.ProfileError,"Retained symlink"):
                        m.profile_plan(self.root,"prx126-runtime-lean")
                finally:
                    link.unlink()

    def test_optional_symlink_to_retained_file_rejected(self):
        path=self.root/"usr/bin/zstdcat"
        path.unlink()
        path.symlink_to("omcid")
        with self.assertRaisesRegex(m.ProfileError,"does not resolve to a pruned file"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_unexpected_runtime_integrity_pin_rejected(self):
        path=self.root/"lib/8311-release-profile"
        path.write_text(path.read_text()+"file candidate usr/bin/zstd 4 abc123\n")
        with self.assertRaisesRegex(m.ProfileError,"pruned utility|still pinned"):
            m.profile_plan(self.root,"prx126-runtime-lean")

    def test_invalid_surviving_elf_does_not_pass_closure(self):
        self.put("usr/bin/recovery",b"\x7fELF"+b"broken")
        with self.assertRaisesRegex(m.ProfileError,"Cannot inspect retained ELF"):
            m.profile_plan(self.root,"prx126-runtime-lean")


if __name__=="__main__":
    unittest.main()
