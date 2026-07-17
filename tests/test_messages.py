from gamebot import config, messages


def test_mention_format():
    assert messages.mention("123") == "<@123>"


def test_loss_result_line_shows_both_team_emoji():
    text = messages.loss_result_line("A", "B")
    assert "🔴 A" in text
    assert "🔵 B" in text


def test_team_announcement_text_contains_all_players_and_emoji():
    teams = {"A": ["p1", "p2"], "B": ["p3", "p4"]}
    text = messages.team_announcement_text(3, teams)
    assert "Game #3" in text
    assert "🔴 A" in text
    assert "🔵 B" in text
    for pid in ("p1", "p2", "p3", "p4"):
        assert messages.mention(pid) in text


def test_identity_card_text_undercover():
    text = messages.identity_card_text("A", config.IDENTITY_UNDERCOVER)
    assert "身份卡" in text
    assert "卧底" in text
    assert "隐藏自己的身份" in text
    assert "被成功指认" in text


def test_identity_card_text_dummy():
    text = messages.identity_card_text("A", config.IDENTITY_DUMMY)
    assert "呆呆鱿" in text
    assert "被票出局" in text


def test_identity_card_text_good():
    text = messages.identity_card_text("A", config.IDENTITY_GOOD)
    assert "好鱿" in text
    assert "帮助队伍获胜" in text


def test_mini_identity_card_text_undercover():
    text = messages.mini_identity_card_text("A", config.IDENTITY_UNDERCOVER)
    assert "身份卡" in text
    assert "Mini" in text
    assert "不计分" in text
    assert "卧底" in text
    assert "隐藏自己的身份" in text
    assert "计分规则" not in text  # mini cards have no scoring section


def test_mini_identity_card_text_good():
    text = messages.mini_identity_card_text("B", config.IDENTITY_GOOD)
    assert "好鱿" in text
    assert "帮助队伍获胜" in text


def test_all_confirmed_line_uses_jelly():
    assert messages.all_confirmed_line().startswith(messages.JELLY)


def test_confirmation_status_text_ready_uses_all_confirmed_line():
    text = messages.confirmation_status_text(4, 4)
    assert messages.all_confirmed_line() in text


def test_confirmation_status_text_not_ready():
    text = messages.confirmation_status_text(2, 4)
    assert "2/4" in text
    assert "可以开始" not in text


def test_confirmation_status_text_ready():
    text = messages.confirmation_status_text(4, 4)
    assert "4/4" in text
    assert "可以开始" in text


def test_reveal_text_lists_all_identities():
    teams = {"A": ["p1"], "B": ["p2"]}
    identities = {"p1": config.IDENTITY_UNDERCOVER, "p2": config.IDENTITY_GOOD}
    text = messages.reveal_text(teams, identities, losing_team="A", winning_team="B")
    assert "身份揭晓" in text
    assert "落败" in text
    assert "胜利" in text
    assert f"{messages.mention('p1')}: 🫥 {config.IDENTITY_UNDERCOVER}" in text
    assert f"{messages.mention('p2')}: {config.IDENTITY_GOOD}" in text


def test_outcome_text_covers_all_categories():
    for category in ("none", "caught", "dummy", "escaped"):
        assert messages.outcome_text(category)


def test_leaderboard_text_empty():
    assert "暂无数据" in messages.leaderboard_text([])


def test_leaderboard_text_formats_average_and_rank():
    board = [
        {"username": "Sophia", "total_score": 8, "games_played": 3, "average": 8 / 3},
        {"username": "Alex", "total_score": 8, "games_played": 4, "average": 2.0},
    ]
    text = messages.leaderboard_text(board)
    assert "第 1 名 · Sophia" in text
    assert "第 2 名 · Alex" in text
    assert "2.67" in text
    assert "2.00" in text
    assert text.index("Sophia") < text.index("Alex")


def test_session_status_text_lists_players():
    text = messages.session_status_text("Friday Night", ["Sophia", "Alex"])
    assert "Friday Night" in text
    assert "参与人数: 2" in text
    assert "Sophia" in text
    assert "Alex" in text


def test_session_status_text_empty_roster():
    text = messages.session_status_text("Friday Night", [])
    assert "参与人数: 0" in text


def test_session_list_text_empty():
    assert "暂无场次" in messages.session_list_text([])


def test_session_list_text_shows_status_and_counts():
    active = {"id": 2, "name": "Second", "status": "active"}
    closed = {"id": 1, "name": None, "status": "closed"}
    text = messages.session_list_text([(active, 3), (closed, 5)])
    assert "#2" in text
    assert "🟢 进行中" in text
    assert "Second" in text
    assert "3 人" in text
    assert "#1" in text
    assert "⚪ 已结束" in text
    assert "Session #1" in text
    assert "5 人" in text


def test_mini_status_text_lists_players_and_capacity():
    text = messages.mini_status_text(["Sophia", "Alex"], 6)
    assert "2/6" in text
    assert "Sophia" in text
    assert "Alex" in text


def test_tie_text_lists_candidates():
    text = messages.tie_text(["Sophia", "Alex"])
    assert "平票" in text
    assert "Sophia" in text
    assert "Alex" in text
