import discord
from discord import app_commands
from discord.ext import commands

from .. import config, game_logic, messages, mini_flow, views
from ..views import ConfirmActionView, IdentityRevealView, ManualTeamSelectView, VotingView


class MiniCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def _require_session(self, ctx):
        session = self.db.get_active_mini_session(ctx.guild.id)
        if session is None:
            raise RuntimeError("当前没有进行中的 Mini 名单，请先使用 /mini join 加入。")
        return session

    def _require_game(self, session):
        game = self.db.get_latest_mini_game(session["id"])
        if game is None:
            raise RuntimeError("当前 Mini 名单还没有开始任何游戏，请先使用 /mini start。")
        return game

    @commands.hybrid_group(name="mini", description="3v3 小局模式（不计分）")
    @commands.guild_only()
    async def mini(self, ctx: commands.Context):
        await ctx.send(
            "请使用 /mini join|leave|status|start|assign|result|"
            "closevote|resolvetie|cancel|reveal|end",
            ephemeral=True,
        )

    @mini.command(name="join", description="加入 Mini 3v3 名单")
    async def join(self, ctx: commands.Context):
        session = self.db.get_active_mini_session(ctx.guild.id)
        if session is None:
            session_id = self.db.create_mini_session(ctx.guild.id, ctx.channel.id)
            session = self.db.get_mini_session(session_id)
        self.db.join_mini_session(session["id"], ctx.author.id, ctx.author.display_name)
        count = len(self.db.get_mini_session_players(session["id"]))
        await ctx.send(
            f"{messages.JELLY} {ctx.author.display_name} 已加入 Mini 名单\n\n"
            f"当前人数: {count}/{config.MINI_GAME_SIZE}"
        )

    @mini.command(name="leave", description="离开 Mini 名单")
    async def leave(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        self.db.leave_mini_session(session["id"], ctx.author.id)
        await ctx.send(f"🌊 {ctx.author.display_name} 已离开 Mini 名单")

    @mini.command(name="kick", description="[管理] 将某玩家移出 Mini 名单")
    @app_commands.describe(member="要移出的玩家")
    async def kick(self, ctx: commands.Context, member: discord.Member):
        session = self.db.get_active_mini_session(ctx.guild.id)
        if session is None:
            await ctx.send("当前没有进行中的 Mini 名单。", ephemeral=True)
            return
        self.db.leave_mini_session(session["id"], member.id)
        await ctx.send(f"🌊 已将 {messages.mention(member.id)} 移出 Mini 名单")

    @mini.command(name="status", description="查看 Mini 名单")
    async def status(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return
        players = self.db.get_mini_session_players(session["id"])
        names = [self.db.name_or_id(p) for p in players]
        await ctx.send(messages.mini_status_text(names, config.MINI_GAME_SIZE))

    @mini.command(name="end", description="结束当前 Mini 名单（不创建新名单）")
    async def end(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return

        latest_game = self.db.get_latest_mini_game(session["id"])
        if latest_game is not None and latest_game["status"] not in config.TERMINAL_GAME_STATUSES:
            await ctx.send(
                f"上一局 (Mini #{latest_game['game_number']}) 还没有结束"
                f"（状态: {latest_game['status']}），请先用 /mini closevote、/mini override 或 "
                "/mini cancel 结束。",
                ephemeral=True,
            )
            return

        self.db.close_mini_session(ctx.guild.id)
        await ctx.send(f"{messages.JELLY} 已结束当前 Mini 名单。再次 /mini join 会开启新的名单。")

    def _check_can_start(self, ctx):
        """Shared by start/assign: active session, previous game
        (if any) is done, and the roster is exactly MINI_GAME_SIZE.
        Returns (session, players) on success, or sends the error and
        returns None."""
        try:
            session = self._require_session(ctx)
        except RuntimeError as e:
            return None, str(e)

        latest_game = self.db.get_latest_mini_game(session["id"])
        if latest_game is not None and latest_game["status"] not in config.TERMINAL_GAME_STATUSES:
            return None, (
                f"上一局 (Mini #{latest_game['game_number']}) 还没有结束"
                f"（状态: {latest_game['status']}），请先用 /mini closevote、/mini override 或 "
                "/mini cancel 结束。"
            )

        players = self.db.get_mini_session_players(session["id"])
        if len(players) != config.MINI_GAME_SIZE:
            return None, (
                f"Mini 需要恰好 {config.MINI_GAME_SIZE} 名玩家才能开始，"
                f"目前有 {len(players)} 人。"
            )
        return (session, players), None

    async def _launch_game(self, session, teams, reply):
        identities = game_logic.assign_mini_game_identities(teams)
        game_id, game_number = self.db.create_mini_game(session["id"])
        self.db.save_mini_team_assignment(game_id, teams, identities)

        view = IdentityRevealView(
            self.db, game_id, teams, identities,
            track_confirmation=False, card_text_fn=messages.mini_identity_card_text,
        )
        await reply(messages.team_announcement_text(game_number, teams, label="Mini"), view)

    @mini.command(name="start", description="开始新的一局 Mini 3v3（随机分队）")
    async def start(self, ctx: commands.Context):
        checked, error = self._check_can_start(ctx)
        if error:
            await ctx.send(error, ephemeral=True)
            return
        session, players = checked

        await ctx.defer()
        teams = game_logic.assign_teams(players, team_size=config.MINI_TEAM_SIZE)
        await self._launch_game(session, teams, lambda content, view: ctx.send(content, view=view))

    @mini.command(name="assign", description="手动指定队伍开始新的一局 Mini 3v3")
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
            team_size=config.MINI_TEAM_SIZE, on_submit=on_submit,
        )
        await ctx.send(
            f"请选择 {config.MINI_TEAM_SIZE} 人加入 🔴 A 队，"
            f"剩下 {config.MINI_TEAM_SIZE} 人自动加入 🔵 B 队。",
            view=view, ephemeral=True,
        )

    @mini.command(name="result", description="记录输方队伍并开始投票")
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

        winning = [t for t in config.TEAMS if t != losing][0]
        self.db.set_mini_game_result(game["id"], losing, winning)
        teams, identities = self.db.get_mini_teams_and_identities(game["id"])
        refreshed_game = self.db.get_mini_game(game["id"])
        _, _, targets = mini_flow.voters_and_targets(self.db, teams, identities, refreshed_game)
        view = VotingView(
            db=self.db, flow=mini_flow, channel=ctx.channel, guild=ctx.guild,
            session=session, game=refreshed_game, teams=teams, identities=identities,
            targets=targets,
        )
        roles_line = views.winning_roles_line(self.db, teams, identities, winning)
        message = await ctx.send(
            f"{messages.loss_result_line(losing, winning)}\n{roles_line}\n\n"
            "可以开始讨论，讨论结束后投票。",
            view=view,
        )
        self.db.set_mini_vote_message_id(game["id"], message.id)

    @mini.command(name="override", description="[管理] 直接宣布本局结果，跳过整个投票流程")
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
            await ctx.send("本局已经结束，无法再次宣布结果。", ephemeral=True)
            return

        losing = losing_team.upper()
        if losing not in config.TEAMS:
            await ctx.send(f"输方队伍必须是 {' 或 '.join(config.TEAMS)}。", ephemeral=True)
            return
        winning = [t for t in config.TEAMS if t != losing][0]

        teams, identities = self.db.get_mini_teams_and_identities(game["id"])
        eliminated = str(caught.id) if caught else None
        if eliminated is not None and eliminated not in teams[losing]:
            await ctx.send("被抓玩家必须是输方队伍成员。", ephemeral=True)
            return

        async def do_override(interaction):
            self.db.set_mini_game_result(game["id"], losing, winning)
            if eliminated:
                self.db.set_mini_eliminated(game["id"], eliminated)
            self.db.complete_mini_game(game["id"])

            category = game_logic.outcome_category(teams, identities, losing, eliminated)
            if eliminated:
                result_line = f"被抓: {self.db.name_or_id(eliminated)}\n\n{messages.outcome_text(category)}"
            else:
                result_line = messages.outcome_text(category)

            roles_line = views.winning_roles_line(self.db, teams, identities, winning)
            await interaction.followup.send(
                f"⚡ 管理员直接宣布结果\n{messages.loss_result_line(losing, winning)}\n"
                f"{roles_line}\n\n{result_line}"
            )

        view = ConfirmActionView(ctx.author.id, do_override)
        await ctx.send(
            f"⚠️ 即将直接宣布结果并跳过投票流程:\n{messages.loss_result_line(losing, winning)}\n\n确定吗？",
            view=view, ephemeral=True,
        )

    @mini.command(name="closevote", description="结束当前一轮投票并进入下一阶段")
    async def closevote(self, ctx: commands.Context):
        try:
            session = self._require_session(ctx)
            game = self._require_game(session)
        except RuntimeError as e:
            await ctx.send(str(e), ephemeral=True)
            return

        if game["status"] not in ("voting_round1", "voting_round2"):
            await ctx.send(
                f"当前状态 ({game['status']}) 不是可结束的投票阶段。", ephemeral=True
            )
            return

        teams, identities = self.db.get_mini_teams_and_identities(game["id"])

        async def do_closevote(interaction):
            round_no, _, _ = mini_flow.voters_and_targets(self.db, teams, identities, game)
            try:
                msg = mini_flow.resolve_current_round(self.db, game, teams, identities)
            except game_logic.VoteError as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return
            if msg is None:
                await interaction.followup.send("这一轮还没有人投票。", ephemeral=True)
                return
            await views.apply_round_result(
                db=self.db, flow=mini_flow, channel=ctx.channel, guild=ctx.guild,
                session=session, game=game, teams=teams, identities=identities,
                round_no=round_no, result=msg,
            )

        view = ConfirmActionView(ctx.author.id, do_closevote)
        await ctx.send(
            "⚠️ 即将提前结束本轮投票，只计算已投票的人。确定吗？", view=view, ephemeral=True
        )

    @mini.command(name="resolvetie", description="手动裁定投票结果，跳过自动重新投票")
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

        teams, identities = self.db.get_mini_teams_and_identities(game["id"])
        eliminated = str(player.id)

        async def do_resolvetie(interaction):
            self.db.set_mini_eliminated(game["id"], eliminated)
            self.db.complete_mini_game(game["id"])
            category = game_logic.outcome_category(
                teams, identities, game["losing_team"], eliminated
            )
            await interaction.followup.send(
                f"被裁定为卧底: {self.db.name_or_id(eliminated)}\n\n{messages.outcome_text(category)}"
            )

        view = ConfirmActionView(ctx.author.id, do_resolvetie)
        await ctx.send(
            f"⚠️ 即将裁定 {self.db.name_or_id(eliminated)} 为卧底，结束本局。确定吗？",
            view=view, ephemeral=True,
        )

    @mini.command(name="cancel", description="[管理] 取消本局 Mini，不计入记录")
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
            self.db.set_mini_game_status(game["id"], "cancelled")
            content = f"🌊 Mini #{game['game_number']} 已取消，不计入记录。"
            message = await views.clear_vote_message(self.db, mini_flow, ctx.channel, game["id"], content)
            if message is None:
                await interaction.followup.send(content)

        view = ConfirmActionView(ctx.author.id, do_cancel)
        await ctx.send(
            f"⚠️ 即将取消 Mini #{game['game_number']}，不计入记录。确定吗？",
            view=view, ephemeral=True,
        )

    @mini.command(name="reveal", description="公开本局所有玩家身份（投票结束后才能使用）")
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
        teams, identities = self.db.get_mini_teams_and_identities(game["id"])
        await ctx.send(
            messages.reveal_text(teams, identities, game["losing_team"], game["winning_team"])
        )
        category = game_logic.outcome_category(
            teams, identities, game["losing_team"], game["eliminated_player"]
        )
        await ctx.send(messages.outcome_text(category))


async def setup(bot):
    await bot.add_cog(MiniCog(bot))
