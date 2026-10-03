#!/usr/bin/env python3
"""Relocate existing HBTs on their reference lattice without changing connectivity.

Coordinate descent minimizes the exact sum of incident-net HPWL. This is a
geometry objective, not a prediction of routed wirelength or timing improvement.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict


DEFAULT_CONFIG = {
    "enabled": True,
    "passes": 2,
    "search_radius": 2,
    "max_moves": 4096,
    "min_improvement_um": 0.1,
}


def _config(overrides):
    values = dict(DEFAULT_CONFIG)
    if overrides:
        unknown = set(overrides) - set(values)
        if unknown:
            raise ValueError(f"Unknown HBT optimization keys: {sorted(unknown)}")
        values.update(overrides)
    if not isinstance(values["enabled"], bool):
        raise ValueError("enabled must be a JSON boolean")
    for key in ("passes", "search_radius", "max_moves"):
        if (not isinstance(values[key], int) or isinstance(values[key], bool)
                or values[key] < 0):
            raise ValueError(f"{key} must be a nonnegative integer")
    value = values["min_improvement_um"]
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("min_improvement_um must be finite and nonnegative")
    return values


def _hpwl(pins):
    if len(pins) < 2:
        return 0
    return (max(p["x"] for p in pins) - min(p["x"] for p in pins)
            + max(p["y"] for p in pins) - min(p["y"] for p in pins))


def _bounds(pins):
    return (min(p["x"] for p in pins), min(p["y"] for p in pins),
            max(p["x"] for p in pins), max(p["y"] for p in pins))


def _optimum_interval(bounds, lower_index, upper_index):
    endpoints = sorted(value for box in bounds
                       for value in (box[lower_index], box[upper_index]))
    n = len(bounds)
    return endpoints[n - 1], endpoints[n]


class _Lattice:
    def __init__(self, manifest):
        self.area = manifest["die_area"]
        self.size = manifest["hbt_master_size"]
        self.pitch = round(6.4 * manifest["dbu_per_micron"])
        self.grid = manifest.get("manufacturing_grid", 1)
        if (self.pitch <= 0 or self.grid <= 0 or self.pitch % self.grid
                or len(self.area) != 4 or self.area[2] <= self.area[0]
                or self.area[3] <= self.area[1] or len(self.size) != 2
                or min(self.size) <= 0 or any(s % 2 for s in self.size)):
            raise ValueError("Invalid HBT lattice geometry")
        hbts = manifest.get("hbts", [])
        residues = {(h["x"] % self.pitch, h["y"] % self.pitch) for h in hbts}
        if len(residues) > 1:
            raise ValueError("Existing HBT centers do not define one pitch lattice")
        rx, ry = next(iter(residues)) if residues else (self.size[0] // 2, self.size[1] // 2)
        lx, ly = self.area[0] + self.size[0] // 2, self.area[1] + self.size[1] // 2
        self.x0 = lx + (rx - lx) % self.pitch
        self.y0 = ly + (ry - ly) % self.pitch
        if ((self.x0 - self.size[0] // 2) % self.grid
                or (self.y0 - self.size[1] // 2) % self.grid):
            raise ValueError("Input HBT lattice is off the manufacturing grid")
        self.nx = max(0, (self.area[2] - self.size[0] // 2 - self.x0) // self.pitch + 1)
        self.ny = max(0, (self.area[3] - self.size[1] // 2 - self.y0) // self.pitch + 1)
        self.occupied = {}
        for hbt in hbts:
            point = (hbt["x"], hbt["y"])
            if point in self.occupied:
                raise ValueError("Existing HBTs occupy the same lattice site")
            self.occupied[point] = hbt["name"]

    def candidates(self, current, optimum, radius):
        """Search bounded neighborhoods around current and the convex optimum.

        Projecting the current point onto the optimum rectangle handles long
        flat intervals without enumerating every grid site inside them. The
        midpoint and corners allow escape when that projection is occupied.
        """
        if not self.nx or not self.ny:
            return []
        xl, yl, xh, yh = optimum
        project = (max(xl, min(xh, current[0])), max(yl, min(yh, current[1])))
        targets = {current, project, ((xl + xh) // 2, (yl + yh) // 2),
                   (xl, yl), (xl, yh), (xh, yl), (xh, yh)}
        indices = set()
        for x, y in targets:
            gx = max(0, min(self.nx - 1, round((x - self.x0) / self.pitch)))
            gy = max(0, min(self.ny - 1, round((y - self.y0) / self.pitch)))
            for ix in range(max(0, gx - radius), min(self.nx, gx + radius + 1)):
                for iy in range(max(0, gy - radius), min(self.ny, gy + radius + 1)):
                    indices.add((ix, iy))
        return [(self.x0 + gx * self.pitch, self.y0 + gy * self.pitch)
                for gx, gy in sorted(indices)]


def optimize_hbts(manifest, config=None):
    """Return (copied_manifest, final_relocations, stats), preserving the input.

    Any HBT touching a package pin, special net, or non-SIGNAL net is protected.
    Relocations retain pin offsets and include only the final location per HBT.
    Nets without an existing HBT are read-only and shared with the input;
    every HBT and every pin in an incident net has an independent dictionary.
    """
    values = _config(config)
    result = dict(manifest)
    hbts = [dict(hbt) for hbt in manifest.get("hbts", [])]
    result["hbts"] = hbts
    hbt_names = {hbt["name"] for hbt in hbts}
    nets = list(manifest.get("nets", []))
    for index, net in enumerate(nets):
        if any(pin["inst"] in hbt_names for pin in net["pins"]):
            nets[index] = dict(net, pins=[dict(pin) for pin in net["pins"]])
    result["nets"] = nets
    stats = {"enabled": values["enabled"], "existing_hbts": len(hbts),
             "eligible_hbts": 0, "moved_hbts": 0, "accepted_moves": 0,
             "passes_completed": 0, "saved_hpwl_um": 0.0, "skipped": {}}
    if not values["enabled"] or not hbts or not values["passes"] or not values["max_moves"]:
        return result, [], stats
    dbu = manifest["dbu_per_micron"]
    if dbu <= 0:
        raise ValueError("dbu_per_micron must be positive")
    lattice = _Lattice(result)
    nets = result["nets"]
    by_name = {h["name"]: h for h in hbts}
    if len(by_name) != len(hbts):
        raise ValueError("Duplicate HBT instance name")
    before = {h["name"]: (h["x"], h["y"]) for h in hbts}
    incident = defaultdict(set)
    pin_refs = defaultdict(list)
    for index, net in enumerate(nets):
        for pin in net["pins"]:
            name = pin["inst"]
            if name in by_name:
                incident[name].add(index)
                pin_refs[name].append(pin)
    protected = set()
    skipped = Counter()
    for name in by_name:
        if not incident[name]:
            protected.add(name)
            skipped["unconnected"] += 1
            continue
        if any(nets[i].get("special")
               or nets[i].get("signal_type", "SIGNAL") != "SIGNAL"
               or nets[i].get("bterms")
               or any(p["inst"] == "PIN" for p in nets[i]["pins"])
               for i in incident[name]):
            protected.add(name)
            skipped["protected_net"] += 1
    eligible = sorted(set(by_name) - protected)
    stats["eligible_hbts"] = len(eligible)
    stats["skipped"] = dict(sorted(skipped.items()))
    affected = {index for name in eligible for index in incident[name]}
    initial_total = sum(_hpwl(nets[i]["pins"]) for i in affected)
    minimum_gain = values["min_improvement_um"] * dbu

    for _ in range(values["passes"]):
        changed = False
        for name in eligible:
            if stats["accepted_moves"] >= values["max_moves"]:
                break
            hbt = by_name[name]
            current = (hbt["x"], hbt["y"])
            groups = []
            # All pins of this HBT move together. Other HBTs already moved in
            # this pass contribute their updated coordinates to these bounds.
            for index in sorted(incident[name]):
                pins = nets[index]["pins"]
                other = [p for p in pins if p["inst"] != name]
                own = [p for p in pins if p["inst"] == name]
                if other:
                    box = _bounds(other)
                    offsets = [(p["x"] - current[0], p["y"] - current[1]) for p in own]
                    offset_bounds = (min(dx for dx, _dy in offsets), min(dy for _dx, dy in offsets),
                                     max(dx for dx, _dy in offsets), max(dy for _dx, dy in offsets))
                    # Public HBT BOT/TOP shapes share the same center; preserve
                    # offsets nevertheless and evaluate the exact HPWL below.
                    groups.append((box, offset_bounds))
            if not groups:
                continue
            boxes = [box for box, _offsets in groups]
            xl, xh = _optimum_interval(boxes, 0, 2)
            yl, yh = _optimum_interval(boxes, 1, 3)

            def objective(point):
                total = 0
                for (bx0, by0, bx1, by1), (dx0, dy0, dx1, dy1) in groups:
                    px0, px1 = point[0] + dx0, point[0] + dx1
                    py0, py1 = point[1] + dy0, point[1] + dy1
                    total += max(bx1, px1) - min(bx0, px0) + max(by1, py1) - min(by0, py0)
                return total

            old_cost = objective(current)
            best_point, best_cost = current, old_cost
            for point in lattice.candidates(current, (xl, yl, xh, yh), values["search_radius"]):
                if point in lattice.occupied and lattice.occupied[point] != name:
                    continue
                candidate_cost = objective(point)
                # Prefer the shortest relocation, then stable x/y ordering.
                candidate_key = (candidate_cost,
                                 abs(point[0] - current[0]) + abs(point[1] - current[1]), point)
                best_key = (best_cost,
                            abs(best_point[0] - current[0]) + abs(best_point[1] - current[1]), best_point)
                if candidate_key < best_key:
                    best_point, best_cost = point, candidate_cost
            if old_cost - best_cost <= 0 or old_cost - best_cost < minimum_gain:
                continue
            del lattice.occupied[current]
            lattice.occupied[best_point] = name
            dx, dy = best_point[0] - current[0], best_point[1] - current[1]
            hbt["x"], hbt["y"] = best_point
            for pin in pin_refs[name]:
                pin["x"] += dx
                pin["y"] += dy
            stats["accepted_moves"] += 1
            changed = True
        stats["passes_completed"] += 1
        if not changed or stats["accepted_moves"] >= values["max_moves"]:
            break
    relocations = []
    for name in sorted(by_name):
        hbt = by_name[name]
        if (hbt["x"], hbt["y"]) != before[name]:
            relocations.append({"name": name, "x": hbt["x"], "y": hbt["y"],
                                "origin_x": hbt["x"] - lattice.size[0] // 2,
                                "origin_y": hbt["y"] - lattice.size[1] // 2,
                                "before_x": before[name][0], "before_y": before[name][1]})
    final_total = sum(_hpwl(nets[i]["pins"]) for i in affected)
    if final_total > initial_total:
        raise RuntimeError("HBT relocation unexpectedly increased total net HPWL")
    stats.update({"moved_hbts": len(relocations),
                  "before_hpwl_um": initial_total / dbu,
                  "after_hpwl_um": final_total / dbu,
                  "saved_hpwl_um": (initial_total - final_total) / dbu})
    return result, relocations, stats
