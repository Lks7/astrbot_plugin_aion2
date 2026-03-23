from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(slots=True)
class Character:
    user_id: str
    char_name: str
    char_class: str
    level: int = 1
    power: int = 0


@dataclass(slots=True)
class Resources:
    char_name: str
    stamina: int = 0
    stamina_updated_at: str | None = None
    nightmare_tix: int = 0
    nightmare_reset_at: str | None = None
    subjugation_tix: int = 0
    awaken_tix: int = 0
    weekly_reset_at: str | None = None
    transcend_count: int = 0
    transcend_updated_at: str | None = None
    expedition_count: int = 0
    expedition_updated_at: str | None = None
    challenge_count: int = 28
    kinah: int = 0
    materials: Dict[str, int] = field(default_factory=dict)
