"""Provision the shared Hetzner box (plan of record: docs/deployment.md).

Usage (venv python, repo root):
    python scripts/deploy/provision.py types
    python scripts/deploy/provision.py create [--type cax11] [--name box]
    python scripts/deploy/provision.py status

`types` lists server types with Falkenstein (EU) pricing so the cax11 pick can
be confirmed against live prices before `create`. `create` uploads the
workstation SSH key, builds the box-edge firewall (22/80/443 + icmp), and
creates the server with deploy/cloud-init.yaml as user data. It refuses to run
if a server with the same name already exists — this box is a pet, not cattle.
Needs HCLOUD_TOKEN (read/write) in .env.

Region/size decided 2026-07-17 (docs/deployment.md): CAX11 (4 GB ARM) in
Falkenstein. CAX (Ampere ARM) is EU-only; the whole stack is multi-arch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import REPO_ROOT, api, load_env

API = "https://api.hetzner.cloud/v1"
CLOUD_INIT = REPO_ROOT / "deploy" / "cloud-init.yaml"


def _find_by_name(token: str, resource: str, name: str) -> dict | None:
    items = api("GET", f"{API}/{resource}?name={name}", token)[resource]
    return items[0] if items else None


def cmd_types(token: str, args) -> None:
    types = api("GET", f"{API}/server_types?per_page=50", token)["server_types"]
    print(f"{'name':8} {'vCPU':>4} {'RAM GB':>6} {'disk GB':>7}  {args.location} EUR/mo")
    for st in sorted(types, key=lambda t: t["memory"]):
        if st.get("deprecation"):
            continue
        price = next(
            (p["price_monthly"]["gross"] for p in st["prices"] if p["location"] == args.location),
            None,
        )
        if price is None:
            continue  # not offered in this location
        print(
            f"{st['name']:8} {st['cores']:>4} {st['memory']:>6.0f} {st['disk']:>7}"
            f"  {float(price):.2f}"
        )


def cmd_create(token: str, args) -> None:
    if _find_by_name(token, "servers", args.name):
        sys.exit(f"server '{args.name}' already exists — use `status` (or the console)")

    pubkey_path = Path(args.pubkey).expanduser()
    if not pubkey_path.is_absolute():
        pubkey_path = REPO_ROOT / pubkey_path
    if not pubkey_path.is_file():
        sys.exit(
            f"no SSH public key at {pubkey_path}:\n"
            "  paste the public key from 1Password into keys/box.pub,\n"
            "  or generate on disk: ssh-keygen -t ed25519 -f keys/box\n"
            "(or pass --pubkey <path>)"
        )
    pubkey = pubkey_path.read_text(encoding="utf-8").strip()

    ssh_key = _find_by_name(token, "ssh_keys", args.key_name)
    if ssh_key is None:
        ssh_key = api(
            "POST", f"{API}/ssh_keys", token, {"name": args.key_name, "public_key": pubkey}
        )["ssh_key"]
        print(f"uploaded SSH key '{args.key_name}'")

    firewall = _find_by_name(token, "firewalls", "box-edge")
    if firewall is None:
        any_ip = ["0.0.0.0/0", "::/0"]
        rules = [
            {"direction": "in", "protocol": "tcp", "port": p, "source_ips": any_ip}
            for p in ("22", "80", "443")
        ]
        rules.append({"direction": "in", "protocol": "udp", "port": "443", "source_ips": any_ip})
        rules.append({"direction": "in", "protocol": "icmp", "source_ips": any_ip})
        firewall = api(
            "POST", f"{API}/firewalls", token, {"name": "box-edge", "rules": rules}
        )["firewall"]
        print("created firewall 'box-edge' (22/80/443 + icmp)")

    user_data = CLOUD_INIT.read_text(encoding="utf-8").replace("__SSH_PUBKEY__", pubkey)
    created = api(
        "POST",
        f"{API}/servers",
        token,
        {
            "name": args.name,
            "server_type": args.type,
            "image": args.image,
            "location": args.location,
            "ssh_keys": [ssh_key["id"]],
            "firewalls": [{"firewall": firewall["id"]}],
            "user_data": user_data,
        },
    )
    ip = created["server"]["public_net"]["ipv4"]["ip"]
    print(f"server '{args.name}' creating -> {ip}")
    print("cloud-init needs a few minutes; then:")
    print(f"  ssh deploy@{ip} docker version")
    print(f"  python scripts/deploy/dns.py add-wine --ip {ip}")
    print("next steps: deploy/README.md")


def cmd_status(token: str, args) -> None:
    server = _find_by_name(token, "servers", args.name)
    if server is None:
        sys.exit(f"no server named '{args.name}'")
    ip = server["public_net"]["ipv4"]["ip"]
    print(f"{server['name']}: {server['status']}  ipv4={ip}  type={server['server_type']['name']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="box", help="server name")
    parser.add_argument("--location", default="fsn1", help="Hetzner location (default: Falkenstein)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("types", help="list server types + prices for the location")
    create = sub.add_parser("create", help="provision the box")
    create.add_argument("--type", default="cax11", help="server type (see `types`)")
    create.add_argument("--image", default="ubuntu-24.04")
    create.add_argument("--pubkey", default="keys/box.pub", help="repo-relative or absolute")
    create.add_argument("--key-name", default="workstation", help="Hetzner-side SSH key name")
    sub.add_parser("status", help="show server state + IP")

    args = parser.parse_args()
    token = load_env("HCLOUD_TOKEN")
    {"types": cmd_types, "create": cmd_create, "status": cmd_status}[args.cmd](token, args)


if __name__ == "__main__":
    main()
