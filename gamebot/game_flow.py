"""Round-resolution logic shared between the host's /game commands and the
automatic all-voted trigger in /vote. Kept Discord-free; callers decide how
to deliver the returned text (interaction response vs. plain channel send).
"""

from . import game_logic, messages


def voters_and_targets(db, teams, identities, game):
    """Eligible voters/targets for whichever round is currently open."""
    all_eligible = game_logic.eligible_voters(
        teams, identities, game["losing_team"], game["winning_team"]
    )
    if game["status"] == "voting_round1":
        return 1, all_eligible, game_logic.eligible_targets(teams, game["losing_team"])
    round_no = db.get_current_round(game["id"])
    candidates = set(db.get_vote_candidates(game["id"]))
    return round_no, all_eligible - candidates, candidates


def _tally_text(db, votes):
    ranked = sorted(game_logic.tally_votes(votes).items(), key=lambda kv: -kv[1])
    return messages.vote_tally_text([(db.name_or_id(pid), count) for pid, count in ranked])


def resolve_round1(db, game):
    """Close round 1. Returns the announcement text, or None if nobody voted."""
    votes = db.get_votes(game["id"], 1)
    candidates, tie = game_logic.resolve_round1(votes)
    if not candidates:
        return None

    db.set_vote_candidates(game["id"], candidates)
    db.set_current_round(game["id"], 2)
    db.set_game_status(game["id"], "voting_round2")

    tally = _tally_text(db, votes)
    if tie:
        names = [db.name_or_id(c) for c in candidates]
        return f"{tally}\n\n{messages.tie_text(names)}\n\n请进行第二轮投票 (/vote)。"
    return (
        f"{tally}\n\n最高票: {db.name_or_id(candidates[0])}\n\n"
        "30 秒申辩后，进行第二轮投票 (/vote)。"
    )


def resolve_runoff(db, session, game, teams, identities):
    """Close the current runoff round. On a tie, automatically opens the
    next runoff round (same losing team + winning undercover minus the
    tied candidates, voting only on the tied candidates) and returns that
    announcement. On a decisive result, finalizes scores and returns the
    result text.
    """
    round_no = db.get_current_round(game["id"])
    candidates = db.get_vote_candidates(game["id"])
    votes = db.get_votes(game["id"], round_no)

    eliminated, tie, tied = game_logic.resolve_runoff(votes, candidates)
    tally = _tally_text(db, votes)

    if tie:
        next_round = round_no + 1
        db.set_vote_candidates(game["id"], tied)
        db.set_current_round(game["id"], next_round)
        names = [db.name_or_id(c) for c in tied]
        return (
            f"{tally}\n\n{messages.tie_text(names)}"
            + f"\n\n仍然平票，开始第 {next_round} 轮投票 (/vote)。"
        )

    db.set_eliminated(game["id"], eliminated)
    final_round_votes = db.get_votes(game["id"], round_no)
    scores = game_logic.calculate_scores(
        teams=teams,
        identities=identities,
        losing_team=game["losing_team"],
        winning_team=game["winning_team"],
        eliminated_player=eliminated,
        final_round_votes=final_round_votes,
    )
    db.finalize_scores(session["id"], game["id"], scores)
    lines = [tally, "", f"被票出: {db.name_or_id(eliminated)}\n", "本局积分:"]
    for player_id, score in scores.items():
        lines.append(f"{db.name_or_id(player_id)}: {score:+d}")
    return "\n".join(lines)


def resolve_current_round(db, session, game, teams, identities):
    """Dispatch to resolve_round1 or resolve_runoff based on game status."""
    if game["status"] == "voting_round1":
        return resolve_round1(db, game)
    if game["status"] == "voting_round2":
        return resolve_runoff(db, session, game, teams, identities)
    return None
