import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from .. import config, game_flow, game_logic, messages
from ..views import ConfirmView


class GameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def _require_session(self, ctx):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            raise RuntimeError("当前没有进行中的场次，请先使用 /session create 创建。")
        return session

    def _require_game(self, session):
        game = self.db.get_latest_game(session["id"])
        if game is None:
            raise RuntimeError("当前场次还没有开始任何游戏，请先使用 /game start。")
        return game

    @commands.hybrid_group(name="game", description="管理单局游戏")
    @commands.guild_only()
    async def game(self, ctx: commands.Context):
        await ctx.send(
            "请使用 /game start|status|confirmations|result|closevote|resolvetie|reveal",
            ephemeral=True,
        )

    @game.command(name="testidentity", description="[测试] 给自己私信一张随机身份卡，不影响任何场次/游戏")
    @app_commands.describe(mode="卧底游戏 (ranked) 还是 Mini 3v3 (mini) 的卡面格式")
    async def testidentity(self, ctx: commands.Context, mode: Literal["ranked", "mini"] = "ranked"):
        team = random.choice(config.TEAMS)
        if mode == "mini":
            identity = random.choice([config.IDENTITY_UNDERCOVER, config.IDENTITY_GOOD])
            card = messages.mini_identity_card_text(team, identity)
        else:
            identity = random.choice(
                [config.IDENTITY_UNDERCOVER, config.IDENTITY_DUMMY, config.IDENTITY_GOOD]
            )
            card = messages.identity_card_text(team, identity)

        try:
            await ctx.author.send(card)
        except discord.Forbidden:
            await ctx.send(
                "⚠️ 私信发送失败，请确认已开启「允许来自服务器成员的私信」", ephemeral=True
            )
            return
        await ctx.send(f"{messages.JELLY} 已发送测试身份卡 ({mode}) 到你的私信", ephemeral=True)

    @game.command(name="start", description="开始新的一局游戏")
    async def start(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return

        latest_game = self.db.get_latest_game(session["id"])
        if latest_game is not None and latest_game["status"] != "completed":
            await ctx.send(
                f"上一局 (Game #{latest_game['game_number']}) 还没有结束"
                f"（状态: {latest_game['status']}），请先用 /game closevote 或 /game override 结束。",
                ephemeral=True,
            )
            return

        players = self.db.get_session_players(session["id"])
        if len(players) != config.GAME_SIZE:
            await ctx.send(
                f"当前场次需要恰好 {config.GAME_SIZE} 名玩家才能开始游戏，"
                f"目前有 {len(players)} 人。",
                ephemeral=True,
            )
            return

        await ctx.defer()

        teams = game_logic.assign_teams(players)
        identities = game_logic.assign_game_identities(teams)
        game_id, game_number = self.db.create_game(session["id"])
        self.db.save_team_assignment(game_id, teams, identities)
        self.db.set_game_status(game_id, "confirming")

        await ctx.send(messages.team_announcement_text(game_number, teams))

        dm_failures = []
        for player_id in players:
            identity, team = self.db.get_identity(game_id, player_id)
            member = ctx.guild.get_member(int(player_id))
            if member is None:
                dm_failures.append(player_id)
                continue
            try:
                card = messages.identity_card_text(team, identity)
                if identity in config.IDENTITIES_NEEDING_CONFIRMATION:
                    view = ConfirmView(self.db, game_id, int(player_id))
                    await member.send(card, view=view)
                else:
                    await member.send(card)
            except discord.Forbidden:
                dm_failures.append(player_id)

        if dm_failures:
            mentions = ", ".join(messages.mention(p) for p in dm_failures)
            await ctx.send(
                f"⚠️ 以下玩家私信发送失败，请确认已开启「允许来自服务器成员的私信」: {mentions}"
            )

    @game.command(name="status", description="查看当前游戏状态")
    async def status(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        await ctx.send(f"🎮 Game #{game['game_number']}\n状态: {game['status']}")

    @game.command(name="confirmations", description="查看特殊身份确认状态")
    async def confirmations(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        _, identities = self.db.get_teams_and_identities(game["id"])
        confirmed_ids = {
            row["player_id"] for row in self.db.get_game_players(game["id"]) if row["confirmed"]
        }
        confirmed, needed = game_logic.confirmation_status(identities, confirmed_ids)
        await ctx.send(messages.confirmation_status_text(confirmed, needed))

    @game.command(name="result", description="记录输方队伍并开始投票")
    @app_commands.describe(losing_team="输方队伍，A 或 B")
    @app_commands.choices(losing_team=[
        app_commands.Choice(name="A", value="A"),
        app_commands.Choice(name="B", value="B"),
    ])
    async def result(self, ctx: commands.Context, losing_team: str):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return

        losing = losing_team.upper()
        if losing not in config.TEAMS:
            await ctx.send(f"输方队伍必须是 {' 或 '.join(config.TEAMS)}。", ephemeral=True)
            return

        _, identities = self.db.get_teams_and_identities(game["id"])
        confirmed_ids = {
            row["player_id"] for row in self.db.get_game_players(game["id"]) if row["confirmed"]
        }
        confirmed, needed = game_logic.confirmation_status(identities, confirmed_ids)
        if confirmed < needed:
            await ctx.send(
                f"特殊身份尚未全部确认（{confirmed}/{needed}），暂不能开始投票。",
                ephemeral=True,
            )
            return

        winning = [t for t in config.TEAMS if t != losing][0]
        self.db.set_game_result(game["id"], losing, winning)
        await ctx.send(
            f"输方: {losing}\n胜方: {winning}\n\n可以开始讨论，讨论结束后使用 /vote 进行第一轮投票。"
        )

    @game.command(name="override", description="[管理] 直接宣布本局结果，跳过整个投票流程")
    @app_commands.describe(
        losing_team="输方队伍，A 或 B",
        caught="被抓到的卧底（不填代表卧底未被抓到）",
    )
    @app_commands.choices(losing_team=[
        app_commands.Choice(name="A", value="A"),
        app_commands.Choice(name="B", value="B"),
    ])
    async def override(
        self, ctx: commands.Context, losing_team: str, caught: discord.Member = None
    ):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        if game["status"] == "completed":
            await ctx.send(
                "本局已经结束，无法再次宣布结果。如需修正积分请使用 /session adjustscore。",
                ephemeral=True,
            )
            return

        losing = losing_team.upper()
        if losing not in config.TEAMS:
            await ctx.send(f"输方队伍必须是 {' 或 '.join(config.TEAMS)}。", ephemeral=True)
            return
        winning = [t for t in config.TEAMS if t != losing][0]

        teams, identities = self.db.get_teams_and_identities(game["id"])
        eliminated = str(caught.id) if caught else None
        if eliminated is not None and eliminated not in teams[losing]:
            await ctx.send("被抓玩家必须是输方队伍成员。", ephemeral=True)
            return

        self.db.set_game_result(game["id"], losing, winning)
        scores = game_logic.calculate_scores(
            teams=teams,
            identities=identities,
            losing_team=losing,
            winning_team=winning,
            eliminated_player=eliminated,
            final_round_votes={},
        )
        self.db.finalize_scores(session["id"], game["id"], scores)

        lines = [f"⚡ 管理员直接宣布结果\n输方: {losing}\n胜方: {winning}\n"]
        if eliminated:
            lines.append(f"被抓: {messages.mention(eliminated)}\n")
        lines.append("本局积分:")
        for player_id, score in scores.items():
            lines.append(f"{messages.mention(player_id)}: {score:+d}")
        await ctx.send("\n".join(lines))

    @game.command(name="closevote", description="结束当前一轮投票并进入下一阶段")
    async def closevote(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return

        teams, identities = self.db.get_teams_and_identities(game["id"])

        if game["status"] not in ("voting_round1", "voting_round2"):
            await ctx.send(
                f"当前状态 ({game['status']}) 不是可结束的投票阶段。", ephemeral=True
            )
            return

        try:
            msg = game_flow.resolve_current_round(self.db, session, game, teams, identities)
        except game_logic.VoteError as e:
            await ctx.send(str(e), ephemeral=True)
            return

        if msg is None:
            await ctx.send("这一轮还没有人投票。", ephemeral=True)
            return

        await ctx.send(msg)

    @game.command(name="resolvetie", description="手动裁定投票结果，跳过自动重新投票")
    @app_commands.describe(player="被裁定为卧底的玩家")
    async def resolvetie(self, ctx: commands.Context, player: discord.Member):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        if game["status"] != "voting_round2":
            await ctx.send("当前不在投票阶段。", ephemeral=True)
            return

        teams, identities = self.db.get_teams_and_identities(game["id"])
        eliminated = str(player.id)
        self.db.set_eliminated(game["id"], eliminated)
        final_round_votes = self.db.get_votes(game["id"], self.db.get_current_round(game["id"]))
        scores = game_logic.calculate_scores(
            teams=teams,
            identities=identities,
            losing_team=game["losing_team"],
            winning_team=game["winning_team"],
            eliminated_player=eliminated,
            final_round_votes=final_round_votes,
        )
        self.db.finalize_scores(session["id"], game["id"], scores)
        lines = [f"被裁定指认: {messages.mention(eliminated)}\n", "本局积分:"]
        for pid, score in scores.items():
            lines.append(f"{messages.mention(pid)}: {score:+d}")
        await ctx.send("\n".join(lines))

    @game.command(name="reveal", description="公开本局所有玩家身份（投票结束后才能使用）")
    async def reveal(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        if game["status"] != "completed":
            await ctx.send("本局投票尚未结束，无法公开身份。", ephemeral=True)
            return
        teams, identities = self.db.get_teams_and_identities(game["id"])
        await ctx.send(messages.reveal_text(teams, identities))


async def setup(bot):
    await bot.add_cog(GameCog(bot))
