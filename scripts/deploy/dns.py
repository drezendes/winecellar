"""Cloudflare DNS for the winecellar host wine.<CLOUDFLARE_ZONE> (token: Zone->DNS->Edit, in .env).

Usage (venv python, repo root):
    python scripts/deploy/dns.py show
    python scripts/deploy/dns.py add-wine --ip <box-ip>   # gray (DNS-only) to verify directly
    python scripts/deploy/dns.py proxy --on               # flip wine to orange-cloud (end state)
    python scripts/deploy/dns.py proxy --off              # back to gray (e.g. to debug the origin)

This tool owns only the winecellar record. The blog apex/www cutover +
WordPress rollback live in the blog repo's dns.py. Start `wine` gray-clouded so
you can verify the app + its DNS-01 cert against the origin directly, then
`proxy --on` for the orange-cloud end state (docs/deployment.md). Because certs
come from DNS-01, the flip needs no cert change. Host switches later are the
same `add-wine --ip <new>` — the public CF edge IP never changes (reversibility).
"""

from __future__ import annotations

import argparse
import sys

from common import api, load_env

API = "https://api.cloudflare.com/client/v4"
try:
    ZONE_NAME = load_env("CLOUDFLARE_ZONE")  # your apex domain, e.g. example.com
except SystemExit:
    ZONE_NAME = ""  # tolerate --help / import without env; guarded in _zone_id
WINE_NAME = f"wine.{ZONE_NAME}" if ZONE_NAME else "wine.<domain>"
TTL = 300


def _zone_id(token: str) -> str:
    if not ZONE_NAME:
        sys.exit("CLOUDFLARE_ZONE not set — add your domain to .env.op / .env (template: .env.op.example)")
    zones = api("GET", f"{API}/zones?name={ZONE_NAME}", token)["result"]
    if not zones:
        sys.exit(f"zone {ZONE_NAME} not visible to this token")
    return zones[0]["id"]


def _records(token: str, zone: str) -> list[dict]:
    return api("GET", f"{API}/zones/{zone}/dns_records?per_page=100", token)["result"]


def _wine_records(token: str, zone: str) -> list[dict]:
    return [r for r in _records(token, zone) if r["type"] == "A" and r["name"] == WINE_NAME]


def _upsert_wine(token: str, zone: str, ip: str, proxied: bool) -> None:
    existing = _wine_records(token, zone)
    payload = {"type": "A", "name": WINE_NAME, "content": ip, "ttl": TTL, "proxied": proxied}
    cloud = "orange (proxied)" if proxied else "gray (DNS-only)"
    if existing:
        api("PUT", f"{API}/zones/{zone}/dns_records/{existing[0]['id']}", token, payload)
        for extra in existing[1:]:
            api("DELETE", f"{API}/zones/{zone}/dns_records/{extra['id']}", token)
        print(f"updated A {WINE_NAME} -> {ip} (ttl {TTL}, {cloud})")
    else:
        api("POST", f"{API}/zones/{zone}/dns_records", token, payload)
        print(f"created A {WINE_NAME} -> {ip} (ttl {TTL}, {cloud})")


def cmd_show(token: str, zone: str, args) -> None:
    for r in sorted(_records(token, zone), key=lambda r: (r["type"], r["name"])):
        if r["type"] not in ("A", "AAAA", "CNAME"):
            continue
        cloud = "proxied" if r["proxied"] else "DNS-only"
        print(f"{r['type']:5} {r['name']:28} -> {r['content']:20} ttl={r['ttl']:>5} {cloud}")


def cmd_add_wine(token: str, zone: str, args) -> None:
    _upsert_wine(token, zone, args.ip, proxied=args.proxied)


def cmd_proxy(token: str, zone: str, args) -> None:
    existing = _wine_records(token, zone)
    if not existing:
        sys.exit(f"no A record for {WINE_NAME} yet — run `add-wine --ip <box-ip>` first")
    _upsert_wine(token, zone, existing[0]["content"], proxied=args.on)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("show", help="list A/AAAA/CNAME records")
    add = sub.add_parser("add-wine", help=f"upsert A {WINE_NAME} -> box IP")
    add.add_argument("--ip", required=True)
    add.add_argument(
        "--proxied", action="store_true", help="create orange-clouded (default: gray/DNS-only)"
    )
    prox = sub.add_parser("proxy", help=f"flip {WINE_NAME} between orange and gray")
    grp = prox.add_mutually_exclusive_group(required=True)
    grp.add_argument("--on", dest="on", action="store_true", help="orange-cloud (proxied)")
    grp.add_argument("--off", dest="on", action="store_false", help="gray (DNS-only)")

    args = parser.parse_args()
    token = load_env("CLOUDFLARE_API_TOKEN")
    zone = _zone_id(token)
    {"show": cmd_show, "add-wine": cmd_add_wine, "proxy": cmd_proxy}[args.cmd](token, zone, args)


if __name__ == "__main__":
    main()
