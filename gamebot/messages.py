"""Pure text-formatting helpers for bot output. Kept discord-free so the
formatting can be unit tested without a live connection.
"""

from . import config

TEAM_EMOJI = {"A": "🔴", "B": "🔵"}

# Decorative glyphs used to dress up bot output. JELLY replaces the plain
# checkmark everywhere -- it's the one deliberate emoji exception, tying
# confirmations back to the bot's own mascot. Everything else here is a
# dingbat/box-drawing character, not an emoji.
JELLY = "🪼"
STAR = "✦"
CARD_TOP = "┏━━━━━━━━━━━━━━━┓"
CARD_BOTTOM = "┗━━━━━━━━━━━━━━━┛"
SECTION_RULE = "┄┄┄"
CLOSING_FLOURISH = "❀ " + "┄" * 15 + " ❀"

IDENTITY_TASKS = {
    config.IDENTITY_UNDERCOVER: (
        "- 导致己方队伍失败\n- 隐藏自己的身份"
    ),
    config.IDENTITY_DUMMY: (
        "- 导致己方队伍失败\n- 被票出局"
    ),
    config.IDENTITY_GOOD: "帮助队伍获胜",
}

IDENTITY_EMOJI = {
    config.IDENTITY_UNDERCOVER: "🫥",
    config.IDENTITY_DUMMY: "🐡",
}

IDENTITY_SCORING = {
    config.IDENTITY_UNDERCOVER: (
        "基础分: +1\n"
        "未被成功指认: +1\n"
        "被成功指认: -1 (抵消基础分)\n\n"
        "额外:\n"
        "如果你属于胜方，需要参与指认输方卧底\n"
        "成功指认: +1"
    ),
    config.IDENTITY_DUMMY: "被票出: +2\n其他情况: 0",
    config.IDENTITY_GOOD: "胜利: +1\n正确投票卧底: +1\n失败: 0",
}


def mention(player_id):
    return f"<@{player_id}>"


def loss_result_line(losing_team, winning_team):
    losing_emoji = TEAM_EMOJI.get(losing_team, losing_team)
    winning_emoji = TEAM_EMOJI.get(winning_team, winning_team)
    return f"{losing_emoji} {losing_team} 落败　{winning_emoji} {winning_team} 胜利"


def winning_special_roles_line(winning_team, undercover_name, dummy_name):
    emoji = TEAM_EMOJI.get(winning_team, winning_team)
    parts = [f"{IDENTITY_EMOJI[config.IDENTITY_UNDERCOVER]} 卧底 {undercover_name}"]
    if dummy_name:
        parts.append(f"{IDENTITY_EMOJI[config.IDENTITY_DUMMY]} 呆呆鱿 {dummy_name}")
    return f"{emoji} {winning_team} 特殊身份　" + "　".join(parts)


def vote_tally_text(tally):
    """tally: list of (name, count) tuples, most votes first."""
    lines = ["🫧 本轮投票结果:"]
    lines.extend(f"{name}: {count} 票" for name, count in tally)
    return "\n".join(lines)


def team_announcement_text(game_number, teams, names, label="Game"):
    lines = [f"{STAR} {label} #{game_number} {STAR}", ""]
    for team, player_ids in teams.items():
        emoji = TEAM_EMOJI.get(team, team)
        lines.append(f"{emoji} {team}")
        for player_id in player_ids:
            lines.append(names[player_id])
        lines.append("")
    lines.append(CLOSING_FLOURISH)
    return "\n".join(lines).strip()


def identity_card_text(team, identity):
    emoji = TEAM_EMOJI.get(team, team)
    return (
        f"{CARD_TOP}\n"
        f"　　{STAR} 身份卡 {STAR}\n"
        f"{CARD_BOTTOM}\n"
        f"队伍　{STAR}　{emoji} {team}\n"
        f"身份　{STAR}　{identity}\n\n"
        f"{SECTION_RULE} 任务 {SECTION_RULE}\n"
        f"{IDENTITY_TASKS[identity]}\n\n"
        f"{SECTION_RULE} 计分规则 {SECTION_RULE}\n"
        f"{IDENTITY_SCORING[identity]}\n"
        f"{CARD_BOTTOM}"
    )


MINI_IDENTITY_TASKS = {
    config.IDENTITY_UNDERCOVER: "- 导致己方队伍失败\n- 隐藏自己的身份",
    config.IDENTITY_GOOD: "帮助队伍获胜",
}


def mini_identity_card_text(team, identity):
    emoji = TEAM_EMOJI.get(team, team)
    return (
        f"{CARD_TOP}\n"
        f"　　{STAR} 身份卡 · Mini 3v3 {STAR}\n"
        f"　　　　（不计分）\n"
        f"{CARD_BOTTOM}\n"
        f"队伍　{STAR}　{emoji} {team}\n"
        f"身份　{STAR}　{identity}\n\n"
        f"{SECTION_RULE} 任务 {SECTION_RULE}\n"
        f"{MINI_IDENTITY_TASKS[identity]}\n"
        f"{CARD_BOTTOM}"
    )


def all_confirmed_line():
    return f"{JELLY} 全部确认，可以开始游戏。"


def confirmation_status_text(confirmed, needed):
    text = f"🎴 特殊身份确认: {confirmed}/{needed}"
    if confirmed >= needed:
        text += f"\n{all_confirmed_line()}"
    return text


def reveal_text(teams, identities, losing_team, winning_team):
    lines = [f"🎨 {STAR} 身份揭晓 {STAR}", ""]
    for team, player_ids in teams.items():
        emoji = TEAM_EMOJI.get(team, team)
        result = "落败" if team == losing_team else "胜利"
        lines.append(f"{emoji} {team}　{result}")
        for player_id in player_ids:
            identity = identities[player_id]
            id_emoji = IDENTITY_EMOJI.get(identity)
            label = f"{id_emoji} {identity}" if id_emoji else identity
            lines.append(f"{mention(player_id)}: {label}")
        lines.append("")
    lines.append(CLOSING_FLOURISH)
    return "\n".join(lines).strip()


OUTCOME_LINES = {
    "none": "😅 卧底未被抓到。",
    "caught": "🎉 抓到卧底了！",
    "dummy": "🐡 呆呆鱿成功被票出，卧底逃脱了！",
    "escaped": "😅 卧底逃脱了！",
}


def outcome_text(category):
    return OUTCOME_LINES[category]


RANK_GLYPHS = {1: "✦", 2: "❀", 3: "⋆"}


def leaderboard_text(board):
    if not board:
        return "🐚 暂无数据"
    lines = [f"🐚 {STAR} 本次活动积分 {STAR}", ""]
    for i, entry in enumerate(board, start=1):
        glyph = RANK_GLYPHS.get(i, "·")
        lines.append(f"{glyph} 第 {i} 名 · {entry['username']}")
        lines.append(
            f"场次 {entry['games_played']}｜总分 {entry['total_score']}｜"
            f"均分 {entry['average']:.2f}"
        )
    lines.append("")
    lines.append(CLOSING_FLOURISH)
    return "\n".join(lines).strip()


def session_list_text(entries):
    """entries: list of (session_row, player_count), newest first."""
    if not entries:
        return f"{STAR} 暂无场次"
    lines = [f"{STAR} 最近场次 {STAR}", ""]
    for session, count in entries:
        title = session["name"] or f"Session #{session['id']}"
        status_label = "🟢 进行中" if session["status"] == "active" else "⚪ 已结束"
        lines.append(f"#{session['id']} {status_label} {title} — {count} 人")
    return "\n".join(lines)


def session_status_text(title, names):
    lines = [f"🫐 {title}　参与人数: {len(names)}"]
    if names:
        lines.append(" ".join(names))
    return "\n".join(lines)


def mini_status_text(names, capacity):
    lines = [f"🫐 Mini 名单　{len(names)}/{capacity}"]
    if names:
        lines.append(" ".join(names))
    return "\n".join(lines)


def vote_status_text(round_no, voted, total):
    return f"🫧 第 {round_no} 轮投票: {voted}/{total} 已投票"


def tie_text(candidate_names):
    return f"⚠️ 平票\n候选人: {' '.join(candidate_names)}"
