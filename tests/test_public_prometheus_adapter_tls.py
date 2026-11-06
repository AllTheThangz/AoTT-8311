"""Loopback-only end-to-end HTTPS collector tests with ephemeral test CA.

Spawns no ONU services and makes no external requests. The mock TLS server
runs on a random loopback port, the certificate and key live in a temporary
directory, and no token, collector address or device identifier is published.
"""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import ssl
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"examples/monitoring/prometheus_json_adapter.py"
spec=importlib.util.spec_from_file_location("aott_https_adapter",MODULE)
adapter=importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

TOKEN="a"*64
ROTATED="b"*64
HOST="127"+".0.0.1"


class CollectorFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        server=self.server
        server.request_count+=1
        server.last_path=self.path
        server.last_token=self.headers.get("X-AoTT-Metrics-Token")
        if self.path!="/cgi-bin/luci/8311/metrics":
            self.send_error(404);return
        if server.last_token!=server.valid_token:
            self.send_error(403);return
        body=json.dumps({"rx_power_dBm":-13.65,"ploam_state":51,
                         "optic_tempC":40.5,
                         "identity_field_that_must_be_omitted":"test"}).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self,*_args):
        # A production bearer must never reach the server's diagnostic logs.
        return


class LocalCollectorTlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="aott-https-fixture-")
        cls.base=Path(cls.temp.name)
        crt,key=cls.base/"fixture.pem",cls.base/"fixture.key"
        config=cls.base/"openssl.cnf"
        command=[
            "openssl","req","-config",str(config),
            "-x509","-newkey","rsa:2048","-nodes",
            "-days","1","-keyout",str(key),"-out",str(crt),
            "-subj","/CN=localhost",
            "-addext","subjectAltName=DNS:localhost,IP:"+HOST
        ]
        try:
            # The isolated runner need not install OpenSSL's host-specific
            # default configuration path. Keep this ephemeral CA independent
            # of that path and of the caller's OPENSSL_CONF environment.
            config.write_text(
                "[req]\nprompt = no\ndistinguished_name = fixture_subject\n"
                "default_md = sha256\n[fixture_subject]\nCN = localhost\n",
                encoding="ascii")
            generated=subprocess.run(command,capture_output=True,text=True,
                                     timeout=18)
            if generated.returncode:
                # This command writes only the synthetic key to its private
                # file. Bound diagnostics and hide the temporary directory;
                # never print key bytes, bearer values, or collector responses.
                detail=generated.stderr[-2048:].replace(
                    str(cls.base),"<fixture-directory>")
                raise AssertionError(
                    "Ephemeral TLS certificate generation failed "
                    "(openssl exit %d): %s" % (generated.returncode,detail))
            key.chmod(0o600)
            cls.server=HTTPServer((HOST,0),CollectorFixture)
            ssl_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(str(crt),str(key))
            cls.server.socket=ssl_context.wrap_socket(
                cls.server.socket,server_side=True)
            cls.server.valid_token=TOKEN
            cls.server.request_count=0
            cls.server.last_token=None
            cls.server.last_path=None
            cls.thread=threading.Thread(target=cls.server.serve_forever,
                                        kwargs={"poll_interval":0.05},
                                        daemon=True)
            cls.thread.start()
            cls.cafile=str(crt)
            cls.url="https://localhost:%d/cgi-bin/luci/8311/metrics" % (
                cls.server.server_address[1])
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"server",None):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def setUp(self):
        self.server.valid_token=TOKEN
        self.server.request_count=0
        self.server.last_token=None
        self.server.last_path=None

    def exporter(self,token=TOKEN,clock=None,trust=True):
        context=(ssl.create_default_context(cafile=self.cafile)
                 if trust else ssl.create_default_context())
        return adapter.CachedExporter(
            self.url,token,context=context,poll_interval=15,
            clock=clock)

    def test_correct_token_and_trusted_identity_yield_numeric_metrics(self):
        exported=self.exporter()
        result=exported.response().decode("ascii")
        self.assertIn("aott8311_collection_success 1",result)
        self.assertIn("aott8311_optic_receive_dbm -13.65",result)
        self.assertIn("aott8311_pon_registration_state 51",result)
        self.assertEqual(self.server.request_count,1)
        self.assertEqual(self.server.last_token,TOKEN)
        self.assertEqual(self.server.last_path,"/cgi-bin/luci/8311/metrics")
        self.assertNotIn(TOKEN,result)
        self.assertNotIn(self.url,result)
        self.assertNotIn("identity_field_that_must_be_omitted",result)

    def test_bad_or_revoked_token_fails_closed_and_does_not_retain_stale_data(self):
        now=[100.0]
        collector=self.exporter(clock=lambda:now[0])
        first=collector.response().decode("ascii")
        self.assertIn("aott8311_collection_success 1",first)
        self.server.valid_token=ROTATED
        self.assertEqual(collector.response().decode("ascii"),first)
        self.assertEqual(self.server.request_count,1,"Unexpected early PON poll")
        now[0]+=16
        failed=collector.response().decode("ascii")
        self.assertIn("aott8311_collection_success 0",failed)
        self.assertNotIn("aott8311_optic_receive_dbm",failed)
        self.assertEqual(self.server.request_count,2)
        new_collector=self.exporter(token=ROTATED)
        self.assertIn("aott8311_collection_success 1",
                      new_collector.response().decode("ascii"))

    def test_default_ca_rejects_synthetic_self_issued_tls_certificate(self):
        collector=self.exporter(trust=False)
        result=collector.response().decode("ascii")
        self.assertIn("aott8311_collection_success 0",result)
        self.assertNotIn(TOKEN,result)
        self.assertNotIn("optic_receive_dbm",result)
        # TLS identity checks must fail before any HTTP request reaches the app.
        self.assertEqual(self.server.request_count,0)


if __name__=="__main__":
    unittest.main()
