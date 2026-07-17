"""Round-resolution logic for Mini (3v3, unscored) games. Mirrors
game_flow.py's structure but never computes or persists a score — a Mini
game just reports whether the accused was actually the undercover.
"""

from . import game_logic, messages


def voters_and_targets(db, teams, identities, game):
    """Eligible voters/targets for whichever round is currently open."""
    all_eligible = game_logic.eligible_voters(
        teams, identities, game["losing_team"], game["winning_team"]
    )
    if game["status"] == "voting_round1":
        return 1, all_eligible, game_logic.eligible_targets(teams, game["losing_team"])
    round_no = db.get_mini_current_round(game["id"])
    candidates = set(db.get_mini_vote_candidates(game["id"]))
    return round_no, all_eligible - candidates, candidates


def resolve_round1(db, game):
    """Close round 1. Returns the announcement text, or None if nobody voted."""
    votes = db.get_mini_votes(game["id"], 1)
    candidates, tie = game_logic.resolve_round1(votes)
    if not candidates:
        return None

    db.set_mini_vote_candidates(game["id"], candidates)
    db.set_mini_current_round(game["id"], 2)
    db.set_mini_game_status(game["id"], "voting_round2")

    if tie:
        return messages.tie_text(candidates) + "\n\n请进行第二轮投票 (/vote)。"
    return (
        f"最高票: {messages.mention(candidates[0])}\n\n"
        "30 秒申辩后，进行第二轮投票 (/vote)。"
    )


def resolve_runoff(db, game, teams, identities):
    """Close the current runoff round. On a tie, automatically opens the
    next runoff round, same as the ranked flow. On a decisive result,
    marks the game completed and reports whether the accused was actually
    the undercover — no score is computed or stored.
    """
    round_no = db.get_mini_current_round(game["id"])
    candidates = db.get_mini_vote_candidates(game["id"])
    votes = db.get_mini_votes(game["id"], round_no)

    eliminated, tie, tied = game_logic.resolve_runoff(votes, candidates)

    if tie:
        next_round = round_no + 1
        db.set_mini_vote_candidates(game["id"], tied)
        db.set_mini_current_round(game["id"], next_round)
        return (
            messages.tie_text(tied)
            + f"\n\n仍然平票，开始第 {next_round} 轮投票 (/vote)。"
        )

    db.set_mini_eliminated(game["id"], eliminated)
    db.complete_mini_game(game["id"])

    losing_undercover = game_logic.find_undercover(teams, identities, game["losing_team"])
    outcome = "🎉 抓到卧底了！" if eliminated == losing_undercover else "😅 卧底逃脱了！"
    return f"被指认: {messages.mention(eliminated)}\n\n{outcome}"


def resolve_current_round(db, game, teams, identities):
    """Dispatch to resolve_round1 or resolve_runoff based on game status."""
    if game["status"] == "voting_round1":
        return resolve_round1(db, game)
    if game["status"] == "voting_round2":
        return resolve_runoff(db, game, teams, identities)
    return None
