"""Exact candidate queries for guide checks; no connectivity rules live here."""

from __future__ import annotations

import re
from collections import defaultdict


INDEX_THRESHOLD = 64
_METAL_RE = re.compile(r"^metal(\d+)$", re.I)
_LEAF_SIZE = 12


class _RectIndex:
    """Static bounding-box hierarchy over original rectangle indices.

    Every node bounds all its members, so pruning cannot discard an actual
    intersection. Degenerate or densely overlapping inputs may still require
    quadratic work, but never switch to an approximate connectivity decision.
    """

    def __init__(self, rects, indices):
        self.rects = rects
        self.root = self._build(list(indices))

    def _build(self, indices):
        rects = self.rects
        bounds = (min(rects[i].x1 for i in indices),
                  min(rects[i].y1 for i in indices),
                  max(rects[i].x2 for i in indices),
                  max(rects[i].y2 for i in indices))
        if len(indices) <= _LEAF_SIZE:
            return bounds, None, None, indices
        # Split by center spread, rather than rectangle width: many parallel
        # long guides have identical X extents but are separated along Y.
        xcenters = [rects[i].x1 + rects[i].x2 for i in indices]
        ycenters = [rects[i].y1 + rects[i].y2 for i in indices]
        if max(xcenters) - min(xcenters) >= max(ycenters) - min(ycenters):
            indices.sort(key=lambda i: (rects[i].x1 + rects[i].x2, i))
        else:
            indices.sort(key=lambda i: (rects[i].y1 + rects[i].y2, i))
        middle = len(indices) // 2
        return bounds, self._build(indices[:middle]), self._build(indices[middle:]), None

    def intersections(self, x1, y1, x2, y2):
        stack = [self.root]
        rects = self.rects
        while stack:
            bounds, left, right, indices = stack.pop()
            if bounds[2] < x1 or x2 < bounds[0] or bounds[3] < y1 or y2 < bounds[1]:
                continue
            if indices is None:
                stack.append(right)
                stack.append(left)
                continue
            for i in indices:
                rect = rects[i]
                if not (rect.x2 < x1 or x2 < rect.x1 or rect.y2 < y1 or y2 < rect.y1):
                    yield i


class GuideSpatialIndex:
    """Reuse exact spatial queries for pin coverage and component discovery."""

    def __init__(self, rects):
        self.rects = rects
        self._all = None
        self._groups = None
        self._layers = {}

    @staticmethod
    def _layer_key(layer):
        match = _METAL_RE.match(layer)
        return ("metal", int(match.group(1))) if match else ("raw", layer)

    def first_covering_rect(self, x, y, margin):
        if not self.rects:
            return None
        if self._all is None:
            self._all = _RectIndex(self.rects, range(len(self.rects)))
        # Original file order decides which component a covered pin belongs
        # to; traversal order of the hierarchy must not affect that choice.
        return min(self._all.intersections(x - margin, y - margin,
                                           x + margin, y + margin), default=None)

    def later_neighbors(self, i):
        if self._groups is None:
            self._groups = defaultdict(list)
            for j, rect in enumerate(self.rects):
                self._groups[self._layer_key(rect.layer)].append(j)
        rect = self.rects[i]
        key = self._layer_key(rect.layer)
        keys = [key]
        if key[0] == "metal":
            keys.extend((("metal", key[1] - 1), ("metal", key[1] + 1)))
        candidates = []
        for layer_key in keys:
            indices = self._groups.get(layer_key)
            if not indices:
                continue
            if layer_key not in self._layers:
                self._layers[layer_key] = _RectIndex(self.rects, indices)
            # One DBU is a conservative broad-phase tolerance. The caller
            # still checks the exact same/adjacent-layer rule for every pair.
            candidates.extend(j for j in self._layers[layer_key].intersections(
                rect.x1 - 1, rect.y1 - 1, rect.x2 + 1, rect.y2 + 1) if j > i)
        # Preserve the old nested-loop union order and component root IDs.
        return sorted(candidates)
