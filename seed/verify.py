#!/usr/bin/env python3
"""Verify the DFW-01 digital twin: assert expected object counts via the
NetBox REST API, print a pass/fail summary table, exit nonzero on failure.

Environment: NETBOX_URL (default http://localhost:8000), NETBOX_TOKEN.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from seed_dc import NetBox


def count(api: "NetBox", path: str, **query) -> int:
    return int(api.get(path, params={**query, "limit": 1}).get("count", 0))


def verify_all(api: "NetBox") -> bool:
    """Run every check; return True only if all pass."""
    checks: list[tuple[str, int, int, str]] = [
        # (label, expected_minimum_or_exact, operator, actual_count)
        ("sites named DFW-01", 1, "==", count(api, "/api/dcim/sites/", name="DFW-01")),
        ("racks (4 rows x 8, 42U)", 32, "==", count(api, "/api/dcim/racks/", site="dfw-01")),
        ("rack groups (rows A-D)", 4, "==", count(api, "/api/dcim/rack-groups/", site="dfw-01")),
        ("device roles", 5, "==", count(api, "/api/dcim/device-roles/")),
        ("device types", 5, "==", count(api, "/api/dcim/device-types/")),
        ("devices", 20, ">=", count(api, "/api/dcim/devices/", site="dfw-01")),
        ("interfaces", 60, ">=", _device_site_count(api)),
        ("prefixes (/24 + /30 links)", 3, "==", count(api, "/api/ipam/prefixes/", site="dfw-01")),
        ("IP addresses", 20, ">=", count(api, "/api/ipam/ip-addresses/")),
        ("cables", 15, ">=", count(api, "/api/dcim/cables/")),
        ("power panels", 1, "==", count(api, "/api/dcim/power-panels/", site="dfw-01")),
        ("power feeds", 1, "==", count(api, "/api/dcim/power-feeds/")),
        ("front ports (patch panel)", 6, "==", count(api, "/api/dcim/front-ports/", device="dfw01-ppnl-a")),
        ("rear ports (patch panel)", 2, "==", count(api, "/api/dcim/rear-ports/", device="dfw01-ppnl-a")),
    ]
    ok = True
    rows: list[tuple[str, str, str, str]] = []
    for label, expected, op, actual in checks:
        passed = (actual == expected) if op == "==" else (actual >= expected)
        ok = ok and passed
        rows.append((label, f"{op} {expected}", str(actual), "PASS" if passed else "FAIL"))

    widths = [max(len(r[i]) for r in rows + [(h, h, h, h)]) for i, h in
              enumerate(("CHECK", "EXPECTED", "ACTUAL", "RESULT"))]
    header = " | ".join(h.ljust(w) for h, w in zip(("CHECK", "EXPECTED", "ACTUAL", "RESULT"), widths))
    print(header)
    print("-" * len(header))
    for r in rows:
        print(" | ".join(c.ljust(w) for c, w in zip(r, widths)))
    print()
    print("ALL CHECKS PASSED" if ok else "VERIFICATION FAILED")
    return ok


def _device_site_count(api: "NetBox") -> int:
    """Count interfaces on devices that live in site DFW-01."""
    site = api.find("/api/dcim/sites/", name="DFW-01")
    if not site:
        return 0
    devices = api.paginated("/api/dcim/devices/", site="dfw-01")
    total = 0
    for dev in devices:
        total += int(api.get("/api/dcim/interfaces/", params={"device_id": dev["id"], "limit": 1}).get("count", 0))
    return total


def main() -> int:
    base = os.environ.get("NETBOX_URL", "http://localhost:8000").rstrip("/")
    token = os.environ.get("NETBOX_TOKEN")
    if not token:
        print("ERROR: set NETBOX_TOKEN (API token of a NetBox superuser).", file=sys.stderr)
        return 2
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from seed_dc import NetBox  # noqa: E402

    ok = verify_all(NetBox(base, token))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
