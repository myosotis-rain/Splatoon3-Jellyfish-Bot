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


def team_announcement_text(game_number, teams, label="Game"):
    lines = [f"{STAR} {label} #{game_number} {STAR}\n"]
    for team, player_ids in teams.items():
        emoji = TEAM_EMOJI.get(team, team)
        lines.append(f"{emoji} {team}")
        for player_id in player_ids:
            lines.append(mention(player_id))
        lines.append("")
    lines.append(CLOSING_FLOURISH)
    return "\n".join(lines).strip()


def identity_card_text(team, identity):
    emoji = TEAM_EMOJI.get(team, team)
    return (
        f"{CARD_TOP}\n"
        f"　　{STAR} 身份卡 {STAR}\n"
        f"{CARD_BOTTOM}\n\n"
        f"队伍　{STAR}　{emoji} {team}\n"
        f"身份　{STAR}　{identity}\n\n"
        f"{SECTION_RULE} 任务 {SECTION_RULE}\n"
        f"{IDENTITY_TASKS[identity]}\n\n"
        f"{SECTION_RULE} 计分规则 {SECTION_RULE}\n"
        f"{IDENTITY_SCORING[identity]}\n\n"
        f"{CLOSING_FLOURISH}"
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
        f"{CARD_BOTTOM}\n\n"
        f"队伍　{STAR}　{emoji} {team}\n"
        f"身份　{STAR}　{identity}\n\n"
        f"{SECTION_RULE} 任务 {SECTION_RULE}\n"
        f"{MINI_IDENTITY_TASKS[identity]}\n\n"
        f"{CLOSING_FLOURISH}"
    )


def confirmation_status_text(confirmed, needed):
    ready = confirmed >= needed
    lines = [
        f"🎴 {STAR} 特殊身份确认状态\n",
        f"已确认: {confirmed}/{needed}",
    ]
    if ready:
        lines.append(f"\n{JELLY} 全部特殊身份已确认，游戏可以开始。")
    return "\n".join(lines)


def reveal_text(teams, identities):
    lines = [f"🎭 {STAR} 身份揭晓 {STAR}\n"]
    for team, player_ids in teams.items():
        emoji = TEAM_EMOJI.get(team, team)
        lines.append(f"{emoji} {team}:")
        for player_id in player_ids:
            lines.append(f"{mention(player_id)}: {identities[player_id]}")
        lines.append("")
    lines.append(CLOSING_FLOURISH)
    return "\n".join(lines).strip()


RANK_GLYPHS = {1: "✦", 2: "❀", 3: "⋆"}


def leaderboard_text(board):
    if not board:
        return "🏆 本次活动积分\n\n暂无数据"
    lines = [f"🏆 {STAR} 本次活动积分 {STAR}\n"]
    for i, entry in enumerate(board, start=1):
        glyph = RANK_GLYPHS.get(i, "·")
        lines.append(
            f"{glyph} 第 {i} 名 · {entry['username']}\n"
            f"游戏数: {entry['games_played']}　"
            f"总分: {entry['total_score']}　"
            f"平均: {entry['average']:.2f}\n"
        )
    lines.append(CLOSING_FLOURISH)
    return "\n".join(lines).strip()


def session_list_text(entries):
    """entries: list of (session_row, player_count), newest first."""
    if not entries:
        return "📚 场次列表\n\n暂无场次"
    lines = [f"📚 {STAR} 最近场次 {STAR}\n"]
    for session, count in entries:
        title = session["name"] or f"Session #{session['id']}"
        status_label = "🟢 进行中" if session["status"] == "active" else "⚪ 已结束"
        lines.append(f"#{session['id']} {status_label} {title} — {count} 人")
    return "\n".join(lines)


def session_status_text(title, player_ids):
    lines = [f"📋 {STAR} {title} {STAR}\n", f"参与人数: {len(player_ids)}"]
    if player_ids:
        lines.append("")
        lines.extend(mention(p) for p in player_ids)
    return "\n".join(lines)


def mini_status_text(player_ids, capacity):
    lines = [f"📋 {STAR} Mini 名单 {STAR}\n", f"人数: {len(player_ids)}/{capacity}"]
    if player_ids:
        lines.append("")
        lines.extend(mention(p) for p in player_ids)
    return "\n".join(lines)


def vote_status_text(round_no, voted, total):
    return f"🗳️ 第 {round_no} 轮投票: {voted}/{total} 已投票"


def tie_text(candidates):
    lines = ["⚠️ 平票\n", "候选人:"]
    lines.extend(mention(c) for c in candidates)
    return "\n".join(lines)
