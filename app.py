"""Local self-serve interface. Python 3.10+ standard library; loopback only."""

import argparse
import base64
import binascii
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
from pathlib import Path
import secrets
import socket
import time
import zipfile

from audit import MAX_FILE_BYTES, MAX_TARGET_ROWS, changes_csv, compare, csv_text, load_csv_bytes

MAX_ENCODED_BYTES = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_REQUEST_BYTES = 2 * MAX_ENCODED_BYTES + 65536
READ_TIMEOUT = 10
READ_DEADLINE = 20
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class LocalServer(HTTPServer):
    def __init__(self, port=0):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.authority = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.authority}"

    def handle_error(self, request, client_address):
        # Never emit request data, tokens, or tracebacks into the terminal.
        print("A local request failed unexpectedly.", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalCatalogAudit"
    sys_version = ""

    def setup(self):
        self.request.settimeout(READ_TIMEOUT)
        super().setup()

    def log_message(self, format, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.respond(code, json.dumps({"error": "Invalid HTTP request."}).encode(),
                     "application/json")

    def respond(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                         "form-action 'none'")
        self.send_header("Connection", "close")
        for name, value in (extra or {}).items():
            self.send_header(name, str(value))
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def require_local(self, post=False):
        if self.headers.get_all("Host") != [self.server.authority]:
            raise RequestError(403, "Use the exact loopback URL printed by this app.")
        origins = self.headers.get_all("Origin")
        if (post and origins != [self.server.origin]) or (
                origins is not None and origins != [self.server.origin]):
            raise RequestError(403, "Foreign or missing request origin.")
        if post:
            tokens = self.headers.get_all("X-Audit-Token")
            if (not tokens or len(tokens) != 1 or not tokens[0].isascii()
                    or not hmac.compare_digest(tokens[0], self.server.token)):
                raise RequestError(403, "Invalid request token. Reload this page.")
        fetch_sites = self.headers.get_all("Sec-Fetch-Site")
        if fetch_sites is not None and fetch_sites not in (["same-origin"], ["none"]):
            raise RequestError(403, "Cross-site requests are not allowed.")

    def read_json(self):
        if self.headers.get_all("Transfer-Encoding") is not None:
            raise RequestError(400, "Transfer-Encoding is not supported.")
        lengths = self.headers.get_all("Content-Length")
        if not lengths:
            raise RequestError(411, "Content-Length is required.")
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise RequestError(400, "Invalid Content-Length.")
        # Bound digit count before integer conversion.
        if len(lengths[0]) > 9:
            raise RequestError(413, "Request exceeds the upload limit.")
        length = int(lengths[0])
        if length > MAX_REQUEST_BYTES:
            raise RequestError(413, "Request exceeds the upload limit.")
        types = self.headers.get_all("Content-Type")
        if not types or len(types) != 1 or types[0].lower() not in (
                "application/json", "application/json; charset=utf-8"):
            raise RequestError(415, "Content-Type must be application/json.")
        body = bytearray()
        deadline = time.monotonic() + READ_DEADLINE
        while len(body) < length:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise RequestError(408, "Upload timed out.")
            self.connection.settimeout(min(READ_TIMEOUT, remaining_time))
            chunk = self.rfile.read1(min(65536, length - len(body)))
            if not chunk:
                raise RequestError(400, "Incomplete request body.")
            body.extend(chunk)
        try:
            payload = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object,
                                 parse_constant=reject_constant)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise RequestError(400, "Malformed JSON; send a UTF-8 JSON object.") from exc
        if not isinstance(payload, dict):
            raise RequestError(400, "Request must be a JSON object.")
        return payload

    def dispatch(self):
        self.require_local(post=self.command == "POST")
        if self.command == "GET":
            if self.path not in ASSETS:
                raise RequestError(404, "Not found.")
            filename, content_type = ASSETS[self.path]
            content = Path(__file__).with_name(filename).read_bytes()
            if self.path == "/":
                content = content.replace(b"__AUDIT_TOKEN__", self.server.token.encode("ascii"))
            self.respond(200, content, content_type)
            return
        if self.command != "POST":
            raise RequestError(405, "Method not allowed.")
        if self.path not in ("/inspect", "/audit"):
            raise RequestError(404, "Not found.")
        payload = self.read_json()
        expected = {"target", "source"}
        if self.path == "/audit":
            expected |= {"key", "fields"}
        if set(payload) != expected:
            raise RequestError(400, "Provide target/source files and, for audit, a key and fields.")
        target_headers, target = decode_csv(payload["target"], MAX_TARGET_ROWS)
        source_headers, source = decode_csv(payload["source"])
        if self.path == "/inspect":
            self.respond(200, json.dumps({
                "target_headers": target_headers, "source_headers": source_headers,
                "common_headers": [name for name in target_headers if name in source_headers],
                "target_rows": len(target), "source_rows": len(source),
            }, ensure_ascii=True).encode(), "application/json")
            return
        key, fields = payload["key"], payload["fields"]
        if (not isinstance(key, str) or not isinstance(fields, list)
                or any(not isinstance(field, str) for field in fields)):
            raise RequestError(400, "Key must be text and fields must be a list of column names.")
        corrected, report = compare(target_headers, target, source_headers, source, key, fields)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as result:
            result.writestr("corrected.csv", csv_text(target_headers, corrected).encode("utf-8"))
            result.writestr("audit.json", (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode())
            result.writestr("changes.csv", changes_csv(report).encode("utf-8"))
        self.respond(200, archive.getvalue(), "application/zip", {
            "Content-Disposition": 'attachment; filename="catalog-audit.zip"',
            "X-Target-Rows": len(target), "X-Source-Rows": len(source),
            "X-Changed-Cells": len(report["changes"]),
            "X-Review-Items": len(report["manual_review"]),
            "X-Formula-Like-Cells-Retained": report["formula_like_cells_retained"],
            "X-Unselected-Preserved": str(report["unapproved_fields_preserved"]).lower(),
        })

    def handle_request(self):
        try:
            self.dispatch()
        except RequestError as exc:
            self.respond(exc.status, json.dumps({"error": str(exc)}).encode(), "application/json")
        except ValueError as exc:
            self.respond(400, json.dumps({"error": str(exc)}).encode(), "application/json")
        except (TimeoutError, socket.timeout):
            self.respond(408, b'{"error":"Upload timed out."}', "application/json")
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = handle_request
    do_POST = handle_request
    do_HEAD = handle_request
    do_OPTIONS = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON number.")


def decode_csv(value, max_rows=None):
    if not isinstance(value, str):
        raise RequestError(400, "Files must be base64 strings.")
    if len(value) > MAX_ENCODED_BYTES:
        raise RequestError(413, "Each CSV must be at most 10 MiB.")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RequestError(400, "Invalid base64 file data.") from exc
    if len(data) > MAX_FILE_BYTES:
        raise RequestError(413, "Each CSV must be at most 10 MiB.")
    return load_csv_bytes(data, max_rows=max_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Loopback port; default asks OS for a free port.")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    with LocalServer(args.port) as server:
        print(f"Open {server.origin}/ in your browser. Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
