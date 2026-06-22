import datetime
import time
import random
import asyncio
import logging

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig

from astrbot.core.agent.message import UserMessageSegment, AssistantMessageSegment, TextPart

logger = logging.getLogger("zzz_sleep_dream")

PREFIX = "zzz_"
# 声明: 本插件的全部逻辑代码与核心功能实现均由 AI 辅助生成。
@register("ZzzZzz 睡眠助手", "TessromaVerra", "纯休息模式 + 朦胧可自定义 + 起床气好感度", "1.0.3")
class ZzzSleepDream(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.sys_cfg = self.config.get("system_settings", {})
        self.rest_cfg = self.config.get("rest_settings", {})
        self.drowsy_cfg = self.config.get("drowsy_settings", {})
        self.affection_cfg = self.config.get("affection_settings", {})

        self._locks = {}
        self._validate_config()
        logger.info(f"[zzz_sleep_dream] 插件已启动，enable_curfew={self.rest_cfg.get('enable_curfew')}, "
                    f"curfew_time={self.rest_cfg.get('curfew_time')}, "
                    f"affection_enabled={self.affection_cfg.get('enable_affection', False)}")

    def _validate_config(self):
        warnings = []
        t = self.rest_cfg.get("curfew_time", "")
        if t and "-" not in t:
            warnings.append("curfew_time 格式错误，应为 HH:MM-HH:MM，当前值: " + t)
        mw = self.rest_cfg.get("max_wakes_per_period", 3)
        if not (1 <= mw <= 10):
            warnings.append(f"max_wakes_per_period 建议在 1-10 之间，当前值: {mw}")
        pm = self.rest_cfg.get("post_wakeup_minutes", 10)
        if pm <= 0:
            warnings.append("post_wakeup_minutes 必须大于 0")
        psm = self.rest_cfg.get("pre_sleep_minutes", 15)
        if psm <= 0:
            warnings.append("pre_sleep_minutes 必须大于 0")

        if self.affection_cfg.get("enable_affection", False):
            try:
                val = int(self.affection_cfg.get("initial_affection", 50))
                if not (0 <= val <= 100):
                    warnings.append("initial_affection 必须在 0~100 之间")
            except ValueError:
                warnings.append("initial_affection 必须为整数")

        for w in warnings:
            logger.warning(f"[zzz_sleep_dream] {w}")

    @staticmethod
    def _time_to_min(t: str) -> int:
        try:
            h, m = map(int, t.split(":"))
            return h * 60 + m
        except Exception:
            return -1

    def _now_in_mode(self, start: str, end: str) -> bool:
        start_m = self._time_to_min(start)
        end_m = self._time_to_min(end)
        if start_m == -1 or end_m == -1:
            return False
        now = datetime.datetime.now()
        now_m = now.hour * 60 + now.minute
        if start_m <= end_m:
            return start_m <= now_m <= end_m
        else:
            return now_m >= start_m or now_m <= end_m

    def _get_sleep_mode(self):
        if not self.rest_cfg.get("enable_curfew", False):
            return None, None
        t = self.rest_cfg.get("curfew_time", "")
        if not t or "-" not in t:
            return None, None
        start, end = t.split("-", 1)
        if self._now_in_mode(start, end):
            return "休息", self.rest_cfg.get("curfew_reply", "")
        return None, None

    async def _check_reminder(self, uid):
        if not self.rest_cfg.get("enable_reminder", True):
            return None
        if not self.rest_cfg.get("enable_curfew", False):
            return None
        
        now = datetime.datetime.now()
        pre_minutes = self.rest_cfg.get("pre_sleep_minutes", 15)
        bot_name = self.sys_cfg.get("bot_nickname", "暝暝")
        t = self.rest_cfg.get("curfew_time", "")
        
        if not t or "-" not in t:
            return None
        start_str, _ = t.split("-", 1)
        start_m = self._time_to_min(start_str)
        if start_m == -1:
            return None
            
        target = now.replace(hour=start_m // 60, minute=start_m % 60, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        diff = (target - now).total_seconds() / 60
        
        if 0 < diff <= pre_minutes:
            today_str = datetime.date.today().isoformat()
            last_key = f"{PREFIX}last_remind_{uid}_{today_str}"
            last_ts = await self.get_kv_data(last_key, 0)
            if time.time() - last_ts > 300:
                await self.put_kv_data(last_key, time.time())
                text = self.rest_cfg.get("reminder_text", "（{bot_name}再过 {minutes} 分钟就要睡觉了，休要打扰。）")
                text = text.replace("{minutes}", str(int(diff))).replace("{bot_name}", bot_name)
                return text
        return None

    async def _randomize_drowsy_level(self, uid):
        level = random.randint(0, 4)  # 5 个等级
        await self.put_kv_data(f"{PREFIX}drowsy_level_{uid}", level)
        return level

    async def _get_drowsy_instruction(self, uid):
        level = await self.get_kv_data(f"{PREFIX}drowsy_level_{uid}", -1)
        if level == -1:
            return None
        
        default_text = f"（朦胧度:{level}/4）"
        text = self.drowsy_cfg.get(f"drowsy_text_level_{level}", default_text)
        return text.replace("{level}", str(level))

    async def _get_affection(self, uid):
        key = f"{PREFIX}affection_{uid}"
        val = await self.get_kv_data(key, None)
        if val is None:
            initial = self.affection_cfg.get("initial_affection", 50)
            await self.put_kv_data(key, initial)
            return initial
        return val

    async def _set_affection(self, uid, value):
        value = max(0, min(100, value))
        await self.put_kv_data(f"{PREFIX}affection_{uid}", value)
        return value

    async def _change_affection(self, uid, delta):
        current = await self._get_affection(uid)
        new_val = current + delta
        return await self._set_affection(uid, new_val)

    async def _affection_recover(self, uid):
        if not self.affection_cfg.get("enable_affection", False):
            return
        now = time.time()
        recover_speed = self.affection_cfg.get("recover_per_hour", 1)
        if recover_speed <= 0:
            return

        last_key = f"{PREFIX}affection_last_recover_{uid}"
        last_ts = await self.get_kv_data(last_key, now)
        delta_hours = (now - last_ts) / 3600.0
        if delta_hours < 0.01:
            return

        rate = 1.0
        mode, _ = self._get_sleep_mode()
        if mode:
            rate = self.affection_cfg.get("rest_recover_rate", 0.5)

        gain = delta_hours * recover_speed * rate
        if gain > 0:
            await self._change_affection(uid, int(gain))
            await self.put_kv_data(last_key, now)

    async def _apply_affection_tone(self, uid, base_text):
        if not self.affection_cfg.get("enable_affection", False):
            return base_text
        threshold = self.affection_cfg.get("low_affection_threshold", 10)
        current = await self._get_affection(uid)
        if current < threshold:
            tone_prefix = self.affection_cfg.get("low_affection_tone", "（冷漠地）")
            return tone_prefix + base_text
        return base_text

    def _get_lock(self, uid: str) -> asyncio.Lock:
        if uid not in self._locks:
            self._locks[uid] = asyncio.Lock()
        return self._locks[uid]

    @filter.on_llm_request()
    async def sleep_interceptor(self, event: AstrMessageEvent, req):
        mode, reply = self._get_sleep_mode()
        if not mode:
            return

        sender = event.get_sender_id()
        group_id = getattr(event, 'group_id', None)
        if sender in self.sys_cfg.get("whitelist_users", []) or \
           (group_id is not None and group_id in self.sys_cfg.get("whitelist_groups", [])):
            return

        uid = event.unified_msg_origin
        lock = self._get_lock(uid)
        
        async with lock:
            await self._affection_recover(uid)

            awake_until = await self.get_kv_data(f"{PREFIX}awake_until_{uid}", 0)
            now_ts = time.time()
            is_awake = (now_ts < awake_until) if awake_until > 0 else False

            if awake_until > 0 and not is_awake:
                await self.put_kv_data(f"{PREFIX}awake_until_{uid}", 0)
                await self.delete_kv_data(f"{PREFIX}drowsy_level_{uid}")
                await self.delete_kv_data(f"{PREFIX}dreams_{uid}")
                await self.delete_kv_data(f"{PREFIX}wake_count_{uid}") 
                
                re_sleep_msg = self.rest_cfg.get("re_sleep_reply", "（打个哈欠）唔...好困，还是再睡一会儿吧...")
                re_sleep_msg = await self._apply_affection_tone(uid, re_sleep_msg)
                await event.send(event.plain_result(re_sleep_msg))
                event.stop_event()
                return

            if not is_awake and awake_until == 0:
                has_count = await self.get_kv_data(f"{PREFIX}wake_count_{uid}", 0)
                if has_count > 0:
                    await self.delete_kv_data(f"{PREFIX}wake_count_{uid}")

            if not is_awake and not event.message_str.strip():
                dreams = await self.get_kv_data(f"{PREFIX}dreams_{uid}", [])
                dreams.append("（戳了戳你）")
                if len(dreams) > 5:
                    dreams = dreams[-5:]
                await self.put_kv_data(f"{PREFIX}dreams_{uid}", dreams)

                reply_with_tone = await self._apply_affection_tone(uid, reply)
                try:
                    await event.send(event.plain_result(reply_with_tone))
                except Exception as e:
                    logger.error(f"[zzz_sleep_dream] 发送纯@睡眠回复失败: {e}")
                event.stop_event()
                return

            reminder = await self._check_reminder(uid)
            if reminder:
                try:
                    await event.send(event.plain_result(reminder))
                except Exception as e:
                    logger.error(f"[zzz_sleep_dream] 发送提醒失败: {e}")

            if is_awake and self.drowsy_cfg.get("enable_drowsy", True):
                inst = await self._get_drowsy_instruction(uid)
                if inst:
                    if self.affection_cfg.get("enable_affection", False):
                        current_aff = await self._get_affection(uid)
                        threshold = self.affection_cfg.get("low_affection_threshold", 10)
                        if current_aff < threshold:
                            inst = f"（因为你的好感度很低，你对用户表现得非常冷漠和不耐烦）{inst}"
                    try:
                        umo = event.unified_msg_origin
                        provider_id = await self.context.get_current_chat_provider_id(umo=umo)
                        user_msg = UserMessageSegment(content=[TextPart(text=event.message_str)])
                        
                        llm_resp = await self.context.llm_generate(
                            chat_provider_id=provider_id,
                            contexts=[user_msg],
                            prompt=inst 
                        )
                        
                        conv_mgr = self.context.conversation_manager
                        curr_cid = await conv_mgr.get_curr_conversation_id(umo)
                        if curr_cid:
                            await conv_mgr.add_message_pair(
                                cid=curr_cid,
                                user_message=user_msg,
                                assistant_message=AssistantMessageSegment(content=[TextPart(text=llm_resp.completion_text)])
                            )
                        
                        await event.send(event.plain_result(llm_resp.completion_text))
                        event.stop_event()
                        return
                    except Exception as e:
                        logger.error(f"[zzz_sleep_dream] 朦胧生成失败: {e}")

            if is_awake:
                return

            bot_name = self.sys_cfg.get("bot_nickname", "暝暝")
            raw_msg = getattr(event, 'raw_message', '') or event.message_str
            at_me = getattr(event, 'is_at_me', False) or \
                    (bot_name and bot_name in event.message_str) or \
                    ("at" in str(raw_msg).lower())
            
            is_wakeup_word = event.message_str.strip() in self.rest_cfg.get("wakeup_words", [])

            if self.sys_cfg.get("interceptor_mode", "mention") == "mention" and not at_me and not is_wakeup_word:
                return

            if is_wakeup_word:
                max_wakes = self.rest_cfg.get("max_wakes_per_period", 3)
                wake_count = await self.get_kv_data(f"{PREFIX}wake_count_{uid}", 0)
                
                if wake_count >= max_wakes:
                    reject_msg = self.rest_cfg.get("reject_wakeup_reply", "（烦躁地翻了个身）我都醒这么多次了，不理你了！")
                    reject_msg = await self._apply_affection_tone(uid, reject_msg)
                    if self.affection_cfg.get("enable_affection", False):
                        deduct = self.affection_cfg.get("reject_wake_deduct", 2)
                        await self._change_affection(uid, -deduct)
                    await event.send(event.plain_result(reject_msg))
                    event.stop_event()
                    return

                if self.affection_cfg.get("enable_affection", False):
                    if is_awake:
                        deduct = self.affection_cfg.get("repeat_wake_deduct", 10)
                    else:
                        deduct = self.affection_cfg.get("wake_deduct", 5)
                    await self._change_affection(uid, -deduct)

                if self.drowsy_cfg.get("enable_drowsy", True):
                    await self._randomize_drowsy_level(uid)
                else:
                    await self.put_kv_data(f"{PREFIX}drowsy_level_{uid}", -1)

                await self.put_kv_data(f"{PREFIX}wake_count_{uid}", wake_count + 1)
                post_mins = self.rest_cfg.get("post_wakeup_minutes", 10)
                await self.put_kv_data(f"{PREFIX}awake_until_{uid}", now_ts + post_mins * 60)

                dreams = await self.get_kv_data(f"{PREFIX}dreams_{uid}", [])
                last_dream = dreams[-1] if dreams else self.rest_cfg.get("empty_dream_text", "虚无")
                await self.delete_kv_data(f"{PREFIX}dreams_{uid}")

                safe_dream = last_dream.replace('"', '“').replace('"', '”')
                
                tpl = self.rest_cfg.get("wakeup_reply", "（揉眼睛）唔...吵死了...你为什么要吵醒我？梦里梦见你说：“{dream}”...")
                reply_msg = tpl.replace("{dream}", safe_dream)
                reply_msg = await self._apply_affection_tone(uid, reply_msg)
                
                await event.send(event.plain_result(reply_msg))
                event.stop_event()
                
            else:
                dreams = await self.get_kv_data(f"{PREFIX}dreams_{uid}", [])
                dreams.append(event.message_str)
                if len(dreams) > 5:
                    dreams = dreams[-5:]
                await self.put_kv_data(f"{PREFIX}dreams_{uid}", dreams)

                reply_with_tone = await self._apply_affection_tone(uid, reply)
                await event.send(event.plain_result(reply_with_tone))
                event.stop_event()