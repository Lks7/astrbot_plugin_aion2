from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

from .db import Database
from .models import Character, Resources


RESOURCE_FIELDS = {
    "stamina",
    "nightmare_tix",
    "subjugation_tix",
    "awaken_tix",
    "transcend_count",
    "expedition_count",
    "challenge_count",
    "kinah",
}

STAMINA_REGEN_INTERVAL_SECONDS = 3 * 60 * 60
STAMINA_REGEN_AMOUNT = 15
NIGHTMARE_DAILY_RESET_VALUE = 2
WEEKLY_RESET_VALUE = 3
DAILY_REFILL_VALUE = 2
DAILY_REFILL_CAP = 21
WEEKLY_CHALLENGE_CAP = 28
ENERGY_COST_PER_DUNGEON = 80
RESET_TIMEZONE = timezone(timedelta(hours=8))


class AionTrackerService:
    def __init__(
        self, db_path: str | Path = "aion_tracker.db", stamina_cap: int | None = None
    ) -> None:
        self.db = Database(db_path)
        self.db.init_schema()
        self.stamina_cap = stamina_cap

    def close(self) -> None:
        self.db.close()

    def add_character(
        self,
        user_id: str,
        char_name: str,
        char_class: str,
        level: int = 1,
        power: int = 0,
    ) -> Character:
        self.db.execute(
            """
            INSERT INTO characters(user_id, char_name, class, level, power)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(user_id, char_name) DO UPDATE SET
                class = excluded.class,
                level = excluded.level,
                power = excluded.power
            """,
            (user_id, char_name, char_class, level, power),
        )
        self.db.execute(
            """
            INSERT INTO resources(user_id, char_name)
            VALUES(?, ?)
            ON CONFLICT(user_id, char_name) DO NOTHING
            """,
            (user_id, char_name),
        )
        return Character(
            user_id=user_id,
            char_name=char_name,
            char_class=char_class,
            level=level,
            power=power,
        )

    def list_characters(self, user_id: str) -> list[Character]:
        rows = self.db.query_all(
            "SELECT user_id, char_name, class, level, power FROM characters WHERE user_id = ? ORDER BY char_name",
            (user_id,),
        )
        return [
            Character(
                user_id=row["user_id"],
                char_name=row["char_name"],
                char_class=row["class"],
                level=row["level"],
                power=row["power"],
            )
            for row in rows
        ]

    def remove_character(self, user_id: str, char_name: str) -> bool:
        cur = self.db.execute(
            "DELETE FROM characters WHERE user_id = ? AND char_name = ?",
            (user_id, char_name),
        )
        removed = cur.rowcount > 0
        if removed:
            active = self.get_active_character_name(user_id)
            if active == char_name:
                self.db.execute(
                    "UPDATE user_state SET active_char_name = NULL WHERE user_id = ?",
                    (user_id,),
                )
        return removed

    def set_active_character(self, user_id: str, char_name: str) -> bool:
        row = self.db.query_one(
            "SELECT 1 FROM characters WHERE user_id = ? AND char_name = ?",
            (user_id, char_name),
        )
        if row is None:
            return False
        self.db.execute(
            """
            INSERT INTO user_state(user_id, active_char_name)
            VALUES(?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                active_char_name = excluded.active_char_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, char_name),
        )
        return True

    def get_active_character_name(self, user_id: str) -> str | None:
        row = self.db.query_one(
            "SELECT active_char_name FROM user_state WHERE user_id = ?",
            (user_id,),
        )
        return None if row is None else row["active_char_name"]

    def set_mode(self, user_id: str, mode: str) -> None:
        current_active = self.get_active_character_name(user_id)
        self.db.execute(
            """
            INSERT INTO user_state(user_id, active_char_name, mode)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                active_char_name = COALESCE(user_state.active_char_name, excluded.active_char_name),
                mode = excluded.mode,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, current_active, mode),
        )

    def get_mode(self, user_id: str) -> str:
        row = self.db.query_one(
            "SELECT mode FROM user_state WHERE user_id = ?",
            (user_id,),
        )
        return "" if row is None else str(row["mode"] or "")

    def get_resources(self, user_id: str, char_name: str) -> Resources | None:
        self._refresh_ticket_resets(user_id, char_name)
        self._refresh_daily_transcend_expedition(user_id, char_name)
        self._refresh_stamina(user_id, char_name)
        row = self.db.query_one(
            """
            SELECT user_id, char_name, stamina, stamina_updated_at, nightmare_tix, subjugation_tix, awaken_tix,
                   nightmare_reset_at, weekly_reset_at,
                   transcend_count, transcend_updated_at,
                   expedition_count, expedition_updated_at,
                   challenge_count, kinah, materials
            FROM resources WHERE user_id = ? AND char_name = ?
            """,
            (user_id, char_name),
        )
        if row is None:
            return None
        return Resources(
            char_name=row["char_name"],
            stamina=row["stamina"],
            stamina_updated_at=row["stamina_updated_at"],
            nightmare_tix=row["nightmare_tix"],
            nightmare_reset_at=row["nightmare_reset_at"],
            subjugation_tix=row["subjugation_tix"],
            awaken_tix=row["awaken_tix"],
            weekly_reset_at=row["weekly_reset_at"],
            transcend_count=row["transcend_count"],
            transcend_updated_at=row["transcend_updated_at"],
            expedition_count=row["expedition_count"],
            expedition_updated_at=row["expedition_updated_at"],
            challenge_count=row["challenge_count"],
            kinah=row["kinah"],
            materials=self.db.parse_materials(row["materials"]),
        )

    def update_resources_full(
        self,
        user_id: str,
        char_name: str,
        stamina: int,
        nightmare_tix: int,
        subjugation_tix: int,
        awaken_tix: int,
        transcend_count: int,
        expedition_count: int,
        challenge_count: int,
        kinah: int,
        materials: Dict[str, int] | None = None,
    ) -> bool:
        if not self._character_exists(user_id, char_name):
            return False
        payload = {
            "stamina": stamina,
            "nightmare_tix": nightmare_tix,
            "subjugation_tix": subjugation_tix,
            "awaken_tix": awaken_tix,
            "transcend_count": transcend_count,
            "expedition_count": expedition_count,
            "challenge_count": challenge_count,
            "kinah": kinah,
            "materials": materials or {},
        }
        self.db.execute(
            """
            UPDATE resources
            SET stamina = ?,
                stamina_updated_at = CURRENT_TIMESTAMP,
                nightmare_tix = ?,
                nightmare_reset_at = CURRENT_TIMESTAMP,
                subjugation_tix = ?,
                awaken_tix = ?,
                weekly_reset_at = CURRENT_TIMESTAMP,
                transcend_count = ?,
                transcend_updated_at = CURRENT_TIMESTAMP,
                expedition_count = ?,
                expedition_updated_at = CURRENT_TIMESTAMP,
                challenge_count = ?,
                kinah = ?,
                materials = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND char_name = ?
            """,
            (
                payload["stamina"],
                payload["nightmare_tix"],
                payload["subjugation_tix"],
                payload["awaken_tix"],
                payload["transcend_count"],
                payload["expedition_count"],
                payload["challenge_count"],
                payload["kinah"],
                self.db.dump_materials(payload["materials"]),
                user_id,
                char_name,
            ),
        )
        return True

    def update_resource_delta(
        self, user_id: str, char_name: str, resource_name: str, delta: int
    ) -> bool:
        if resource_name not in RESOURCE_FIELDS:
            return False
        if not self._character_exists(user_id, char_name):
            return False
        if resource_name in {"nightmare_tix", "subjugation_tix", "awaken_tix"}:
            self._refresh_ticket_resets(user_id, char_name)
        if resource_name in {"transcend_count", "expedition_count"}:
            self._refresh_daily_transcend_expedition(user_id, char_name)
        if resource_name == "challenge_count":
            self._refresh_ticket_resets(user_id, char_name)
        if resource_name == "stamina":
            self._refresh_stamina(user_id, char_name)
            self.db.execute(
                """
                UPDATE resources
                SET stamina = MAX(stamina + ?, 0),
                    stamina_updated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND char_name = ?
                """,
                (delta, user_id, char_name),
            )
            return True
        if resource_name in {"transcend_count", "expedition_count"}:
            self.db.execute(
                f"""
                UPDATE resources
                SET {resource_name} = MIN(MAX({resource_name} + ?, 0), ?),
                    {resource_name.replace("_count", "_updated_at")} = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND char_name = ?
                """,
                (delta, DAILY_REFILL_CAP, user_id, char_name),
            )
            return True
        if resource_name == "challenge_count":
            self.db.execute(
                """
                UPDATE resources
                SET challenge_count = MIN(MAX(challenge_count + ?, 0), ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND char_name = ?
                """,
                (delta, WEEKLY_CHALLENGE_CAP, user_id, char_name),
            )
            return True
        self.db.execute(
            f"""
            UPDATE resources
            SET {resource_name} = MAX({resource_name} + ?, 0),
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND char_name = ?
            """,
            (delta, user_id, char_name),
        )
        return True

    def update_material_delta(
        self, user_id: str, char_name: str, material_name: str, delta: int
    ) -> bool:
        res = self.get_resources(user_id, char_name)
        if res is None:
            return False
        value = max(res.materials.get(material_name, 0) + delta, 0)
        if value == 0 and material_name in res.materials:
            del res.materials[material_name]
        else:
            res.materials[material_name] = value
        self.db.execute(
            """
            UPDATE resources
            SET materials = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND char_name = ?
            """,
            (self.db.dump_materials(res.materials), user_id, char_name),
        )
        return True

    def consume_dungeon_runs(
        self,
        user_id: str,
        char_name: str,
        expedition_runs: int = 0,
        transcend_runs: int = 0,
    ) -> tuple[bool, str]:
        if expedition_runs < 0 or transcend_runs < 0:
            return False, "次数不能为负数。"
        total_runs = expedition_runs + transcend_runs
        if total_runs == 0:
            return False, "请至少提供一次远征或超越次数。"
        if not self._character_exists(user_id, char_name):
            return False, f"未找到角色: {char_name}"

        res = self.get_resources(user_id, char_name)
        if res is None:
            return False, "角色资源不存在。"
        if res.expedition_count < expedition_runs:
            return (
                False,
                f"远征次数不足，当前 {res.expedition_count}，需要 {expedition_runs}。",
            )
        if res.transcend_count < transcend_runs:
            return (
                False,
                f"超越次数不足，当前 {res.transcend_count}，需要 {transcend_runs}。",
            )
        if res.challenge_count < total_runs:
            return (
                False,
                f"挑战次数不足，当前 {res.challenge_count}，需要 {total_runs}。",
            )

        energy_cost = total_runs * ENERGY_COST_PER_DUNGEON
        if res.stamina < energy_cost:
            return False, f"体力不足，当前 {res.stamina}，需要 {energy_cost}。"

        self.db.execute(
            """
            UPDATE resources
            SET stamina = stamina - ?,
                stamina_updated_at = CURRENT_TIMESTAMP,
                expedition_count = expedition_count - ?,
                expedition_updated_at = CURRENT_TIMESTAMP,
                transcend_count = transcend_count - ?,
                transcend_updated_at = CURRENT_TIMESTAMP,
                challenge_count = challenge_count - ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND char_name = ?
            """,
            (
                energy_cost,
                expedition_runs,
                transcend_runs,
                total_runs,
                user_id,
                char_name,
            ),
        )
        return (
            True,
            f"已记录 {char_name}: 远征{expedition_runs}次, 超越{transcend_runs}次, 扣除体力 {energy_cost}。",
        )

    def render_status(self, user_id: str, char_name: str) -> str:
        char_row = self.db.query_one(
            "SELECT char_name, class, level, power FROM characters WHERE user_id = ? AND char_name = ?",
            (user_id, char_name),
        )
        if char_row is None:
            return "未找到该角色。"
        resources = self.get_resources(user_id, char_name)
        if resources is None:
            return "角色存在，但资源数据缺失。"

        materials_text = (
            "、".join(f"{k}:{v}" for k, v in sorted(resources.materials.items()))
            or "无"
        )
        next_tick_text = self._next_stamina_tick_text(user_id, char_name)
        return (
            f"角色: {char_row['char_name']} ({char_row['class']}) 战力:{char_row['power']}\n"
            f"体力: {resources.stamina} (每3小时+15，{next_tick_text})\n"
            f"噩梦券: {resources.nightmare_tix}\n"
            f"讨伐券: {resources.subjugation_tix}\n"
            f"觉醒券: {resources.awaken_tix}\n"
            f"超越次数: {resources.transcend_count}\n"
            f"远征次数: {resources.expedition_count}\n"
            f"挑战次数: {resources.challenge_count}\n"
            f"基纳: {resources.kinah}\n"
            f"材料: {materials_text}"
        )

    def render_all(self, user_id: str) -> str:
        chars = self.list_characters(user_id)
        if not chars:
            return "你还没有绑定任何角色。"

        lines = ["角色总览:"]
        active = self.get_active_character_name(user_id)
        for char in chars:
            res = self.get_resources(user_id, char.char_name)
            if res is None:
                continue
            marker = "*" if active == char.char_name else " "
            lines.append(
                f"{marker}名字:{char.char_name:<8} 职业:{char.char_class:<6} 战力:{char.power:<6} "
                f"体力:{res.stamina:<4} 噩梦:{res.nightmare_tix:<3} 觉醒:{res.awaken_tix:<3} 讨伐:{res.subjugation_tix:<3} "
                f"超越:{res.transcend_count:<3} 远征:{res.expedition_count:<3} 挑战:{res.challenge_count:<3} 基纳:{res.kinah}"
            )
        lines.append("注: * 表示当前激活角色")
        return "\n".join(lines)

    def render_all_key_resources(self, user_id: str) -> str:
        chars = self.list_characters(user_id)
        if not chars:
            return "你还没有绑定任何角色。"

        active = self.get_active_character_name(user_id)
        lines = ["全角色核心资源:"]
        for char in chars:
            res = self.get_resources(user_id, char.char_name)
            if res is None:
                continue
            marker = "*" if active == char.char_name else " "
            lines.append(
                f"{marker} {char.char_name:<10} 基纳:{res.kinah:<10} 体力:{res.stamina:<4} 噩梦:{res.nightmare_tix:<3} "
                f"觉醒:{res.awaken_tix:<3} 讨伐:{res.subjugation_tix:<3} 超越:{res.transcend_count:<3} 远征:{res.expedition_count:<3} 挑战:{res.challenge_count:<3}"
            )
        lines.append("注: * 表示当前激活角色")
        return "\n".join(lines)

    def build_plan_payload(self, user_id: str) -> dict:
        payload = {
            "user_id": user_id,
            "active_character": self.get_active_character_name(user_id),
            "characters": [],
        }
        for char in self.list_characters(user_id):
            res = self.get_resources(user_id, char.char_name)
            if res is None:
                continue
            payload["characters"].append(
                {
                    "char_name": char.char_name,
                    "class": char.char_class,
                    "level": char.level,
                    **asdict(res),
                }
            )
        return payload

    def _character_exists(self, user_id: str, char_name: str) -> bool:
        row = self.db.query_one(
            "SELECT 1 FROM characters WHERE user_id = ? AND char_name = ?",
            (user_id, char_name),
        )
        return row is not None

    def _refresh_stamina(self, user_id: str, char_name: str) -> None:
        row = self.db.query_one(
            "SELECT stamina, stamina_updated_at FROM resources WHERE user_id = ? AND char_name = ?",
            (user_id, char_name),
        )
        if row is None:
            return

        now = datetime.utcnow()
        last = self._parse_timestamp(row["stamina_updated_at"]) or now
        elapsed_seconds = int((now - last).total_seconds())
        if elapsed_seconds < STAMINA_REGEN_INTERVAL_SECONDS:
            return

        ticks = elapsed_seconds // STAMINA_REGEN_INTERVAL_SECONDS
        gain = ticks * STAMINA_REGEN_AMOUNT
        new_stamina = int(row["stamina"]) + gain
        if self.stamina_cap is not None:
            new_stamina = min(new_stamina, self.stamina_cap)

        advanced_at = last + timedelta(seconds=ticks * STAMINA_REGEN_INTERVAL_SECONDS)
        self.db.execute(
            """
            UPDATE resources
            SET stamina = ?, stamina_updated_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND char_name = ?
            """,
            (
                new_stamina,
                advanced_at.strftime("%Y-%m-%d %H:%M:%S"),
                user_id,
                char_name,
            ),
        )

    def _refresh_ticket_resets(self, user_id: str, char_name: str) -> None:
        row = self.db.query_one(
            """
            SELECT nightmare_tix, nightmare_reset_at, subjugation_tix, awaken_tix, weekly_reset_at, challenge_count
            FROM resources
            WHERE user_id = ? AND char_name = ?
            """,
            (user_id, char_name),
        )
        if row is None:
            return

        now_utc = datetime.utcnow()
        changed = False
        nightmare_tix = int(row["nightmare_tix"])
        subjugation_tix = int(row["subjugation_tix"])
        awaken_tix = int(row["awaken_tix"])
        challenge_count = int(row["challenge_count"])
        nightmare_reset_at = row["nightmare_reset_at"]
        weekly_reset_at = row["weekly_reset_at"]

        nightmare_last = self._parse_timestamp(nightmare_reset_at) or now_utc
        if self._is_new_local_day(nightmare_last, now_utc):
            nightmare_tix = NIGHTMARE_DAILY_RESET_VALUE
            nightmare_reset_at = now_utc.strftime("%Y-%m-%d %H:%M:%S")
            changed = True

        weekly_last = self._parse_timestamp(weekly_reset_at) or now_utc
        if self._crossed_wednesday_reset(weekly_last, now_utc):
            subjugation_tix = WEEKLY_RESET_VALUE
            awaken_tix = WEEKLY_RESET_VALUE
            challenge_count = WEEKLY_CHALLENGE_CAP
            weekly_reset_at = now_utc.strftime("%Y-%m-%d %H:%M:%S")
            changed = True

        if changed:
            self.db.execute(
                """
                UPDATE resources
                SET nightmare_tix = ?,
                    nightmare_reset_at = ?,
                    subjugation_tix = ?,
                    awaken_tix = ?,
                    challenge_count = ?,
                    weekly_reset_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND char_name = ?
                """,
                (
                    nightmare_tix,
                    nightmare_reset_at,
                    subjugation_tix,
                    awaken_tix,
                    challenge_count,
                    weekly_reset_at,
                    user_id,
                    char_name,
                ),
            )

    def _refresh_daily_transcend_expedition(self, user_id: str, char_name: str) -> None:
        row = self.db.query_one(
            """
            SELECT transcend_count, transcend_updated_at, expedition_count, expedition_updated_at
            FROM resources
            WHERE user_id = ? AND char_name = ?
            """,
            (user_id, char_name),
        )
        if row is None:
            return

        now_utc = datetime.utcnow()
        changed = False
        transcend_count = int(row["transcend_count"])
        expedition_count = int(row["expedition_count"])
        transcend_updated_at = row["transcend_updated_at"]
        expedition_updated_at = row["expedition_updated_at"]

        transcend_last = self._parse_timestamp(transcend_updated_at) or now_utc
        expedition_last = self._parse_timestamp(expedition_updated_at) or now_utc
        transcend_days = self._elapsed_local_days(transcend_last, now_utc)
        expedition_days = self._elapsed_local_days(expedition_last, now_utc)

        if transcend_days > 0:
            transcend_count = min(
                DAILY_REFILL_CAP, transcend_count + DAILY_REFILL_VALUE * transcend_days
            )
            transcend_updated_at = now_utc.strftime("%Y-%m-%d %H:%M:%S")
            changed = True
        if expedition_days > 0:
            expedition_count = min(
                DAILY_REFILL_CAP,
                expedition_count + DAILY_REFILL_VALUE * expedition_days,
            )
            expedition_updated_at = now_utc.strftime("%Y-%m-%d %H:%M:%S")
            changed = True

        if changed:
            self.db.execute(
                """
                UPDATE resources
                SET transcend_count = ?,
                    transcend_updated_at = ?,
                    expedition_count = ?,
                    expedition_updated_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND char_name = ?
                """,
                (
                    transcend_count,
                    transcend_updated_at,
                    expedition_count,
                    expedition_updated_at,
                    user_id,
                    char_name,
                ),
            )

    def _next_stamina_tick_text(self, user_id: str, char_name: str) -> str:
        row = self.db.query_one(
            "SELECT stamina_updated_at FROM resources WHERE user_id = ? AND char_name = ?",
            (user_id, char_name),
        )
        if row is None:
            return "下次恢复时间未知"
        last = self._parse_timestamp(row["stamina_updated_at"])
        if last is None:
            return "下次恢复时间未知"
        now = datetime.utcnow()
        elapsed = int((now - last).total_seconds())
        remaining = STAMINA_REGEN_INTERVAL_SECONDS - (
            elapsed % STAMINA_REGEN_INTERVAL_SECONDS
        )
        if remaining == STAMINA_REGEN_INTERVAL_SECONDS:
            remaining = 0
        hours, rem = divmod(remaining, 3600)
        minutes = rem // 60
        return f"下次恢复 {hours}小时{minutes}分钟后"

    @staticmethod
    def _parse_timestamp(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @staticmethod
    def _is_new_local_day(previous_utc: datetime, now_utc: datetime) -> bool:
        prev_local = previous_utc.replace(tzinfo=timezone.utc).astimezone(
            RESET_TIMEZONE
        )
        now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(RESET_TIMEZONE)
        return now_local.date() > prev_local.date()

    @staticmethod
    def _crossed_wednesday_reset(previous_utc: datetime, now_utc: datetime) -> bool:
        previous_local = previous_utc.replace(tzinfo=timezone.utc).astimezone(
            RESET_TIMEZONE
        )
        now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(RESET_TIMEZONE)
        if now_local <= previous_local:
            return False
        cursor = previous_local.date() + timedelta(days=1)
        while cursor <= now_local.date():
            if cursor.weekday() == 2:
                return True
            cursor += timedelta(days=1)
        return False

    @staticmethod
    def _elapsed_local_days(previous_utc: datetime, now_utc: datetime) -> int:
        previous_local = previous_utc.replace(tzinfo=timezone.utc).astimezone(
            RESET_TIMEZONE
        )
        now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(RESET_TIMEZONE)
        return max((now_local.date() - previous_local.date()).days, 0)
