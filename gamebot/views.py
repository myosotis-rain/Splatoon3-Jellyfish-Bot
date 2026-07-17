import discord

from . import messages


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
