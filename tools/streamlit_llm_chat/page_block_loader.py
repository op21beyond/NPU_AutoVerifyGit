"""Load page_blocks.jsonl and build selected_page_blocks from one text selection spec."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Set, Tuple


def load_jsonl_from_bytes(data: bytes) -> List[Dict[str, Any]]:
    text = data.decode("utf-8", errors="replace")
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def sort_key_row(r: Dict[str, Any]) -> Tuple[int, float, float]:
    p = int(r.get("page", 0) or 0)
    bbox = r.get("bbox") or [0, 0, 0, 0]
    if isinstance(bbox, list) and len(bbox) >= 4:
        return (p, float(bbox[1]), float(bbox[0]))
    return (p, 0.0, 0.0)


def rows_reading_order(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = list(rows)
    out.sort(key=sort_key_row)
    return out


def normalize_selector_token(raw: str) -> str:
    """
    영어/한글, 대소문자 무시. 공백 제거 후 토큰 하나로 정규화.
    - 페이지 1, 1페이지, page 1, 1 => p1
    - 숫자만 단일 페이지: 1 => p1
    - 숫자 범위 1-3 => p1-p3
    """
    t = raw.strip().lower()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"(?i)페이지(\d+)", r"p\1", t)
    t = re.sub(r"(?i)(\d+)페이지", r"p\1", t)
    t = re.sub(r"(?i)page(\d+)", r"p\1", t)
    t = re.sub(r"(?i)(\d+)page", r"p\1", t)
    if re.match(r"^\d+$", t):
        return f"p{int(t)}"
    m = re.match(r"^(\d+)-(\d+)$", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        return f"p{a}-p{b}"
    return t


def _add_block_if_text(out: Dict[str, str], row: Dict[str, Any]) -> None:
    bid = str(row.get("block_id") or "").strip()
    if not bid:
        return
    raw = (row.get("raw_text") or "").strip()
    if not raw:
        return
    out[bid] = raw


def parse_block_selection_spec(spec: str, rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    단일 문자열로 페이지·블록 선택 (쉼표로 여러 조각 합집합).

    예:
    - 페이지 1 / p1 / 1 → 해당 페이지의 모든 블록
    - p1_20 → 블록 id p1_b20 한 개
    - p1, p2 또는 p1-p2 → 페이지 범위 전체 블록
    - p1_10, p2_20 → 두 블록만
    - p1_10-p2_20 → 읽기 순서에서 p1_b10부터 p2_b20까지(양 끝 포함), 중간 페이지 전부 포함
    """
    if not (spec or "").strip():
        raise ValueError("페이지·블록 선택이 비어 있습니다.")

    ordered = rows_reading_order(rows)
    id_to_idx: Dict[str, int] = {}
    for i, r in enumerate(ordered):
        bid = str(r.get("block_id") or "").strip()
        if bid:
            id_to_idx[bid] = i

    out: Dict[str, str] = {}
    parts = re.split(r"\s*,\s*", spec.strip())
    for raw_part in parts:
        if not raw_part.strip():
            continue
        part = normalize_selector_token(raw_part)

        # 블록 구간 p1_10-p2_20 (읽기 순서, 양끝 포함, 중간 페이지 전체)
        m = re.match(r"^p(\d+)_(\d+)-p(\d+)_(\d+)$", part)
        if m:
            p1, b1, p2, b2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            id_a = f"p{p1}_b{b1}"
            id_b = f"p{p2}_b{b2}"
            i0 = id_to_idx.get(id_a)
            i1 = id_to_idx.get(id_b)
            if i0 is None:
                raise ValueError(f"문서에 블록이 없습니다: {id_a} (입력: {raw_part.strip()})")
            if i1 is None:
                raise ValueError(f"문서에 블록이 없습니다: {id_b} (입력: {raw_part.strip()})")
            if i0 > i1:
                i0, i1 = i1, i0
            for r in ordered[i0 : i1 + 1]:
                _add_block_if_text(out, r)
            continue

        # 페이지 구간 p1-p2
        m = re.match(r"^p(\d+)-p(\d+)$", part)
        if m:
            p1, p2 = int(m.group(1)), int(m.group(2))
            if p1 > p2:
                p1, p2 = p2, p1
            for r in ordered:
                pg = int(r.get("page", 0) or 0)
                if p1 <= pg <= p2:
                    _add_block_if_text(out, r)
            continue

        # 단일 블록 p1_20 → p1_b20
        m = re.match(r"^p(\d+)_(\d+)$", part)
        if m:
            bid = f"p{int(m.group(1))}_b{int(m.group(2))}"
            if bid not in id_to_idx:
                raise ValueError(f"문서에 블록이 없습니다: {bid} (입력: {raw_part.strip()})")
            _add_block_if_text(out, ordered[id_to_idx[bid]])
            continue

        # 단일 페이지 전체 p1
        m = re.match(r"^p(\d+)$", part)
        if m:
            pg = int(m.group(1))
            for r in ordered:
                if int(r.get("page", 0) or 0) == pg:
                    _add_block_if_text(out, r)
            continue

        raise ValueError(f"알 수 없는 선택 형식: {raw_part.strip()}")

    if not out:
        raise ValueError("선택 조건에 맞는 비어 있지 않은 raw_text 블록이 없습니다.")
    return out
