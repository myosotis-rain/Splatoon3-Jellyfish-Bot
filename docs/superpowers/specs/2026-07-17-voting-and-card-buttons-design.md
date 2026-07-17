# Voting & Identity-Card Buttons

## Context

Today identity cards are DM'd to each player, with an in-DM `ConfirmView`
button for special roles (undercover/dummy). `/vote` is a typed command.
This has two real problems: DM delivery silently fails for players who've
disabled "allow messages from server members" (tracked today via a
`dm_failures` list in `game.py`/`mini.py`), and the channel gets a brand
new message after *every single vote* until a round resolves.

## Goals

- Replace DM-based identity cards with an ephemeral, button-triggered
  reveal attached directly to the team-announcement message.
- Merge "reveal" and "confirm" into one click for identities that need
  confirmation (undercover, dummy). Good identities get reveal only, no
  confirmation step — unchanged from today.
- Replace per-vote channel spam with one persistent message per round,
  edited in place, using ephemeral replies for each voter's private
  confirmation.
- Keep `/vote` working as a typed fallback, sharing the same validation
  path as the buttons.
- Apply the same mechanism to both ranked and mini modes.

## Non-goals

- No change to `game_logic.py`'s rules (scoring, vote validation, tie
  resolution) — this is purely a delivery-mechanism change.
- No persistence of view state across bot restarts, matching the existing
  accepted limitation documented on `ConfirmView`. If the bot restarts
  mid-round, the host falls back to the existing manual commands
  (`/game closevote`, `/game override`, `/game resolvetie`).
- Not touching `/session`/`/rename`/leaderboard command naming — deferred
  pending the separate ranked+mini-coexistence decision.

## Components

### `views.py` additions

**`IdentityRevealView(discord.ui.View)`**
Attached to the team-announcement message in place of the DM loop.
Constructed with `db`, `game_id`, `teams`, `identities`. Single button
`🎴 查看身份卡`. On click:
- If the clicking user isn't in `teams`, ephemeral "你不在本局游戏中", no
  state change.
- Otherwise send `messages.identity_card_text`/`mini_identity_card_text`
  ephemeral.
- If their identity is in `config.IDENTITIES_NEEDING_CONFIRMATION`, call
  `db.set_confirmed` (idempotent on repeat clicks), recompute
  `game_logic.confirmation_status`, and if now fully confirmed, edit the
  parent message to append `🪼 全员已确认` exactly once.

**`VotingView(discord.ui.View)`**
Attached to the round message. Built fresh each round (initial round 1
after `/game result`, and again on any tie->next-round) from
`voters_and_targets(...)` (already in `game_flow.py`/`mini_flow.py`). One
button per target, labeled with `member.display_name` (fallback to the
raw id if they've left the guild). On click:
- `game_logic.validate_vote` → ephemeral success/`VoteError` reply
  (same message text `/vote` already produces).
- `db.record_vote`/`record_mini_vote`.
- Edit the parent message's status line via `messages.vote_status_text`.
- If that vote completes the round, call `resolve_current_round`; edit
  the message again — either a fresh `VotingView` for round 2 (tie) or
  the final result text with buttons removed (decisive).

Both views are thin Discord glue only — no game rules live in `views.py`,
matching how `ConfirmView` is written today.

### Existing code changes

- `game.py`/`mini.py` `start`: replace the per-player DM loop with
  posting the team announcement + `IdentityRevealView`. The `dm_failures`
  handling for cards is deleted — there's no DM step left to fail.
- `game.py`/`mini.py` `result`: post the round message with
  `VotingView` attached instead of plain text.
- `voting.py`: `/vote` keeps calling the same validate/record path, but
  now needs to edit the same tracked round message rather than sending a
  new one. Requires a new `vote_message_id` column on `games` (and
  `mini_games`) so both the button path and the typed path stay in sync
  regardless of which one casts the deciding vote.

## Data flow: identity reveal

1. `/game start` assigns teams/identities as today.
2. Bot posts the team announcement with `IdentityRevealView` attached.
3. Each player clicks `🎴 查看身份卡` → ephemeral card; special
   identities are simultaneously confirmed.
4. On the last special-identity confirmation, edit the announcement to
   add "🪼 全员已确认，可以开始".
5. `/game result` is still gated on `confirmation_status` as today;
   `/game confirmations` remains for polling if confirmations stall.

## Data flow: voting

1. `/game result` records the losing team, posts the round-1 message
   with `VotingView`, stores its message id.
2. Eligible voters click a target button, or use `/vote` — both funnel
   through the same validate/record/check-completion logic.
3. Each click edits the same message's status line; no new messages.
4. Round completion: tie → edit in a new `VotingView` for the narrowed
   candidates; decisive → edit to final score text, buttons removed.
5. `/game closevote`/`/game resolvetie`/`/game override` remain as manual
   escape hatches, unchanged.

## Error handling

- Non-participant clicks a button: ephemeral rejection, no state change
  (`IdentityRevealView` checks team membership directly; `VotingView`
  gets this for free from `validate_vote` raising `VoteError`, the same
  path `/vote` already uses).
- Repeat clicks (re-opening a card, voting twice): `validate_vote`
  already rejects double votes; re-clicking the card button just
  re-shows the same ephemeral card, and `set_confirmed` is idempotent.
- Message edit failure (e.g. message deleted): caught so it doesn't
  crash the interaction — falls back to the ephemeral reply alone; host
  recovers via `/game status`/`/game closevote`.
- Bot restart mid-round: views aren't persisted (documented non-goal).
  Buttons on old messages stop working; host uses the manual commands.

## Testing

- `game_logic.py`/`db.py` are unchanged, so their existing unit tests
  keep passing as-is.
- New pure-logic seam to unit test without Discord: extend
  `game_flow.py`/`mini_flow.py` with a small helper that computes "what
  should the round message look like next" (target list + status text)
  as a function of `(game, teams, identities, votes)`, keeping
  `views.py` itself Discord-glue-only like `ConfirmView` is today.
- Manual smoke test against the live bot before calling it done, same as
  how `views.py` is verified today (discord.ui code isn't unit tested).
