import pytest

from gamebot import config, mini_flow
from gamebot.db import Database


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def _setup_game(db):
    session_id = db.create_mini_session("server1", "chan1")
    game_id, _ = db.create_mini_game(session_id)
    teams = {"A": [1, 2, 3], "B": [4, 5, 6]}
    identities = {
        1: config.IDENTITY_UNDERCOVER, 2: config.IDENTITY_GOOD, 3: config.IDENTITY_GOOD,
        4: config.IDENTITY_UNDERCOVER, 5: config.IDENTITY_GOOD, 6: config.IDENTITY_GOOD,
    }
    db.save_mini_team_assignment(game_id, teams, identities)
    db.set_mini_game_result(game_id, losing_team="A", winning_team="B")
    game = db.get_mini_game(game_id)
    teams, identities = db.get_mini_teams_and_identities(game_id)
    return game, teams, identities


def test_resolve_round1_no_votes_returns_none(db):
    game, teams, identities = _setup_game(db)
    assert mini_flow.resolve_round1(db, game) is None


def test_resolve_round1_tie_moves_to_runoff(db):
    game, teams, identities = _setup_game(db)
    db.record_mini_vote(game["id"], 1, voter_id="2", target_id="1")
    db.record_mini_vote(game["id"], 1, voter_id="3", target_id="4")
    # "4" isn't a valid target for round 1 in practice (only losing team is),
    # but mini_flow.resolve_round1 just tallies whatever votes exist.
    msg = mini_flow.resolve_round1(db, game)
    game = db.get_mini_game(game["id"])
    assert game["status"] == "voting_round2"
    assert db.get_mini_current_round(game["id"]) == 2


def test_resolve_runoff_decisive_catches_undercover(db):
    game, teams, identities = _setup_game(db)
    db.set_mini_vote_candidates(game["id"], ["1", "2"])
    db.set_mini_current_round(game["id"], 2)
    db.set_mini_game_status(game["id"], "voting_round2")
    db.record_mini_vote(game["id"], 2, voter_id="3", target_id="1")

    game = db.get_mini_game(game["id"])
    msg = mini_flow.resolve_runoff(db, game, teams, identities)
    assert "抓到卧底了" in msg

    finished = db.get_mini_game(game["id"])
    assert finished["status"] == "completed"
    assert finished["eliminated_player"] == "1"


def test_resolve_runoff_decisive_wrong_target_reports_escape(db):
    game, teams, identities = _setup_game(db)
    db.set_mini_vote_candidates(game["id"], ["1", "2"])
    db.set_mini_current_round(game["id"], 2)
    db.set_mini_game_status(game["id"], "voting_round2")
    db.record_mini_vote(game["id"], 2, voter_id="3", target_id="2")

    game = db.get_mini_game(game["id"])
    msg = mini_flow.resolve_runoff(db, game, teams, identities)
    assert "逃脱了" in msg

    finished = db.get_mini_game(game["id"])
    assert finished["status"] == "completed"
    assert finished["eliminated_player"] == "2"


def test_resolve_runoff_tie_starts_next_round(db):
    game, teams, identities = _setup_game(db)
    db.set_mini_vote_candidates(game["id"], ["1", "2"])
    db.set_mini_current_round(game["id"], 2)
    db.set_mini_game_status(game["id"], "voting_round2")
    # only losing team's player 3 and winning undercover 4 are eligible;
    # split their votes evenly across the two candidates to force a tie.
    db.record_mini_vote(game["id"], 2, voter_id="3", target_id="1")
    db.record_mini_vote(game["id"], 2, voter_id="4", target_id="2")

    game = db.get_mini_game(game["id"])
    msg = mini_flow.resolve_runoff(db, game, teams, identities)
    assert "仍然平票" in msg
    assert "第 3 轮" in msg

    game = db.get_mini_game(game["id"])
    assert game["status"] == "voting_round2"
    assert db.get_mini_current_round(game["id"]) == 3
    assert set(db.get_mini_vote_candidates(game["id"])) == {"1", "2"}


def test_voters_and_targets_round1(db):
    game, teams, identities = _setup_game(db)
    round_no, voters, targets = mini_flow.voters_and_targets(db, teams, identities, game)
    assert round_no == 1
    assert voters == {"1", "2", "3", "4"}
    assert targets == {"1", "2", "3"}


def test_voters_and_targets_runoff_excludes_candidates(db):
    game, teams, identities = _setup_game(db)
    db.set_mini_vote_candidates(game["id"], ["1", "2"])
    db.set_mini_current_round(game["id"], 2)
    db.set_mini_game_status(game["id"], "voting_round2")
    game = db.get_mini_game(game["id"])

    round_no, voters, targets = mini_flow.voters_and_targets(db, teams, identities, game)
    assert round_no == 2
    assert voters == {"3", "4"}
    assert targets == {"1", "2"}


def test_resolve_current_round_dispatches_by_status(db):
    game, teams, identities = _setup_game(db)
    db.record_mini_vote(game["id"], 1, voter_id="2", target_id="1")
    msg = mini_flow.resolve_current_round(db, game, teams, identities)
    assert "最高票" in msg
