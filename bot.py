import asyncio
import logging

import discord
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


async def main():
    if not config.DISCORD_TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill in your bot token."
        )
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
