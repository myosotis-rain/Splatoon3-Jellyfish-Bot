# Voting & Identity-Card Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DM-based identity cards and typed-only voting with Discord
buttons: a `🎴 查看身份卡` button that reveals a player's card ephemeral and
(for special identities) doubles as confirmation, and per-round vote
buttons that replace repeated channel messages with one message edited in
place.

**Architecture:** Two new `discord.ui.View` subclasses in `views.py`
(`IdentityRevealView`, `VotingView`) plus one shared async helper
(`cast_vote`) that both the vote buttons and the existing typed `/vote`
command call, so there is exactly one code path for validating/recording a
vote and updating the round message. `game_logic.py`/`game_flow.py`/
`mini_flow.py` are untouched — this is a delivery-mechanism change only.

**Tech Stack:** Python 3.9, discord.py 2.7, pytest/pytest-asyncio, sqlite3.

## Global Constraints

- No DM sends anywhere in the new code paths (that's the whole point).
- `/vote` stays working as a fallback, sharing `cast_vote` with the buttons
  — never two implementations of vote validation.
- No persistence of view state across bot restarts (documented non-goal in
  the design doc) — don't add any.
- Follow existing code style: ranked/mini are separate methods with a
  `mini_` prefix on the mini side (see `db.py`), not a generic
  mode-parameterized helper.
- Spec: `docs/superpowers/specs/2026-07-17-voting-and-card-buttons-design.md`

---

### Task 1: Persist the tracked round message id

**Files:**
- Modify: `gamebot/db.py:129-131` (schema init), `gamebot/db.py:412-417`
  (after `set_eliminated`, ranked), `gamebot/db.py:617-622` (after
  `set_mini_eliminated`, mini)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.set_vote_message_id(game_id, message_id)`,
  `db.get_vote_message_id(game_id) -> str | None`,
  `db.set_mini_vote_message_id(game_id, message_id)`,
  `db.get_mini_vote_message_id(game_id) -> str | None`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_vote_message_id_round_trip(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    assert db.get_vote_message_id(game_id) is None
    db.set_vote_message_id(game_id, 999)
    assert db.get_vote_message_id(game_id) == "999"


def test_mini_vote_message_id_round_trip(db):
    game_id, _ = db.create_mini_game(db.create_mini_session("server1", "chan1"))
    assert db.get_mini_vote_message_id(game_id) is None
    db.set_mini_vote_message_id(game_id, 888)
    assert db.get_mini_vote_message_id(game_id) == "888"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_db.py -k vote_message_id -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'set_vote_message_id'`

- [ ] **Step 3: Add the migration**

In `gamebot/db.py`, change `init_schema` (currently lines 129-131):

```python
    def init_schema(self):
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        for table in ("games", "mini_games"):
            cols = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if "vote_message_id" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN vote_message_id TEXT")
```

- [ ] **Step 4: Add the ranked getter/setter**

In `gamebot/db.py`, immediately after `set_eliminated` (current lines
412-417):

```python
    def set_vote_message_id(self, game_id, message_id):
        self.conn.execute(
            "UPDATE games SET vote_message_id = ? WHERE id = ?",
            (str(message_id), game_id),
        )
        self.conn.commit()

    def get_vote_message_id(self, game_id):
        row = self.conn.execute(
            "SELECT vote_message_id FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        return row["vote_message_id"] if row else None
```

- [ ] **Step 5: Add the mini getter/setter**

In `gamebot/db.py`, immediately after `set_mini_eliminated` (current lines
617-622):

```python
    def set_mini_vote_message_id(self, game_id, message_id):
        self.conn.execute(
            "UPDATE mini_games SET vote_message_id = ? WHERE id = ?",
            (str(message_id), game_id),
        )
        self.conn.commit()

    def get_mini_vote_message_id(self, game_id):
        row = self.conn.execute(
            "SELECT vote_message_id FROM mini_games WHERE id = ?", (game_id,)
        ).fetchone()
        return row["vote_message_id"] if row else None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: all PASS, including the two new tests.

- [ ] **Step 7: Commit**

```bash
git add gamebot/db.py tests/test_db.py
git commit -m "Persist the tracked vote-round message id"
```

---

### Task 2: Extract the "all confirmed" line

**Files:**
- Modify: `gamebot/messages.py` (the `confirmation_status_text` function)
- Test: `tests/test_messages.py`

**Interfaces:**
- Produces: `messages.all_confirmed_line() -> str`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_messages.py`:

```python
def test_all_confirmed_line_uses_jelly():
    assert messages.all_confirmed_line().startswith(messages.JELLY)


def test_confirmation_status_text_ready_uses_all_confirmed_line():
    text = messages.confirmation_status_text(4, 4)
    assert messages.all_confirmed_line() in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_messages.py -k confirmed -v`
Expected: FAIL with `AttributeError: module 'gamebot.messages' has no attribute 'all_confirmed_line'`

- [ ] **Step 3: Implement**

Replace the current `confirmation_status_text` function in
`gamebot/messages.py` with:

```python
def all_confirmed_line():
    return f"{JELLY} 全部确认，可以开始游戏。"


def confirmation_status_text(confirmed, needed):
    text = f"🎴 特殊身份确认: {confirmed}/{needed}"
    if confirmed >= needed:
        text += f"\n{all_confirmed_line()}"
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_messages.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add gamebot/messages.py tests/test_messages.py
git commit -m "Extract all_confirmed_line for reuse by the card-reveal view"
```

---

### Task 3: `IdentityRevealView`

**Files:**
- Modify: `gamebot/views.py`

**Interfaces:**
- Consumes: `db.get_game_players(game_id)`, `db.set_confirmed(game_id, player_id)`
  (existing), `game_logic.confirmation_status(identities, confirmed_ids)`
  (existing), `config.IDENTITIES_NEEDING_CONFIRMATION` (existing),
  `messages.all_confirmed_line()` (Task 2)
- Produces: `views.IdentityRevealView(db, game_id, teams, identities, track_confirmation, card_text_fn)`

No unit test for this task — it's Discord interaction glue with no pure
logic of its own (same as the existing untested `ConfirmView`). It's
exercised by the manual smoke test in Task 8.

- [ ] **Step 1: Add imports**

At the top of `gamebot/views.py`, change:

```python
import discord

from . import messages
```

to:

```python
import discord

from . import config, game_logic, messages
```

- [ ] **Step 2: Add the view class**

Append to `gamebot/views.py`, after `ConfirmView`:

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add gamebot/views.py
git commit -m "Add IdentityRevealView"
```

---

### Task 4: Wire `IdentityRevealView` into ranked `/game start`

**Files:**
- Modify: `gamebot/cogs/game.py:1-116` (imports + the `start` command)

**Interfaces:**
- Consumes: `views.IdentityRevealView` (Task 3)

No unit test — Discord command glue. Verified in Task 8.

- [ ] **Step 1: Update the import**

In `gamebot/cogs/game.py`, change line 9:

```python
from ..views import ConfirmView
```

to:

```python
from ..views import IdentityRevealView
```

- [ ] **Step 2: Replace the DM loop**

Replace the body of `start` from `await ctx.send(messages.team_announcement_text(...))`
through the end of the `dm_failures` block (current lines 93-116) with:

```python
        view = IdentityRevealView(
            self.db, game_id, teams, identities,
            track_confirmation=True, card_text_fn=messages.identity_card_text,
        )
        await ctx.send(messages.team_announcement_text(game_number, teams), view=view)
```

- [ ] **Step 3: Commit**

```bash
git add gamebot/cogs/game.py
git commit -m "Ranked /game start: reveal cards via button instead of DM"
```

---

### Task 5: Wire `IdentityRevealView` into `/mini start`

**Files:**
- Modify: `gamebot/cogs/mini.py:1-148` (imports + the `start` command)

**Interfaces:**
- Consumes: `views.IdentityRevealView` (Task 3)

No unit test — Discord command glue. Verified in Task 8.

- [ ] **Step 1: Add the import**

In `gamebot/cogs/mini.py`, change line 1-5 imports to add:

```python
from ..views import IdentityRevealView
```

- [ ] **Step 2: Replace the DM loop**

Replace the body of `start` from `await ctx.send(messages.team_announcement_text(...))`
through the end of the `dm_failures` block (current lines 129-148) with:

```python
        view = IdentityRevealView(
            self.db, game_id, teams, identities,
            track_confirmation=False, card_text_fn=messages.mini_identity_card_text,
        )
        await ctx.send(
            messages.team_announcement_text(game_number, teams, label="Mini"), view=view
        )
```

- [ ] **Step 3: Commit**

```bash
git add gamebot/cogs/mini.py
git commit -m "Mini /mini start: reveal cards via button instead of DM"
```

---

### Task 6: Shared `cast_vote` helper + `VotingView`

**Files:**
- Modify: `gamebot/views.py`

**Interfaces:**
- Consumes: `game_flow`/`mini_flow` (`voters_and_targets`, `resolve_current_round`),
  `game_logic.validate_vote`, `messages.vote_status_text`/`tie_text`,
  `db.record_vote`/`get_votes`/`set_vote_message_id` (ranked) and their
  `mini_` counterparts
- Produces: `views.cast_vote(...)` (async), `views.VotingView(...)`

No unit test for this task (Discord glue: message edits, button
construction). Verified in Task 8. `game_logic.validate_vote` itself
already has full unit coverage in `tests/test_game_logic.py` and is not
being changed.

- [ ] **Step 1: Add imports**

In `gamebot/views.py`, change the import line from Task 3:

```python
from . import config, game_logic, messages
```

to:

```python
from . import config, game_flow, game_logic, messages, mini_flow
```

- [ ] **Step 2: Add `VotingView`**

Append to `gamebot/views.py`:

```python
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
```

- [ ] **Step 3: Add `cast_vote`**

Append to `gamebot/views.py`:

```python
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
        await reply(f"❌ {e}\n\n可投对象: {options}", ephemeral=True)
        return

    ops["record_vote"](db, game["id"], round_no, voter_id, target_id)
    votes = ops["get_votes"](db, game["id"], round_no)
    await reply(
        f"{messages.JELLY} 已记录你的第 {round_no} 轮投票 ({len(votes)}/{len(voters)})",
        ephemeral=True,
    )

    message_id = db.get_vote_message_id(game["id"]) if flow is game_flow else db.get_mini_vote_message_id(game["id"])
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
```

- [ ] **Step 4: Commit**

```bash
git add gamebot/views.py
git commit -m "Add VotingView and shared cast_vote helper"
```

---

### Task 7: Wire voting buttons into `/game result`, `/mini result`, and `/vote`

**Files:**
- Modify: `gamebot/cogs/game.py` (the `result` command)
- Modify: `gamebot/cogs/mini.py` (the `result` command)
- Modify: `gamebot/cogs/voting.py` (the `vote` command body)

**Interfaces:**
- Consumes: `views.VotingView`, `views.cast_vote` (Task 6)

No unit test — Discord command glue. Verified in Task 8.

- [ ] **Step 1: Post the round-1 message with buttons in `/game result`**

In `gamebot/cogs/game.py`, find the `result` command. After
`self.db.set_game_result(game["id"], losing, winning)`, replace the final
`await ctx.send(...)` with posting the votable message and attaching
`VotingView`:

```python
        self.db.set_game_result(game["id"], losing, winning)
        refreshed_game = self.db.get_game(game["id"])
        _, _, targets = game_flow.voters_and_targets(self.db, teams, identities, refreshed_game)
        view = VotingView(
            db=self.db, flow=game_flow, channel=ctx.channel, guild=ctx.guild,
            session=session, game=refreshed_game, teams=teams, identities=identities,
            targets=targets,
        )
        message = await ctx.send(
            f"输方: {losing}\n胜方: {winning}\n\n可以开始讨论，讨论结束后投票。",
            view=view,
        )
        self.db.set_vote_message_id(game["id"], message.id)
```

Add `from ..views import IdentityRevealView, VotingView` (extending the
Task 4 import) at the top.

- [ ] **Step 2: Same for `/mini result`**

In `gamebot/cogs/mini.py`, apply the mirrored change to the `result`
command:

```python
        self.db.set_mini_game_result(game["id"], losing, winning)
        refreshed_game = self.db.get_mini_game(game["id"])
        _, _, targets = mini_flow.voters_and_targets(self.db, teams, identities, refreshed_game)
        view = VotingView(
            db=self.db, flow=mini_flow, channel=ctx.channel, guild=ctx.guild,
            session=session, game=refreshed_game, teams=teams, identities=identities,
            targets=targets,
        )
        message = await ctx.send(
            f"输方: {losing}\n胜方: {winning}\n\n可以开始讨论，讨论结束后投票。",
            view=view,
        )
        self.db.set_mini_vote_message_id(game["id"], message.id)
```

Extend the Task 5 import line to `from ..views import IdentityRevealView, VotingView`.

- [ ] **Step 3: Route `/vote` through `cast_vote`**

In `gamebot/cogs/voting.py`, replace the body of the `vote` command
(current lines 60-106) with:

```python
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
```

Add `from .. import views` to the imports at the top of
`gamebot/cogs/voting.py`.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all existing tests PASS (no test touches cogs directly, so
this only guards against import/syntax errors breaking collection).

- [ ] **Step 5: Commit**

```bash
git add gamebot/cogs/game.py gamebot/cogs/mini.py gamebot/cogs/voting.py
git commit -m "Route /game result, /mini result, and /vote through voting buttons"
```

---

### Task 8: Manual smoke test and restart the live bot

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite one more time**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 2: Restart the live bot process**

```bash
pgrep -fl "bot.py"
kill <pid>
nohup .venv/bin/python -u bot.py >> bot.log 2>&1 &
disown
tail -n 15 bot.log
```

Expected: clean login, no traceback, `小水母 已上线` in the log.

- [ ] **Step 3: Manual smoke test in Discord**

Using a real (or test) server with 8 members: `/session create` →
8x `/session join` → `/game start` → confirm the team announcement carries
a `🎴 查看身份卡` button, clicking it as different members shows each their
own card ephemeral, and undercover/dummy clicks eventually produce the
"🪼 全部确认" line appended to the announcement. Then `/game result` →
confirm a votable message appears with one button per losing-team member,
clicking as an eligible voter records the vote and edits the status line,
and once everyone's voted the message auto-edits to the round result
(or round-2 buttons on a tie). Confirm typed `/vote` still works
interchangeably with the buttons mid-round. Repeat the `/mini` mirror
briefly (join, start, result, vote) to confirm mini mode isn't broken.

- [ ] **Step 4: Report results**

If everything above works, the feature is done. If something in the
smoke test fails, fix it in the relevant task's file (not a new
ad-hoc patch) and re-run from Step 1.
