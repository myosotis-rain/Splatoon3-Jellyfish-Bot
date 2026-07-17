import discord
from discord import app_commands
from discord.ext import commands

from .. import game_flow, mini_flow, views


class VotingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def _ranked_context(self, guild_id):
        session = self.db.get_active_session(guild_id)
        if session is None:
            return None
        game = self.db.get_latest_game(session["id"])
        if game is None or game["status"] not in ("voting_round1", "voting_round2"):
            return None
        return session, game

    def _mini_context(self, guild_id):
        session = self.db.get_active_mini_session(guild_id)
        if session is None:
            return None
        game = self.db.get_latest_mini_game(session["id"])
        if game is None or game["status"] not in ("voting_round1", "voting_round2"):
            return None
        return session, game

    def _find_voting_context(self, ctx, voter_id):
        """Locate which vote (ranked or mini) this player currently needs
        to cast, and in which guild. In a guild channel that's just this
        guild (ranked checked before mini). In a DM, search every guild
        the bot is in.
        """
        guild_ids = [ctx.guild.id] if ctx.guild is not None else [g.id for g in self.bot.guilds]

        for guild_id in guild_ids:
            ranked = self._ranked_context(guild_id)
            if ranked is not None:
                session, game = ranked
                teams, identities = self.db.get_teams_and_identities(game["id"])
                _, voters, _ = game_flow.voters_and_targets(self.db, teams, identities, game)
                if voter_id in voters:
                    return "ranked", session, game, teams, identities

            mini = self._mini_context(guild_id)
            if mini is not None:
                session, game = mini
                teams, identities = self.db.get_mini_teams_and_identities(game["id"])
                _, voters, _ = mini_flow.voters_and_targets(self.db, teams, identities, game)
                if voter_id in voters:
                    return "mini", session, game, teams, identities

        return None, None, None, None, None

    @commands.hybrid_command(name="vote", description="对可疑玩家投票")
    @app_commands.describe(target="你要投票指认的玩家")
    async def vote(self, ctx: commands.Context, target: discord.User):
        voter_id = str(ctx.author.id)
        target_id = str(target.id)

        mode, session, game, teams, identities = self._find_voting_context(ctx, voter_id)
        if mode is None:
            await ctx.send("当前没有需要你投票的游戏。", ephemeral=True)
            return

        flow = game_flow if mode == "ranked" else mini_flow
        channel = self.bot.get_channel(int(session["channel_id"]))
        if channel is None:
            await ctx.send("找不到本场次的频道。", ephemeral=True)
            return

        async def reply(content, ephemeral=False):
            await ctx.send(content, ephemeral=ephemeral)

        await views.cast_vote(
            db=self.db, flow=flow, channel=channel, guild=ctx.guild, session=session,
            game=game, teams=teams, identities=identities, voter_id=voter_id,
            target_id=target_id, reply=reply,
        )


async def setup(bot):
    await bot.add_cog(VotingCog(bot))
