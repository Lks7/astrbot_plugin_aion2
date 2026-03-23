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
    "讨伐次数": "subjugation_tix",
    "觉醒": "awaken_tix",
    "觉醒券": "awaken_tix",
    "觉醒次数": "awaken_tix",
    "超越": "transcend_count",
    "超越次数": "transcend_count",
    "远征": "expedition_count",
    "远征次数": "expedition_count",
    "挑战": "challenge_count",
    "挑战次数": "challenge_count",
    "基纳": "kinah",
    "战力": "power",
    "战斗力": "power",
}

RESOURCE_LABELS = {
    "stamina": "体力",
    "nightmare_tix": "噩梦券",
    "subjugation_tix": "讨伐券",
    "awaken_tix": "觉醒券",
    "transcend_count": "超越次数",
    "expedition_count": "远征次数",
    "challenge_count": "挑战次数",
    "kinah": "基纳",
    "power": "战力",
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

    def enter_mode(self, user_id: str) -> str:
        self.service.set_mode(user_id, "aion")
        return "好的，已进入 Aion 管家模式。你直接说人话就行，我来帮你记。"

    def exit_mode(self, user_id: str) -> str:
        self.service.set_mode(user_id, "")
        return "已退出 Aion 管家模式。需要时再叫我。"

    def handle_add_character(
        self,
        user_id: str,
        char_name: str,
        char_class: str,
        level: int = 1,
        power: int = 0,
    ) -> str:
        self.service.add_character(user_id, char_name, char_class, level, power)
        return f"已绑定角色: {char_name} ({char_class}) 战力:{power}"

    def handle_switch(self, user_id: str, char_name: str) -> str:
        ok = self.service.set_active_character(user_id, char_name)
        if not ok:
            return f"没找到角色 {char_name}，你先确认一下名字。"
        return f"好，当前角色切到 {char_name} 了。"

    def handle_status(self, user_id: str) -> str:
        active = self.service.get_active_character_name(user_id)
        if not active:
            return "你还没有设置当前角色，先告诉我要看谁，或者先切一下角色。"
        return self.service.render_status(user_id, active)

    def handle_status_for_character(self, user_id: str, char_name: str) -> str:
        return self.service.render_status(user_id, char_name)

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
        return msg

    def handle_natural_message(self, user_id: str, text: str) -> str | None:
        msg = text.strip()
        if not msg:
            return None

        if self._looks_like_enter_mode(msg):
            return self.enter_mode(user_id)
        if self._looks_like_exit_mode(msg):
            return self.exit_mode(user_id)

        intent = self._detect_intent(msg)
        slots = self._extract_slots(user_id, msg)

        if intent == "query_all":
            if self._looks_like_all_resources(msg):
                return self.handle_all_resources(user_id)
            return self.handle_all(user_id)

        if intent == "add_character":
            char_name = slots.get("char_name")
            char_class = slots.get("char_class")
            if not char_name or not char_class:
                return "我知道你想加角色，但角色名或职业我还没听清。"
            return self.handle_add_character(
                user_id=user_id,
                char_name=str(char_name),
                char_class=str(char_class),
                level=int(slots.get("level", 1)),
                power=int(slots.get("power", 0)),
            )

        if intent == "switch_character":
            char_name = slots.get("char_name")
            if not char_name:
                return "你想切角色的话，告诉我角色名就行。"
            return self.handle_switch(user_id, str(char_name))

        if intent == "query_status":
            char_name = slots.get("char_name")
            if char_name:
                return self.handle_status_for_character(user_id, str(char_name))
            return self.handle_status(user_id)

        if intent == "query_resource":
            char_name = str(
                slots.get("char_name")
                or self.service.get_active_character_name(user_id)
                or ""
            )
            if not char_name:
                return "你想查资源，但我还不知道是哪个角色。"
            resource_name = slots.get("resource_name")
            if not resource_name:
                return self.handle_status_for_character(user_id, char_name)
            return self._render_single_resource(user_id, char_name, str(resource_name))

        if intent == "update_resource":
            return self._handle_semantic_resource_update(user_id, msg, slots)

        if self.service.get_mode(user_id) == "aion":
            return "我知道你在和 Aion 管家对话，但这句我还没完全理解。你可以直接说你想看谁，或者谁的什么资源变了。"

        return None

    def _detect_intent(self, msg: str) -> str:
        if self._looks_like_all(msg):
            return "query_all"
        if re.search(r"(添加|新增|绑定).*(角色|名字|职业)", msg):
            return "add_character"
        if re.search(r"(切换|切到|换到|设为当前)", msg):
            return "switch_character"
        if re.search(r"(查看|看看|我想看|我要看|面板|状态|信息|资料)", msg):
            return "query_status"
        if self._looks_like_update(msg):
            return "update_resource"
        if self._looks_like_resource_question(msg):
            return "query_resource"
        return "unknown"

    def _extract_slots(self, user_id: str, msg: str) -> dict:
        slots: dict = {}
        chars = self.service.list_characters(user_id)
        names = sorted((c.char_name for c in chars), key=len, reverse=True)
        classes = sorted(
            {c.char_class for c in chars if c.char_class}, key=len, reverse=True
        )

        for name in names:
            if name and name in msg:
                slots["char_name"] = name
                break

        named_add_match = re.search(
            r"名字[：:]\s*([^\s]+).*?职业[：:]\s*([^\s]+)(?:.*?(?:战力|战斗力)[：:]\s*(\d+))?(?:.*?(?:lv|LV|等级)[：:]?\s*(\d+))?",
            msg,
        )
        if named_add_match:
            slots["char_name"] = named_add_match.group(1)
            slots["char_class"] = named_add_match.group(2)
            slots["power"] = int(named_add_match.group(3) or 0)
            slots["level"] = int(named_add_match.group(4) or 1)
            return slots

        add_match = re.search(
            r"(?:添加|新增|绑定)(?:角色)?\s+([^\s]+)\s+([^\s]+)(?:\s*(\d+))?(?:\s*(?:lv|LV|等级)?\s*(\d+))?",
            msg,
        )
        if add_match:
            slots.setdefault("char_name", add_match.group(1))
            slots["char_class"] = add_match.group(2)
            slots["power"] = int(add_match.group(3) or 0)
            slots["level"] = int(add_match.group(4) or 1)

        for cls in classes:
            if cls and cls in msg and "char_class" not in slots:
                slots["char_class"] = cls
                break

        switch_match = re.search(
            r"(?:切换(?:到)?|设为当前(?:角色)?|换到)\s*([^\s]+)", msg
        )
        if switch_match:
            slots["char_name"] = switch_match.group(1)

        for alias, internal in RESOURCE_ALIASES.items():
            if alias in msg:
                slots["resource_name"] = internal
                break

        value_match = re.search(r"(\d+)", msg)
        if value_match:
            slots["value"] = int(value_match.group(1))

        if re.search(r"(完成了|打完了|用完了|清空了|没了|归零)", msg):
            slots["value"] = 0
            slots["set_mode"] = True
        elif re.search(r"(还有|剩|剩下|目前|现在|为)", msg):
            slots["set_mode"] = True
        elif re.search(r"(增加|加了|获得|恢复)", msg):
            slots["delta_mode"] = True
        elif re.search(r"(减少|扣了|消耗了|用了|花了)", msg):
            slots["delta_mode"] = True
            slots["negative"] = True

        return slots

    def _handle_semantic_resource_update(
        self, user_id: str, msg: str, slots: dict
    ) -> str:
        char_name = str(
            slots.get("char_name")
            or self.service.get_active_character_name(user_id)
            or ""
        )
        if not char_name:
            return "我听出来你是在更新数据，但还不知道是哪个角色。"

        resource_name = slots.get("resource_name")
        if not resource_name:
            payload = self._parse_conversational_resource_entries(msg)
            if payload:
                return self._apply_resource_entries(
                    user_id, msg, payload, conversational=True
                )
            return "我知道你想更新信息，但还没识别到是哪个资源。"

        if resource_name == "power":
            return "战力更新我已经识别到了，但这部分我下一步再接到角色资料更新里。"

        value = slots.get("value")
        if value is None:
            payload = self._parse_conversational_resource_entries(msg)
            if payload:
                return self._apply_resource_entries(
                    user_id, msg, payload, conversational=True
                )
            return "我知道你想更新资源，但数值我还没听清。"

        res = self.service.get_resources(user_id, char_name)
        if res is None:
            return f"没找到角色 {char_name}。"

        current = int(getattr(res, str(resource_name)))
        if slots.get("set_mode"):
            delta = int(value) - current
        else:
            delta = -int(value) if slots.get("negative") else int(value)

        ok = self.service.update_resource_delta(
            user_id, char_name, str(resource_name), delta
        )
        if not ok:
            return "这次更新没成功，你再说一次我继续帮你记。"

        latest = self.service.get_resources(user_id, char_name)
        latest_value = (
            int(getattr(latest, str(resource_name))) if latest else current + delta
        )
        return f"好，我记下了。{char_name} 的{RESOURCE_LABELS[str(resource_name)]}现在是 {latest_value}。"

    def _render_single_resource(
        self, user_id: str, char_name: str, resource_name: str
    ) -> str:
        if resource_name == "power":
            chars = self.service.list_characters(user_id)
            target = next((c for c in chars if c.char_name == char_name), None)
            if target is None:
                return f"没找到角色 {char_name}。"
            return f"{char_name} 的战力是 {target.power}。"

        res = self.service.get_resources(user_id, char_name)
        if res is None:
            return f"没找到角色 {char_name}。"
        return f"{char_name} 的{RESOURCE_LABELS[resource_name]}是 {getattr(res, resource_name)}。"

    def _looks_like_enter_mode(self, msg: str) -> bool:
        return bool(
            re.search(
                r"(进入|开启|打开).*(aion|永恒之塔).*(模式|管家)?|^(进入aion|进入永恒之塔)$",
                msg,
                re.IGNORECASE,
            )
        )

    def _looks_like_exit_mode(self, msg: str) -> bool:
        return bool(
            re.search(
                r"(退出|关闭).*(aion|永恒之塔).*(模式|管家)?|^(退出aion|退出永恒之塔)$",
                msg,
                re.IGNORECASE,
            )
        )

    def _looks_like_status(self, msg: str) -> bool:
        return bool(re.search(r"(状态|面板|当前角色|查看当前)", msg))

    def _looks_like_all(self, msg: str) -> bool:
        return bool(re.search(r"(全部角色|所有角色|角色总览|看板)", msg))

    def _looks_like_all_resources(self, msg: str) -> bool:
        return bool(
            re.search(r"(所有角色|全部角色)", msg)
            and re.search(r"(基纳|体力|噩梦|觉醒|讨伐|超越|远征|挑战)", msg)
        )

    def _looks_like_update(self, msg: str) -> bool:
        return bool(
            re.search(
                r"(完成了|打完了|用完了|清空了|还有|剩|剩下|目前|现在|为|增加|加了|获得|恢复|减少|扣了|消耗了|用了|花了|更新|改成|改为)",
                msg,
            )
        )

    def _looks_like_resource_question(self, msg: str) -> bool:
        return bool(
            re.search(r"(多少|还有几|还剩几|还有多少|情况|信息)", msg)
            and any(alias in msg for alias in RESOURCE_ALIASES)
        )

    def _parse_conversational_resource_entries(self, msg: str) -> list[dict]:
        patterns = [
            (
                r"(体力|能量|噩梦券|噩梦|讨伐次数|讨伐券|讨伐|觉醒次数|觉醒券|觉醒|超越次数|超越|远征次数|远征|挑战次数|挑战|基纳).*?(还有|剩|剩下|目前|现在|为)\s*(\d+)",
                "=",
            ),
            (
                r"(体力|能量|噩梦券|噩梦|讨伐次数|讨伐券|讨伐|觉醒次数|觉醒券|觉醒|超越次数|超越|远征次数|远征|挑战次数|挑战|基纳).*?(完成了|打完了|用完了|清空了|没了|归零)",
                "=",
            ),
        ]
        entries: list[dict] = []
        for pattern, op in patterns:
            for match in re.finditer(pattern, msg):
                name = match.group(1)
                resource_name = RESOURCE_ALIASES.get(
                    name.replace("次数", ""), RESOURCE_ALIASES.get(name)
                )
                if not resource_name:
                    continue
                value = (
                    0
                    if match.lastindex == 2
                    else int(match.group(match.lastindex) or 0)
                )
                entries.append(
                    {"resource_name": resource_name, "op": op, "value": value}
                )
        return entries

    def _apply_resource_entries(
        self, user_id: str, msg: str, entries: list[dict], conversational: bool = False
    ) -> str:
        char_name = self._extract_char_name_from_text(user_id, msg)
        if not char_name:
            char_name = self.service.get_active_character_name(user_id)
        if not char_name:
            return "请先在消息中带上角色名，或先切换当前角色。"

        has_set_word = bool(re.search(r"(设为|设置为|改为|更新为|覆盖)", msg))
        has_sub_word = bool(re.search(r"(减少|消耗|扣除|用了|使用了|减|花了)", msg))
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
                output_lines.append(
                    f"{RESOURCE_LABELS.get(resource_name, resource_name)}调整失败"
                )
                continue

            latest = self.service.get_resources(user_id, char_name)
            latest_value = int(getattr(latest, resource_name)) if latest else value
            output_lines.append(
                f"{RESOURCE_LABELS.get(resource_name, resource_name)} {latest_value}"
            )

        if not output_lines:
            return "没有识别到可更新的资源。"
        if conversational:
            return f"好，我记下了。{char_name} 现在：" + "，".join(output_lines)
        return f"已更新 {char_name}: " + "，".join(output_lines)

    def _extract_char_name_from_text(self, user_id: str, msg: str) -> str | None:
        chars = self.service.list_characters(user_id)
        if not chars:
            return None
        names = sorted((c.char_name for c in chars), key=len, reverse=True)
        for name in names:
            if name and name in msg:
                return name
        return None
