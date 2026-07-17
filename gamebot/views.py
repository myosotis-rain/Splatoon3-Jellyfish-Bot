import discord

from . import config, game_logic, messages


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

    def __init__(self, db, game_id, teams, identities, track_confirmation, card_text_fn):
        super().__init__(timeout=None)
        self.db = db
        self.game_id = game_id
        self.teams = teams
        self.identities = identities
        self.track_confirmation = track_confirmation
        self.card_text_fn = card_text_fn
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
            await interaction.message.edit(
                content=f"{interaction.message.content}\n\n{messages.all_confirmed_line()}"
            )
