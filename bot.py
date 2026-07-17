import asyncio
import logging

import discord
from aiohttp import web
from discord.ext import commands

from gamebot import config
from gamebot.db import Database

logging.basicConfig(level=logging.INFO)

EXTENSIONS = (
    "gamebot.cogs.session",
    "gamebot.cogs.game",
    "gamebot.cogs.mini",
    "gamebot.cogs.voting",
)


class JellyfishBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)
        self.db = Database(config.DATABASE_PATH)

    async def setup_hook(self):
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        await self.tree.sync()

    async def close(self):
        self.db.close()
        await super().close()


bot = JellyfishBot()


@bot.event
async def on_ready():
    print(f"小水母 已上线: {bot.user} (id={bot.user.id})")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("该命令只能在服务器内使用。")
        return
    if isinstance(error, commands.CommandNotFound):
        return
    raise error


async def start_web_server():
    """A Discord bot never receives HTTP traffic on its own, but Render's
    free tier only exists for Web Services, which require something to
    bind $PORT and answer health checks. This is that something -- pair
    the deployed service with an external uptime pinger (UptimeRobot,
    cron-job.org, etc.) hitting it every ~10 minutes, or Render's own
    15-minute inactivity spin-down will still kill the bot."""
    async def health(request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()


async def main():
    if not config.DISCORD_TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill in your bot token."
        )
    await start_web_server()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
