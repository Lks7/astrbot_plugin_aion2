from __future__ import annotations

import re
from pathlib import Path

from .service import AionTrackerService


RESOURCE_ALIASES = {
    "体力": "stamina",
    "能量": "stamina",
    "噩梦": "nightmare_tix",
    "噩梦券": "nightmare_tix",
    "讨伐": "subjugation_tix",
    "讨伐券": "subjugation_tix",
    "觉醒": "awaken_tix",
    "觉醒券": "awaken_tix",
    "超越": "transcend_count",
    "超越次数": "transcend_count",
    "远征": "expedition_count",
    "远征次数": "expedition_count",
    "挑战": "challenge_count",
    "挑战次数": "challenge_count",
    "基纳": "kinah",
}

RESOURCE_TOKEN_PATTERN = re.compile(
    r"(体力|能量|噩梦券|噩梦|讨伐券|讨伐|觉醒券|觉醒|超越次数|超越|远征次数|远征|挑战次数|挑战|基纳)\s*([:+\-=：]|加|减)?\s*(\d+)",
    re.IGNORECASE,
)


class AionTrackerPlugin:
    def __init__(
        self, data_dir: str | Path = "./data", stamina_cap: int | None = None
    ) -> None:
        db_path = Path(data_dir) / "aion_tracker.db"
        self.service = AionTrackerService(db_path, stamina_cap=stamina_cap)

    def handle_add_character(
        self, user_id: str, char_name: str, char_class: str, level: int = 1
    ) -> str:
        self.service.add_character(user_id, char_name, char_class, level)
        return f"已绑定角色: {char_name} ({char_class}) Lv.{level}"

    def handle_switch(self, user_id: str, char_name: str) -> str:
        ok = self.service.set_active_character(user_id, char_name)
        if not ok:
            return f"切换失败，未找到角色: {char_name}"
        return f"已切换当前角色为: {char_name}"

    def handle_status(self, user_id: str) -> str:
        active = self.service.get_active_character_name(user_id)
        if not active:
            return "你还没有设置当前角色，请先使用切换指令。"
        return self.service.render_status(user_id, active)

    def handle_all(self, user_id: str) -> str:
        return self.service.render_all(user_id)

    def handle_all_resources(self, user_id: str) -> str:
        return self.service.render_all_key_resources(user_id)

    def handle_update_full(
        self,
        user_id: str,
        stamina: int,
        nightmare_tix: int,
        subjugation_tix: int,
        awaken_tix: int,
        transcend_count: int,
        expedition_count: int,
        challenge_count: int,
        kinah: int,
    ) -> str:
        active = self.service.get_active_character_name(user_id)
        if not active:
            return "请先切换到一个角色后再更新资源。"
        ok = self.service.update_resources_full(
            user_id=user_id,
            char_name=active,
            stamina=stamina,
            nightmare_tix=nightmare_tix,
            subjugation_tix=subjugation_tix,
            awaken_tix=awaken_tix,
            transcend_count=transcend_count,
            expedition_count=expedition_count,
            challenge_count=challenge_count,
            kinah=kinah,
        )
        if not ok:
            return "更新失败，请确认角色是否存在。"
        return f"已更新 {active} 的核心资源。"

    def handle_add_resource(self, user_id: str, resource_name: str, amount: int) -> str:
        active = self.service.get_active_character_name(user_id)
        if not active:
            return "请先切换到一个角色后再修改资源。"
        ok = self.service.update_resource_delta(user_id, active, resource_name, amount)
        if ok:
            sign = "+" if amount >= 0 else ""
            return f"已调整 {active} 的 {resource_name}: {sign}{amount}"
        return "调整失败，请检查资源名是否正确。"

    def handle_plan_payload(self, user_id: str) -> dict:
        return self.service.build_plan_payload(user_id)

    def handle_dungeon_runs(
        self,
        user_id: str,
        char_name: str,
        expedition_runs: int = 0,
        transcend_runs: int = 0,
    ) -> str:
        ok, msg = self.service.consume_dungeon_runs(
            user_id=user_id,
            char_name=char_name,
            expedition_runs=expedition_runs,
            transcend_runs=transcend_runs,
        )
        return msg if ok else msg

    def handle_natural_message(self, user_id: str, text: str) -> str | None:
        msg = text.strip()
        if not msg:
            return None

        if self._looks_like_all_resources(msg):
            return self.handle_all_resources(user_id)
        if self._looks_like_all(msg):
            return self.handle_all(user_id)
        if self._looks_like_status(msg):
            return self.handle_status(user_id)

        add_match = re.search(
            r"(?:添加|新增|绑定)(?:角色)?\s+([^\s]+)\s+([^\s]+)(?:\s*(?:lv|LV|等级)?\s*(\d+))?",
            msg,
        )
        if add_match:
            char_name = add_match.group(1)
            char_class = add_match.group(2)
            level = int(add_match.group(3) or 1)
            return self.handle_add_character(user_id, char_name, char_class, level)

        switch_match = re.search(r"(?:切换(?:到)?|设为当前(?:角色)?)\s+([^\s]+)", msg)
        if switch_match:
            return self.handle_switch(user_id, switch_match.group(1))

        dungeon_payload = self._parse_dungeon_runs(user_id, msg)
        if dungeon_payload is not None:
            if dungeon_payload.get("error"):
                return str(dungeon_payload["error"])
            return self.handle_dungeon_runs(
                user_id=user_id,
                char_name=dungeon_payload["char_name"],
                expedition_runs=dungeon_payload["expedition_runs"],
                transcend_runs=dungeon_payload["transcend_runs"],
            )

        resource_entries = self._parse_resource_entries(msg)
        if resource_entries:
            return self._apply_resource_entries(user_id, msg, resource_entries)

        return None

    def _looks_like_status(self, msg: str) -> bool:
        return bool(re.search(r"(状态|面板|当前角色|查看当前)", msg))

    def _looks_like_all(self, msg: str) -> bool:
        return bool(re.search(r"(全部角色|所有角色|角色总览|看板)", msg))

    def _looks_like_all_resources(self, msg: str) -> bool:
        return bool(
            re.search(r"(所有角色|全部角色)", msg)
            and re.search(r"(基纳|体力|噩梦|觉醒|讨伐|超越|远征|挑战)", msg)
        )

    def _extract_char_name_from_text(self, user_id: str, msg: str) -> str | None:
        chars = self.service.list_characters(user_id)
        if not chars:
            return None
        names = sorted((c.char_name for c in chars), key=len, reverse=True)
        for name in names:
            if name and name in msg:
                return name
        return None

    def _parse_dungeon_runs(self, user_id: str, msg: str) -> dict | None:
        if not re.search(r"(打了|刷了|副本|远征|超越)", msg):
            return None
        expedition_runs = self._extract_keyword_count(msg, "远征")
        transcend_runs = self._extract_keyword_count(msg, "超越")
        if expedition_runs == 0 and transcend_runs == 0:
            return None
        char_name = self._extract_char_name_from_text(user_id, msg)
        if not char_name:
            char_name = self.service.get_active_character_name(user_id)
        if not char_name:
            return {
                "char_name": "",
                "expedition_runs": 0,
                "transcend_runs": 0,
                "error": "请先在消息中带上角色名，或先切换当前角色。",
            }
        return {
            "char_name": char_name,
            "expedition_runs": expedition_runs,
            "transcend_runs": transcend_runs,
        }

    def _extract_keyword_count(self, msg: str, keyword: str) -> int:
        patterns = [
            rf"{keyword}\s*(\d+)\s*次?",
            rf"(\d+)\s*次?\s*{keyword}",
        ]
        for pattern in patterns:
            found = re.search(pattern, msg)
            if found:
                return int(found.group(1))
        return 0

    def _parse_resource_entries(self, msg: str) -> list[dict]:
        entries: list[dict] = []
        for match in RESOURCE_TOKEN_PATTERN.finditer(msg):
            name, op, value_raw = match.groups()
            resource_name = RESOURCE_ALIASES.get(name)
            if not resource_name:
                continue
            value = int(value_raw)
            entries.append(
                {"resource_name": resource_name, "op": op or "", "value": value}
            )
        return entries

    def _apply_resource_entries(
        self, user_id: str, msg: str, entries: list[dict]
    ) -> str:
        char_name = self._extract_char_name_from_text(user_id, msg)
        if not char_name:
            char_name = self.service.get_active_character_name(user_id)
        if not char_name:
            return "请先在消息中带上角色名，或先切换当前角色。"

        has_set_word = bool(re.search(r"(设为|设置为|改为|更新为|覆盖)", msg))
        has_sub_word = bool(re.search(r"(减少|消耗|扣除|用了|使用了|减)", msg))
        has_add_word = bool(re.search(r"(增加|加|获得|恢复)", msg))

        res = self.service.get_resources(user_id, char_name)
        if res is None:
            return f"未找到角色: {char_name}"

        output_lines: list[str] = []
        for entry in entries:
            resource_name = entry["resource_name"]
            op = entry["op"]
            value = int(entry["value"])

            if op in {":", "：", "="} or has_set_word:
                current = int(getattr(res, resource_name))
                delta = value - current
            elif op in {"-", "减"}:
                delta = -value
            elif op in {"+", "加"}:
                delta = value
            else:
                delta = -value if has_sub_word and not has_add_word else value

            ok = self.service.update_resource_delta(
                user_id, char_name, resource_name, delta
            )
            if not ok:
                output_lines.append(f"{resource_name} 调整失败")
                continue

            sign = "+" if delta >= 0 else ""
            output_lines.append(f"{resource_name} {sign}{delta}")

        if not output_lines:
            return "没有识别到可更新的资源。"
        return f"已更新 {char_name}: " + "，".join(output_lines)
