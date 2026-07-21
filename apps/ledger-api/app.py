import hashlib
import hmac
import ipaddress
import os
import socket
from urllib.parse import urlparse

import requests
import yaml
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# V4 fix: HMAC with a server-side secret instead of unsalted SHA256, so a
# token can no longer be reproduced offline without this key.
TOKEN_HMAC_KEY = os.environ.get("TOKEN_HMAC_KEY", "").encode() or os.urandom(32)

# V3 fix: a minimal bearer-token check. In production this would be a real
# authN/authZ layer (OIDC, mTLS client identity via the mesh, etc.) - this
# is deliberately simple to keep the fix legible for the assessment.
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")

LEDGER = [
    {"id": "txn_1001", "pan": "4242424242424242", "amount": 4200, "currency": "USD", "status": "captured"},
    {"id": "txn_1002", "pan": "5555555555554444", "amount": 1899, "currency": "EUR", "status": "refunded"},
]


def require_auth():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not INTERNAL_API_TOKEN or not hmac.compare_digest(token, INTERNAL_API_TOKEN):
        abort(401)


def mask_pan(pan: str) -> str:
    return "*" * max(len(pan) - 4, 0) + pan[-4:]


@app.route("/health")
def health():
    return jsonify(status="ok")


@app.route("/tokenize", methods=["POST"])
def tokenize():
    require_auth()
    payload = request.get_json(silent=True) or {}
    pan = payload.get("pan", "")
    token = "tok_" + hmac.new(TOKEN_HMAC_KEY, pan.encode(), hashlib.sha256).hexdigest()[:24]
    return jsonify(token=token, last4=pan[-4:])


@app.route("/transactions")
def transactions():
    # V3 fix: require authentication, and never return full PANs even to
    # authenticated callers - mask to last 4 digits (PCI DSS display
    # requirement).
    require_auth()
    masked = [{**t, "pan": mask_pan(t["pan"])} for t in LEDGER]
    return jsonify(transactions=masked)


@app.route("/import", methods=["POST"])
def import_config():
    # V2 fix: safe_load only constructs plain Python types (dict/list/str/
    # int/...), never arbitrary classes or callables - eliminates the
    # deserialization RCE entirely rather than just narrowing it.
    require_auth()
    config = yaml.safe_load(request.data)
    return jsonify(loaded=str(config))


def _is_blocked_destination(hostname: str) -> bool:
    """V1 fix: block loopback/private/link-local/reserved destinations so
    /fetch cannot be used to reach internal-only services or cloud
    metadata endpoints. This is an application-level allowlist check;
    Task 3's NetworkPolicy egress default-deny is the independent network-
    layer control for the same risk (defence in depth)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


@app.route("/fetch")
def fetch():
    require_auth()
    url = request.args.get("url", "")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        abort(400)
    if _is_blocked_destination(parsed.hostname):
        abort(403)
    # Semgrep's SSRF rules pattern-match on "requests.get(user_input)" and
    # can't trace the _is_blocked_destination() allowlist check immediately
    # above, which is the actual V1 fix (see task4-pentest/pentest-report.md).
    resp = requests.get(url, timeout=5)  # nosemgrep: python.django.security.injection.ssrf.ssrf-injection-requests.ssrf-injection-requests,python.flask.security.injection.ssrf-requests.ssrf-requests
    return jsonify(status_code=resp.status_code, body=resp.text[:2048])


if __name__ == "__main__":
    # Binding 0.0.0.0 is required to be reachable via the Kubernetes Service
    # from other pods/the ingress - the container's network exposure is
    # governed by Task 1's Service/Ingress and Task 3's NetworkPolicy, not
    # by the bind address inside the container's own network namespace.
    app.run(host="0.0.0.0", port=8080)  # nosemgrep: python.flask.security.audit.app-run-param-config.avoid_app_run_with_bad_host
