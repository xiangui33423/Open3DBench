#!/usr/bin/env python3
"""Deterministic, dependency-free metal layer sharing prototype.

Geometry is in OpenDB database units. Congestion is estimated from net bounding
boxes, not measured by a router. Optional measured slack guards timing-critical
nets; no timing improvement is asserted by this planning stage.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median_low


DEFAULT_CONFIG = {
    "enabled": True,
    "pitch_um": 6.4,
    "capacity_fraction": 0.30,
    "max_new_hbts": 384,
    "max_shared_nets": 192,
    "max_fanout": 16,
    "min_span_um": 40.0,
    "grid_bins": 32,
    "search_radius": 8,
    "max_local_fraction": 0.35,
    "max_detour_fraction": 0.30,
    "hbt_cost_um": 12.8,
    "min_score": 0.0,
    "min_slack_ns": 0.0,
    "dynamic_demand": True,
    "joint_site_placement": True,
    "relocation_enabled": True,
    "relocation_passes": 2,
    "relocation_radius": 2,
    "relocation_max_moves": 65536,
    "relocation_min_improvement_um": 0.1,
}


def bbox(pins):
    return (min(p["x"] for p in pins), min(p["y"] for p in pins),
            max(p["x"] for p in pins), max(p["y"] for p in pins))


def hpwl(pins):
    xl, yl, xh, yh = bbox(pins)
    return xh - xl + yh - yl


def distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def center(pins):
    return (median_low(sorted(p["x"] for p in pins)),
            median_low(sorted(p["y"] for p in pins)))


def config_values(overrides=None):
    values = dict(DEFAULT_CONFIG)
    if overrides:
        unknown = set(overrides) - set(values)
        if unknown:
            raise ValueError(f"Unknown MLS configuration keys: {sorted(unknown)}")
        values.update(overrides)
    for key in ("enabled", "dynamic_demand", "joint_site_placement", "relocation_enabled"):
        if not isinstance(values[key], bool):
            raise ValueError(f"{key} must be a JSON boolean")
    for key in ("pitch_um", "min_span_um"):
        if not math.isfinite(values[key]) or values[key] <= 0:
            raise ValueError(f"{key} must be positive and finite")
    # Do not allow configuration to silently weaken the public HBT constraints.
    if values["pitch_um"] != 6.4:
        raise ValueError("pitch_um must match the contest's fixed 6.4 um lattice")
    if not 0 <= values["capacity_fraction"] <= 0.30:
        raise ValueError("capacity_fraction must be in [0, 0.30]")
    for key in ("max_new_hbts", "max_shared_nets", "search_radius",
                "relocation_passes", "relocation_radius", "relocation_max_moves"):
        if not isinstance(values[key], int) or isinstance(values[key], bool) or values[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    for key in ("grid_bins", "max_fanout"):
        if not isinstance(values[key], int) or not 2 <= values[key] <= 256:
            raise ValueError(f"{key} must be an integer in [2, 256]")
    for key in ("max_local_fraction", "max_detour_fraction"):
        if not 0 <= values[key] <= 1:
            raise ValueError(f"{key} must be in [0, 1]")
    for key in ("hbt_cost_um", "min_score", "min_slack_ns", "relocation_min_improvement_um"):
        if not math.isfinite(values[key]):
            raise ValueError(f"{key} must be finite")
    if values["relocation_min_improvement_um"] < 0:
        raise ValueError("relocation_min_improvement_um must be nonnegative")
    if values["hbt_cost_um"] < 0:
        raise ValueError("hbt_cost_um must be nonnegative")
    return values


class DemandGrid:
    """RUDY-like rectangular demand estimate, built using difference arrays."""

    def __init__(self, area, bins, nets, dbu):
        self.area, self.bins = area, bins
        self.dx = (area[2] - area[0]) / bins
        self.dy = (area[3] - area[1]) / bins
        diff = {die: [[0.0] * (bins + 1) for _ in range(bins + 1)]
                for die in ("bottom", "upper")}
        for net in nets:
            pins = net["pins"]
            dies = {p.get("die") for p in pins}
            if len(pins) < 2 or len(dies) != 1 or next(iter(dies)) not in diff:
                continue
            if net.get("special") or net.get("signal_type", "SIGNAL") not in ("SIGNAL", "CLOCK"):
                continue
            die = next(iter(dies))
            ix0, iy0, ix1, iy1 = self.indices(bbox(pins))
            count = (ix1 - ix0 + 1) * (iy1 - iy0 + 1)
            weight = hpwl(pins) / dbu / count
            grid = diff[die]
            grid[iy0][ix0] += weight
            grid[iy0][ix1 + 1] -= weight
            grid[iy1 + 1][ix0] -= weight
            grid[iy1 + 1][ix1 + 1] += weight
        self.prefix = {}
        self.values = {}
        self.dirty = set()
        for die, grid in diff.items():
            prefix = [[0.0] * (bins + 1) for _ in range(bins + 1)]
            for y in range(bins):
                for x in range(bins):
                    grid[y][x] += ((grid[y - 1][x] if y else 0)
                                   + (grid[y][x - 1] if x else 0)
                                   - (grid[y - 1][x - 1] if x and y else 0))
                    prefix[y + 1][x + 1] = (grid[y][x] + prefix[y][x + 1]
                                             + prefix[y + 1][x] - prefix[y][x])
            self.prefix[die] = prefix
            self.values[die] = [row[:bins] for row in grid[:bins]]

    def indices(self, bounds):
        xl, yl, xh, yh = bounds
        n, area = self.bins, self.area
        clamp = lambda value: max(0, min(n - 1, int(value)))
        return (clamp((xl - area[0]) / self.dx), clamp((yl - area[1]) / self.dy),
                clamp((xh - area[0]) / self.dx), clamp((yh - area[1]) / self.dy))

    def adjust(self, die, pins, amount, dbu):
        """Replace demand after a committed split so the target cannot overfill."""
        x0, y0, x1, y1 = self.indices(bbox(pins))
        weight = amount * hpwl(pins) / dbu / ((x1 - x0 + 1) * (y1 - y0 + 1))
        cells = self.values[die]
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                cells[y][x] += weight
        self.dirty.add(die)

    def mean(self, die, bounds):
        if die in self.dirty:
            cells, n = self.values[die], self.bins
            prefix = [[0.0] * (n + 1) for _ in range(n + 1)]
            for y in range(n):
                row_sum = 0.0
                for x in range(n):
                    row_sum += cells[y][x]
                    prefix[y + 1][x + 1] = prefix[y][x + 1] + row_sum
            self.prefix[die] = prefix
            self.dirty.remove(die)
        x0, y0, x1, y1 = self.indices(bounds)
        p = self.prefix[die]
        total = p[y1 + 1][x1 + 1] - p[y0][x1 + 1] - p[y1 + 1][x0] + p[y0][x0]
        return max(0.0, total / ((x1 - x0 + 1) * (y1 - y0 + 1)))


class HbtSites:
    """Bounded lattice search with pitch checks against a spatial hash."""

    def __init__(self, area, size, pitch, grid, existing):
        self.area, self.size, self.pitch = area, size, pitch
        self.step = math.ceil(pitch / grid) * grid
        if self.step != pitch:
            raise ValueError("HBT pitch must be divisible by the manufacturing grid")
        # The evaluator requires the same pitch-grid residue as the input DEF,
        # in addition to ordinary spacing and manufacturing-grid checks.
        residues = {(h["x"] % pitch, h["y"] % pitch) for h in existing}
        if len(residues) > 1:
            raise ValueError("Existing HBT centers do not define one pitch lattice")
        rx, ry = next(iter(residues)) if residues else (size[0] // 2, size[1] // 2)
        lower_x, lower_y = area[0] + size[0] // 2, area[1] + size[1] // 2
        self.x0 = lower_x + (rx - lower_x) % pitch
        self.y0 = lower_y + (ry - lower_y) % pitch
        if (self.x0 - size[0] // 2) % grid or (self.y0 - size[1] // 2) % grid:
            raise ValueError("Input HBT lattice is off the manufacturing grid")
        self.nx = max(0, (area[2] - size[0] + size[0] // 2 - self.x0) // self.step + 1)
        self.ny = max(0, (area[3] - size[1] + size[1] // 2 - self.y0) // self.step + 1)
        self.occupied = defaultdict(list)
        for hbt in existing:
            self.reserve((hbt["x"], hbt["y"]))

    def reserve(self, point):
        key = (point[0] // self.pitch, point[1] // self.pitch)
        self.occupied[key].append(point)

    def legal(self, point, extra=()):
        x, y = point
        bx, by = x // self.pitch, y // self.pitch
        nearby = list(extra)
        for ix in range(bx - 1, bx + 2):
            for iy in range(by - 1, by + 2):
                nearby.extend(self.occupied.get((ix, iy), ()))
        # Conservative square spacing also protects CUT SPACING for diagonal pairs.
        return all(abs(x - px) >= self.pitch or abs(y - py) >= self.pitch
                   for px, py in nearby)

    def nearby(self, target, radius, extra=(), limit=8):
        if not self.nx or not self.ny:
            return []
        ix = max(0, min(self.nx - 1, round((target[0] - self.x0) / self.step)))
        iy = max(0, min(self.ny - 1, round((target[1] - self.y0) / self.step)))
        candidates = []
        for gx in range(max(0, ix - radius), min(self.nx, ix + radius + 1)):
            for gy in range(max(0, iy - radius), min(self.ny, iy + radius + 1)):
                point = (self.x0 + gx * self.step, self.y0 + gy * self.step)
                candidates.append((distance(point, target), gx, gy, point))
        available = []
        for _, _, _, point in sorted(candidates):
            if self.legal(point, extra):
                available.append(point)
                if len(available) >= limit:
                    break
        return available

    def nearest(self, target, radius, extra=()):
        points = self.nearby(target, radius, extra, limit=1)
        return points[0] if points else None


def place_pair(sites, a, b, pa, pb, radius, joint):
    if not joint or radius == 0:
        p0 = sites.nearest(pa, radius)
        p1 = sites.nearest(pb, radius, [p0]) if p0 is not None else None
        return p0, p1
    # A bbox's interior is a flat optimum for HPWL. Search the corner facing
    # the other cluster as well as the median, then optimize the complete chain.
    def proposals(pins, own, other):
        xl, yl, xh, yh = bbox(pins)
        projected = (min(xh, max(xl, other[0])), min(yh, max(yl, other[1])))
        return sorted(set(sites.nearby(own, radius) + sites.nearby(projected, radius)))
    first, second = proposals(a, pa, pb), proposals(b, pb, pa)
    options = []
    for p0 in first:
        local_a = hpwl(a + [{"x": p0[0], "y": p0[1]}])
        for p1 in second:
            if not sites.legal(p1, [p0]):
                continue
            cost = local_a + distance(p0, p1) + hpwl(b + [{"x": p1[0], "y": p1[1]}])
            options.append((cost, distance(p0, pa) + distance(p1, pb), p0, p1))
    if not options:
        return None, None
    _, _, p0, p1 = min(options)
    return p0, p1


def candidate(net, config, dbu, demand):
    pins = net["pins"]
    if (net.get("special") or net.get("signal_type", "SIGNAL") != "SIGNAL"
            or "__MLS__" in net["name"] or not 2 <= len(pins) <= config["max_fanout"]):
        return None, "type_or_fanout"
    if net["name"].endswith(("_BOT", "_TOP")):
        return None, "existing_subnet"
    if any(p.get("hbt") or p["inst"].startswith(("HBT_", "LS_HBT_"))
           or p["inst"] == "PIN" for p in pins):
        return None, "hbt_or_package_pin"
    dies = {p.get("die") for p in pins}
    if len(dies) != 1 or next(iter(dies)) not in ("bottom", "upper"):
        return None, "die"
    drivers = [p for p in pins if p.get("io") == "OUTPUT"]
    if len(drivers) != 1 or any(p.get("io") not in ("INPUT", "OUTPUT") for p in pins):
        return None, "driver"
    slack = net.get("slack_ns")
    if slack is not None and (not math.isfinite(slack) or slack < config["min_slack_ns"]):
        return None, "timing_guard"
    span = hpwl(pins)
    if span < config["min_span_um"] * dbu:
        return None, "short"
    die = next(iter(dies))
    other = "upper" if die == "bottom" else "bottom"
    options = []
    for axis in ("x", "y"):
        ordered = sorted(pins, key=lambda p: (p[axis], p["inst"], p["pin"]))
        cut = max(range(1, len(ordered)),
                  key=lambda i: (ordered[i][axis] - ordered[i - 1][axis], -i))
        a, b = ordered[:cut], ordered[cut:]
        if drivers[0] not in a:
            a, b = b, a
        local = hpwl(a) + hpwl(b)
        if local > config["max_local_fraction"] * span:
            continue
        pa, pb = center(a), center(b)
        trunk = distance(pa, pb)
        bounds = bbox([{"x": pa[0], "y": pa[1]}, {"x": pb[0], "y": pb[1]}])
        source_demand = demand.mean(die, bounds)
        target_demand = demand.mean(other, bounds)
        gain = (source_demand - target_demand) / (1.0 + source_demand)
        score = gain * trunk / dbu - local / dbu - config["hbt_cost_um"]
        options.append((score, axis, a, b, pa, pb, span, die, source_demand, target_demand))
    if not options:
        return None, "cluster_spread"
    best = max(options, key=lambda item: (item[0], item[1]))
    if best[0] < config["min_score"]:
        return None, "score"
    return best, None


def plan_design(manifest, config=None):
    config = config_values(config)
    original_manifest = manifest
    from hbt_optimizer import optimize_hbts
    manifest, relocations, relocation_stats = optimize_hbts(manifest, {
        "enabled": config["enabled"] and config["relocation_enabled"],
        "passes": config["relocation_passes"],
        "search_radius": config["relocation_radius"],
        "max_moves": config["relocation_max_moves"],
        "min_improvement_um": config["relocation_min_improvement_um"],
    })
    dbu = int(manifest["dbu_per_micron"])
    grid = int(manifest.get("manufacturing_grid", 1))
    area = list(map(int, manifest["die_area"]))
    size = list(map(int, manifest.get("hbt_master_size", (dbu, dbu))))
    if dbu <= 0 or grid <= 0 or len(area) != 4 or area[2] <= area[0] or area[3] <= area[1]:
        raise ValueError("Invalid database units, manufacturing grid, or die area")
    if len(size) != 2 or min(size) <= 0 or any(s % 2 for s in size):
        raise ValueError("HBT dimensions must be positive even database units")
    pitch = math.ceil(config["pitch_um"] * dbu)
    capacity = ((area[2] - area[0]) // pitch) * ((area[3] - area[1]) // pitch)
    existing = manifest.get("hbts", [])
    budget = max(0, min(config["max_new_hbts"],
                        math.floor(capacity * config["capacity_fraction"]) - len(existing)))
    stats = {"input_nets": len(manifest["nets"]), "existing_hbts": len(existing),
             "capacity": capacity, "hbt_limit": math.floor(capacity * config["capacity_fraction"]),
             "new_hbt_budget": budget, "selected_nets": 0, "new_hbts": 0,
             "timing_source": "provided_slack" if any("slack_ns" in n for n in manifest["nets"])
                              else "geometry_only", "skipped": {}}
    stats["relocation"] = relocation_stats
    result = {"version": 2, "config": config, "selected": [],
              "relocations": relocations, "stats": stats}
    if not config["enabled"] or budget < 2 or config["max_shared_nets"] == 0:
        validate_plan(original_manifest, result)
        return result
    demand = DemandGrid(area, config["grid_bins"], manifest["nets"], dbu)
    sites = HbtSites(area, size, pitch, grid, existing)
    skipped = Counter()
    candidates = []
    names = {n["name"] for n in manifest["nets"]}
    inst_names = {p["inst"] for n in manifest["nets"] for p in n["pins"]}
    inst_names.update(h["name"] for h in existing)
    for net in manifest["nets"]:
        choice, reason = candidate(net, config, dbu, demand)
        if choice:
            candidates.append((choice[0], net["name"], net, choice))
        else:
            skipped[reason] += 1
    stats["candidate_nets"] = len(candidates)
    identifier = 0
    for _, _, net, choice in sorted(candidates, key=lambda entry: (-entry[0], entry[1])):
        if len(result["selected"]) >= config["max_shared_nets"] or stats["new_hbts"] + 2 > budget:
            break
        score, axis, a, b, pa, pb, span, die, source_demand, target_demand = choice
        if config["dynamic_demand"]:
            choice, reason = candidate(net, config, dbu, demand)
            if choice is None:
                skipped["updated_" + reason] += 1
                continue
            score, axis, a, b, pa, pb, span, die, source_demand, target_demand = choice
        p0, p1 = place_pair(sites, a, b, pa, pb, config["search_radius"],
                            config["joint_site_placement"])
        if p0 is None or p1 is None:
            skipped["no_legal_site"] += 1
            continue
        local_a = hpwl(a + [{"x": p0[0], "y": p0[1]}])
        local_b = hpwl(b + [{"x": p1[0], "y": p1[1]}])
        routed_span = local_a + distance(p0, p1) + local_b
        if routed_span > span * (1 + config["max_detour_fraction"]):
            skipped["placement_detour"] += 1
            continue
        realized = (score - max(0, routed_span - span) / dbu)
        if realized < config["min_score"]:
            skipped["placement_score"] += 1
            continue
        source_suffix, other_suffix = ("BOT", "TOP") if die == "bottom" else ("TOP", "BOT")
        subnames = [f"{net['name']}__MLS__S0__{source_suffix}",
                    f"{net['name']}__MLS__S1__{other_suffix}",
                    f"{net['name']}__MLS__S2__{source_suffix}"]
        if any(name in names for name in subnames):
            skipped["name_collision"] += 1
            continue
        hnames = []
        for _ in range(2):
            while f"LS_HBT_{identifier}" in inst_names:
                identifier += 1
            hnames.append(f"LS_HBT_{identifier}")
            inst_names.add(hnames[-1])
            identifier += 1
        ref = lambda p: {"inst": p["inst"], "pin": p["pin"]}
        subnets = [
            {"name": subnames[0], "die": die, "pins": [ref(p) for p in a] + [{"inst": hnames[0], "pin": source_suffix}]},
            {"name": subnames[1], "die": "upper" if die == "bottom" else "bottom", "pins":
             [{"inst": name, "pin": other_suffix} for name in hnames]},
            {"name": subnames[2], "die": die, "pins": [{"inst": hnames[1], "pin": source_suffix}] + [ref(p) for p in b]},
        ]
        masters = ("HBT_BOTIN", "HBT_TOPIN") if die == "bottom" else ("HBT_TOPIN", "HBT_BOTIN")
        hbts = [{"name": name, "master": master, "x": point[0], "y": point[1],
                 "origin_x": point[0] - size[0] // 2, "origin_y": point[1] - size[1] // 2,
                 "from_subnet": subnames[i], "to_subnet": subnames[i + 1]}
                for i, (name, master, point) in enumerate(zip(hnames, masters, (p0, p1)))]
        result["selected"].append({"original": net["name"], "subnets": subnets,
                                   "hbts": hbts, "score": realized, "split_axis": axis,
                                   "original_hpwl_um": span / dbu,
                                   "estimated_shared_hpwl_um": routed_span / dbu,
                                   "source_demand": source_demand, "target_demand": target_demand,
                                   "slack_ns": net.get("slack_ns")})
        sites.reserve(p0)
        sites.reserve(p1)
        if config["dynamic_demand"]:
            point0, point1 = {"x": p0[0], "y": p0[1]}, {"x": p1[0], "y": p1[1]}
            demand.adjust(die, net["pins"], -1, dbu)
            demand.adjust(die, a + [point0], 1, dbu)
            demand.adjust(die, b + [point1], 1, dbu)
            demand.adjust("upper" if die == "bottom" else "bottom", [point0, point1], 1, dbu)
        stats["new_hbts"] += 2
    stats["selected_nets"] = len(result["selected"])
    stats["skipped"] = dict(sorted(skipped.items()))
    validate_plan(original_manifest, result)
    return result


def validate_plan(manifest, plan):
    """Verify pin equivalence, subnet connectivity, geometry, and HBT budgets."""
    originals = {n["name"]: n for n in manifest["nets"]}
    pitch = math.ceil(plan["config"]["pitch_um"] * manifest["dbu_per_micron"])
    reference = manifest.get("hbts", [])
    sites = HbtSites(manifest["die_area"], manifest["hbt_master_size"], pitch,
                     manifest.get("manufacturing_grid", 1), reference)
    moves = {h["name"]: h for h in plan.get("relocations", [])}
    if len(moves) != len(plan.get("relocations", [])) or set(moves) - {h["name"] for h in reference}:
        raise ValueError("Unknown or duplicate relocated HBT")
    existing = []
    for h in reference:
        moved = moves.get(h["name"], h)
        x, y = moved["x"], moved["y"]
        if h["name"] in moves:
            if (moved["before_x"], moved["before_y"]) != (h["x"], h["y"]):
                raise ValueError("Relocation reference position changed")
            if (x, y) != (moved["origin_x"] + sites.size[0] // 2,
                          moved["origin_y"] + sites.size[1] // 2):
                raise ValueError("Relocation center and origin disagree")
        if (x - sites.x0) % pitch or (y - sites.y0) % pitch:
            raise ValueError("Relocated HBT off input lattice")
        ox, oy = x - sites.size[0] // 2, y - sites.size[1] // 2
        if not (sites.area[0] <= ox <= sites.area[2] - sites.size[0]
                and sites.area[1] <= oy <= sites.area[3] - sites.size[1]):
            raise ValueError("Relocated HBT outside die")
        if ox % manifest.get("manufacturing_grid", 1) or oy % manifest.get("manufacturing_grid", 1):
            raise ValueError("Relocated HBT off manufacturing grid")
        existing.append({"name": h["name"], "x": x, "y": y})
    sites.occupied.clear()
    for h in existing:
        point = h["x"], h["y"]
        if not sites.legal(point):
            raise ValueError("Relocated HBT pitch violation")
        sites.reserve(point)
    identities = {h["name"] for h in existing}
    selected_names = set()
    for entry in plan["selected"]:
        if entry["original"] in selected_names:
            raise ValueError("Original net selected more than once")
        selected_names.add(entry["original"])
        original = originals[entry["original"]]
        expected = Counter((p["inst"], p["pin"]) for p in original["pins"])
        pin_dies = {(p["inst"], p["pin"]): p.get("die") for p in original["pins"]}
        actual = Counter((p["inst"], p["pin"]) for s in entry["subnets"] for p in s["pins"]
                         if not p["inst"].startswith("LS_HBT_"))
        if actual != expected:
            raise ValueError(f"Changed terminal set on {entry['original']}")
        if len(entry["subnets"]) != 3 or len(entry["hbts"]) != 2:
            raise ValueError("MLS prototype requires three subnets and two HBTs")
        connected = defaultdict(list)
        subnet_names = {s["name"] for s in entry["subnets"]}
        if len(subnet_names) != 3:
            raise ValueError("Duplicate MLS subnet name")
        for s in entry["subnets"]:
            if not s["name"].startswith(entry["original"] + "__MLS__S"):
                raise ValueError("Invalid MLS subnet name")
            suffix = "__BOT" if s["die"] == "bottom" else "__TOP"
            if not s["name"].endswith(suffix):
                raise ValueError("Subnet name/die mismatch")
            for p in s["pins"]:
                if p["inst"].startswith("LS_HBT_"):
                    if p["pin"] != ("BOT" if s["die"] == "bottom" else "TOP"):
                        raise ValueError("HBT terminal connected to the wrong die")
                    connected[p["inst"]].append((s["name"], p["pin"]))
                elif pin_dies[(p["inst"], p["pin"])] != s["die"]:
                    raise ValueError("Original terminal moved to the wrong die")
        graph = defaultdict(set)
        for h in entry["hbts"]:
            if h["name"] in identities:
                raise ValueError("Duplicate HBT instance name")
            identities.add(h["name"])
            if {p for _, p in connected[h["name"]]} != {"BOT", "TOP"} or len(connected[h["name"]]) != 2:
                raise ValueError("HBT must connect exactly one subnet per die")
            ends = [n for n, _ in connected[h["name"]]]
            if {h["from_subnet"], h["to_subnet"]} != set(ends):
                raise ValueError("HBT endpoints disagree with subnet connectivity")
            pin_at_source = next(p for n, p in connected[h["name"]] if n == h["from_subnet"])
            if h["master"] != ("HBT_BOTIN" if pin_at_source == "BOT" else "HBT_TOPIN"):
                raise ValueError("HBT Liberty direction disagrees with signal direction")
            graph[ends[0]].add(ends[1])
            graph[ends[1]].add(ends[0])
            x, y = h["x"], h["y"]
            area, size = sites.area, sites.size
            if x != h["origin_x"] + size[0] // 2 or y != h["origin_y"] + size[1] // 2:
                raise ValueError("HBT center and origin disagree")
            if (x - sites.x0) % pitch or (y - sites.y0) % pitch:
                raise ValueError("HBT does not preserve the input pitch-grid residue")
            if not (area[0] <= h["origin_x"] <= area[2] - size[0]
                    and area[1] <= h["origin_y"] <= area[3] - size[1]):
                raise ValueError("HBT outside die area")
            grid = manifest.get("manufacturing_grid", 1)
            if h["origin_x"] % grid or h["origin_y"] % grid:
                raise ValueError("HBT origin off manufacturing grid")
            if not sites.legal((x, y)):
                raise ValueError("HBT pitch violation")
            sites.reserve((x, y))
        visited, pending = set(), [entry["subnets"][0]["name"]]
        while pending:
            node = pending.pop()
            if node not in visited:
                visited.add(node)
                pending.extend(graph[node] - visited)
        if visited != {s["name"] for s in entry["subnets"]}:
            raise ValueError("Disconnected MLS family")
    added = sum(len(s["hbts"]) for s in plan["selected"])
    if added > plan["stats"]["new_hbt_budget"]:
        raise ValueError("HBT budget exceeded")


def tcl_word(value):
    """Quote one Tcl word, suppressing substitutions even for hostile net names."""
    escaped = str(value).translate(str.maketrans({"\\": "\\\\", '"': '\\"',
                                                  "$": "\\$", "[": "\\[", "]": "\\]",
                                                  "\n": "\\n", "\r": "\\r"}))
    return '"' + escaped + '"'


def emit_tcl(plan):
    lines = ["# Generated MLS edits; executed inside GRT_PREPARE_TCL.",
             "set mls_block [ord::get_db_block]", "set mls_db [ord::get_db]"]
    for h in plan.get("relocations", []):
        lines += [f"set mls_inst [$mls_block findInst {tcl_word(h['name'])}]",
                  'if {$mls_inst eq "NULL"} {error "Relocated HBT instance missing"}',
                  "$mls_inst setPlacementStatus PLACED",
                  "$mls_inst setOrient R0",
                  f"$mls_inst setOrigin {h['origin_x']} {h['origin_y']}",
                  "$mls_inst setPlacementStatus FIRM"]
    for entry in plan["selected"]:
        original = tcl_word(entry["original"])
        lines += [f"set mls_old [$mls_block findNet {original}]",
                  'if {$mls_old eq "NULL"} {error "MLS original net missing"}']
        for index, subnet in enumerate(entry["subnets"]):
            lines.append(f"set mls_s{index} [odb::dbNet_create $mls_block {tcl_word(subnet['name'])}]")
            lines.append(f'if {{$mls_s{index} eq "NULL"}} {{error "MLS subnet creation failed"}}')
            lines.append(f"$mls_s{index} setSigType SIGNAL")
        for h in entry["hbts"]:
            lines += [f"set mls_master [$mls_db findMaster {tcl_word(h['master'])}]",
                      'if {$mls_master eq "NULL"} {error "MLS HBT master missing"}',
                      f"set mls_inst [odb::dbInst_create $mls_block $mls_master {tcl_word(h['name'])}]",
                      'if {$mls_inst eq "NULL"} {error "MLS HBT creation failed"}',
                      "$mls_inst setOrient R0",
                      f"$mls_inst setOrigin {h['origin_x']} {h['origin_y']}",
                      "$mls_inst setPlacementStatus FIRM"]
        for index, subnet in enumerate(entry["subnets"]):
            for pin in subnet["pins"]:
                lines += [f"set mls_inst [$mls_block findInst {tcl_word(pin['inst'])}]",
                          f"set mls_term [$mls_inst findITerm {tcl_word(pin['pin'])}]",
                          'if {$mls_term eq "NULL"} {error "MLS instance terminal missing"}',
                          "$mls_term disconnect", f"$mls_term connect $mls_s{index}"]
        lines.append("odb::dbNet_destroy $mls_old")
    lines.append(f'puts "MLS: relocated {len(plan.get("relocations", []))} existing HBTs, applied {len(plan["selected"])} sharing nets, {plan["stats"]["new_hbts"]} new HBTs"')
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--timing-csv", type=Path,
                        help="Optional CSV with net,slack_ns columns; negative-slack nets are guarded")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--apply-tcl", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    overrides = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
    if args.timing_csv:
        with args.timing_csv.open(encoding="utf-8", newline="") as handle:
            slacks = {row["net"]: float(row["slack_ns"]) for row in csv.DictReader(handle)}
        for net in manifest["nets"]:
            if net["name"] in slacks:
                net["slack_ns"] = slacks[net["name"]]
    plan = plan_design(manifest, overrides)
    args.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.apply_tcl.write_text(emit_tcl(plan), encoding="utf-8")
    print(json.dumps(plan["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
