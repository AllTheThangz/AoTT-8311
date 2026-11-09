from pathlib import Path
import datetime as dt
import ipaddress
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT=Path(__file__).resolve().parents[1]
LUA=ROOT/"overlay/usr/lib/lua"
MODULE=LUA/"8311/tls_import.lua"
FIXTURE=ROOT/"tests/v3_tls_import_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))
LOOPBACK=".".join(("127","0","0","1"))
MGMT_IP=".".join(("192","0","2","10"))

def name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,cn)])

def make_cert(subject,issuer,public_key,signer,dns=(),ips=(),ca=False,
              not_before=None,not_after=None):
    now=dt.datetime.now(dt.timezone.utc)
    builder=(x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer)
        .public_key(public_key).serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now-dt.timedelta(minutes=5))
        .not_valid_after(not_after or now+dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca,path_length=None),critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True,key_encipherment=not ca,
            content_commitment=False,data_encipherment=False,key_agreement=False,
            key_cert_sign=ca,crl_sign=ca,encipher_only=None,decipher_only=None),
            critical=True))
    sans=[x509.DNSName(v) for v in dns]+[
        x509.IPAddress(ipaddress.ip_address(v)) for v in ips]
    if sans:
        builder=builder.add_extension(x509.SubjectAlternativeName(sans),critical=False)
    if not ca:
        builder=builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
    return builder.sign(signer,hashes.SHA256())

def write(path,data):
    path.write_bytes(data)
    return path

class V3TlsImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (VENDOR/"usr/bin/lua").is_file() or not shutil.which("qemu-mips-static"):
            raise unittest.SkipTest("Extracted vendor MIPS runtime unavailable")

    def run_fixture(self,leaf,key,chain,dns,ips,expected):
        p=subprocess.run([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(LUA),str(leaf),str(key),
            str(chain) if chain else "-",dns,ips,expected
        ],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout

    def test_self_signed_rsa_pem_and_der(self):
        with tempfile.TemporaryDirectory(prefix="aott-tls-import-test-") as td:
            d=Path(td)
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            cert=make_cert(name("onu.example.test"),name("onu.example.test"),
                           key.public_key(),key,dns=("onu.example.test",),
                           ips=(MGMT_IP,))
            pem_cert=write(d/"leaf.pem",cert.public_bytes(serialization.Encoding.PEM))
            pem_key=write(d/"key.pem",key.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            out=self.run_fixture(pem_cert,pem_key,None,
                                 "onu.example.test",MGMT_IP,"ok")
            self.assertIn("AOTT_V3_TLS_IMPORT_INSPECT_PASS",out)

            der_cert=write(d/"leaf.der",cert.public_bytes(serialization.Encoding.DER))
            der_key=write(d/"key.der",key.private_bytes(
                serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            out=self.run_fixture(der_cert,der_key,None,
                                 "onu.example.test",MGMT_IP,"ok")
            self.assertIn("AOTT_V3_TLS_IMPORT_INSPECT_PASS",out)

    def test_ec_leaf_with_complete_ca_chain(self):
        with tempfile.TemporaryDirectory(prefix="aott-tls-import-test-") as td:
            d=Path(td)
            ca_key=ec.generate_private_key(ec.SECP256R1())
            ca_name=name("AoTT Test Root")
            ca=make_cert(ca_name,ca_name,ca_key.public_key(),ca_key,ca=True)
            leaf_key=ec.generate_private_key(ec.SECP256R1())
            leaf=make_cert(name("onu.example.test"),ca_name,leaf_key.public_key(),
                           ca_key,dns=("onu.example.test",))
            leaf_path=write(d/"leaf.pem",leaf.public_bytes(serialization.Encoding.PEM))
            key_path=write(d/"key.pem",leaf_key.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            chain=write(d/"chain.pem",ca.public_bytes(serialization.Encoding.PEM))
            out=self.run_fixture(leaf_path,key_path,chain,
                                 "onu.example.test","","ok")
            self.assertIn("chain=1",out)

    def test_nonselfsigned_leaf_requires_issuer_chain(self):
        with tempfile.TemporaryDirectory(prefix="aott-tls-import-test-") as td:
            d=Path(td)
            ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            ca_name=name("AoTT Test Root")
            leaf_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            leaf=make_cert(name("onu.example.test"),ca_name,leaf_key.public_key(),
                           ca_key,dns=("onu.example.test",))
            leaf_path=write(d/"leaf.pem",leaf.public_bytes(serialization.Encoding.PEM))
            key_path=write(d/"key.pem",leaf_key.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            out=self.run_fixture(leaf_path,key_path,None,
                                 "onu.example.test","","refuse")
            self.assertIn("issuer_chain_required",out)

    def test_standard_intermediate_only_fullchain_is_accepted(self):
        with tempfile.TemporaryDirectory(prefix="aott-tls-import-test-") as td:
            d=Path(td)
            root_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            root_name=name("AoTT Test Root")
            root=make_cert(root_name,root_name,root_key.public_key(),root_key,ca=True)
            intermediate_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            intermediate_name=name("AoTT Test Intermediate")
            now=dt.datetime.now(dt.timezone.utc)
            intermediate=(x509.CertificateBuilder()
                .subject_name(intermediate_name).issuer_name(root_name)
                .public_key(intermediate_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now-dt.timedelta(minutes=5))
                .not_valid_after(now+dt.timedelta(days=30))
                .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
                .add_extension(x509.KeyUsage(
                    digital_signature=True,key_encipherment=False,
                    content_commitment=False,data_encipherment=False,key_agreement=False,
                    key_cert_sign=True,crl_sign=True,encipher_only=None,decipher_only=None),
                    critical=True)
                .sign(root_key,hashes.SHA256()))
            leaf_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            leaf=make_cert(name("onu.example.test"),intermediate_name,
                           leaf_key.public_key(),intermediate_key,
                           dns=("onu.example.test",))
            leafp=write(d/"leaf.pem",leaf.public_bytes(serialization.Encoding.PEM))
            keyp=write(d/"key.pem",leaf_key.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            # Public fullchain files normally include intermediates but omit the root.
            chainp=write(d/"chain.pem",intermediate.public_bytes(serialization.Encoding.PEM))
            out=self.run_fixture(leafp,keyp,chainp,"onu.example.test","","ok")
            self.assertIn("chain=1",out)

    def test_weak_rsa_and_unapproved_ec_curve_are_refused(self):
        with tempfile.TemporaryDirectory(prefix="aott-tls-import-test-") as td:
            d=Path(td)
            weak=rsa.generate_private_key(public_exponent=65537,key_size=1024)
            weak_cert=make_cert(name("onu.example.test"),name("onu.example.test"),
                                weak.public_key(),weak,dns=("onu.example.test",))
            weakp=write(d/"weak.pem",weak_cert.public_bytes(serialization.Encoding.PEM))
            weakkey=write(d/"weak.key",weak.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            out=self.run_fixture(weakp,weakkey,None,"onu.example.test","","refuse")
            self.assertIn("rsa_key_size_refused",out)

            ec_key=ec.generate_private_key(ec.SECP521R1())
            ec_cert=make_cert(name("onu.example.test"),name("onu.example.test"),
                              ec_key.public_key(),ec_key,dns=("onu.example.test",))
            ecp=write(d/"ec.pem",ec_cert.public_bytes(serialization.Encoding.PEM))
            eckey=write(d/"ec.key",ec_key.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            out=self.run_fixture(ecp,eckey,None,"onu.example.test","","refuse")
            self.assertIn("ec_curve_refused",out)

    def test_san_mismatch_and_expired_leaf_refused(self):
        with tempfile.TemporaryDirectory(prefix="aott-tls-import-test-") as td:
            d=Path(td)
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            cert=make_cert(name("onu.example.test"),name("onu.example.test"),
                           key.public_key(),key,dns=("onu.example.test",))
            leaf=write(d/"leaf.pem",cert.public_bytes(serialization.Encoding.PEM))
            keyp=write(d/"key.pem",key.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            out=self.run_fixture(leaf,keyp,None,"wrong.example.test","","refuse")
            self.assertIn("expected_dns_not_in_san",out)

            now=dt.datetime.now(dt.timezone.utc)
            expired=make_cert(name("onu.example.test"),name("onu.example.test"),
                              key.public_key(),key,dns=("onu.example.test",),
                              not_before=now-dt.timedelta(days=2),
                              not_after=now-dt.timedelta(days=1))
            expiredp=write(d/"expired.pem",expired.public_bytes(serialization.Encoding.PEM))
            out=self.run_fixture(expiredp,keyp,None,"onu.example.test","","refuse")
            self.assertIn("certificate_not_current",out)

    def test_native_vendor_uhttpd_rejects_mismatched_key(self):
        with tempfile.TemporaryDirectory(prefix="aott-uhttpd-pair-test-") as td:
            d=Path(td)
            (d/"index.html").write_text("pair-test\n")
            key1=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            key2=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            cert=make_cert(name("localhost"),name("localhost"),key1.public_key(),key1,
                           dns=("localhost",),ips=(LOOPBACK,))
            certp=write(d/"cert.pem",cert.public_bytes(serialization.Encoding.PEM))
            wrong=write(d/"wrong.pem",key2.private_bytes(
                serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            sock=socket.socket();sock.bind((LOOPBACK,0));port=sock.getsockname()[1];sock.close()
            proc=subprocess.Popen([
                "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/sbin/uhttpd"),
                "-f","-h",str(d),"-s",f"{LOOPBACK}:{port}",
                "-C",str(certp),"-K",str(wrong)
            ],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                time.sleep(.5)
                fetch=subprocess.run([
                    "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"bin/uclient-fetch"),
                    "--no-check-certificate","--timeout=2","-q","-O","-",
                    f"https://{LOOPBACK}:{port}/index.html"
                ],capture_output=True,text=True,timeout=5)
                self.assertNotEqual(fetch.returncode,0)
            finally:
                proc.terminate()
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=2)

    def test_import_source_never_activates_persistent_https(self):
        s=MODULE.read_text()
        self.assertIn('candidate.install_material',s)
        self.assertIn('"/usr/sbin/uhttpd"',s)
        self.assertIn('local LOOPBACK="127"..".0.0.1"',s)
        self.assertIn('"/bin/uclient-fetch"',s)
        self.assertIn("browser_trust_unverified=true",s)
        for forbidden in ("/ptconf/8311/uhttpd/uhttpd.crt",
                          "/ptconf/8311/uhttpd/uhttpd.key",
                          '"/etc/init.d/uhttpd","restart"',
                          "os.execute","io.popen","shellquote"):
            self.assertNotIn(forbidden,s)

if __name__=="__main__":
    unittest.main()
