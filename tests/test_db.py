import pytest

from gamebot.db import Database


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def test_create_and_get_active_session(db):
    session_id = db.create_session("server1", "chan1", "Friday Night")
    session = db.get_active_session("server1")
    assert session["id"] == session_id
    assert session["name"] == "Friday Night"
    assert session["status"] == "active"


def test_creating_new_session_closes_previous_active_one(db):
    first_id = db.create_session("server1", "chan1", "First")
    second_id = db.create_session("server1", "chan1", "Second")
    active = db.get_active_session("server1")
    assert active["id"] == second_id
    first = db.get_session(first_id)
    assert first["status"] == "closed"


def test_get_username_returns_none_for_unseen_player(db):
    assert db.get_username(999) is None


def test_name_or_id_falls_back_to_id_string(db):
    assert db.name_or_id(999) == "999"


def test_name_or_id_returns_username_when_known(db):
    db.upsert_player(111, "Sophia")
    assert db.name_or_id(111) == "Sophia"


def test_upsert_player_always_overwrites(db):
    db.upsert_player(111, "Sophia")
    db.upsert_player(111, "CustomName")
    assert db.get_username(111) == "CustomName"


def test_ensure_player_seen_does_not_clobber_existing_name(db):
    db.upsert_player(111, "CustomName")
    db.ensure_player_seen(111, "DiscordDisplayName")
    assert db.get_username(111) == "CustomName"


def test_ensure_player_seen_sets_name_for_new_player(db):
    db.ensure_player_seen(111, "DiscordDisplayName")
    assert db.get_username(111) == "DiscordDisplayName"


def test_join_session_does_not_clobber_a_rename(db):
    session_id = db.create_session("server1", "chan1")
    db.upsert_player(111, "CustomName")
    db.join_session(session_id, 111, "DiscordDisplayName")
    assert db.get_username(111) == "CustomName"


def test_join_and_leave_session(db):
    session_id = db.create_session("server1", "chan1")
    db.join_session(session_id, 111, "Sophia")
    assert db.get_session_players(session_id) == ["111"]
    assert db.is_active_in_session(session_id, 111) is True

    db.leave_session(session_id, 111)
    assert db.get_session_players(session_id) == []
    assert db.is_active_in_session(session_id, 111) is False


def test_leave_then_rejoin_preserves_score(db):
    session_id = db.create_session("server1", "chan1")
    db.join_session(session_id, 111, "Sophia")
    game_id, _ = db.create_game(session_id)
    db.save_team_assignment(
        game_id,
        {"A": [111, 2, 3, 4], "B": [5, 6, 7, 8]},
        {111: "好鱿", 2: "好鱿", 3: "好鱿", 4: "好鱿",
         5: "好鱿", 6: "好鱿", 7: "好鱿", 8: "好鱿"},
    )
    db.finalize_scores(session_id, game_id, {111: 3})

    db.leave_session(session_id, 111)
    db.join_session(session_id, 111, "Sophia")

    board = db.get_session_leaderboard(session_id)
    entry = next(e for e in board if e["player_id"] == "111")
    assert entry["total_score"] == 3
    assert entry["games_played"] == 1


def test_session_leaderboard_ranks_by_average_then_total(db):
    session_id = db.create_session("server1", "chan1")
    for pid in (1, 2):
        db.join_session(session_id, pid, f"p{pid}")
    game_id, _ = db.create_game(session_id)
    teams = {"A": [1, 3, 4, 5], "B": [2, 6, 7, 8]}
    identities = {p: "好鱿" for team in teams.values() for p in team}
    db.save_team_assignment(game_id, teams, identities)
    db.finalize_scores(session_id, game_id, {1: 4, 2: 2, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0})

    board = db.get_session_leaderboard(session_id)
    ranked_ids = [e["player_id"] for e in board if e["player_id"] in ("1", "2")]
    assert ranked_ids == ["1", "2"]


def test_create_game_increments_game_number(db):
    session_id = db.create_session("server1", "chan1")
    _, first_number = db.create_game(session_id)
    _, second_number = db.create_game(session_id)
    assert first_number == 1
    assert second_number == 2


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


def test_save_team_assignment_marks_special_identities_unconfirmed(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    teams = {"A": [1, 2, 3, 4], "B": [5, 6, 7, 8]}
    identities = {
        1: "卧底", 2: "呆呆鱿", 3: "好鱿", 4: "好鱿",
        5: "卧底", 6: "呆呆鱿", 7: "好鱿", 8: "好鱿",
    }
    db.save_team_assignment(game_id, teams, identities)

    assert db.is_confirmed(game_id, 1) is False
    assert db.is_confirmed(game_id, 2) is False
    assert db.is_confirmed(game_id, 3) is True
    assert db.is_confirmed(game_id, 4) is True


def test_confirm_flow(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    teams = {"A": [1, 2, 3, 4], "B": [5, 6, 7, 8]}
    identities = {p: "好鱿" for team in teams.values() for p in team}
    identities[1] = "卧底"
    db.save_team_assignment(game_id, teams, identities)

    assert db.is_confirmed(game_id, 1) is False
    db.set_confirmed(game_id, 1)
    assert db.is_confirmed(game_id, 1) is True


def test_get_identity_returns_identity_and_team(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    teams = {"A": [1, 2, 3, 4], "B": [5, 6, 7, 8]}
    identities = {p: "好鱿" for team in teams.values() for p in team}
    identities[1] = "卧底"
    db.save_team_assignment(game_id, teams, identities)

    identity, team = db.get_identity(game_id, 1)
    assert identity == "卧底"
    assert team == "A"


def test_votes_round_trip(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    db.record_vote(game_id, 1, 10, 20)
    db.record_vote(game_id, 1, 11, 20)
    votes = db.get_votes(game_id, 1)
    assert votes == {"10": "20", "11": "20"}


def test_record_vote_overwrites_previous_vote_same_round(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    db.record_vote(game_id, 1, 10, 20)
    db.record_vote(game_id, 1, 10, 30)
    votes = db.get_votes(game_id, 1)
    assert votes == {"10": "30"}


def test_vote_candidates_round_trip(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    db.set_vote_candidates(game_id, [10, 20])
    assert db.get_vote_candidates(game_id) == ["10", "20"]


def test_current_round_defaults_to_one_and_updates(db):
    game_id, _ = db.create_game(db.create_session("server1", "chan1"))
    assert db.get_current_round(game_id) == 1
    db.set_current_round(game_id, 3)
    assert db.get_current_round(game_id) == 3


def test_finalize_scores_updates_session_totals_and_game_status(db):
    session_id = db.create_session("server1", "chan1")
    db.join_session(session_id, 1, "p1")
    game_id, _ = db.create_game(session_id)
    teams = {"A": [1, 2, 3, 4], "B": [5, 6, 7, 8]}
    identities = {p: "好鱿" for team in teams.values() for p in team}
    db.save_team_assignment(game_id, teams, identities)

    db.finalize_scores(session_id, game_id, {1: 2, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0})

    game = db.get_game(game_id)
    assert game["status"] == "completed"
    board = db.get_session_leaderboard(session_id)
    entry = next(e for e in board if e["player_id"] == "1")
    assert entry["total_score"] == 2
    assert entry["games_played"] == 1


def test_adjust_score_modifies_existing_player(db):
    session_id = db.create_session("server1", "chan1")
    db.join_session(session_id, 1, "p1")
    db.adjust_score(session_id, 1, 5)
    row = db.get_session_player_row(session_id, 1)
    assert row["total_score"] == 5
    db.adjust_score(session_id, 1, -2)
    row = db.get_session_player_row(session_id, 1)
    assert row["total_score"] == 3


def test_get_session_player_row_missing_player_returns_none(db):
    session_id = db.create_session("server1", "chan1")
    assert db.get_session_player_row(session_id, 999) is None


def test_get_sessions_lists_all_newest_first(db):
    first_id = db.create_session("server1", "chan1", "First")
    second_id = db.create_session("server1", "chan1", "Second")
    sessions = db.get_sessions("server1")
    assert [s["id"] for s in sessions] == [second_id, first_id]
    assert sessions[0]["status"] == "active"
    assert sessions[1]["status"] == "closed"


def test_get_sessions_scoped_to_server(db):
    db.create_session("server1", "chan1")
    db.create_session("server2", "chan1")
    assert len(db.get_sessions("server1")) == 1
    assert len(db.get_sessions("server2")) == 1


def test_get_sessions_caps_at_ten_by_default(db):
    ids = [db.create_session("server1", "chan1", f"Session {i}") for i in range(12)]
    sessions = db.get_sessions("server1")
    assert len(sessions) == 10
    assert [s["id"] for s in sessions] == list(reversed(ids))[:10]


def test_reopen_session_reactivates_and_closes_current(db):
    first_id = db.create_session("server1", "chan1", "First")
    second_id = db.create_session("server1", "chan1", "Second")

    assert db.reopen_session("server1", first_id) is True

    assert db.get_session(first_id)["status"] == "active"
    assert db.get_session(second_id)["status"] == "closed"
    assert db.get_active_session("server1")["id"] == first_id


def test_reopen_session_returns_false_for_unknown_id(db):
    db.create_session("server1", "chan1")
    assert db.reopen_session("server1", 9999) is False


def test_close_session_leaves_no_active_session(db):
    session_id = db.create_session("server1", "chan1")
    db.close_session("server1")
    assert db.get_active_session("server1") is None
    assert db.get_session(session_id)["status"] == "closed"


def test_close_mini_session_leaves_no_active_mini_session(db):
    session_id = db.create_mini_session("server1", "chan1")
    db.close_mini_session("server1")
    assert db.get_active_mini_session("server1") is None
    assert db.get_mini_session(session_id)["status"] == "closed"


# -- mini sessions (3v3, unscored) -------------------------------------------


def test_create_and_get_active_mini_session(db):
    session_id = db.create_mini_session("server1", "chan1")
    session = db.get_active_mini_session("server1")
    assert session["id"] == session_id
    assert session["status"] == "active"


def test_creating_new_mini_session_closes_previous_active_one(db):
    first_id = db.create_mini_session("server1", "chan1")
    second_id = db.create_mini_session("server1", "chan1")
    active = db.get_active_mini_session("server1")
    assert active["id"] == second_id
    assert db.get_mini_session(first_id)["status"] == "closed"


def test_mini_join_and_leave(db):
    session_id = db.create_mini_session("server1", "chan1")
    db.join_mini_session(session_id, 111, "Sophia")
    assert db.get_mini_session_players(session_id) == ["111"]
    db.leave_mini_session(session_id, 111)
    assert db.get_mini_session_players(session_id) == []


def test_create_mini_game_increments_game_number(db):
    session_id = db.create_mini_session("server1", "chan1")
    _, first_number = db.create_mini_game(session_id)
    _, second_number = db.create_mini_game(session_id)
    assert first_number == 1
    assert second_number == 2


def test_save_mini_team_assignment_and_fetch(db):
    session_id = db.create_mini_session("server1", "chan1")
    game_id, _ = db.create_mini_game(session_id)
    teams = {"A": [1, 2, 3], "B": [4, 5, 6]}
    identities = {
        1: "卧底", 2: "好鱿", 3: "好鱿",
        4: "卧底", 5: "好鱿", 6: "好鱿",
    }
    db.save_mini_team_assignment(game_id, teams, identities)

    fetched_teams, fetched_identities = db.get_mini_teams_and_identities(game_id)
    assert set(fetched_teams["A"]) == {"1", "2", "3"}
    assert fetched_identities["1"] == "卧底"


def test_mini_votes_round_trip(db):
    session_id = db.create_mini_session("server1", "chan1")
    game_id, _ = db.create_mini_game(session_id)
    db.record_mini_vote(game_id, 1, 10, 20)
    db.record_mini_vote(game_id, 1, 11, 20)
    assert db.get_mini_votes(game_id, 1) == {"10": "20", "11": "20"}


def test_mini_vote_candidates_and_current_round(db):
    session_id = db.create_mini_session("server1", "chan1")
    game_id, _ = db.create_mini_game(session_id)
    assert db.get_mini_current_round(game_id) == 1
    db.set_mini_vote_candidates(game_id, [10, 20])
    db.set_mini_current_round(game_id, 2)
    assert db.get_mini_vote_candidates(game_id) == ["10", "20"]
    assert db.get_mini_current_round(game_id) == 2


def test_complete_mini_game_sets_status_without_touching_scores(db):
    session_id = db.create_mini_session("server1", "chan1")
    game_id, _ = db.create_mini_game(session_id)
    db.set_mini_eliminated(game_id, "1")
    db.complete_mini_game(game_id)
    game = db.get_mini_game(game_id)
    assert game["status"] == "completed"
    assert game["eliminated_player"] == "1"
