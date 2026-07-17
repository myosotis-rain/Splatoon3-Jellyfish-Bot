"""Pure game-logic functions: team/identity assignment, voting, scoring.

No Discord or database dependencies here on purpose, so this module is
fully unit-testable without a bot connection.
"""

import random

from . import config


class VoteError(ValueError):
    pass


def assign_teams(player_ids, team_size=config.TEAM_SIZE):
    """Randomly split exactly 2 * team_size players into two even teams.

    Returns {"A": [ids], "B": [ids]}.
    """
    game_size = team_size * 2
    if len(player_ids) != game_size:
        raise ValueError(
            f"Game requires exactly {game_size} players, got {len(player_ids)}"
        )
    shuffled = list(player_ids)
    random.shuffle(shuffled)
    return {
        config.TEAMS[0]: shuffled[:team_size],
        config.TEAMS[1]: shuffled[team_size:],
    }


def assign_identities(team_player_ids):
    """Randomly assign 1 undercover, 1 dummy, 2 good within one team of 4.

    Returns {player_id: identity}.
    """
    if len(team_player_ids) != config.TEAM_SIZE:
        raise ValueError(
            f"Team requires exactly {config.TEAM_SIZE} players, got {len(team_player_ids)}"
        )
    shuffled = list(team_player_ids)
    random.shuffle(shuffled)
    return {
        shuffled[0]: config.IDENTITY_UNDERCOVER,
        shuffled[1]: config.IDENTITY_DUMMY,
        shuffled[2]: config.IDENTITY_GOOD,
        shuffled[3]: config.IDENTITY_GOOD,
    }


def assign_game_identities(teams):
    """teams: {"A": [...4], "B": [...4]} -> {player_id: identity} across both teams."""
    identities = {}
    for team_players in teams.values():
        identities.update(assign_identities(team_players))
    return identities


def assign_mini_identities(team_player_ids):
    """Mini (3v3) variant: 1 undercover + 2 good within one team of 3.
    No dummy — Mini has no elimination-for-points role since it isn't scored.

    Returns {player_id: identity}.
    """
    if len(team_player_ids) != config.MINI_TEAM_SIZE:
        raise ValueError(
            f"Mini team requires exactly {config.MINI_TEAM_SIZE} players, "
            f"got {len(team_player_ids)}"
        )
    shuffled = list(team_player_ids)
    random.shuffle(shuffled)
    return {
        shuffled[0]: config.IDENTITY_UNDERCOVER,
        shuffled[1]: config.IDENTITY_GOOD,
        shuffled[2]: config.IDENTITY_GOOD,
    }


def assign_mini_game_identities(teams):
    """teams: {"A": [...3], "B": [...3]} -> {player_id: identity} across both teams."""
    identities = {}
    for team_players in teams.values():
        identities.update(assign_mini_identities(team_players))
    return identities


def find_undercover(teams, identities, team):
    for player_id in teams[team]:
        if identities[player_id] == config.IDENTITY_UNDERCOVER:
            return player_id
    raise ValueError(f"No undercover found on team {team}")


def confirmation_status(identities, confirmed_ids):
    """Returns (confirmed_count, needed_count) for special identities only."""
    needing = [
        p for p, ident in identities.items()
        if ident in config.IDENTITIES_NEEDING_CONFIRMATION
    ]
    confirmed = [p for p in needing if p in confirmed_ids]
    return len(confirmed), len(needing)


def eligible_voters(teams, identities, losing_team, winning_team):
    """输方全员 + 胜方卧底 may vote (both rounds)."""
    voters = set(teams[losing_team])
    voters.add(find_undercover(teams, identities, winning_team))
    return voters


def eligible_targets(teams, losing_team):
    """Only losing-team members can be accused/voted on, in either round."""
    return set(teams[losing_team])


def validate_vote(voter_id, target_id, voters, targets):
    if voter_id == target_id:
        raise VoteError("不能投自己")
    if voter_id not in voters:
        raise VoteError("你没有投票资格")
    if target_id not in targets:
        raise VoteError("目标玩家没有资格被投票")


def tally_votes(votes):
    """votes: {voter_id: target_id} -> {target_id: count}."""
    counts = {}
    for target in votes.values():
        counts[target] = counts.get(target, 0) + 1
    return counts


def top_candidates(votes):
    """Returns (top_candidate_ids, is_tie). Empty votes -> ([], False)."""
    counts = tally_votes(votes)
    if not counts:
        return [], False
    max_count = max(counts.values())
    top = [p for p, c in counts.items() if c == max_count]
    return top, len(top) > 1


def resolve_round1(votes):
    """Round 1 (open vote among all eligible voters).

    Returns (candidates, tie). If not a tie, candidates is a single-element
    list and the game moves straight to elimination judgement. If a tie,
    candidates are the tied players who advance to round 2.
    """
    return top_candidates(votes)


def resolve_runoff(votes, candidates):
    """A runoff round (round 2, or any repeat after a tie).

    Only the current candidates may be targeted, and they may not vote.
    Returns (eliminated_player_or_None, tie, tied_candidates).
    """
    candidates = set(candidates)
    invalid_voters = set(votes.keys()) & candidates
    if invalid_voters:
        raise VoteError(f"候选人不能在第二轮投票: {sorted(invalid_voters)}")
    invalid_targets = set(votes.values()) - candidates
    if invalid_targets:
        raise VoteError(f"第二轮只能投候选人: {sorted(invalid_targets)}")
    top, tie = top_candidates(votes)
    if tie:
        return None, True, top
    return top[0], False, top


def calculate_scores(*, teams, identities, losing_team, winning_team,
                      eliminated_player, final_round_votes):
    """Compute per-player score deltas for one completed game.

    final_round_votes: {voter_id: target_id} cast in the decisive runoff
    round only — per the ruling that voting bonus is scored on that round's
    correctness alone, regardless of earlier tied rounds.
    """
    losing_undercover = find_undercover(teams, identities, losing_team)
    caught = eliminated_player == losing_undercover

    scores = {}
    for team_name, player_ids in teams.items():
        is_losing = team_name == losing_team
        for player_id in player_ids:
            identity = identities[player_id]
            if is_losing:
                if identity == config.IDENTITY_UNDERCOVER:
                    score = 1 + (1 if not caught else -1)
                elif identity == config.IDENTITY_DUMMY:
                    score = 2 if eliminated_player == player_id else 0
                else:
                    score = 0
            else:
                if identity == config.IDENTITY_UNDERCOVER:
                    score = -1
                elif identity == config.IDENTITY_DUMMY:
                    # Spec's +1-for-everyone winning bonus explicitly excludes
                    # the winning-team dummy, and no other rule scores them.
                    score = 0
                else:
                    score = 1

            if final_round_votes.get(player_id) == losing_undercover:
                score += 1

            scores[player_id] = score

    return scores
