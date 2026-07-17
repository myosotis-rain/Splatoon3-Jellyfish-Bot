import discord
from discord import app_commands
from discord.ext import commands

from .. import messages


class SessionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def _active_game_in_progress(self, ctx):
        """The active session's latest game, if it exists and isn't
        completed yet -- used to guard against silently orphaning an
        in-progress game when creating/reopening a session."""
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            return None
        game = self.db.get_latest_game(session["id"])
        if game is not None and game["status"] != "completed":
            return game
        return None

    @commands.hybrid_group(name="session", description="管理游戏活动场次")
    @commands.guild_only()
    async def session(self, ctx: commands.Context):
        await ctx.send(
            "请使用 /session create|join|leave|leaderboard|status|list|reopen|end", ephemeral=True
        )

    @session.command(name="create", description="创建新的游戏活动场次")
    @app_commands.describe(name="场次名称，例如 2026-07-16 Game Night")
    async def create(self, ctx: commands.Context, *, name: str = None):
        existing = self.db.get_active_session(ctx.guild.id)
        if existing is not None:
            title = existing["name"] or f"Session #{existing['id']}"
            await ctx.send(
                f"⚠️ 当前已有进行中的场次: {title}\n"
                "请先使用 /session end 结束该场次，再创建新场次。",
                ephemeral=True,
            )
            return
        session_id = self.db.create_session(ctx.guild.id, ctx.channel.id, name)
        title = name or f"Session #{session_id}"
        await ctx.send(f"{messages.JELLY} 已创建场次: {title}")

    @session.command(name="join", description="加入当前场次")
    async def join(self, ctx: commands.Context):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            await ctx.send(
                "当前没有进行中的场次，请先使用 /session create 创建。", ephemeral=True
            )
            return
        self.db.join_session(session["id"], ctx.author.id, str(ctx.author))
        count = len(self.db.get_session_players(session["id"]))
        await ctx.send(
            f"{messages.JELLY} {ctx.author.display_name} 已加入本次活动\n\n当前参与人数:\n{count}"
        )

    @session.command(name="leave", description="离开当前场次（保留历史积分）")
    async def leave(self, ctx: commands.Context):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            await ctx.send("当前没有进行中的场次。", ephemeral=True)
            return
        self.db.leave_session(session["id"], ctx.author.id)
        await ctx.send(f"👋 {ctx.author.display_name} 已离开本次活动")

    @session.command(name="leaderboard", description="查看本次活动排行榜")
    async def leaderboard(self, ctx: commands.Context):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            await ctx.send("当前没有进行中的场次。", ephemeral=True)
            return
        board = self.db.get_session_leaderboard(session["id"])
        await ctx.send(messages.leaderboard_text(board))

    @session.command(name="status", description="查看当前场次状态")
    async def status(self, ctx: commands.Context):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            await ctx.send("当前没有进行中的场次。", ephemeral=True)
            return
        players = self.db.get_session_players(session["id"])
        title = session["name"] or f"Session #{session['id']}"
        await ctx.send(messages.session_status_text(title, players))

    @session.command(name="list", description="列出本服务器的所有场次（含已结束的）")
    async def list_sessions(self, ctx: commands.Context):
        sessions = self.db.get_sessions(ctx.guild.id)
        entries = [(s, len(self.db.get_session_players(s["id"]))) for s in sessions]
        await ctx.send(messages.session_list_text(entries))

    @session.command(name="reopen", description="重新激活一个已结束的场次")
    @app_commands.describe(session_id="要重新激活的场次编号（见 /session list）")
    async def reopen(self, ctx: commands.Context, session_id: int):
        target = self.db.get_session(session_id)
        if target is None or str(target["server_id"]) != str(ctx.guild.id):
            await ctx.send("找不到该场次编号，请用 /session list 查看。", ephemeral=True)
            return
        if target["status"] == "active":
            await ctx.send("该场次已经是进行中的场次。", ephemeral=True)
            return

        blocking_game = self._active_game_in_progress(ctx)
        if blocking_game:
            await ctx.send(
                f"⚠️ 当前场次还有未结束的游戏 (Game #{blocking_game['game_number']}, "
                f"状态: {blocking_game['status']})，请先用 /game closevote 或 /game override "
                "结束，再切换场次。",
                ephemeral=True,
            )
            return

        self.db.reopen_session(ctx.guild.id, session_id)
        title = target["name"] or f"Session #{session_id}"
        await ctx.send(f"{messages.JELLY} 已重新激活场次: {title}")

    @session.command(name="end", description="结束当前场次（不创建新场次）")
    async def end(self, ctx: commands.Context):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            await ctx.send("当前没有进行中的场次。", ephemeral=True)
            return

        blocking_game = self._active_game_in_progress(ctx)
        if blocking_game:
            await ctx.send(
                f"⚠️ 当前场次还有未结束的游戏 (Game #{blocking_game['game_number']}, "
                f"状态: {blocking_game['status']})，请先用 /game closevote 或 /game override "
                "结束。",
                ephemeral=True,
            )
            return

        self.db.close_session(ctx.guild.id)
        title = session["name"] or f"Session #{session['id']}"
        await ctx.send(
            f"{messages.JELLY} 已结束场次: {title}\n\n可用 /session list 查看历史，/session reopen 重新激活。"
        )

    @commands.hybrid_command(name="rename", description="设置你在本 Bot 中显示的名字（用于排行榜等，账号级别，不分场次）")
    @app_commands.describe(name="新的显示名称")
    async def rename(self, ctx: commands.Context, *, name: str):
        self.db.upsert_player(ctx.author.id, name)
        await ctx.send(f"{messages.JELLY} 已将你的显示名称设置为: {name}")

    @session.command(name="kick", description="[管理] 将某玩家移出本场次（保留历史积分）")
    @app_commands.describe(member="要移出的玩家")
    async def kick(self, ctx: commands.Context, member: discord.Member):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            await ctx.send("当前没有进行中的场次。", ephemeral=True)
            return
        self.db.leave_session(session["id"], member.id)
        await ctx.send(f"👋 已将 {messages.mention(member.id)} 移出本次活动")

    @session.command(name="adjustscore", description="[管理] 调整某玩家在本场次的总分")
    @app_commands.describe(member="要调整的玩家", delta="加减分数，可为负数")
    async def adjustscore(self, ctx: commands.Context, member: discord.Member, delta: int):
        session = self.db.get_active_session(ctx.guild.id)
        if session is None:
            await ctx.send("当前没有进行中的场次。", ephemeral=True)
            return
        row = self.db.get_session_player_row(session["id"], member.id)
        if row is None:
            await ctx.send(f"{member.display_name} 还没有加入本场次。", ephemeral=True)
            return
        self.db.adjust_score(session["id"], member.id, delta)
        updated = self.db.get_session_player_row(session["id"], member.id)
        await ctx.send(
            f"{messages.JELLY} 已调整 {messages.mention(member.id)} 的积分 ({delta:+d})\n"
            f"当前总分: {updated['total_score']}"
        )


async def setup(bot):
    await bot.add_cog(SessionCog(bot))
