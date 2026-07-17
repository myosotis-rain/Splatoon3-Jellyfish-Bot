import pytest

from gamebot import config, game_flow, game_logic
from gamebot.db import Database


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def _setup_game(db):
    session_id = db.create_session("server1", "chan1")
    game_id, _ = db.create_game(session_id)
    teams = {"A": [1, 2, 3, 4], "B": [5, 6, 7, 8]}
    identities = {
        1: config.IDENTITY_UNDERCOVER, 2: config.IDENTITY_DUMMY,
        3: config.IDENTITY_GOOD, 4: config.IDENTITY_GOOD,
        5: config.IDENTITY_UNDERCOVER, 6: config.IDENTITY_DUMMY,
        7: config.IDENTITY_GOOD, 8: config.IDENTITY_GOOD,
    }
    db.save_team_assignment(game_id, teams, identities)
    db.set_game_result(game_id, losing_team="A", winning_team="B")
    session = db.get_session(session_id)
    game = db.get_game(game_id)
    teams, identities = db.get_teams_and_identities(game_id)
    return session, game, teams, identities


def test_resolve_round1_no_votes_returns_none(db):
    session, game, teams, identities = _setup_game(db)
    assert game_flow.resolve_round1(db, game) is None


def test_resolve_round1_tie_moves_to_runoff(db):
    session, game, teams, identities = _setup_game(db)
    db.record_vote(game["id"], 1, voter_id="3", target_id="1")
    db.record_vote(game["id"], 1, voter_id="4", target_id="2")
    msg = game_flow.resolve_round1(db, game)
    assert "平票" in msg

    game = db.get_game(game["id"])
    assert game["status"] == "voting_round2"
    assert db.get_current_round(game["id"]) == 2
    assert set(db.get_vote_candidates(game["id"])) == {"1", "2"}


def test_resolve_round1_decisive_still_advances_to_confirmation_round(db):
    session, game, teams, identities = _setup_game(db)
    db.record_vote(game["id"], 1, voter_id="3", target_id="1")
    db.record_vote(game["id"], 1, voter_id="4", target_id="1")
    msg = game_flow.resolve_round1(db, game)
    assert "最高票" in msg

    game = db.get_game(game["id"])
    assert game["status"] == "voting_round2"
    assert db.get_vote_candidates(game["id"]) == ["1"]


def test_resolve_runoff_decisive_finalizes_game(db):
    session, game, teams, identities = _setup_game(db)
    db.set_vote_candidates(game["id"], ["1", "2"])
    db.set_current_round(game["id"], 2)
    db.set_game_status(game["id"], "voting_round2")
    db.record_vote(game["id"], 2, voter_id="3", target_id="1")
    db.record_vote(game["id"], 2, voter_id="4", target_id="1")

    game = db.get_game(game["id"])
    msg = game_flow.resolve_runoff(db, session, game, teams, identities)
    assert "本局积分" in msg

    finished = db.get_game(game["id"])
    assert finished["status"] == "completed"
    assert finished["eliminated_player"] == "1"


def test_resolve_runoff_tie_starts_next_round_with_narrowed_voters(db):
    session, game, teams, identities = _setup_game(db)
    db.set_vote_candidates(game["id"], ["1", "2"])
    db.set_current_round(game["id"], 2)
    db.set_game_status(game["id"], "voting_round2")
    # only losing team's 3 & 4 (plus winning undercover 5) are eligible;
    # candidates 1 & 2 cannot vote. Split evenly -> tie.
    db.record_vote(game["id"], 2, voter_id="3", target_id="1")
    db.record_vote(game["id"], 2, voter_id="4", target_id="2")

    game = db.get_game(game["id"])
    msg = game_flow.resolve_runoff(db, session, game, teams, identities)
    assert "仍然平票" in msg
    assert "第 3 轮" in msg

    game = db.get_game(game["id"])
    assert game["status"] == "voting_round2"
    assert db.get_current_round(game["id"]) == 3
    assert set(db.get_vote_candidates(game["id"])) == {"1", "2"}

    # round 3: voters are still (losing team + winning undercover) minus
    # the (still) tied candidates -- same pool as round 2 here, but now
    # everyone breaks for candidate "1".
    db.record_vote(game["id"], 3, voter_id="3", target_id="1")
    db.record_vote(game["id"], 3, voter_id="4", target_id="1")
    game = db.get_game(game["id"])
    msg = game_flow.resolve_runoff(db, session, game, teams, identities)
    assert "本局积分" in msg
    finished = db.get_game(game["id"])
    assert finished["status"] == "completed"
    assert finished["eliminated_player"] == "1"


def test_voters_and_targets_round1(db):
    session, game, teams, identities = _setup_game(db)
    round_no, voters, targets = game_flow.voters_and_targets(db, teams, identities, game)
    assert round_no == 1
    assert voters == {"1", "2", "3", "4", "5"}
    assert targets == {"1", "2", "3", "4"}


def test_voters_and_targets_runoff_excludes_candidates(db):
    session, game, teams, identities = _setup_game(db)
    db.set_vote_candidates(game["id"], ["1", "2"])
    db.set_current_round(game["id"], 2)
    db.set_game_status(game["id"], "voting_round2")
    game = db.get_game(game["id"])

    round_no, voters, targets = game_flow.voters_and_targets(db, teams, identities, game)
    assert round_no == 2
    assert voters == {"3", "4", "5"}
    assert targets == {"1", "2"}


def test_resolve_current_round_dispatches_by_status(db):
    session, game, teams, identities = _setup_game(db)
    db.record_vote(game["id"], 1, voter_id="3", target_id="1")
    msg = game_flow.resolve_current_round(db, session, game, teams, identities)
    assert "最高票" in msg
