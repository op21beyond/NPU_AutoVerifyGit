"""Merge PyMuPDF find_tables() bboxes: overlap, vertical adjacency, optional horizontal adjacency."""

from __future__ import annotations

from collections import defaultdict
from typing import List, Tuple

BBox = Tuple[float, float, float, float]


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def _union_bbox(boxes: List[BBox]) -> BBox:
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


def _intersection_area(a: BBox, b: BBox) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return float((ix1 - ix0) * (iy1 - iy0))


def _merge_overlap(a: BBox, b: BBox) -> bool:
    if _intersection_area(a, b) > 0:
        return True
    cx_a, cy_a = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    cx_b, cy_b = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    if b[0] <= cx_a <= b[2] and b[1] <= cy_a <= b[3]:
        return True
    if a[0] <= cx_b <= a[2] and a[1] <= cy_b <= a[3]:
        return True
    return False


def _width_overlap_ratio(a: BBox, b: BBox) -> float:
    ax0, ax1 = a[0], a[2]
    bx0, bx1 = b[0], b[2]
    ix0, ix1 = max(ax0, bx0), min(ax1, bx1)
    if ix1 <= ix0:
        return 0.0
    inter = ix1 - ix0
    w1 = max(0.0, ax1 - ax0)
    w2 = max(0.0, bx1 - bx0)
    m = min(w1, w2)
    return inter / m if m > 0 else 0.0


def _height_overlap_ratio(a: BBox, b: BBox) -> float:
    ay0, ay1 = a[1], a[3]
    by0, by1 = b[1], b[3]
    iy0, iy1 = max(ay0, by0), min(ay1, by1)
    if iy1 <= iy0:
        return 0.0
    inter = iy1 - iy0
    h1 = max(0.0, ay1 - ay0)
    h2 = max(0.0, by1 - by0)
    m = min(h1, h2)
    return inter / m if m > 0 else 0.0


def _merge_vertical_adjacent(a: BBox, b: BBox, gap_px: float, min_w_ratio: float) -> bool:
    for upper, lower in ((a, b), (b, a)):
        if upper[3] <= lower[1]:
            gap = lower[1] - upper[3]
            if gap <= gap_px and _width_overlap_ratio(upper, lower) >= min_w_ratio:
                return True
    return False


def _merge_horizontal_adjacent(a: BBox, b: BBox, gap_px: float, min_h_ratio: float) -> bool:
    for left, right in ((a, b), (b, a)):
        if left[2] <= right[0]:
            gap = right[0] - left[2]
            if gap <= gap_px and _height_overlap_ratio(left, right) >= min_h_ratio:
                return True
    return False


def _should_merge_pair(
    a: BBox,
    b: BBox,
    *,
    gap_px: float,
    vertical_min_width_overlap: float,
    horizontal_min_height_overlap: float,
    horizontal_merge: bool,
) -> bool:
    if _merge_overlap(a, b):
        return True
    if _merge_vertical_adjacent(a, b, gap_px, vertical_min_width_overlap):
        return True
    if horizontal_merge and _merge_horizontal_adjacent(a, b, gap_px, horizontal_min_height_overlap):
        return True
    return False


def merge_table_bboxes(
    bboxes: List[BBox],
    *,
    gap_px: float = 5.0,
    vertical_min_width_overlap: float = 0.5,
    horizontal_min_height_overlap: float = 0.5,
    horizontal_merge: bool = False,
) -> Tuple[List[BBox], List[List[int]]]:
    """
    Cluster table bboxes by overlap (required), vertical adjacency, and optional horizontal adjacency.
    Returns merged bbox per cluster and original index groups (sorted for stable ordering).
    """
    n = len(bboxes)
    if n == 0:
        return [], []
    if n == 1:
        return [bboxes[0]], [[0]]

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _should_merge_pair(
                bboxes[i],
                bboxes[j],
                gap_px=gap_px,
                vertical_min_width_overlap=vertical_min_width_overlap,
                horizontal_min_height_overlap=horizontal_min_height_overlap,
                horizontal_merge=horizontal_merge,
            ):
                uf.union(i, j)

    buckets: defaultdict[int, List[int]] = defaultdict(list)
    for i in range(n):
        buckets[uf.find(i)].append(i)

    groups: List[Tuple[BBox, List[int]]] = []
    for _root, idxs in buckets.items():
        idxs_sorted = sorted(idxs)
        ub = _union_bbox([bboxes[i] for i in idxs_sorted])
        groups.append((ub, idxs_sorted))

    groups.sort(key=lambda g: (g[0][1], g[0][0]))
    merged = [g[0] for g in groups]
    indices = [g[1] for g in groups]
    return merged, indices


def expand_bbox_to_page_width(
    bbox: BBox,
    page_width: float,
    margin_left: float,
    margin_right: float,
) -> BBox:
    """Keep y0/y1; set x to [margin_left, page_width - margin_right]."""
    x0 = float(margin_left)
    x1 = float(page_width) - float(margin_right)
    if x1 <= x0:
        return bbox
    y0, y1 = bbox[1], bbox[3]
    return (x0, y0, x1, y1)
