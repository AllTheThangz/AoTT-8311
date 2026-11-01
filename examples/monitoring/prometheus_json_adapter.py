#!/usr/bin/env python3
"""External, standard-library-only Prometheus JSON adapter for AoTT-8311.

Runs on a user-owned monitoring server, NEVER on an ONU. Exposes only
allowlisted numeric metrics, no subscriber identity or collector credentials.
Does not disable certificate verification or persist measurements.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import re
import ssl
import stat
import time
import urllib.request
from urllib.parse import urlsplit

FIELDS = {
    "cpu1_tempC": ("aott8311_cpu1_temperature_celsius", "CPU temperature sensor one, degrees Celsius."),
    "cpu2_tempC": ("aott8311_cpu2_temperature_celsius", "CPU temperature sensor two, degrees Celsius."),
    "module_voltage": ("aott8311_optic_supply_volts", "Optic module supply voltage in volts."),
    "optic_tempC": ("aott8311_optic_temperature_celsius", "Optic module temperature in degrees Celsius."),
    "ploam_state": ("aott8311_pon_registration_state", "Numerical PON registration state."),
    "rx_power_dBm": ("aott8311_optic_receive_dbm", "Optic receive power in dBm."),
    "tx_bias_mA": ("aott8311_optic_laser_bias_milliamps", "Optic laser bias in milliamps."),
    "tx_power_dBm": ("aott8311_optic_transmit_dbm", "Optic transmit power in dBm."),
}
MAX_JSON = 8192
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path != "/cgi-bin/luci/8311/metrics"):
        raise ValueError("Use the exact HTTPS read-only metrics URL without credentials or query")
    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        raise ValueError("Invalid HTTPS port")
    return url


def read_token_file(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or
                info.st_uid != os.geteuid() or
                stat.S_IMODE(info.st_mode) & 0o077 or
                info.st_size < 64 or info.st_size > 66):
            raise ValueError("Token file must be owned by this user, regular and private")
        with os.fdopen(os.dup(fd), "rb") as handle:
            token = handle.read(67).decode("ascii").strip()
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("Collector token must be exactly 64 lowercase hexadecimal digits")
        return token
    finally:
        os.close(fd)


def as_prometheus(values, success):
    lines = [
        "# HELP aott8311_collection_success 1 if the last ONU request succeeded, 0 otherwise.",
        "# TYPE aott8311_collection_success gauge",
        "aott8311_collection_success " + ("1" if success else "0"),
    ]
    for key, (name, help_text) in FIELDS.items():
        value = values.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            number = float(value)
        except (OverflowError, ValueError, TypeError):
            continue
        if not math.isfinite(number):
            continue
        lines.extend([
            "# HELP " + name + " " + help_text,
            "# TYPE " + name + " gauge",
            name + " " + format(number, ".12g"),
        ])
    return ("\n".join(lines) + "\n").encode("ascii")


class CachedExporter:
    def __init__(self, url, token, context=None, poll_interval=60.0,
                 fetch=None, clock=None):
        self.url = validate_endpoint(url)
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("Invalid metrics token")
        if poll_interval < 15:
            raise ValueError("Collector poll interval must be at least 15 seconds")
        self.token = token
        self.poll_interval = float(poll_interval)
        self.context = context if context is not None else ssl.create_default_context()
        self.fetch = fetch if fetch is not None else urllib.request.urlopen
        self.clock = clock if clock is not None else time.monotonic
        self.last_fetch = None
        self.cached = as_prometheus({}, False)

    def response(self):
        now = self.clock()
        if self.last_fetch is not None and now - self.last_fetch < self.poll_interval:
            return self.cached
        self.last_fetch = now
        req = urllib.request.Request(
            self.url, headers={
                "X-AoTT-Metrics-Token": self.token, "Accept": "application/json",
            }, method="GET",
        )
        try:
            with self.fetch(req, timeout=5, context=self.context) as resp:
                if resp.status != 200:
                    raise ValueError("Non-success HTTP response")
                raw = resp.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError("Oversized ONU response")
            values = json.loads(raw)
            if not isinstance(values, dict):
                raise ValueError("Unexpected ONU response structure")
            self.cached = as_prometheus(values, True)
        except (OSError, TimeoutError, ValueError, TypeError, UnicodeError,
                json.JSONDecodeError):
            # Do not disclose URLs, tokens, raw responses, or subscriber data.
            # The exporter itself remains up; alert on collection_success == 0.
            self.cached = as_prometheus({}, False)
        return self.cached


def make_handler(exporter):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = exporter.response()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *args):
            # Avoid logging endpoint URLs or request headers in production.
            return

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onu-url", required=True,
                        help="The exact HTTPS AoTT-8311 read-only JSON endpoint")
    parser.add_argument("--token-file", required=True,
                        help="Owner-only file containing the one-time collector token")
    parser.add_argument("--ca-file", help="Custom trusted CA bundle; never disable TLS checks")
    parser.add_argument("--port", type=int, default=9109)
    parser.add_argument("--minimum-poll", type=float, default=60.0)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be in range 1..65535")
    try:
        context = ssl.create_default_context(cafile=args.ca_file)
        exporter = CachedExporter(args.onu_url, read_token_file(args.token_file),
                                  context=context, poll_interval=args.minimum_poll)
    except (ValueError, OSError, ssl.SSLError) as exc:
        parser.error("Collector setup rejected: " + type(exc).__name__)
    # The adapter binds only to local loopback by design.
    with HTTPServer(("127" + ".0.0.1", args.port), make_handler(exporter)) as server:
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
