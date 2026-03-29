"""OPCODE 문자열 파싱·정규화 (문서에 0x 16진 또는 10진 표기 혼재 가능)."""

from __future__ import annotations

import re
from typing import Optional, Tuple

_HEX_PREFIX = re.compile(r"^\s*0[xX]")


def parse_opcode_token(raw: str) -> Tuple[Optional[int], str]:
    """
    Returns (opcode_value, opcode_radix) where opcode_radix is 'hex'|'dec'|'unknown'.

    규칙(스켈레톤):
    - `0x` / `0X` 접두 → 16진
    - 그 외 숫자만 → 10진으로 시도
    - 실패 시 (None, 'unknown')
    """
    if raw is None:
        return None, "unknown"
    s = raw.strip()
    if not s or s.upper() == "UNKNOWN":
        return None, "unknown"
    if _HEX_PREFIX.match(s):
        try:
            return int(s, 16), "hex"
        except ValueError:
            return None, "unknown"
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        try:
            return int(s, 10), "dec"
        except ValueError:
            return None, "unknown"
    return None, "unknown"
