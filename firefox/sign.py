#!/usr/bin/env python3
"""Build the extension into an .xpi and get it signed by Mozilla (unlisted).

    python3 firefox/sign.py           build, submit, wait, download the signed .xpi
    python3 firefox/sign.py --build   only build dist/browser-agent-<version>.xpi

Unlisted add-ons are signed automatically and never appear on
addons.mozilla.org. The signed file installs permanently in release Firefox.

Credentials come from ~/.config/amo/credentials (AMO_JWT_ISSUER and
AMO_JWT_SECRET, from addons.mozilla.org > Tools > Manage API Keys). Nothing
secret goes into the .xpi: the lab3 key is pasted into cfg once and stays in
the extension's own storage.

Each upload needs a new version number in manifest.json.
"""
import base64, hashlib, hmac, json, os, secrets, sys, time, urllib.error, urllib.request, uuid, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
SHIP = ["manifest.json", "background.js", "lib", "sidebar", "options", "icons"]   # what goes into the .xpi
API = "https://addons.mozilla.org/api/v5"
CREDS = Path.home() / ".config/amo/credentials"

# python.org builds ship without CA certificates; fall back to macOS's bundle.
import ssl
TLS = ssl.create_default_context()
if not TLS.get_ca_certs() and Path("/etc/ssl/cert.pem").exists():
    TLS = ssl.create_default_context(cafile="/etc/ssl/cert.pem")


def build():
    manifest = json.loads((HERE / "manifest.json").read_text())
    version, guid = manifest["version"], manifest["browser_specific_settings"]["gecko"]["id"]
    DIST.mkdir(exist_ok=True)
    out = DIST / f"browser-agent-{version}.xpi"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in SHIP:
            p = HERE / item
            files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file())
            for f in files:
                if f.name.startswith(".") or f.suffix == ".svg" and f.parent.name == "icons":
                    continue
                z.write(f, f.relative_to(HERE).as_posix())
    print(f"built {out.relative_to(HERE.parent)} ({out.stat().st_size // 1024} KB)")
    return out, version, guid


def credentials():
    vals = {}
    if CREDS.exists():
        for line in CREDS.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    issuer, secret = vals.get("AMO_JWT_ISSUER"), vals.get("AMO_JWT_SECRET")
    if not issuer or not secret:
        sys.exit(f"Add AMO_JWT_ISSUER and AMO_JWT_SECRET to {CREDS} first.")
    return issuer, secret


def jwt(issuer, secret):
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
    now = int(time.time())
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"iss": issuer, "jti": secrets.token_hex(16), "iat": now, "exp": now + 60}).encode())
    sig = b64(hmac.new(secret.encode(), head + b"." + body, hashlib.sha256).digest())
    return (head + b"." + body + b"." + sig).decode()


class Amo:
    def __init__(self, issuer, secret):
        self.issuer, self.secret = issuer, secret

    def call(self, method, url, data=None, ctype=None, raw=False):
        req = urllib.request.Request(url if url.startswith("http") else API + url, data=data, method=method)
        req.add_header("Authorization", "JWT " + jwt(self.issuer, self.secret))
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=120, context=TLS) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        return 200, body if raw else json.loads(body or b"{}")

    def upload(self, xpi):
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="channel"\r\n\r\nunlisted\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="upload"; filename="{xpi.name}"\r\n'
            f"Content-Type: application/x-xpinstall\r\n\r\n".encode() + xpi.read_bytes() + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        code, r = self.call("POST", "/addons/upload/", b"".join(parts), f"multipart/form-data; boundary={boundary}")
        if code != 200:
            sys.exit(f"upload refused ({code}): {r}")
        return r["uuid"]


def wait(what, check, every=5, limit=900):
    start = time.time()
    while time.time() - start < limit:
        done = check()
        if done:
            return done
        print(f"  waiting for {what}…", flush=True)
        time.sleep(every)
    sys.exit(f"gave up waiting for {what}")


def sign(xpi, version, guid):
    amo = Amo(*credentials())
    print("uploading to addons.mozilla.org (unlisted)…")
    up = amo.upload(xpi)

    def validated():
        code, r = amo.call("GET", f"/addons/upload/{up}/")
        if code == 200 and r.get("processed"):
            if not r.get("valid"):
                msgs = [m.get("message") for m in (r.get("validation") or {}).get("messages", []) if m.get("type") == "error"]
                sys.exit("Mozilla's validator rejected it:\n  " + "\n  ".join(map(str, msgs or [r])))
            return r
    wait("validation", validated)
    print("validated")

    code, _ = amo.call("GET", f"/addons/addon/{guid}/")
    if code == 200:
        code, r = amo.call("POST", f"/addons/addon/{guid}/versions/", json.dumps({"upload": up}).encode(), "application/json")
    else:
        code, r = amo.call("POST", "/addons/addon/", json.dumps({"version": {"upload": up}}).encode(), "application/json")
    if code not in (200, 201):
        sys.exit(f"creating version {version} failed ({code}): {r}")

    def signed():
        code, r = amo.call("GET", f"/addons/addon/{guid}/versions/v{version}/")
        f = (r or {}).get("file") if code == 200 else None
        if f and f.get("status") == "public" and f.get("url"):
            return f["url"]
        if f and f.get("status") == "disabled":
            sys.exit("Mozilla disabled this version; check the add-on's page on addons.mozilla.org.")
    url = wait("signing", signed, every=10)

    code, data = amo.call("GET", url, raw=True)
    if code != 200:
        sys.exit(f"download failed ({code}): {data}")
    out = DIST / f"browser-agent-{version}-signed.xpi"
    out.write_bytes(data)
    print(f"signed: {out}")
    return out


if __name__ == "__main__":
    xpi, version, guid = build()
    if "--build" not in sys.argv:
        sign(xpi, version, guid)
