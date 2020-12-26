import asyncio
import datetime
import discord
from discord.ext import tasks
from discord.ext import commands
from modules.client import CorkClient


class Tasks(commands.Cog):
    def __init__(self, bot: CorkClient):
        self.bot = bot
        self.repeat_alarm_loop.start()
        self.alarm_alarm_loop.start()
        self.queued = {"repeat": {}, "alarm": {}}

    def cog_unload(self):
        self.repeat_alarm_loop.cancel()
        self.alarm_alarm_loop.cancel()

    @tasks.loop()
    async def repeat_alarm_loop(self):
        await self.bot.wait_until_ready()
        while True: # 그냥 이렇게 해봤어요
            repeats = await self.bot.db.res_sql("""SELECT * FROM repeat""")
            now = datetime.datetime.now()
            for x in repeats:
                if now.strftime("%Y-%m-%d") == x["last_called_at"]:
                    continue
                user = self.bot.get_user(x["user_id"])
                channel = self.bot.get_channel(x["channel_id"])
                if user.id not in self.queued["repeat"].keys():
                    self.queued["repeat"][user.id] = {}
                if channel.id not in self.queued["repeat"][user.id].keys():
                    self.queued["repeat"][user.id][channel.id] = []
                if x["name"] in self.queued["repeat"][user.id][channel.id]:
                    continue
                if x["type"] == "weekly":
                    week_dict = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
                    if week_dict[x["duration"]] != now.weekday():
                        continue
                elif x["type"] == "monthly":
                    if int(x["duration"]) != now.day:
                        continue
                elif x["type"] == "yearly":
                    mm, dd = x["duration"].split("-")
                    if mm != now.month or dd != now.day:
                        continue
                elif x["type"] == "duration":
                    called_at = datetime.datetime.strptime(x["last_called_at"], "%Y-%m-%d")
                    to_call = called_at + datetime.timedelta(days=int(x["duration"]))
                    # 일단 빠른 개발을 위해 걍 str로 바꿔서 비교합니다.
                    if now.strftime("%Y-%m-%d") != to_call.strftime("%Y-%m-%d"):
                        continue
                if x["hour"] == now.hour:
                    if x["min"] < now.minute:
                        continue
                    self.prepare_alarm(x["min"], now, user, channel, x["name"], "repeat",  x["content"])
                    last_called_at = now.strftime("%Y-%m-%d")
                    await self.bot.db.exec_sql("""UPDATE repeat SET last_called_at=? WHERE name=? AND user_id=? AND channel_id=?""",
                                               (last_called_at, x["name"], user.id, channel.id))
            await asyncio.sleep(1)

    @tasks.loop()
    async def alarm_alarm_loop(self):
        await self.bot.wait_until_ready()
        while True:  # 그냥 이렇게 해봤어요
            alarms = await self.bot.db.res_sql("""SELECT * FROM alarm""")
            now = datetime.datetime.now()
            for x in alarms:
                user = self.bot.get_user(x["user_id"])
                channel = self.bot.get_channel(x["channel_id"])
                if user.id not in self.queued["alarm"].keys():
                    self.queued["alarm"][user.id] = {}
                if channel.id not in self.queued["alarm"][user.id].keys():
                    self.queued["alarm"][user.id][channel.id] = []
                if x["name"] in self.queued["alarm"][user.id][channel.id]:
                    continue
                if x["year"] == now.year:
                    if x["month"] == now.month:
                        if x["date"] == now.day:
                            if x["hour"] == now.hour:
                                if x["min"] >= now.minute:
                                    self.prepare_alarm(x["min"], now, user, channel, x["name"], "alarm", x["content"])
                                await self.bot.db.exec_sql("""DELETE FROM alarm WHERE name=? AND user_id=? AND channel_id=?""",
                                                           (x["name"], user.id, channel.id))
            await asyncio.sleep(1)

    def prepare_alarm(self, _min, now, user: discord.User, channel: discord.TextChannel, name, _type, cont):
        _min = _min - now.minute
        secs = _min * 60 - now.second
        secs = secs if secs > 0 else 0
        self.bot.loop.create_task(self.ring_alarm(secs, user, channel, name, cont, True))
        self.queued[_type][user.id][channel.id].append(name)

    async def ring_alarm(self, wait, user: discord.User, channel: discord.TextChannel, name, cont, clr_after):
        await asyncio.sleep(wait)
        embed = discord.Embed(title="⏰ 시간이 됐어요!", description=f"설정하신 `{name}` 알림이 울렸어요!")
        embed.add_field(name="알림 내용", value=cont)
        msg = await channel.send(user.mention, embed=embed)
        if clr_after:
            _list = self.queued["repeat"][user.id][channel.id]
            self.queued["repeat"][user.id][channel.id] = [x for x in _list if x != name]
        self.bot.loop.create_task(msg.add_reaction("⏰"))
        try:
            await self.bot.wait_for("reaction_add",
                                    timeout=30,
                                    check=lambda r, u: str(r) == "⏰" and u.id == user.id and r.message.id == msg.id)
        except asyncio.TimeoutError:
            msg = await channel.send("이런! 알림을 확인하지 않으셔서 스누즈 기능이 활성화되었어요. 5분 뒤에 다시 알림을 울릴께요.\n"
                                     "아니면 5분 안에 :alarm_clock: 이모지 반응을 눌러주세요.")
            self.bot.loop.create_task(msg.add_reaction("⏰"))
            try:
                await self.bot.wait_for("reaction_add",
                                        timeout=60*5,
                                        check=lambda r, u: str(r) == "⏰" and u.id == user.id and r.message.id == msg.id)
                await channel.send("스누즈가 취소되었어요.")
            except asyncio.TimeoutError:
                self.bot.loop.create_task(self.ring_alarm(0, user, channel, name, cont, False))


def setup(bot):
    bot.add_cog(Tasks(bot))
