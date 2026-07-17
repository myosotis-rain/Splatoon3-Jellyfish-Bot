import pytest

from gamebot import config, game_logic


PLAYERS = [f"p{i}" for i in range(1, 9)]


def test_assign_teams_splits_evenly():
    teams = game_logic.assign_teams(PLAYERS)
    assert set(teams.keys()) == set(config.TEAMS)
    assert len(teams["A"]) == config.TEAM_SIZE
    assert len(teams["B"]) == config.TEAM_SIZE
    assert set(teams["A"]) | set(teams["B"]) == set(PLAYERS)
    assert set(teams["A"]) & set(teams["B"]) == set()


def test_assign_teams_wrong_size_raises():
    with pytest.raises(ValueError):
        game_logic.assign_teams(PLAYERS[:7])


def test_assign_teams_mini_size():
    mini_players = [f"p{i}" for i in range(1, 7)]
    teams = game_logic.assign_teams(mini_players, team_size=config.MINI_TEAM_SIZE)
    assert len(teams["A"]) == config.MINI_TEAM_SIZE
    assert len(teams["B"]) == config.MINI_TEAM_SIZE
    assert set(teams["A"]) | set(teams["B"]) == set(mini_players)


def test_assign_teams_partial_no_picks_is_fully_random():
    teams = game_logic.assign_teams_partial(PLAYERS, [], [])
    assert len(teams["A"]) == config.TEAM_SIZE
    assert len(teams["B"]) == config.TEAM_SIZE
    assert set(teams["A"]) | set(teams["B"]) == set(PLAYERS)


def test_assign_teams_partial_respects_specific_picks():
    teams = game_logic.assign_teams_partial(PLAYERS, ["p1"], ["p2", "p3"])
    assert "p1" in teams["A"]
    assert "p2" in teams["B"]
    assert "p3" in teams["B"]
    assert len(teams["A"]) == config.TEAM_SIZE
    assert len(teams["B"]) == config.TEAM_SIZE
    assert set(teams["A"]) | set(teams["B"]) == set(PLAYERS)
    assert set(teams["A"]) & set(teams["B"]) == set()


def test_assign_teams_partial_all_picked_is_fully_manual():
    teams = game_logic.assign_teams_partial(PLAYERS, PLAYERS[:4], PLAYERS[4:])
    assert teams["A"] == PLAYERS[:4]
    assert teams["B"] == PLAYERS[4:]


def test_assign_teams_partial_raises_on_overlap():
    with pytest.raises(ValueError):
        game_logic.assign_teams_partial(PLAYERS, ["p1"], ["p1"])


def test_assign_teams_partial_raises_on_oversized_team():
    with pytest.raises(ValueError):
        game_logic.assign_teams_partial(PLAYERS, PLAYERS[:5], [])


def test_assign_teams_partial_raises_on_wrong_total_player_count():
    with pytest.raises(ValueError):
        game_logic.assign_teams_partial(PLAYERS[:7], [], [])


def test_assign_mini_identities_distribution():
    team = [f"p{i}" for i in range(1, 4)]
    identities = game_logic.assign_mini_identities(team)
    assert set(identities.keys()) == set(team)
    counts = {}
    for ident in identities.values():
        counts[ident] = counts.get(ident, 0) + 1
    assert counts[config.IDENTITY_UNDERCOVER] == 1
    assert counts[config.IDENTITY_GOOD] == 2
    assert config.IDENTITY_DUMMY not in counts


def test_assign_mini_identities_wrong_size_raises():
    with pytest.raises(ValueError):
        game_logic.assign_mini_identities(["p1", "p2"])


def test_assign_mini_game_identities_covers_both_teams():
    teams = {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3"]}
    identities = game_logic.assign_mini_game_identities(teams)
    assert set(identities.keys()) == {"a1", "a2", "a3", "b1", "b2", "b3"}
    for team_players in teams.values():
        team_identities = [identities[p] for p in team_players]
        assert team_identities.count(config.IDENTITY_UNDERCOVER) == 1
        assert team_identities.count(config.IDENTITY_GOOD) == 2


def test_assign_identities_distribution():
    team = PLAYERS[:4]
    identities = game_logic.assign_identities(team)
    assert set(identities.keys()) == set(team)
    counts = {}
    for ident in identities.values():
        counts[ident] = counts.get(ident, 0) + 1
    assert counts[config.IDENTITY_UNDERCOVER] == 1
    assert counts[config.IDENTITY_DUMMY] == 1
    assert counts[config.IDENTITY_GOOD] == 2


def test_assign_identities_wrong_size_raises():
    with pytest.raises(ValueError):
        game_logic.assign_identities(PLAYERS[:3])


def test_assign_game_identities_covers_both_teams():
    teams = {"A": PLAYERS[:4], "B": PLAYERS[4:]}
    identities = game_logic.assign_game_identities(teams)
    assert set(identities.keys()) == set(PLAYERS)
    for team_players in teams.values():
        team_identities = [identities[p] for p in team_players]
        assert team_identities.count(config.IDENTITY_UNDERCOVER) == 1
        assert team_identities.count(config.IDENTITY_DUMMY) == 1
        assert team_identities.count(config.IDENTITY_GOOD) == 2


def _make_game():
    teams = {"A": ["a1", "a2", "a3", "a4"], "B": ["b1", "b2", "b3", "b4"]}
    identities = {
        "a1": config.IDENTITY_UNDERCOVER,
        "a2": config.IDENTITY_DUMMY,
        "a3": config.IDENTITY_GOOD,
        "a4": config.IDENTITY_GOOD,
        "b1": config.IDENTITY_UNDERCOVER,
        "b2": config.IDENTITY_DUMMY,
        "b3": config.IDENTITY_GOOD,
        "b4": config.IDENTITY_GOOD,
    }
    return teams, identities


def test_find_player_with_identity_returns_none_when_absent():
    teams, identities = _make_game()
    del identities["a2"]
    identities["a2"] = config.IDENTITY_GOOD
    assert game_logic.find_player_with_identity(
        teams, identities, "A", config.IDENTITY_DUMMY
    ) is None


def test_find_undercover():
    teams, identities = _make_game()
    assert game_logic.find_undercover(teams, identities, "A") == "a1"
    assert game_logic.find_undercover(teams, identities, "B") == "b1"


def test_find_undercover_missing_raises():
    teams, identities = _make_game()
    identities["a1"] = config.IDENTITY_GOOD
    with pytest.raises(ValueError):
        game_logic.find_undercover(teams, identities, "A")


def test_outcome_category_caught():
    teams, identities = _make_game()
    assert game_logic.outcome_category(teams, identities, "A", "a1") == "caught"


def test_outcome_category_dummy():
    teams, identities = _make_game()
    assert game_logic.outcome_category(teams, identities, "A", "a2") == "dummy"


def test_outcome_category_escaped():
    teams, identities = _make_game()
    assert game_logic.outcome_category(teams, identities, "A", "a3") == "escaped"


def test_outcome_category_none():
    teams, identities = _make_game()
    assert game_logic.outcome_category(teams, identities, "A", None) == "none"


def test_confirmation_status_counts_special_identities_only():
    _, identities = _make_game()
    confirmed, needed = game_logic.confirmation_status(identities, {"a1"})
    # 2 undercovers + 2 dummies across both teams need confirmation.
    assert needed == 4
    assert confirmed == 1


def test_eligible_voters_losing_team_plus_winning_undercover():
    teams, identities = _make_game()
    voters = game_logic.eligible_voters(teams, identities, losing_team="A", winning_team="B")
    assert voters == {"a1", "a2", "a3", "a4", "b1"}


def test_eligible_targets_losing_team_only():
    teams, _ = _make_game()
    targets = game_logic.eligible_targets(teams, "A")
    assert targets == {"a1", "a2", "a3", "a4"}


def test_validate_vote_rejects_self_vote():
    with pytest.raises(game_logic.VoteError):
        game_logic.validate_vote("a1", "a1", voters={"a1"}, targets={"a1"})


def test_validate_vote_rejects_ineligible_voter():
    with pytest.raises(game_logic.VoteError):
        game_logic.validate_vote("x", "a1", voters={"a1"}, targets={"a1"})


def test_validate_vote_rejects_ineligible_target():
    with pytest.raises(game_logic.VoteError):
        game_logic.validate_vote("a1", "x", voters={"a1"}, targets={"a2"})


def test_validate_vote_accepts_valid_vote():
    game_logic.validate_vote("a1", "a2", voters={"a1"}, targets={"a2"})


def test_tally_and_top_candidates_no_tie():
    votes = {"v1": "a1", "v2": "a1", "v3": "a2"}
    top, tie = game_logic.top_candidates(votes)
    assert top == ["a1"]
    assert tie is False


def test_top_candidates_tie():
    votes = {"v1": "a1", "v2": "a2"}
    top, tie = game_logic.top_candidates(votes)
    assert set(top) == {"a1", "a2"}
    assert tie is True


def test_top_candidates_empty():
    assert game_logic.top_candidates({}) == ([], False)


def test_resolve_runoff_decisive():
    votes = {"a3": "a1", "a4": "a1", "b1": "a2"}
    eliminated, tie, top = game_logic.resolve_runoff(votes, candidates=["a1", "a2"])
    assert eliminated == "a1"
    assert tie is False


def test_resolve_runoff_tie():
    votes = {"a3": "a1", "a4": "a2"}
    eliminated, tie, top = game_logic.resolve_runoff(votes, candidates=["a1", "a2"])
    assert eliminated is None
    assert tie is True
    assert set(top) == {"a1", "a2"}


def test_resolve_runoff_candidate_cannot_vote():
    votes = {"a1": "a2"}
    with pytest.raises(game_logic.VoteError):
        game_logic.resolve_runoff(votes, candidates=["a1", "a2"])


def test_resolve_runoff_only_candidates_are_valid_targets():
    votes = {"a3": "b1"}
    with pytest.raises(game_logic.VoteError):
        game_logic.resolve_runoff(votes, candidates=["a1", "a2"])


class TestCalculateScores:
    def _base(self, eliminated_player, final_round_votes=None):
        teams, identities = _make_game()
        return game_logic.calculate_scores(
            teams=teams,
            identities=identities,
            losing_team="A",
            winning_team="B",
            eliminated_player=eliminated_player,
            final_round_votes=final_round_votes or {},
        )

    def test_losing_undercover_caught(self):
        scores = self._base(eliminated_player="a1")
        assert scores["a1"] == 0  # base +1, caught -1

    def test_losing_undercover_not_caught(self):
        scores = self._base(eliminated_player="a2")  # dummy voted out instead
        assert scores["a1"] == 2  # base +1, not caught +1

    def test_losing_dummy_voted_out(self):
        scores = self._base(eliminated_player="a2")
        assert scores["a2"] == 2

    def test_losing_dummy_not_voted_out(self):
        scores = self._base(eliminated_player="a1")
        assert scores["a2"] == 0

    def test_losing_good_players_score_zero(self):
        scores = self._base(eliminated_player="a1")
        assert scores["a3"] == 0
        assert scores["a4"] == 0

    def test_winning_undercover_base_penalty(self):
        scores = self._base(eliminated_player="a1")
        assert scores["b1"] == -1

    def test_winning_undercover_bonus_for_correct_final_round_vote(self):
        scores = self._base(eliminated_player="a1", final_round_votes={"b1": "a1"})
        assert scores["b1"] == 0  # -1 base + 1 bonus

    def test_winning_dummy_scores_zero(self):
        scores = self._base(eliminated_player="a1")
        assert scores["b2"] == 0

    def test_winning_good_players_score_one(self):
        scores = self._base(eliminated_player="a1")
        assert scores["b3"] == 1
        assert scores["b4"] == 1

    def test_losing_member_correct_final_round_vote_bonus(self):
        scores = self._base(eliminated_player="a1", final_round_votes={"a3": "a1"})
        assert scores["a3"] == 1  # 0 base + 1 bonus

    def test_incorrect_final_round_vote_gives_no_bonus(self):
        scores = self._base(eliminated_player="a1", final_round_votes={"a3": "a2"})
        assert scores["a3"] == 0

    def test_vote_bonus_is_per_player_independent_of_group_result(self):
        # Group got it wrong -- eliminated the dummy (a2), not the real
        # undercover (a1) -- but a3 personally voted for a1 anyway.
        scores = self._base(
            eliminated_player="a2", final_round_votes={"a3": "a1", "a4": "a2"}
        )
        assert scores["a3"] == 1  # 0 base + 1 bonus: individually correct
        assert scores["a4"] == 0  # 0 base + 0: individually wrong, even
        # though "a2" matches the group's (wrong) elimination target.

    def test_all_players_scored(self):
        scores = self._base(eliminated_player="a1")
        assert set(scores.keys()) == {
            "a1", "a2", "a3", "a4", "b1", "b2", "b3", "b4",
        }

    def test_no_one_eliminated_treated_as_undercover_not_caught(self):
        # /game override with no `caught` player: eliminated_player=None,
        # meaning nobody was voted out at all.
        scores = self._base(eliminated_player=None)
        assert scores["a1"] == 2  # losing undercover: base +1, not caught +1
        assert scores["a2"] == 0  # losing dummy: not voted out
