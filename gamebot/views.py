import discord

from . import config, game_flow, game_logic, messages, mini_flow


def winning_roles_line(db, teams, identities, winning_team):
    """Shared by game.py/mini.py's result/override and LossDeclareView so
    the winning team's special roles are announced consistently wherever
    a game result first gets declared."""
    undercover_id = game_logic.find_undercover(teams, identities, winning_team)
    dummy_id = game_logic.find_player_with_identity(
        teams, identities, winning_team, config.IDENTITY_DUMMY
    )
    return messages.winning_special_roles_line(
        winning_team,
        db.name_or_id(undercover_id),
        db.name_or_id(dummy_id) if dummy_id else None,
    )


class ManualTeamSelectView(discord.ui.View):
    """Ephemeral UI shown to the host running /game assign or /mini
    assign. Two independent dropdowns -- pin down 0 to team_size
    specific players per team -- populated with only the current roster
    (never the whole server), plus a confirm button. Anyone left
    unpicked in either dropdown is randomly split to fill both teams to
    team_size (game_logic.assign_teams_partial), so leaving both empty
    is equivalent to a fully random /game start, and filling both
    completely is equivalent to the old fully-manual assignment."""

    def __init__(self, *, invoker_id, players, names, team_size, on_submit):
        super().__init__(timeout=180)
        self.invoker_id = invoker_id
        self.players = players
        self.names = names
        self.team_size = team_size
        self.on_submit = on_submit
        self.picked_a = []
        self.picked_b = []

        def make_options():
            return [discord.SelectOption(label=names.get(p, p)[:100], value=p) for p in players]

        self.select_a = discord.ui.Select(
            placeholder=f"（可选）指定最多 {team_size} 人加入 🔴 A 队",
            min_values=0, max_values=team_size, options=make_options(),
        )
        self.select_a.callback = self._make_select_callback("A", self.select_a)
        self.add_item(self.select_a)

        self.select_b = discord.ui.Select(
            placeholder=f"（可选）指定最多 {team_size} 人加入 🔵 B 队",
            min_values=0, max_values=team_size, options=make_options(),
        )
        self.select_b.callback = self._make_select_callback("B", self.select_b)
        self.add_item(self.select_b)

        confirm_button = discord.ui.Button(label="✦ 确认分队", style=discord.ButtonStyle.success)
        confirm_button.callback = self._on_confirm
        self.add_item(confirm_button)

    def _make_select_callback(self, which, select):
        async def callback(interaction):
            if interaction.user.id != self.invoker_id:
                await interaction.response.send_message("只有发起者可以选择。", ephemeral=True)
                return
            if which == "A":
                self.picked_a = list(select.values)
            else:
                self.picked_b = list(select.values)
            await interaction.response.defer()
        return callback

    async def _on_confirm(self, interaction):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("只有发起者可以确认。", ephemeral=True)
            return
        overlap = set(self.picked_a) & set(self.picked_b)
        if overlap:
            overlap_names = ", ".join(self.names.get(p, p) for p in overlap)
            await interaction.response.send_message(
                f"⚠️ 不能同时指定到两队: {overlap_names}，请重新选择。", ephemeral=True
            )
            return
        teams = game_logic.assign_teams_partial(
            self.players, self.picked_a, self.picked_b, team_size=self.team_size
        )
        await self.on_submit(interaction, teams)


class IdentitySelectView(discord.ui.View):
    """Step 2 of /game assign or /mini assign, shown once teams are
    already finalized: optionally pin down each team's undercover (and
    dummy, ranked only) from within that team's now-fixed roster.
    Anything left unpicked is randomly assigned from the remaining
    roles (game_logic.assign_game_identities_partial /
    assign_mini_game_identities_partial), so leaving every dropdown
    empty is fully random, same as today's default.

    Discord limits a View to 5 action rows and a select menu always
    takes a full row, so this is exactly at the ceiling with dummy
    selects included (2 teams x 2 roles = 4 selects + 1 confirm
    button); without dummy (Mini) it's 2 selects + 1 button."""

    def __init__(self, *, invoker_id, teams, names, include_dummy, on_submit):
        super().__init__(timeout=180)
        self.invoker_id = invoker_id
        self.teams = teams
        self.include_dummy = include_dummy
        self.on_submit = on_submit
        self.picks = {team: {"undercover": None, "dummy": None} for team in teams}

        for team, player_ids in teams.items():
            emoji = messages.TEAM_EMOJI.get(team, team)
            options = [
                discord.SelectOption(label=names.get(p, p)[:100], value=p) for p in player_ids
            ]

            undercover_select = discord.ui.Select(
                placeholder=f"（可选）指定 {emoji} {team} 队的卧底", min_values=0, max_values=1,
                options=options,
            )
            undercover_select.callback = self._make_callback(team, "undercover", undercover_select)
            self.add_item(undercover_select)

            if include_dummy:
                dummy_select = discord.ui.Select(
                    placeholder=f"（可选）指定 {emoji} {team} 队的呆呆鱿", min_values=0, max_values=1,
                    options=options,
                )
                dummy_select.callback = self._make_callback(team, "dummy", dummy_select)
                self.add_item(dummy_select)

        confirm_button = discord.ui.Button(label="✦ 确认身份", style=discord.ButtonStyle.success)
        confirm_button.callback = self._on_confirm
        self.add_item(confirm_button)

    def _make_callback(self, team, role, select):
        async def callback(interaction):
            if interaction.user.id != self.invoker_id:
                await interaction.response.send_message("只有发起者可以选择。", ephemeral=True)
                return
            self.picks[team][role] = select.values[0] if select.values else None
            await interaction.response.defer()
        return callback

    async def _on_confirm(self, interaction):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("只有发起者可以确认。", ephemeral=True)
            return
        for team, picks in self.picks.items():
            if picks["undercover"] and picks["dummy"] and picks["undercover"] == picks["dummy"]:
                await interaction.response.send_message(
                    f"⚠️ {team} 队的卧底和呆呆鱿不能是同一人，请重新选择。", ephemeral=True
                )
                return
        await self.on_submit(interaction, self.picks)


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


class ConfirmActionView(discord.ui.View):
    """Generic confirm/cancel gate in front of one-shot, hard-to-reverse
    admin actions (override, closevote, resolvetie). Only the invoker can
    confirm or cancel, and the action runs at most once. Not persisted
    across bot restarts (same accepted limitation as the other views)."""

    def __init__(self, invoker_id, on_confirm):
        super().__init__(timeout=None)
        self.invoker_id = invoker_id
        self.on_confirm = on_confirm
        self._done = False

    async def _guard(self, interaction):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("只有发起者可以确认/取消。", ephemeral=True)
            return False
        if self._done:
            await interaction.response.send_message("已经处理过了。", ephemeral=True)
            return False
        self._done = True
        return True

    @discord.ui.button(label="✦ 确认执行", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await self.on_confirm(interaction)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="已取消。", view=self)


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
            roles_line = winning_roles_line(self.db, self.teams, self.identities, winning)
            content = (
                f"{interaction.message.content}\n\n"
                f"{messages.loss_result_line(losing, winning)}\n{roles_line}\n\n"
                "可以开始讨论，讨论结束后投票。"
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
            label = db.get_username(target_id)
            if label is None:
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


async def _fetch_vote_message(db, flow, channel, game_id):
    message_id = db.get_vote_message_id(game_id) if flow is game_flow \
        else db.get_mini_vote_message_id(game_id)
    if message_id is None:
        return None
    return await channel.fetch_message(int(message_id))


async def clear_vote_message(db, flow, channel, game_id, content):
    """Edit the tracked voting message (if any) to `content` with its
    buttons removed. Used when a game is cancelled mid-vote, so stale
    vote buttons can't be clicked afterward."""
    message = await _fetch_vote_message(db, flow, channel, game_id)
    if message is not None:
        await message.edit(content=content, view=None)
    return message


async def apply_round_result(*, db, flow, channel, guild, session, game, teams,
                              identities, round_no, result):
    """After a round resolves -- whether triggered by the last vote coming
    in (cast_vote) or a manual /game closevote -- reflect it on the
    tracked message: attach a fresh VotingView if another round opened
    (a tie, or ranked's always-required round-2 runoff), or drop the
    buttons if the game is now decided. Shared so closevote can't leave
    stale/missing buttons the way it used to before this existed."""
    ops = _mode_ops(flow)
    message = await _fetch_vote_message(db, flow, channel, game["id"])
    refreshed_game = ops["get_game"](db, game["id"])
    content = f"{messages.JELLY} 已结算第 {round_no} 轮:\n\n{result}"

    if refreshed_game["status"] in ("voting_round1", "voting_round2"):
        _, _, next_targets = flow.voters_and_targets(db, teams, identities, refreshed_game)
        next_view = VotingView(
            db=db, flow=flow, channel=channel, guild=guild, session=session,
            game=refreshed_game, teams=teams, identities=identities, targets=next_targets,
        )
        if message is not None:
            await message.edit(content=content, view=next_view)
        else:
            message = await channel.send(content, view=next_view)
        ops["set_vote_message_id"](db, refreshed_game["id"], message.id)
    elif message is not None:
        await message.edit(content=content, view=None)
    else:
        await channel.send(content)


async def cast_vote(*, db, flow, channel, guild, session, game, teams, identities,
                     voter_id, target_id, reply):
    """Validate, record, and reflect one vote. Shared by VotingView's
    buttons and the typed /vote command (gamebot/cogs/voting.py) so there
    is exactly one path that can mutate vote state."""
    ops = _mode_ops(flow)
    # Re-fetch rather than trusting the passed-in game: VotingView holds a
    # snapshot from whenever it was built, and a button click can arrive
    # after the round advanced or the game was cancelled out from under it.
    game = ops["get_game"](db, game["id"])
    if game["status"] not in ("voting_round1", "voting_round2"):
        await reply("当前不是投票阶段，可能已被取消或结算。", ephemeral=True)
        return
    round_no, voters, targets = flow.voters_and_targets(db, teams, identities, game)

    try:
        game_logic.validate_vote(voter_id, target_id, voters, targets)
    except game_logic.VoteError as e:
        options = ", ".join(db.name_or_id(t) for t in targets) or "无"
        await reply(f"⚠️ {e}\n\n可投对象: {options}", ephemeral=True)
        return

    ops["record_vote"](db, game["id"], round_no, voter_id, target_id)
    votes = ops["get_votes"](db, game["id"], round_no)
    await reply(
        f"{messages.JELLY} 已记录你的第 {round_no} 轮投票 ({len(votes)}/{len(voters)})",
        ephemeral=True,
    )

    if len(votes) < len(voters):
        message = await _fetch_vote_message(db, flow, channel, game["id"])
        if message is not None:
            # No `view=` kwarg: Message.edit() leaves existing components
            # untouched when the param is omitted -- only the status text
            # changes, the vote buttons stay as-is.
            await message.edit(
                content=messages.vote_status_text(round_no, len(votes), len(voters))
            )
        return

    try:
        if flow is game_flow:
            result = game_flow.resolve_current_round(db, session, game, teams, identities)
        else:
            result = mini_flow.resolve_current_round(db, game, teams, identities)
    except game_logic.VoteError as e:
        message = await _fetch_vote_message(db, flow, channel, game["id"])
        if message is not None:
            await message.edit(
                content=f"⚠️ 自动结算失败，请使用 {ops['closevote_cmd']} 处理: {e}", view=None
            )
        return

    if result is None:
        return

    await apply_round_result(
        db=db, flow=flow, channel=channel, guild=guild, session=session, game=game,
        teams=teams, identities=identities, round_no=round_no, result=result,
    )
