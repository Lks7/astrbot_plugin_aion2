from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class Database:
    def __init__(self, db_path: str | Path = "aion_tracker.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(sql, tuple(params))
        self._conn.commit()
        return cur

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        cur = self._conn.execute(sql, tuple(params))
        return cur.fetchone()

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        cur = self._conn.execute(sql, tuple(params))
        return cur.fetchall()

    def init_schema(self) -> None:
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                user_id TEXT NOT NULL,
                char_name TEXT NOT NULL,
                class TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, char_name)
            )
            """
        )
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
                user_id TEXT NOT NULL,
                char_name TEXT NOT NULL,
                stamina INTEGER NOT NULL DEFAULT 0,
                stamina_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                nightmare_tix INTEGER NOT NULL DEFAULT 0,
                nightmare_reset_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                subjugation_tix INTEGER NOT NULL DEFAULT 0,
                awaken_tix INTEGER NOT NULL DEFAULT 0,
                weekly_reset_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                transcend_count INTEGER NOT NULL DEFAULT 0,
                transcend_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expedition_count INTEGER NOT NULL DEFAULT 0,
                expedition_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                challenge_count INTEGER NOT NULL DEFAULT 28,
                kinah INTEGER NOT NULL DEFAULT 0,
                materials TEXT NOT NULL DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, char_name),
                FOREIGN KEY (user_id, char_name)
                    REFERENCES characters(user_id, char_name)
                    ON DELETE CASCADE
            )
            """
        )
        self._migrate_resources_table()
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS user_state (
                user_id TEXT PRIMARY KEY,
                active_char_name TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _migrate_resources_table(self) -> None:
        cols = self.query_all("PRAGMA table_info(resources)")
        col_names = {row["name"] for row in cols}
        if "stamina_updated_at" not in col_names:
            self.execute(
                "ALTER TABLE resources ADD COLUMN stamina_updated_at TIMESTAMP"
            )
            self.execute(
                """
                UPDATE resources
                SET stamina_updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                WHERE stamina_updated_at IS NULL
                """
            )
        if "nightmare_reset_at" not in col_names:
            self.execute(
                "ALTER TABLE resources ADD COLUMN nightmare_reset_at TIMESTAMP"
            )
            self.execute(
                """
                UPDATE resources
                SET nightmare_reset_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                WHERE nightmare_reset_at IS NULL
                """
            )
        if "weekly_reset_at" not in col_names:
            self.execute("ALTER TABLE resources ADD COLUMN weekly_reset_at TIMESTAMP")
            self.execute(
                """
                UPDATE resources
                SET weekly_reset_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                WHERE weekly_reset_at IS NULL
                """
            )
        if "transcend_count" not in col_names:
            self.execute(
                "ALTER TABLE resources ADD COLUMN transcend_count INTEGER NOT NULL DEFAULT 0"
            )
        if "transcend_updated_at" not in col_names:
            self.execute(
                "ALTER TABLE resources ADD COLUMN transcend_updated_at TIMESTAMP"
            )
            self.execute(
                """
                UPDATE resources
                SET transcend_updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                WHERE transcend_updated_at IS NULL
                """
            )
        if "expedition_count" not in col_names:
            self.execute(
                "ALTER TABLE resources ADD COLUMN expedition_count INTEGER NOT NULL DEFAULT 0"
            )
        if "expedition_updated_at" not in col_names:
            self.execute(
                "ALTER TABLE resources ADD COLUMN expedition_updated_at TIMESTAMP"
            )
            self.execute(
                """
                UPDATE resources
                SET expedition_updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                WHERE expedition_updated_at IS NULL
                """
            )
        if "challenge_count" not in col_names:
            self.execute(
                "ALTER TABLE resources ADD COLUMN challenge_count INTEGER NOT NULL DEFAULT 28"
            )

    @staticmethod
    def parse_materials(raw: str | None) -> Dict[str, int]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k): int(v) for k, v in data.items()}
        except (ValueError, TypeError):
            pass
        return {}

    @staticmethod
    def dump_materials(materials: Dict[str, int]) -> str:
        return json.dumps(materials, ensure_ascii=False, separators=(",", ":"))
