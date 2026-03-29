from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StageRun:
    stage_name: str
    stage_run_id: str
    started_at: str

    @classmethod
    def create(cls, stage_name: str) -> "StageRun":
        return cls(stage_name=stage_name, stage_run_id=f"{stage_name}-{uuid4().hex[:12]}", started_at=utc_now())

    def to_dict(self) -> Dict[str, str]:
        return {
            "stage_name": self.stage_name,
            "stage_run_id": self.stage_run_id,
            "started_at": self.started_at,
            "ended_at": utc_now(),
        }


def artifact_path(*parts: str) -> Path:
    return Path("artifacts").joinpath(*parts)
