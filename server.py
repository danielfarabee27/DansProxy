#!/usr/bin/env python3
"""DansProxy: a minimal web proxy using only the Python standard library.

Proxied pages are served at /p/<absolute-url>, e.g. /p/https://example.com/
"""

import html
import ipaddress
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8080"))
TIMEOUT = 20
MAX_REWRITE_BYTES = 15 * 1024 * 1024
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
PASSTHROUGH_HEADERS = {"content-type", "cache-control", "content-disposition", "last-modified", "etag"}
FORWARD_REQUEST_HEADERS = {"user-agent", "accept", "accept-language", "content-type", "range"}


class ProxyError(Exception):
    def __init__(self, status, title, message):
        super().__init__(message)
        self.status, self.title, self.message = status, title, message


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Let the browser follow redirects so every hop goes back through /p/."""

    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


# ---------------------------------------------------------------- URL helpers

def parse_target(raw):
    raw = raw.strip()
    raw = re.sub(r"^(https?):/+", r"\1://", raw, flags=re.I)
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise ProxyError(400, "Unsupported address", "Only http:// and https:// websites are supported.")
    if not parts.hostname:
        raise ProxyError(400, "Invalid address", "That doesn't look like a valid web address.")
    return raw


def check_host_allowed(hostname, port):
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ProxyError(502, "Site not found",
                         f"Couldn't find \u201c{hostname}\u201d. Check the address for typos.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            raise ProxyError(403, "Address not allowed",
                             "For safety, the proxy can't access local or private network addresses.")


def proxify(url, base):
    url = html.unescape(url).strip()
    if not url or url.startswith(("#", "javascript:", "data:", "mailto:", "tel:", "blob:", "about:")):
        return url
    absolute = urllib.parse.urljoin(base, url)
    if not absolute.lower().startswith(("http://", "https://")):
        return url
    return "/p/" + absolute


# ------------------------------------------------------------------ rewriting

ATTR_RE = re.compile(
    r"""(\s(?:href|src|action|poster|formaction|data-src|background)\s*=\s*)(["'])(.*?)\2""",
    re.I | re.S)
SRCSET_RE = re.compile(r"""(\s(?:srcset|data-srcset)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
CSS_URL_RE = re.compile(r"""url\(\s*(["']?)([^"')]*?)\1\s*\)""", re.I)
CSS_IMPORT_RE = re.compile(r"""@import\s+(["'])(.*?)\1""", re.I)
INTEGRITY_RE = re.compile(r"""\s(?:integrity|nonce)\s*=\s*(["']).*?\1""", re.I | re.S)
META_CSP_RE = re.compile(r"""<meta[^>]+http-equiv\s*=\s*["']?content-security-policy[^>]*>""", re.I)
BASE_RE = re.compile(r"""<base[^>]+href\s*=\s*(["'])(.*?)\1""", re.I | re.S)


def rewrite_css(css, base):
    css = CSS_URL_RE.sub(lambda m: f"url({m.group(1)}{proxify(m.group(2), base)}{m.group(1)})", css)
    return CSS_IMPORT_RE.sub(lambda m: f"@import {m.group(1)}{proxify(m.group(2), base)}{m.group(1)}", css)


def rewrite_html(doc, base):
    m = BASE_RE.search(doc)
    if m:
        base = urllib.parse.urljoin(base, html.unescape(m.group(2)))
    doc = META_CSP_RE.sub("", doc)
    doc = INTEGRITY_RE.sub("", doc)
    doc = ATTR_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{html.escape(proxify(m.group(3), base))}{m.group(2)}", doc)

    def srcset(m):
        items = []
        for item in m.group(3).split(","):
            bits = item.strip().split(None, 1)
            if bits:
                bits[0] = html.escape(proxify(bits[0], base))
                items.append(" ".join(bits))
        return f"{m.group(1)}{m.group(2)}{', '.join(items)}{m.group(2)}"

    doc = SRCSET_RE.sub(srcset, doc)
    return rewrite_css(doc, base)


def detect_charset(content_type, body):
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if not m:
        m = re.search(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", body[:4096], re.I)
    charset = m.group(1) if m else "utf-8"
    if isinstance(charset, bytes):
        charset = charset.decode("ascii", "ignore")
    try:
        "".encode(charset)
        return charset
    except LookupError:
        return "utf-8"


# ------------------------------------------------------------------ handler

ERROR_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;font-family:system-ui,sans-serif;
background:#0f1115;color:#e7e9ee;padding:24px;box-sizing:border-box}}
.box{{max-width:440px;text-align:center}}h1{{font-size:1.4rem;margin:0 0 8px}}
p{{color:#9aa3b2;line-height:1.5}}code{{word-break:break-all;color:#c9d1dc}}
a{{display:inline-block;margin-top:12px;padding:10px 18px;border-radius:10px;background:#5b8cff;
color:#fff;text-decoration:none;font-weight:600}}</style></head><body><div class="box">
<div style="font-size:2.5rem">&#9888;&#65039;</div><h1>{title}</h1><p>{message}</p>
{target}<a href="/" target="_top">Back to home</a></div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "DansProxy/1.0"

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def route(self):
        path = self.path
        if path.startswith("/p/"):
            return self.handle_proxy(path[3:])
        clean = urllib.parse.urlsplit(path).path
        if self.command == "GET" and clean in STATIC_FILES:
            return self.serve_static(*STATIC_FILES[clean])
        if clean == "/favicon.ico":
            return self.send_simple(204)
        # Root-relative requests made by proxied scripts (e.g. fetch("/api")): recover via Referer.
        referer_path = urllib.parse.urlsplit(self.headers.get("Referer", "")).path
        if referer_path.startswith("/p/"):
            try:
                origin_parts = urllib.parse.urlsplit(parse_target(referer_path[3:]))
                return self.redirect(f"/p/{origin_parts.scheme}://{origin_parts.netloc}{path}")
            except ProxyError:
                pass
        self.send_error_page(ProxyError(404, "Not found", "That page doesn't exist."))

    def serve_static(self, name, ctype):
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_simple(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def redirect(self, location, status=302):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_error_page(self, err, target=""):
        target_html = f"<p><code>{html.escape(target)}</code></p>" if target else ""
        body = ERROR_PAGE.format(title=html.escape(err.title), message=html.escape(err.message),
                                 target=target_html).encode()
        self.send_response(err.status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_proxy(self, raw_target):
        target = raw_target
        try:
            target = parse_target(raw_target)
            parts = urllib.parse.urlsplit(target)
            check_host_allowed(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
            self.fetch_and_forward(target)
        except ProxyError as err:
            self.send_error_page(err, target)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def fetch_and_forward(self, target):
        body = None
        if self.command == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""

        headers = {k: v for k, v in self.headers.items() if k.lower() in FORWARD_REQUEST_HEADERS}
        headers["Accept-Encoding"] = "identity"
        req = urllib.request.Request(target, data=body, headers=headers, method=self.command)

        try:
            resp = OPENER.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                location = e.headers.get("Location")
                if location:
                    return self.redirect(proxify(location, target), 307 if e.code in (307, 308) else 302)
            resp = e  # 4xx/5xx: still show the site's own error page
        except urllib.error.URLError as e:
            raise ProxyError(502, *describe_network_error(e.reason))
        except (socket.timeout, TimeoutError):
            raise ProxyError(504, "Site took too long", "The website didn't respond in time. Try again later.")
        except (ssl.SSLError, ConnectionError, OSError) as e:
            raise ProxyError(502, *describe_network_error(e))

        with resp:
            status = resp.status if hasattr(resp, "status") else resp.code
            ctype = resp.headers.get("Content-Type", "")
            lower = ctype.lower()
            is_html = "text/html" in lower or "application/xhtml" in lower
            is_css = "text/css" in lower

            self.send_response(status)
            rewriting = is_html or is_css
            for key, value in resp.headers.items():
                k = key.lower()
                if k in PASSTHROUGH_HEADERS and not (rewriting and k in ("content-type", "etag")):
                    self.send_header(key, value)

            try:
                if rewriting:
                    raw = resp.read(MAX_REWRITE_BYTES)
                    charset = detect_charset(ctype, raw)
                    text = raw.decode(charset, errors="replace")
                    text = rewrite_html(text, target) if is_html else rewrite_css(text, target)
                    out = text.encode("utf-8")
                    self.send_header("Content-Type", ("text/html" if is_html else "text/css") + "; charset=utf-8")
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    self.wfile.write(out)
                else:
                    length = resp.headers.get("Content-Length")
                    if length:
                        self.send_header("Content-Length", length)
                    self.end_headers()
                    while chunk := resp.read(64 * 1024):
                        self.wfile.write(chunk)
            except (socket.timeout, TimeoutError):
                pass  # headers already sent; just end the response

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def describe_network_error(reason):
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "Site took too long", "The website didn't respond in time. Try again later."
    if isinstance(reason, socket.gaierror):
        return "Site not found", "Couldn't find that website. Check the address for typos."
    if isinstance(reason, ssl.SSLError):
        return "Secure connection failed", "The website's security certificate couldn't be verified."
    if isinstance(reason, ConnectionRefusedError):
        return "Connection refused", "The website refused the connection."
    return "Couldn't reach the site", f"Something went wrong connecting to the website ({reason})."


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0") else HOST
    print(f"DansProxy running at http://{shown}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
