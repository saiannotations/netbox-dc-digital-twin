#!/usr/bin/env python3
"""Seed a 32-rack data-center digital twin into NetBox via its REST API.

Home-lab/portfolio project: builds one fictional site (DFW-01), 4 rows x 8
racks (42U), a lab-scale device population, IPAM, a sample cable plant for
one row, and power feeds/PDUs/UPS wiring.

Idempotent: every object is looked up by name/slug before creation, so the
script can be re-run safely without duplicating anything.

Environment:
    NETBOX_URL    Base URL of NetBox, e.g. http://localhost:8000
                  (default: http://localhost:8000)
    NETBOX_TOKEN  API token of a superuser (required)

Usage:
    python seed/seed_dc.py
    python seed/seed_dc.py --verify-only   # run the count checks without seeding
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Optional

import requests

NETBOX_URL = os.environ.get("NETBOX_URL", "http://localhost:8000").rstrip("/")
NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN")

# --------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------


class NetBox:
    """Tiny NetBox REST client with get-or-create semantics."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self.session.timeout = 30

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        resp = self.session.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        resp = self.session.post(f"{self.base_url}{path}", json=payload)
        resp.raise_for_status()
        return resp.json()

    def find(self, path: str, **query: Any) -> Optional[dict[str, Any]]:
        """Return the first matching object, or None."""
        data = self.get(path, params=query)
        results = data.get("results", [])
        return results[0] if results else None

    def get_or_create(
        self, path: str, lookup: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Look an object up; create it if missing. Returns (obj, created)."""
        obj = self.find(path, **lookup)
        if obj:
            return obj, False
        return self.post(path, payload), True

    def paginated(self, path: str, **query: Any) -> list[dict[str, Any]]:
        """Fetch all pages of a list endpoint."""
        items: list[dict[str, Any]] = []
        params: Optional[dict[str, Any]] = dict(query)
        url: Optional[str] = f"{self.base_url}{path}"
        while url:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("results", []))
            url = data.get("next")
            params = None
        return items


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


# --------------------------------------------------------------------------
# Builders (all idempotent)
# --------------------------------------------------------------------------


def ensure_site(api: NetBox) -> dict[str, Any]:
    site, created = api.get_or_create(
        "/api/dcim/sites/",
        {"name": "DFW-01"},
        {
            "name": "DFW-01",
            "slug": "dfw-01",
            "status": "active",
            "description": "Home-lab digital twin (Dallas, TX).",
            # Clearly fictional lab address — not a real facility.
            "physical_address": "1234 Lab Way, Dallas, TX (fictional lab address)",
            "comments": (
                "Portfolio home-lab model built with the seed script in this repo. "
                "Does not represent any real facility or employer."
            ),
        },
    )
    log(f"{'created' if created else 'exists'} site DFW-01")
    return site


def ensure_rack_groups(api: NetBox, site_id: int) -> dict[str, dict[str, Any]]:
    groups = {}
    for row in ("A", "B", "C", "D"):
        name = f"DFW-01-Row-{row}"
        group, created = api.get_or_create(
            "/api/dcim/rack-groups/",
            {"name": name},
            {"name": name, "slug": name.lower(), "site": site_id},
        )
        log(f"{'created' if created else 'exists'} rack group {name}")
        groups[row] = group
    return groups


def ensure_racks(
    api: NetBox, site_id: int, groups: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    racks = {}
    for row in ("A", "B", "C", "D"):
        for i in range(1, 9):
            name = f"DFW-01-{row}{i:02d}"
            rack, created = api.get_or_create(
                "/api/dcim/racks/",
                {"name": name},
                {
                    "name": name,
                    "site": site_id,
                    "group": groups[row]["id"],
                    "status": "active",
                    "u_height": 42,
                    "facility_id": name,
                    "comments": f"Row {row}, position {i:02d} (lab model)",
                },
            )
            racks[name] = rack
    log(f"racks: {len(racks)} total (4 rows x 8, 42U)")
    return racks


def ensure_manufacturers(api: NetBox) -> dict[str, dict[str, Any]]:
    makers = {}
    for name in ("Dell", "HPE", "Arista Networks", "APC"):
        m, created = api.get_or_create(
            "/api/dcim/manufacturers/",
            {"name": name},
            {"name": name, "slug": name.lower().replace(" ", "-")},
        )
        makers[name] = m
    return makers


def ensure_device_roles(api: NetBox) -> dict[str, dict[str, Any]]:
    specs = [
        ("Server", "ff9800"),
        ("Network Switch", "2196f3"),
        ("Patch Panel", "9e9e9e"),
        ("PDU", "4caf50"),
        ("UPS", "f44336"),
    ]
    roles = {}
    for name, color in specs:
        slug = name.lower().replace(" ", "-")
        role, created = api.get_or_create(
            "/api/dcim/device-roles/",
            {"name": name},
            {"name": name, "slug": slug, "color": color},
        )
        roles[slug] = role
    return roles


def ensure_device_types(api: NetBox, makers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    specs = [
        ("Dell", "PowerEdge R650", "dell-poweredge-r650", 1),
        ("HPE", "ProLiant DL380 Gen10", "hpe-dl380-gen10", 2),
        ("Arista Networks", "DCS-7050SX3-48", "arista-dcs-7050sx3-48", 1),
        ("APC", "AP8886 Metered Rack PDU", "apc-ap8886", 0),
        ("APC", "Smart-UPS SRT 8000", "apc-srt-8000", 2),
    ]
    types = {}
    for maker, model, slug, u_height in specs:
        dt, created = api.get_or_create(
            "/api/dcim/device-types/",
            {"model": model},
            {
                "manufacturer": makers[maker]["id"],
                "model": model,
                "slug": slug,
                "u_height": u_height,
                "is_full_depth": False,
                "comments": f"{model} (lab model, selected for twin)",
            },
        )
        types[slug] = dt
    log(f"device types: {len(types)}")
    return types


def ensure_templates(api: NetBox, types: dict[str, dict[str, Any]]) -> None:
    """Interface / power-port / power-outlet templates so created devices
    come with components to cable."""
    for slug in ("dell-poweredge-r650", "hpe-dl380-gen10"):
        for ifname in ("eth0", "eth1"):
            api.get_or_create(
                "/api/dcim/interface-templates/",
                {"devicetype_id": types[slug]["id"], "name": ifname},
                {
                    "device_type": types[slug]["id"],
                    "name": ifname,
                    "type": "1000base-t",
                },
            )
    sw = types["arista-dcs-7050sx3-48"]["id"]
    for n in list(range(1, 7)) + [47, 48]:
        api.get_or_create(
            "/api/dcim/interface-templates/",
            {"devicetype_id": sw, "name": f"Ethernet{n}"},
            {"device_type": sw, "name": f"Ethernet{n}", "type": "1000base-t"},
        )
    for name in ("mgmt0", "Uplink1", "Uplink2"):
        api.get_or_create(
            "/api/dcim/interface-templates/",
            {"devicetype_id": sw, "name": name},
            {"device_type": sw, "name": name, "type": "1000base-t"},
        )
    ups = types["apc-srt-8000"]["id"]
    api.get_or_create(
        "/api/dcim/power-port-templates/",
        {"devicetype_id": ups, "name": "PSU1"},
        {"device_type": ups, "name": "PSU1", "type": "iec-60320-c20"},
    )
    for n in (1, 2):
        api.get_or_create(
            "/api/dcim/power-outlet-templates/",
            {"devicetype_id": ups, "name": f"OUT{n}"},
            {
                "device_type": ups,
                "name": f"OUT{n}",
                "type": "iec-60320-c19",
                "power_port_template": api.find(
                    "/api/dcim/power-port-templates/", devicetype_id=ups, name="PSU1"
                )["id"],
            },
        )
    pdu = types["apc-ap8886"]["id"]
    api.get_or_create(
        "/api/dcim/power-port-templates/",
        {"devicetype_id": pdu, "name": "INPUT"},
        {"device_type": pdu, "name": "INPUT", "type": "iec-60320-c20"},
    )
    log("component templates ensured (server NICs, switch ports, PDU/UPS power)")


def ensure_patch_panel_ports(api: NetBox, panel_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rear ports + front ports for the row-A patch panel."""
    rear = {}
    for n in (1, 2):
        rp, _ = api.get_or_create(
            "/api/dcim/rear-ports/",
            {"device_id": panel_id, "name": f"RP{n}"},
            {"device": panel_id, "name": f"RP{n}", "type": "8p8c", "positions": 3},
        )
        rear[n] = rp
    front = {}
    for n in range(1, 7):
        rp = rear[1 if n <= 3 else 2]
        fp, _ = api.get_or_create(
            "/api/dcim/front-ports/",
            {"device_id": panel_id, "name": f"FP{n}"},
            {
                "device": panel_id,
                "name": f"FP{n}",
                "type": "8p8c",
                "rear_port": rp["id"],
                "rear_port_position": (n - 1) % 3 + 1,
            },
        )
        front[n] = fp
    return rear, front


def get_iface(api: NetBox, device_id: int, name: str) -> dict[str, Any]:
    iface = api.find("/api/dcim/interfaces/", device_id=device_id, name=name)
    if not iface:
        raise RuntimeError(f"interface {name} not found on device {device_id}")
    return iface


def get_power(api: NetBox, kind: str, device_id: int, name: str) -> dict[str, Any]:
    obj = api.find(f"/api/dcim/{kind}/", device_id=device_id, name=name)
    if not obj:
        raise RuntimeError(f"{kind} {name} not found on device {device_id}")
    return obj


def cable(
    api: NetBox,
    a_type: str,
    a_id: int,
    b_type: str,
    b_id: int,
    label: str,
    cable_type: str = "",
) -> None:
    """Create a cable between two terminations unless one already exists."""
    existing = api.paginated("/api/dcim/cables/", label=label)
    if existing:
        return
    payload: dict[str, Any] = {
        "termination_a_type": a_type,
        "termination_a_id": a_id,
        "termination_b_type": b_type,
        "termination_b_id": b_id,
        "label": label,
        "status": "connected",
    }
    if cable_type:
        payload["type"] = cable_type
    api.post("/api/dcim/cables/", payload)


def ensure_devices(
    api: NetBox,
    site_id: int,
    racks: dict[str, dict[str, Any]],
    roles: dict[str, dict[str, Any]],
    types: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Place the lab device population. Row A is the fully cabled sample row."""
    plan: list[tuple[str, str, str, int]] = []  # (name, type_slug, role_slug, rack)
    server_types = ("dell-poweredge-r650", "hpe-dl380-gen10")
    sw = "arista-dcs-7050sx3-48"
    pp = "apc-ap8886"

    # --- Row A (sample row, fully cabled) ---
    pos = 20
    plan.append(("dfw01-tor-a", sw, "network-switch", "DFW-01-A01"))
    plan.append(("dfw01-ppnl-a", "patch-panel-generic", "patch-panel", "DFW-01-A01"))
    plan.append(("dfw01-pdu-a1", pp, "pdu", "DFW-01-A01"))
    plan.append(("dfw01-pdu-a2", pp, "pdu", "DFW-01-A01"))
    plan.append(("dfw01-ups-a", "apc-srt-8000", "ups", "DFW-01-A04"))
    for n in range(1, 7):
        plan.append(
            (f"dfw01-srv-a0{n}", server_types[n % 2], "server", f"DFW-01-A{2 + (n - 1) // 3:02d}")
        )

    # --- Rows B, C, D (lighter footprint) ---
    for row in ("B", "C", "D"):
        plan.append((f"dfw01-tor-{row.lower()}", sw, "network-switch", f"DFW-01-{row}01"))
        plan.append((f"dfw01-pdu-{row.lower()}1", pp, "pdu", f"DFW-01-{row}01"))
        for n in range(1, 4):
            plan.append(
                (
                    f"dfw01-srv-{row.lower()}0{n}",
                    server_types[(n + 1) % 2],
                    "server",
                    f"DFW-01-{row}{2 + (n - 1) // 2:02d}",
                )
            )

    devices: dict[str, dict[str, Any]] = {}
    # Patch panels are 0U "devices" with a generic type entry created below.
    panel_type, _ = api.get_or_create(
        "/api/dcim/device-types/",
        {"model": "24-port Cat6 Patch Panel"},
        {
            "manufacturer": api.find("/api/dcim/manufacturers/", name="APC")["id"],
            "model": "24-port Cat6 Patch Panel",
            "slug": "generic-cat6-patch-panel-24",
            "u_height": 1,
            "is_full_depth": False,
        },
    )
    type_map = {**types, "patch-panel-generic": panel_type}

    for idx, (name, type_slug, role_slug, rack_name) in enumerate(plan):
        dev, created = api.get_or_create(
            "/api/dcim/devices/",
            {"name": name},
            {
                "name": name,
                "device_type": type_map[type_slug]["id"],
                "device_role": roles[role_slug]["id"],
                "site": site_id,
                "rack": racks[rack_name]["id"],
                "status": "active",
                "face": "front",
                "position": 20 + (idx % 10),
            },
        )
        devices[name] = dev
    log(f"devices: {len(devices)} total")
    return devices


def ensure_cabling(
    api: NetBox, devices: dict[str, dict[str, Any]], panel_id: int
) -> int:
    """Cable plant for sample row A: servers -> ToR switch and patch panel,
    panel rear -> switch, plus UPS power feeds."""
    tor = devices["dfw01-tor-a"]["id"]
    rear, front = ensure_patch_panel_ports(api, panel_id)
    n_cables = 0

    # Data: server eth0 -> ToR switch Ethernet1..6 (direct connect)
    for n in range(1, 7):
        srv = devices[f"dfw01-srv-a0{n}"]["id"]
        cable(
            api,
            "dcim.interface",
            get_iface(api, srv, "eth0")["id"],
            "dcim.interface",
            get_iface(api, tor, f"Ethernet{n}")["id"],
            label=f"DFW-01-A: srv-a0{n} eth0 -> tor-a Ethernet{n}",
            cable_type="cat6",
        )
        n_cables += 1

    # Structured: server eth1 -> patch panel front ports
    for n in range(1, 7):
        srv = devices[f"dfw01-srv-a0{n}"]["id"]
        cable(
            api,
            "dcim.interface",
            get_iface(api, srv, "eth1")["id"],
            "dcim.frontport",
            front[n]["id"],
            label=f"DFW-01-A: srv-a0{n} eth1 -> ppnl-a FP{n}",
            cable_type="cat6",
        )
        n_cables += 1

    # Patch panel rear -> ToR switch uplink ports
    for rp_n, eth in ((1, 47), (2, 48)):
        cable(
            api,
            "dcim.rearport",
            rear[rp_n]["id"],
            "dcim.interface",
            get_iface(api, tor, f"Ethernet{eth}")["id"],
            label=f"DFW-01-A: ppnl-a RP{rp_n} -> tor-a Ethernet{eth}",
            cable_type="cat6",
        )
        n_cables += 1

    log(f"cable plant: {n_cables} data cables ensured (row A)")
    return n_cables


def ensure_power(
    api: NetBox, site_id: int, racks: dict[str, dict[str, Any]], devices: dict[str, dict[str, Any]]
) -> int:
    """Utility feed -> UPS, UPS outlets -> PDUs (row A)."""
    panel, _ = api.get_or_create(
        "/api/dcim/power-panels/",
        {"name": "DFW-01-PP-1"},
        {"name": "DFW-01-PP-1", "site": site_id},
    )
    feed, _ = api.get_or_create(
        "/api/dcim/power-feeds/",
        {"name": "DFW-01-PF-A1"},
        {
            "name": "DFW-01-PF-A1",
            "power_panel": panel["id"],
            "rack": racks["DFW-01-A04"]["id"],
            "status": "active",
            "voltage": 208,
            "amperage": 30,
            "phase": "three-phase",
            "comments": "Utility feed to UPS (lab model)",
        },
    )
    ups_id = devices["dfw01-ups-a"]["id"]
    cable(
        api,
        "dcim.powerfeed",
        feed["id"],
        "dcim.powerport",
        get_power(api, "power-ports", ups_id, "PSU1")["id"],
        label="DFW-01-A: PF-A1 -> ups-a PSU1",
        cable_type="power",
    )
    for n, pdu in (("1", "dfw01-pdu-a1"), ("2", "dfw01-pdu-a2")):
        pdu_id = devices[pdu]["id"]
        cable(
            api,
            "dcim.poweroutlet",
            get_power(api, "power-outlets", ups_id, f"OUT{n}")["id"],
            "dcim.powerport",
            get_power(api, "power-ports", pdu_id, "INPUT")["id"],
            label=f"DFW-01-A: ups-a OUT{n} -> pdu-a{n} INPUT",
            cable_type="power",
        )
    log("power chain: utility feed -> UPS -> 2 PDUs")
    return 3


def ensure_ipam(api: NetBox, site_id: int, devices: dict[str, dict[str, Any]]) -> int:
    """One /24 management network plus two /30 point-to-point links."""
    api.get_or_create(
        "/api/ipam/prefixes/",
        {"prefix": "10.10.0.0/24"},
        {"prefix": "10.10.0.0/24", "site": site_id, "description": "DFW-01 lab management"},
    )
    p2p = [
        ("10.255.0.0/30", "ToR-A <-> agg uplink 1 (lab)"),
        ("10.255.0.4/30", "ToR-A <-> agg uplink 2 (lab)"),
    ]
    for prefix, desc in p2p:
        api.get_or_create(
            "/api/ipam/prefixes/",
            {"prefix": prefix},
            {"prefix": prefix, "site": site_id, "description": desc},
        )

    assigned = 0

    def assign(ip: str, device_name: str, iface_name: str) -> None:
        nonlocal assigned
        iface = get_iface(api, devices[device_name]["id"], iface_name)
        obj, created = api.get_or_create(
            "/api/ipam/ip-addresses/",
            {"address": ip},
            {
                "address": ip,
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": iface["id"],
                "status": "active",
                "description": f"{device_name} {iface_name} (lab)",
            },
        )
        assigned += 1

    # Management IPs across the server fleet
    base = 10
    for name in sorted(devices):
        if name.startswith("dfw01-srv-"):
            assign(f"10.10.0.{base}/24", name, "eth0")
            base += 1
    for row, ip in (("a", 5), ("b", 6), ("c", 7), ("d", 8)):
        assign(f"10.10.0.{ip}/24", f"dfw01-tor-{row}", "mgmt0")
    # Point-to-point uplink IPs on ToR-A
    assign("10.255.0.1/30", "dfw01-tor-a", "Uplink1")
    assign("10.255.0.5/30", "dfw01-tor-a", "Uplink2")
    log(f"IPAM: 3 prefixes, {assigned} addresses assigned")
    return assigned


def seed() -> None:
    api = NetBox(NETBOX_URL, NETBOX_TOKEN)
    print(f"Seeding {NETBOX_URL} ...")
    site = ensure_site(api)
    groups = ensure_rack_groups(api, site["id"])
    racks = ensure_racks(api, site["id"], groups)
    makers = ensure_manufacturers(api)
    roles = ensure_device_roles(api)
    types = ensure_device_types(api, makers)
    ensure_templates(api, types)
    devices = ensure_devices(api, site["id"], racks, roles, types)
    ensure_cabling(api, devices, devices["dfw01-ppnl-a"]["id"])
    ensure_power(api, site["id"], racks, devices)
    ensure_ipam(api, site["id"], devices)
    print("Seed complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the DFW-01 digital twin into NetBox.")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Run the count checks only (no seeding).",
    )
    args = parser.parse_args()

    if args.verify_only:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from verify import verify_all  # noqa: E402

        ok = verify_all(NetBox(NETBOX_URL, NETBOX_TOKEN or ""))
        return 0 if ok else 1

    if not NETBOX_TOKEN:
        print("ERROR: set NETBOX_TOKEN (API token of a NetBox superuser).", file=sys.stderr)
        return 2
    try:
        seed()
    except requests.HTTPError as exc:
        body = exc.response.text[:500] if exc.response is not None else ""
        print(f"ERROR: HTTP {exc.response.status_code if exc.response else '?'}: {body}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
