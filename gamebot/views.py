import discord

from . import config, game_flow, game_logic, messages, mini_flow


class ConfirmView(discord.ui.View):
    """DM'd alongside a special-identity card; player taps to confirm they
    understand their role. Not persisted across bot restarts (acceptable for
    a locally-run, single-process bot)."""

    def __init__(self, db, game_id, player_id):
        super().__init__(timeout=None)
        self.db = db
        self.game_id = game_id
        self.player_id = player_id

    @discord.ui.button(label=f"{messages.JELLY} 已确认身份", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("这不是你的身份卡。", ephemeral=True)
            return
        self.db.set_confirmed(self.game_id, self.player_id)
        button.disabled = True
        button.label = f"{messages.JELLY} 已确认"
        await interaction.response.edit_message(view=self)


class IdentityRevealView(discord.ui.View):
    """Attached to the team-announcement message. Each player clicks once
    to privately reveal their card; for undercover/dummy that same click
    doubles as confirmation, replacing the old DM'd card + in-DM confirm
    button with a single step. Not persisted across bot restarts (same
    accepted limitation as ConfirmView)."""

    def __init__(self, db, game_id, teams, identities, track_confirmation, card_text_fn, session=None):
        super().__init__(timeout=None)
        self.db = db
        self.game_id = game_id
        self.teams = teams
        self.identities = identities
        self.track_confirmation = track_confirmation
        self.card_text_fn = card_text_fn
        self.session = session
        self._announced = False

    def _team_of(self, player_id):
        for team, player_ids in self.teams.items():
            if player_id in player_ids:
                return team
        return None

    @discord.ui.button(label="🎴 查看身份卡", style=discord.ButtonStyle.primary)
    async def reveal(self, interaction: discord.Interaction, button: discord.ui.Button):
        player_id = str(interaction.user.id)
        team = self._team_of(player_id)
        if team is None:
            await interaction.response.send_message("你不在本局游戏中。", ephemeral=True)
            return

        identity = self.identities[player_id]
        await interaction.response.send_message(
            self.card_text_fn(team, identity), ephemeral=True
        )

        if not self.track_confirmation or identity not in config.IDENTITIES_NEEDING_CONFIRMATION:
            return

        self.db.set_confirmed(self.game_id, player_id)
        if self._announced:
            return

        confirmed_ids = {
            row["player_id"] for row in self.db.get_game_players(self.game_id) if row["confirmed"]
        }
        confirmed, needed = game_logic.confirmation_status(self.identities, confirmed_ids)
        if confirmed >= needed:
            self._announced = True
            loss_view = LossDeclareView(
                db=self.db, channel=interaction.channel, guild=interaction.guild,
                session=self.session, game_id=self.game_id, teams=self.teams,
                identities=self.identities,
            )
            await interaction.message.edit(
                content=f"{interaction.message.content}\n\n{messages.all_confirmed_line()}",
                view=loss_view,
            )


class LossDeclareView(discord.ui.View):
    """Replaces IdentityRevealView on the team-announcement message once
    every special identity is confirmed (ranked only -- mini has no
    confirmation gate to wait for, so it keeps the typed /mini result
    path only). Clicking a team's button turns this same message into
    the round-1 voting message, no new message needed. Not persisted
    across bot restarts (same accepted limitation as the other views)."""

    def __init__(self, *, db, channel, guild, session, game_id, teams, identities):
        super().__init__(timeout=None)
        self.db = db
        self.channel = channel
        self.guild = guild
        self.session = session
        self.game_id = game_id
        self.teams = teams
        self.identities = identities

        for losing in config.TEAMS:
            winning = [t for t in config.TEAMS if t != losing][0]
            emoji = messages.TEAM_EMOJI.get(losing, losing)
            button = discord.ui.Button(
                label=f"{emoji} {losing} 落败", style=discord.ButtonStyle.danger
            )
            button.callback = self._make_callback(losing, winning)
            self.add_item(button)

    def _make_callback(self, losing, winning):
        async def callback(interaction):
            game = self.db.get_game(self.game_id)
            if game["status"] != "confirming":
                await interaction.response.send_message("本局结果已经记录过了。", ephemeral=True)
                return

            self.db.set_game_result(self.game_id, losing, winning)
            refreshed_game = self.db.get_game(self.game_id)
            _, _, targets = game_flow.voters_and_targets(
                self.db, self.teams, self.identities, refreshed_game
            )
            voting_view = VotingView(
                db=self.db, flow=game_flow, channel=self.channel, guild=self.guild,
                session=self.session, game=refreshed_game, teams=self.teams,
                identities=self.identities, targets=targets,
            )
            content = (
                f"{interaction.message.content}\n\n"
                f"{messages.loss_result_line(losing, winning)}\n\n可以开始讨论，讨论结束后投票。"
            )
            await interaction.response.edit_message(content=content, view=voting_view)
            self.db.set_vote_message_id(self.game_id, interaction.message.id)
        return callback


class VotingView(discord.ui.View):
    """Attached to the current round's message. One button per eligible
    target; clicking funnels through cast_vote, the same path the typed
    /vote command uses, so buttons and /vote can never disagree about
    state. Not persisted across bot restarts (same accepted limitation as
    ConfirmView/IdentityRevealView)."""

    def __init__(self, *, db, flow, channel, guild, session, game, teams, identities, targets):
        super().__init__(timeout=None)
        self.db = db
        self.flow = flow
        self.channel = channel
        self.guild = guild
        self.session = session
        self.game = game
        self.teams = teams
        self.identities = identities

        for target_id in sorted(targets):
            member = guild.get_member(int(target_id))
            label = member.display_name if member else target_id
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            button.callback = self._make_callback(target_id)
            self.add_item(button)

    def _make_callback(self, target_id):
        async def callback(interaction):
            async def reply(content, ephemeral=False):
                await interaction.response.send_message(content, ephemeral=ephemeral)

            await cast_vote(
                db=self.db, flow=self.flow, channel=self.channel, guild=self.guild,
                session=self.session, game=self.game, teams=self.teams,
                identities=self.identities, voter_id=str(interaction.user.id),
                target_id=target_id, reply=reply,
            )
        return callback


def _mode_ops(flow):
    if flow is game_flow:
        return dict(
            record_vote=lambda db, *a: db.record_vote(*a),
            get_votes=lambda db, *a: db.get_votes(*a),
            set_vote_message_id=lambda db, *a: db.set_vote_message_id(*a),
            get_game=lambda db, gid: db.get_game(gid),
            closevote_cmd="/game closevote",
        )
    return dict(
        record_vote=lambda db, *a: db.record_mini_vote(*a),
        get_votes=lambda db, *a: db.get_mini_votes(*a),
        set_vote_message_id=lambda db, *a: db.set_mini_vote_message_id(*a),
        get_game=lambda db, gid: db.get_mini_game(gid),
        closevote_cmd="/mini closevote",
    )


async def cast_vote(*, db, flow, channel, guild, session, game, teams, identities,
                     voter_id, target_id, reply):
    """Validate, record, and reflect one vote. Shared by VotingView's
    buttons and the typed /vote command (gamebot/cogs/voting.py) so there
    is exactly one path that can mutate vote state."""
    ops = _mode_ops(flow)
    round_no, voters, targets = flow.voters_and_targets(db, teams, identities, game)

    try:
        game_logic.validate_vote(voter_id, target_id, voters, targets)
    except game_logic.VoteError as e:
        options = ", ".join(messages.mention(t) for t in targets) or "无"
        await reply(f"⚠️ {e}\n\n可投对象: {options}", ephemeral=True)
        return

    ops["record_vote"](db, game["id"], round_no, voter_id, target_id)
    votes = ops["get_votes"](db, game["id"], round_no)
    await reply(
        f"{messages.JELLY} 已记录你的第 {round_no} 轮投票 ({len(votes)}/{len(voters)})",
        ephemeral=True,
    )

    message_id = db.get_vote_message_id(game["id"]) if flow is game_flow \
        else db.get_mini_vote_message_id(game["id"])
    message = await channel.fetch_message(int(message_id)) if message_id else None
    if message is None:
        return

    if len(votes) < len(voters):
        # No `view=` kwarg: Message.edit() leaves existing components
        # untouched when the param is omitted, which is what we want here
        # (only the status text changes; the vote buttons stay as-is).
        await message.edit(content=messages.vote_status_text(round_no, len(votes), len(voters)))
        return

    try:
        if flow is game_flow:
            result = game_flow.resolve_current_round(db, session, game, teams, identities)
        else:
            result = mini_flow.resolve_current_round(db, game, teams, identities)
    except game_logic.VoteError as e:
        await message.edit(content=f"⚠️ 自动结算失败，请使用 {ops['closevote_cmd']} 处理: {e}", view=None)
        return

    if result is None:
        return

    refreshed_game = ops["get_game"](db, game["id"])
    content = f"{messages.JELLY} 全员已投票，自动结算第 {round_no} 轮:\n\n{result}"
    if refreshed_game["status"] in ("voting_round1", "voting_round2"):
        _, _, next_targets = flow.voters_and_targets(db, teams, identities, refreshed_game)
        next_view = VotingView(
            db=db, flow=flow, channel=channel, guild=guild, session=session,
            game=refreshed_game, teams=teams, identities=identities, targets=next_targets,
        )
        await message.edit(content=content, view=next_view)
        ops["set_vote_message_id"](db, refreshed_game["id"], message.id)
    else:
        await message.edit(content=content, view=None)
