from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from aion_tracker.plugin import AionTrackerPlugin


@register(
    "astrbot_plugin_aion_tracker",
    "local",
    "永恒之塔多角色养成追踪，支持自然语言录入与自动结算。",
    "0.1.4",
)
class AionTrackerStarPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        data_dir = Path(__file__).resolve().parent / "data"
        self.plugin = AionTrackerPlugin(data_dir=data_dir)

    @filter.command_group("at")
    def at(self):
        pass

    @at.command("addchar")
    async def at_addchar(
        self,
        event: AstrMessageEvent,
        char_name: str,
        char_class: str,
        power: int = 0,
        level: int = 1,
    ):
        yield event.plain_result(
            self.plugin.handle_add_character(
                user_id=event.get_sender_id(),
                char_name=char_name,
                char_class=char_class,
                level=level,
                power=power,
            )
        )

    @at.command("switch")
    async def at_switch(self, event: AstrMessageEvent, char_name: str):
        yield event.plain_result(
            self.plugin.handle_switch(
                user_id=event.get_sender_id(), char_name=char_name
            )
        )

    @at.command("status")
    async def at_status(self, event: AstrMessageEvent):
        yield event.plain_result(
            self.plugin.handle_status(user_id=event.get_sender_id())
        )

    @at.command("all")
    async def at_all(self, event: AstrMessageEvent):
        yield event.plain_result(self.plugin.handle_all(user_id=event.get_sender_id()))

    @at.command("allres")
    async def at_allres(self, event: AstrMessageEvent):
        yield event.plain_result(
            self.plugin.handle_all_resources(user_id=event.get_sender_id())
        )

    @at.command("add")
    async def at_add(self, event: AstrMessageEvent, resource_name: str, amount: int):
        yield event.plain_result(
            self.plugin.handle_add_resource(
                user_id=event.get_sender_id(),
                resource_name=resource_name,
                amount=amount,
            )
        )

    @at.command("update")
    async def at_update(
        self,
        event: AstrMessageEvent,
        stamina: int,
        nightmare_tix: int,
        subjugation_tix: int,
        awaken_tix: int,
        transcend_count: int,
        expedition_count: int,
        challenge_count: int,
        kinah: int,
    ):
        yield event.plain_result(
            self.plugin.handle_update_full(
                user_id=event.get_sender_id(),
                stamina=stamina,
                nightmare_tix=nightmare_tix,
                subjugation_tix=subjugation_tix,
                awaken_tix=awaken_tix,
                transcend_count=transcend_count,
                expedition_count=expedition_count,
                challenge_count=challenge_count,
                kinah=kinah,
            )
        )

    @at.command("run")
    async def at_run(
        self,
        event: AstrMessageEvent,
        char_name: str,
        expedition_runs: int = 0,
        transcend_runs: int = 0,
    ):
        yield event.plain_result(
            self.plugin.handle_dungeon_runs(
                user_id=event.get_sender_id(),
                char_name=char_name,
                expedition_runs=expedition_runs,
                transcend_runs=transcend_runs,
            )
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_nlp(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if not text:
            return
        if text.startswith("/"):
            return
        resp = self.plugin.handle_natural_message(
            user_id=event.get_sender_id(), text=text
        )
        if resp:
            yield event.plain_result(resp)

    async def terminate(self):
        self.plugin.service.close()
