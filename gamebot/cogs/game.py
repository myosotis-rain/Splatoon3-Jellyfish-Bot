import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from .. import config, game_flow, game_logic, messages, views
from ..views import ConfirmActionView, IdentityRevealView, ManualTeamSelectView, VotingView


class GameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def _require_session(self, ctx):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            raise RuntimeError("当前没有进行中的场次，请先使用 /session start 创建。")
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
            "请使用 /game start|assign|status|confirmations|forceconfirm|result|"
            "closevote|resolvetie|cancel|reveal",
            ephemeral=True,
        )

    @game.command(name="testidentity", description="[测试] 预览随机身份卡样式，不影响任何场次/游戏")
    @app_commands.describe(mode="卧底游戏 (ranked) 还是 Mini 3v3 (mini) 的卡面格式")
    async def testidentity(self, ctx: commands.Context, mode: Literal["ranked", "mini"] = "ranked"):
        team = random.choice(config.TEAMS)
        player_id = str(ctx.author.id)
        if mode == "mini":
            identity = random.choice([config.IDENTITY_UNDERCOVER, config.IDENTITY_GOOD])
            card_text_fn = messages.mini_identity_card_text
            track_confirmation = False
        else:
            identity = random.choice(
                [config.IDENTITY_UNDERCOVER, config.IDENTITY_DUMMY, config.IDENTITY_GOOD]
            )
            card_text_fn = messages.identity_card_text
            track_confirmation = True

        # game_id=0 is a sentinel that can never match a real game (ids are
        # autoincrement from 1), so set_confirmed/get_game_players below are
        # harmless no-ops -- this reuses the exact same view real games use.
        view = IdentityRevealView(
            self.db, 0, {team: [player_id]}, {player_id: identity},
            track_confirmation=track_confirmation, card_text_fn=card_text_fn,
        )
        await ctx.send(
            f"[测试] 点击下方按钮查看身份卡样式 ({mode})，不影响任何场次/游戏",
            view=view, ephemeral=True,
        )

    def _check_can_start(self, ctx):
        """Shared by start/assign: active session, previous game
        (if any) is done, and the roster is exactly GAME_SIZE. Returns
        (session, players) on success, or sends the error and returns None."""
        try:
            session = self._require_session(ctx)
        except RuntimeError as e:
            return None, str(e)

        latest_game = self.db.get_latest_game(session["id"])
        if latest_game is not None and latest_game["status"] not in config.TERMINAL_GAME_STATUSES:
            return None, (
                f"上一局 (Game #{latest_game['game_number']}) 还没有结束"
                f"（状态: {latest_game['status']}），请先用 /game closevote、/game override 或 "
                "/game cancel 结束。"
            )

        players = self.db.get_session_players(session["id"])
        if len(players) != config.GAME_SIZE:
            return None, (
                f"当前场次需要恰好 {config.GAME_SIZE} 名玩家才能开始游戏，"
                f"目前有 {len(players)} 人。"
            )
        return (session, players), None

    async def _launch_game(self, session, teams, reply):
        """reply(content, view): however the caller wants to deliver the
        team announcement -- ctx.send for /game start, an interaction
        followup for /game assign's dropdown submission."""
        identities = game_logic.assign_game_identities(teams)
        game_id, game_number = self.db.create_game(session["id"])
        self.db.save_team_assignment(game_id, teams, identities)
        self.db.set_game_status(game_id, "confirming")

        view = IdentityRevealView(
            self.db, game_id, teams, identities,
            track_confirmation=True, card_text_fn=messages.identity_card_text,
            session=session,
        )
        names = {p: self.db.name_or_id(p) for players in teams.values() for p in players}
        await reply(messages.team_announcement_text(game_number, teams, names), view)

    @game.command(name="start", description="开始新的一局游戏（随机分队）")
    async def start(self, ctx: commands.Context):
        checked, error = self._check_can_start(ctx)
        if error:
            await ctx.send(error, ephemeral=True)
            return
        session, players = checked

        await ctx.defer()
        teams = game_logic.assign_teams(players)
        await self._launch_game(session, teams, lambda content, view: ctx.send(content, view=view))

    @game.command(name="assign", description="手动指定队伍开始新的一局游戏")
    async def assign(self, ctx: commands.Context):
        checked, error = self._check_can_start(ctx)
        if error:
            await ctx.send(error, ephemeral=True)
            return
        session, players = checked
        names = {p: self.db.name_or_id(p) for p in players}

        async def on_submit(interaction, teams):
            await interaction.response.defer()
            await self._launch_game(
                session, teams,
                lambda content, view: interaction.followup.send(content, view=view),
            )

        view = ManualTeamSelectView(
            invoker_id=ctx.author.id, players=players, names=names,
            team_size=config.TEAM_SIZE, on_submit=on_submit,
        )
        await ctx.send(
            "可选：指定特定人选到 🔴 A 队和/或 🔵 B 队，其余人自动随机分配到两队"
            "（全部不选则完全随机）。",
            view=view, ephemeral=True,
        )

    @game.command(name="status", description="查看当前游戏状态")
    async def status(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        await ctx.send(f"✦ Game #{game['game_number']}　状态: {game['status']}")

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

    @game.command(name="forceconfirm", description="[管理] 强制将本局所有特殊身份标记为已确认")
    async def forceconfirm(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        _, identities = self.db.get_teams_and_identities(game["id"])
        for player_id, identity in identities.items():
            if identity in config.IDENTITIES_NEEDING_CONFIRMATION:
                self.db.set_confirmed(game["id"], player_id)
        await ctx.send(
            f"{messages.JELLY} 已强制标记全部特殊身份为已确认，可以使用 /game result 开始投票。"
        )

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

        teams, identities = self.db.get_teams_and_identities(game["id"])
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
        refreshed_game = self.db.get_game(game["id"])
        _, _, targets = game_flow.voters_and_targets(self.db, teams, identities, refreshed_game)
        view = VotingView(
            db=self.db, flow=game_flow, channel=ctx.channel, guild=ctx.guild,
            session=session, game=refreshed_game, teams=teams, identities=identities,
            targets=targets,
        )
        roles_line = views.winning_roles_line(self.db, teams, identities, winning)
        message = await ctx.send(
            f"{messages.loss_result_line(losing, winning)}\n{roles_line}\n\n"
            "可以开始讨论，讨论结束后投票。",
            view=view,
        )
        self.db.set_vote_message_id(game["id"], message.id)

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
        if game["status"] in config.TERMINAL_GAME_STATUSES:
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

        async def do_override(interaction):
            self.db.set_game_result(game["id"], losing, winning)
            if eliminated:
                self.db.set_eliminated(game["id"], eliminated)
            scores = game_logic.calculate_scores(
                teams=teams,
                identities=identities,
                losing_team=losing,
                winning_team=winning,
                eliminated_player=eliminated,
                final_round_votes={},
            )
            self.db.finalize_scores(session["id"], game["id"], scores)

            roles_line = views.winning_roles_line(self.db, teams, identities, winning)
            lines = [
                f"⚡ 管理员直接宣布结果\n{messages.loss_result_line(losing, winning)}\n{roles_line}\n"
            ]
            if eliminated:
                lines.append(f"被抓: {self.db.name_or_id(eliminated)}\n")
            lines.append("本局积分:")
            for player_id, score in scores.items():
                lines.append(f"{self.db.name_or_id(player_id)}: {score:+d}")
            await interaction.followup.send("\n".join(lines))

        caught_line = f"\n被抓: {self.db.name_or_id(eliminated)}" if eliminated else ""
        view = ConfirmActionView(ctx.author.id, do_override)
        await ctx.send(
            f"⚠️ 即将直接宣布结果并跳过投票流程:\n{messages.loss_result_line(losing, winning)}"
            f"{caught_line}\n\n确定吗？",
            view=view, ephemeral=True,
        )

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

        async def do_closevote(interaction):
            round_no, _, _ = game_flow.voters_and_targets(self.db, teams, identities, game)
            try:
                msg = game_flow.resolve_current_round(self.db, session, game, teams, identities)
            except game_logic.VoteError as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return
            if msg is None:
                await interaction.followup.send("这一轮还没有人投票。", ephemeral=True)
                return
            await views.apply_round_result(
                db=self.db, flow=game_flow, channel=ctx.channel, guild=ctx.guild,
                session=session, game=game, teams=teams, identities=identities,
                round_no=round_no, result=msg,
            )

        view = ConfirmActionView(ctx.author.id, do_closevote)
        await ctx.send(
            "⚠️ 即将提前结束本轮投票，只计算已投票的人。确定吗？", view=view, ephemeral=True
        )

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

        async def do_resolvetie(interaction):
            self.db.set_eliminated(game["id"], eliminated)
            final_round_votes = self.db.get_votes(
                game["id"], self.db.get_current_round(game["id"])
            )
            scores = game_logic.calculate_scores(
                teams=teams,
                identities=identities,
                losing_team=game["losing_team"],
                winning_team=game["winning_team"],
                eliminated_player=eliminated,
                final_round_votes=final_round_votes,
            )
            self.db.finalize_scores(session["id"], game["id"], scores)
            lines = [f"被裁定为卧底: {self.db.name_or_id(eliminated)}\n", "本局积分:"]
            for pid, score in scores.items():
                lines.append(f"{self.db.name_or_id(pid)}: {score:+d}")
            await interaction.followup.send("\n".join(lines))

        view = ConfirmActionView(ctx.author.id, do_resolvetie)
        await ctx.send(
            f"⚠️ 即将裁定 {self.db.name_or_id(eliminated)} 为卧底，直接计分。确定吗？",
            view=view, ephemeral=True,
        )

    @game.command(name="cancel", description="[管理] 取消本局游戏，不计分且不计入记录")
    async def cancel(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        if game["status"] in config.TERMINAL_GAME_STATUSES:
            await ctx.send("本局已经结束。", ephemeral=True)
            return

        async def do_cancel(interaction):
            self.db.set_game_status(game["id"], "cancelled")
            content = f"🌊 Game #{game['game_number']} 已取消，不计分。"
            message = await views.clear_vote_message(self.db, game_flow, ctx.channel, game["id"], content)
            if message is None:
                await interaction.followup.send(content)

        view = ConfirmActionView(ctx.author.id, do_cancel)
        await ctx.send(
            f"⚠️ 即将取消 Game #{game['game_number']}，不计分且不计入记录。确定吗？",
            view=view, ephemeral=True,
        )

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
        await ctx.send(
            messages.reveal_text(teams, identities, game["losing_team"], game["winning_team"])
        )
        category = game_logic.outcome_category(
            teams, identities, game["losing_team"], game["eliminated_player"]
        )
        await ctx.send(messages.outcome_text(category))


async def setup(bot):
    await bot.add_cog(GameCog(bot))
