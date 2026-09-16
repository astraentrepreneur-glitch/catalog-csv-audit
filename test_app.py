import base64
import http.client
import io
import json
from pathlib import Path
import socket
import threading
import unittest
from unittest.mock import patch
import zipfile

import app
from audit import MAX_FILE_BYTES, changes_csv, load_csv_bytes

ROOT = Path(__file__).parent


def encoded(data):
    return base64.b64encode(data).decode("ascii")


class SharedParsingTests(unittest.TestCase):
    def test_bom_unicode_quotes_newlines_and_leading_zeros(self):
        headers, rows = load_csv_bytes(
            '\ufeffSKU,Color,SEO\r\n0001,"blå, ""blue""","one\r\ntwo"\r\n'.encode())
        self.assertEqual(headers, ["SKU", "Color", "SEO"])
        self.assertEqual(rows, [{"SKU": "0001", "Color": 'blå, "blue"', "SEO": "one\r\ntwo"}])

    def test_invalid_inputs_and_limits(self):
        for data in (b"\xff", b'a,b\n1,"unterminated', b"a,b\n1\n", b"a,a\n",
                     b" ,b\n", b"", b"x" * (MAX_FILE_BYTES + 1)):
            with self.subTest(data_length=len(data)), self.assertRaises(ValueError):
                load_csv_bytes(data)
        with self.assertRaises(ValueError):
            load_csv_bytes(b"SKU,Color\n" + b"1,red\n" * 501, max_rows=500)

    def test_empty_change_projection_keeps_headers(self):
        self.assertEqual(changes_csv({"changes": []}),
                         "target_record,key,source_record,field,before,after\n")

    def test_change_projection_preserves_every_value(self):
        change = {
            "target_record": 2, "key": "0001", "source_record": 7,
            "field": 'Color, "display"', "before": "=untrusted\r\nold",
            "after": 'blå, "blue"\nnew',
        }
        headers, rows = load_csv_bytes(changes_csv({"changes": [change]}).encode("utf-8"))
        self.assertEqual(headers, ["target_record", "key", "source_record", "field", "before", "after"])
        self.assertEqual(rows, [{name: str(value) for name, value in change.items()}])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.LocalServer()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls.thread.is_alive():
            raise AssertionError("HTTP server did not shut down")

    def payload(self):
        return {"target": encoded((ROOT / "synthetic-target.csv").read_bytes()),
                "source": encoded((ROOT / "synthetic-source.csv").read_bytes())}

    def request(self, path="/inspect", payload=None, body=None, headers=None, method="POST"):
        defaults = {"Origin": self.server.origin, "X-Audit-Token": self.server.token,
                    "Content-Type": "application/json"}
        if headers:
            for key, value in headers.items():
                if value is None:
                    defaults.pop(key, None)
                else:
                    defaults[key] = value
        if body is None and method == "POST":
            body = json.dumps(self.payload() if payload is None else payload).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=defaults)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_sample_inspect_and_zip(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        metadata = json.loads(body)
        self.assertEqual(metadata["target_rows"], 10)
        self.assertIn("SKU", metadata["common_headers"])
        payload = {**self.payload(), "key": "SKU", "fields": ["Color", "Finish"]}
        status, headers, body = self.request("/audit", payload)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertEqual(headers["X-Changed-Cells"], "3")
        self.assertEqual(headers["X-Review-Items"], "3")
        self.assertEqual(headers["X-Unselected-Preserved"], "true")
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(archive.namelist(), ["corrected.csv", "audit.json", "changes.csv"])
            report = json.loads(archive.read("audit.json"))
            _, corrected = load_csv_bytes(archive.read("corrected.csv"))
            _, original = load_csv_bytes((ROOT / "synthetic-target.csv").read_bytes())
            for old, new in zip(original, corrected):
                for column in old:
                    if column not in payload["fields"]:
                        self.assertEqual(old[column], new[column])
            self.assertEqual(len(report["changes"]), 3)
            self.assertEqual(len(report["manual_review"]), 3)
            self.assertEqual(archive.read("changes.csv").decode(), changes_csv(report))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_http_unicode_and_preservation(self):
        payload = {
            "target": encoded('\ufeffSKU,Color,SEO\r\n0001,red,"=KEEP\r\n原文"\r\n'.encode()),
            "source": encoded('SKU,Color,SEO\n0001,"blå, ""blue""",discard\n'.encode()),
            "key": "SKU", "fields": ["Color"],
        }
        status, headers, body = self.request("/audit", payload)
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Formula-Like-Cells-Retained"], "1")
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            _, rows = load_csv_bytes(archive.read("corrected.csv"))
            self.assertEqual(rows, [{"SKU": "0001", "Color": 'blå, "blue"', "SEO": "=KEEP\r\n原文"}])
            _, changes = load_csv_bytes(archive.read("changes.csv"))
            self.assertEqual(changes, [{
                "target_record": "2", "key": "0001", "source_record": "2",
                "field": "Color", "before": "red", "after": 'blå, "blue"',
            }])

    def test_selection_validation(self):
        base = {**self.payload(), "key": "SKU", "fields": ["Color"]}
        invalid = [
            self.payload(), {**base, "fields": []}, {**base, "fields": ["Color", "Color"]},
            {**base, "fields": ["SKU"]}, {**base, "fields": ["missing"]},
            {**base, "fields": ["a", "b", "c", "d", "e", "f"]},
            {**base, "fields": "Color"}, {**base, "fields": [1]},
            {**base, "key": []}, {**base, "key": "missing"},
        ]
        for payload in invalid:
            with self.subTest(payload_keys=list(payload)):
                status, _, body = self.request("/audit", payload)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))

    def test_bad_shapes_encoding_csv_and_row_limit(self):
        invalid = [[], None, 2, {}, {"target": [], "source": ""},
                   {"target": "!", "source": ""}, {"target": "☃", "source": ""},
                   {**self.payload(), "extra": 1}]
        for payload in invalid:
            status, _, _ = self.request(body=json.dumps(payload).encode())
            self.assertEqual(status, 400)
        for data in (b"\xff", b'a,b\n1,"open', b"a,a\n", b"a,b\n1,2,3\n",
                     b"a,b\n" + b"1,2\n" * 501):
            status, _, _ = self.request(payload={**self.payload(), "target": encoded(data)})
            self.assertEqual(status, 400)

    def test_json_and_content_type(self):
        for body in (b"{", b"\xff", b'{"target":"","target":"","source":""}',
                     b'{"target":NaN,"source":""}', b"[" * 1200):
            self.assertEqual(self.request(body=body)[0], 400)
        for content_type in (None, "text/plain", "application/x-www-form-urlencoded"):
            self.assertEqual(self.request(headers={"Content-Type": content_type})[0], 415)

    def test_csrf_origin_and_host(self):
        for headers in (
            {"X-Audit-Token": None}, {"X-Audit-Token": "bad"}, {"Origin": None},
            {"Origin": "http://foreign.invalid"}, {"Origin": "null"},
            {"Host": "localhost:" + str(self.server.server_port)},
            {"Host": "foreign.invalid"}, {"Sec-Fetch-Site": "cross-site"},
        ):
            self.assertEqual(self.request(headers=headers)[0], 403)
        self.assertEqual(self.request("/", method="GET", headers={"Host": "foreign.invalid"})[0], 403)

    def test_allowlisted_assets_and_html_wiring(self):
        for path in ("/", "/app.js", "/style.css"):
            status, headers, body = self.request(path, method="GET")
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            if path == "/":
                self.assertIn(self.server.token.encode(), body)
                self.assertNotIn(b"__AUDIT_TOKEN__", body)
                self.assertIn(b'src="/app.js"', body)
                self.assertIn(b'href="/style.css"', body)
        for path in ("/../audit.py", "/%2e%2e/audit.py", "/audit.py", "/LICENSE", "/?token=x"):
            self.assertEqual(self.request(path, method="GET")[0], 404)
        self.assertEqual(self.request("/missing")[0], 404)
        self.assertEqual(self.request("/inspect", method="OPTIONS")[0], 405)

    def raw_request(self, extra, body=b""):
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5) as sock:
            raw = (f"POST /inspect HTTP/1.1\r\nHost: {self.server.authority}\r\n"
                   f"Origin: {self.server.origin}\r\nX-Audit-Token: {self.server.token}\r\n"
                   "Content-Type: application/json\r\n" + extra + "\r\n").encode() + body
            sock.sendall(raw)
            sock.shutdown(socket.SHUT_WR)
            response = bytearray()
            while chunk := sock.recv(65536):
                response.extend(chunk)
        return int(response.split(b" ", 2)[1])

    def test_request_framing_and_limits(self):
        cases = [
            ("", 411), ("Content-Length: -1\r\n", 400),
            ("Content-Length: nope\r\n", 400),
            ("Content-Length: 0\r\nContent-Length: 0\r\n", 400),
            ("Transfer-Encoding: chunked\r\nContent-Length: 0\r\n", 400),
            (f"Content-Length: {app.MAX_REQUEST_BYTES + 1}\r\n", 413),
            ("Content-Length: " + "9" * 100 + "\r\n", 413),
            ("Content-Length: 5\r\n", 400),
        ]
        for extra, expected in cases:
            with self.subTest(extra=extra):
                self.assertEqual(self.raw_request(extra), expected)
        with patch.object(app, "MAX_ENCODED_BYTES", 4):
            self.assertEqual(self.request()[0], 413)
        with patch.object(app, "MAX_FILE_BYTES", 1):
            self.assertEqual(self.request()[0], 413)

    def test_body_timeout(self):
        with patch.object(app, "READ_TIMEOUT", 0.05):
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5) as sock:
                sock.sendall((f"POST /inspect HTTP/1.1\r\nHost: {self.server.authority}\r\n"
                              f"Origin: {self.server.origin}\r\nX-Audit-Token: {self.server.token}\r\n"
                              "Content-Type: application/json\r\nContent-Length: 5\r\n\r\n").encode())
                self.assertIn(b" 408 ", sock.recv(4096))


if __name__ == "__main__":
    unittest.main()
