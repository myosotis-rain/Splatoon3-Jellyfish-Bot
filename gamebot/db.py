"""SQLite persistence layer.

Synchronous by design (sqlite3 is a blocking API); callers running inside
the Discord async event loop should wrap calls in asyncio.to_thread.
"""

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    discord_id TEXT PRIMARY KEY,
    username TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    name TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS session_players (
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    player_id TEXT NOT NULL REFERENCES players(discord_id),
    total_score INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (session_id, player_id)
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    game_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'team_assigned',
    winning_team TEXT,
    losing_team TEXT,
    eliminated_player TEXT,
    vote_candidates TEXT,
    current_round INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_players (
    game_id INTEGER NOT NULL REFERENCES games(id),
    player_id TEXT NOT NULL,
    team TEXT NOT NULL,
    identity TEXT NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    score INTEGER,
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS votes (
    game_id INTEGER NOT NULL REFERENCES games(id),
    round INTEGER NOT NULL,
    voter_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    PRIMARY KEY (game_id, round, voter_id)
);

-- Mini (3v3, unscored) mirrors the tables above one-for-one, minus the
-- scoring columns. Kept as a fully separate table set (rather than a mode
-- flag on the tables above) so ranked leaderboard math can never be
-- contaminated by unscored games. Scoring could be added to this table set
-- later without touching the ranked tables at all.

CREATE TABLE IF NOT EXISTS mini_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS mini_session_players (
    session_id INTEGER NOT NULL REFERENCES mini_sessions(id),
    player_id TEXT NOT NULL REFERENCES players(discord_id),
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (session_id, player_id)
);

CREATE TABLE IF NOT EXISTS mini_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES mini_sessions(id),
    game_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'assigned',
    winning_team TEXT,
    losing_team TEXT,
    eliminated_player TEXT,
    vote_candidates TEXT,
    current_round INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mini_game_players (
    game_id INTEGER NOT NULL REFERENCES mini_games(id),
    player_id TEXT NOT NULL,
    team TEXT NOT NULL,
    identity TEXT NOT NULL,
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS mini_votes (
    game_id INTEGER NOT NULL REFERENCES mini_games(id),
    round INTEGER NOT NULL,
    voter_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    PRIMARY KEY (game_id, round, voter_id)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def init_schema(self):
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        for table in ("games", "mini_games"):
            cols = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if "vote_message_id" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN vote_message_id TEXT")

    def close(self):
        self.conn.close()

    # -- players -----------------------------------------------------

    def upsert_player(self, discord_id, username):
        self.conn.execute(
            "INSERT INTO players (discord_id, username) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET username = excluded.username",
            (str(discord_id), username),
        )
        self.conn.commit()

    def ensure_player_seen(self, discord_id, default_username):
        """Like upsert_player, but only sets the name the first time this
        player is seen -- never clobbers a name set via /rename."""
        self.conn.execute(
            "INSERT INTO players (discord_id, username) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO NOTHING",
            (str(discord_id), default_username),
        )
        self.conn.commit()

    def get_username(self, discord_id):
        row = self.conn.execute(
            "SELECT username FROM players WHERE discord_id = ?", (str(discord_id),)
        ).fetchone()
        return row["username"] if row else None

    # -- sessions ------------------------------------------------------

    def get_active_session(self, server_id):
        return self.conn.execute(
            "SELECT * FROM sessions WHERE server_id = ? AND status = 'active' "
            "ORDER BY id DESC LIMIT 1",
            (str(server_id),),
        ).fetchone()

    def create_session(self, server_id, channel_id, name=None):
        self.conn.execute(
            "UPDATE sessions SET status = 'closed' WHERE server_id = ? AND status = 'active'",
            (str(server_id),),
        )
        cur = self.conn.execute(
            "INSERT INTO sessions (server_id, channel_id, name, created_at, status) "
            "VALUES (?, ?, ?, ?, 'active')",
            (str(server_id), str(channel_id), name, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_session(self, session_id):
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

    def get_sessions(self, server_id, limit=10):
        return self.conn.execute(
            "SELECT * FROM sessions WHERE server_id = ? ORDER BY id DESC LIMIT ?",
            (str(server_id), limit),
        ).fetchall()

    def close_session(self, server_id):
        self.conn.execute(
            "UPDATE sessions SET status = 'closed' WHERE server_id = ? AND status = 'active'",
            (str(server_id),),
        )
        self.conn.commit()

    def reopen_session(self, server_id, session_id):
        self.conn.execute(
            "UPDATE sessions SET status = 'closed' WHERE server_id = ? AND status = 'active'",
            (str(server_id),),
        )
        cur = self.conn.execute(
            "UPDATE sessions SET status = 'active' WHERE id = ? AND server_id = ?",
            (session_id, str(server_id)),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def join_session(self, session_id, player_id, username):
        self.ensure_player_seen(player_id, username)
        row = self.conn.execute(
            "SELECT 1 FROM session_players WHERE session_id = ? AND player_id = ?",
            (session_id, str(player_id)),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO session_players (session_id, player_id, active) "
                "VALUES (?, ?, 1)",
                (session_id, str(player_id)),
            )
        else:
            self.conn.execute(
                "UPDATE session_players SET active = 1 "
                "WHERE session_id = ? AND player_id = ?",
                (session_id, str(player_id)),
            )
        self.conn.commit()

    def leave_session(self, session_id, player_id):
        self.conn.execute(
            "UPDATE session_players SET active = 0 "
            "WHERE session_id = ? AND player_id = ?",
            (session_id, str(player_id)),
        )
        self.conn.commit()

    def is_active_in_session(self, session_id, player_id):
        row = self.conn.execute(
            "SELECT active FROM session_players WHERE session_id = ? AND player_id = ?",
            (session_id, str(player_id)),
        ).fetchone()
        return bool(row and row["active"])

    def get_session_players(self, session_id, active_only=True):
        query = "SELECT player_id FROM session_players WHERE session_id = ?"
        if active_only:
            query += " AND active = 1"
        rows = self.conn.execute(query, (session_id,)).fetchall()
        return [r["player_id"] for r in rows]

    def get_session_player_row(self, session_id, player_id):
        return self.conn.execute(
            "SELECT * FROM session_players WHERE session_id = ? AND player_id = ?",
            (session_id, str(player_id)),
        ).fetchone()

    def adjust_score(self, session_id, player_id, delta):
        self.conn.execute(
            "UPDATE session_players SET total_score = total_score + ? "
            "WHERE session_id = ? AND player_id = ?",
            (delta, session_id, str(player_id)),
        )
        self.conn.commit()

    def get_session_leaderboard(self, session_id):
        rows = self.conn.execute(
            """
            SELECT sp.player_id, p.username, sp.total_score, sp.games_played
            FROM session_players sp
            JOIN players p ON p.discord_id = sp.player_id
            WHERE sp.session_id = ? AND sp.games_played > 0
            """,
            (session_id,),
        ).fetchall()
        board = []
        for r in rows:
            avg = r["total_score"] / r["games_played"] if r["games_played"] else 0.0
            board.append({
                "player_id": r["player_id"],
                "username": r["username"],
                "total_score": r["total_score"],
                "games_played": r["games_played"],
                "average": avg,
            })
        board.sort(key=lambda x: (-x["average"], -x["total_score"]))
        return board

    # -- games -----------------------------------------------------------

    def get_next_game_number(self, session_id):
        row = self.conn.execute(
            "SELECT COALESCE(MAX(game_number), 0) AS n FROM games WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["n"] + 1

    def create_game(self, session_id):
        game_number = self.get_next_game_number(session_id)
        cur = self.conn.execute(
            "INSERT INTO games (session_id, game_number, status, created_at) "
            "VALUES (?, ?, 'team_assigned', ?)",
            (session_id, game_number, _now()),
        )
        self.conn.commit()
        return cur.lastrowid, game_number

    def get_game(self, game_id):
        return self.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()

    def get_latest_game(self, session_id):
        return self.conn.execute(
            "SELECT * FROM games WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()

    def set_game_status(self, game_id, status):
        self.conn.execute("UPDATE games SET status = ? WHERE id = ?", (status, game_id))
        self.conn.commit()

    def save_team_assignment(self, game_id, teams, identities):
        for team, player_ids in teams.items():
            for player_id in player_ids:
                self.conn.execute(
                    "INSERT INTO game_players (game_id, player_id, team, identity, confirmed) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        game_id,
                        str(player_id),
                        team,
                        identities[player_id],
                        0 if identities[player_id] in ("卧底", "呆呆鱿") else 1,
                    ),
                )
        self.conn.commit()

    def get_game_players(self, game_id):
        return self.conn.execute(
            "SELECT * FROM game_players WHERE game_id = ?", (game_id,)
        ).fetchall()

    def get_teams_and_identities(self, game_id):
        rows = self.get_game_players(game_id)
        teams = {}
        identities = {}
        for r in rows:
            teams.setdefault(r["team"], []).append(r["player_id"])
            identities[r["player_id"]] = r["identity"]
        return teams, identities

    def set_confirmed(self, game_id, player_id):
        self.conn.execute(
            "UPDATE game_players SET confirmed = 1 WHERE game_id = ? AND player_id = ?",
            (game_id, str(player_id)),
        )
        self.conn.commit()

    def is_confirmed(self, game_id, player_id):
        row = self.conn.execute(
            "SELECT confirmed FROM game_players WHERE game_id = ? AND player_id = ?",
            (game_id, str(player_id)),
        ).fetchone()
        return bool(row and row["confirmed"])

    def get_identity(self, game_id, player_id):
        row = self.conn.execute(
            "SELECT identity, team FROM game_players WHERE game_id = ? AND player_id = ?",
            (game_id, str(player_id)),
        ).fetchone()
        return (row["identity"], row["team"]) if row else (None, None)

    def set_game_result(self, game_id, losing_team, winning_team):
        self.conn.execute(
            "UPDATE games SET losing_team = ?, winning_team = ?, status = 'voting_round1' "
            "WHERE id = ?",
            (losing_team, winning_team, game_id),
        )
        self.conn.commit()

    # -- voting ------------------------------------------------------------

    def record_vote(self, game_id, round_no, voter_id, target_id):
        self.conn.execute(
            "INSERT INTO votes (game_id, round, voter_id, target_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(game_id, round, voter_id) DO UPDATE SET target_id = excluded.target_id",
            (game_id, round_no, str(voter_id), str(target_id)),
        )
        self.conn.commit()

    def get_votes(self, game_id, round_no):
        rows = self.conn.execute(
            "SELECT voter_id, target_id FROM votes WHERE game_id = ? AND round = ?",
            (game_id, round_no),
        ).fetchall()
        return {r["voter_id"]: r["target_id"] for r in rows}

    def set_vote_candidates(self, game_id, candidate_ids):
        self.conn.execute(
            "UPDATE games SET vote_candidates = ? WHERE id = ?",
            (",".join(str(c) for c in candidate_ids), game_id),
        )
        self.conn.commit()

    def get_vote_candidates(self, game_id):
        row = self.conn.execute(
            "SELECT vote_candidates FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        if not row or not row["vote_candidates"]:
            return []
        return row["vote_candidates"].split(",")

    def set_current_round(self, game_id, round_no):
        self.conn.execute(
            "UPDATE games SET current_round = ? WHERE id = ?", (round_no, game_id)
        )
        self.conn.commit()

    def get_current_round(self, game_id):
        row = self.conn.execute(
            "SELECT current_round FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        return row["current_round"] if row else 1

    def set_eliminated(self, game_id, player_id):
        self.conn.execute(
            "UPDATE games SET eliminated_player = ? WHERE id = ?",
            (player_id, game_id),
        )
        self.conn.commit()

    def set_vote_message_id(self, game_id, message_id):
        self.conn.execute(
            "UPDATE games SET vote_message_id = ? WHERE id = ?",
            (str(message_id), game_id),
        )
        self.conn.commit()

    def get_vote_message_id(self, game_id):
        row = self.conn.execute(
            "SELECT vote_message_id FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        return row["vote_message_id"] if row else None

    # -- scoring -------------------------------------------------------------

    def finalize_scores(self, session_id, game_id, scores):
        for player_id, score in scores.items():
            self.conn.execute(
                "UPDATE game_players SET score = ? WHERE game_id = ? AND player_id = ?",
                (score, game_id, str(player_id)),
            )
            self.conn.execute(
                "UPDATE session_players SET total_score = total_score + ?, "
                "games_played = games_played + 1 "
                "WHERE session_id = ? AND player_id = ?",
                (score, session_id, str(player_id)),
            )
        self.conn.execute(
            "UPDATE games SET status = 'completed' WHERE id = ?", (game_id,)
        )
        self.conn.commit()

    # -- mini sessions (3v3, unscored) ---------------------------------------

    def get_active_mini_session(self, server_id):
        return self.conn.execute(
            "SELECT * FROM mini_sessions WHERE server_id = ? AND status = 'active' "
            "ORDER BY id DESC LIMIT 1",
            (str(server_id),),
        ).fetchone()

    def create_mini_session(self, server_id, channel_id):
        self.conn.execute(
            "UPDATE mini_sessions SET status = 'closed' WHERE server_id = ? AND status = 'active'",
            (str(server_id),),
        )
        cur = self.conn.execute(
            "INSERT INTO mini_sessions (server_id, channel_id, created_at, status) "
            "VALUES (?, ?, ?, 'active')",
            (str(server_id), str(channel_id), _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_mini_session(self, session_id):
        return self.conn.execute(
            "SELECT * FROM mini_sessions WHERE id = ?", (session_id,)
        ).fetchone()

    def close_mini_session(self, server_id):
        self.conn.execute(
            "UPDATE mini_sessions SET status = 'closed' WHERE server_id = ? AND status = 'active'",
            (str(server_id),),
        )
        self.conn.commit()

    def join_mini_session(self, session_id, player_id, username):
        self.ensure_player_seen(player_id, username)
        row = self.conn.execute(
            "SELECT 1 FROM mini_session_players WHERE session_id = ? AND player_id = ?",
            (session_id, str(player_id)),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO mini_session_players (session_id, player_id, active) "
                "VALUES (?, ?, 1)",
                (session_id, str(player_id)),
            )
        else:
            self.conn.execute(
                "UPDATE mini_session_players SET active = 1 "
                "WHERE session_id = ? AND player_id = ?",
                (session_id, str(player_id)),
            )
        self.conn.commit()

    def leave_mini_session(self, session_id, player_id):
        self.conn.execute(
            "UPDATE mini_session_players SET active = 0 "
            "WHERE session_id = ? AND player_id = ?",
            (session_id, str(player_id)),
        )
        self.conn.commit()

    def get_mini_session_players(self, session_id, active_only=True):
        query = "SELECT player_id FROM mini_session_players WHERE session_id = ?"
        if active_only:
            query += " AND active = 1"
        rows = self.conn.execute(query, (session_id,)).fetchall()
        return [r["player_id"] for r in rows]

    # -- mini games ------------------------------------------------------

    def get_next_mini_game_number(self, session_id):
        row = self.conn.execute(
            "SELECT COALESCE(MAX(game_number), 0) AS n FROM mini_games WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["n"] + 1

    def create_mini_game(self, session_id):
        game_number = self.get_next_mini_game_number(session_id)
        cur = self.conn.execute(
            "INSERT INTO mini_games (session_id, game_number, status, created_at) "
            "VALUES (?, ?, 'assigned', ?)",
            (session_id, game_number, _now()),
        )
        self.conn.commit()
        return cur.lastrowid, game_number

    def get_mini_game(self, game_id):
        return self.conn.execute(
            "SELECT * FROM mini_games WHERE id = ?", (game_id,)
        ).fetchone()

    def get_latest_mini_game(self, session_id):
        return self.conn.execute(
            "SELECT * FROM mini_games WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()

    def set_mini_game_status(self, game_id, status):
        self.conn.execute("UPDATE mini_games SET status = ? WHERE id = ?", (status, game_id))
        self.conn.commit()

    def save_mini_team_assignment(self, game_id, teams, identities):
        for team, player_ids in teams.items():
            for player_id in player_ids:
                self.conn.execute(
                    "INSERT INTO mini_game_players (game_id, player_id, team, identity) "
                    "VALUES (?, ?, ?, ?)",
                    (game_id, str(player_id), team, identities[player_id]),
                )
        self.conn.commit()

    def get_mini_game_players(self, game_id):
        return self.conn.execute(
            "SELECT * FROM mini_game_players WHERE game_id = ?", (game_id,)
        ).fetchall()

    def get_mini_teams_and_identities(self, game_id):
        rows = self.get_mini_game_players(game_id)
        teams = {}
        identities = {}
        for r in rows:
            teams.setdefault(r["team"], []).append(r["player_id"])
            identities[r["player_id"]] = r["identity"]
        return teams, identities

    def set_mini_game_result(self, game_id, losing_team, winning_team):
        self.conn.execute(
            "UPDATE mini_games SET losing_team = ?, winning_team = ?, status = 'voting_round1' "
            "WHERE id = ?",
            (losing_team, winning_team, game_id),
        )
        self.conn.commit()

    # -- mini voting -----------------------------------------------------

    def record_mini_vote(self, game_id, round_no, voter_id, target_id):
        self.conn.execute(
            "INSERT INTO mini_votes (game_id, round, voter_id, target_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(game_id, round, voter_id) DO UPDATE SET target_id = excluded.target_id",
            (game_id, round_no, str(voter_id), str(target_id)),
        )
        self.conn.commit()

    def get_mini_votes(self, game_id, round_no):
        rows = self.conn.execute(
            "SELECT voter_id, target_id FROM mini_votes WHERE game_id = ? AND round = ?",
            (game_id, round_no),
        ).fetchall()
        return {r["voter_id"]: r["target_id"] for r in rows}

    def set_mini_vote_candidates(self, game_id, candidate_ids):
        self.conn.execute(
            "UPDATE mini_games SET vote_candidates = ? WHERE id = ?",
            (",".join(str(c) for c in candidate_ids), game_id),
        )
        self.conn.commit()

    def get_mini_vote_candidates(self, game_id):
        row = self.conn.execute(
            "SELECT vote_candidates FROM mini_games WHERE id = ?", (game_id,)
        ).fetchone()
        if not row or not row["vote_candidates"]:
            return []
        return row["vote_candidates"].split(",")

    def set_mini_current_round(self, game_id, round_no):
        self.conn.execute(
            "UPDATE mini_games SET current_round = ? WHERE id = ?", (round_no, game_id)
        )
        self.conn.commit()

    def get_mini_current_round(self, game_id):
        row = self.conn.execute(
            "SELECT current_round FROM mini_games WHERE id = ?", (game_id,)
        ).fetchone()
        return row["current_round"] if row else 1

    def set_mini_eliminated(self, game_id, player_id):
        self.conn.execute(
            "UPDATE mini_games SET eliminated_player = ? WHERE id = ?",
            (player_id, game_id),
        )
        self.conn.commit()

    def set_mini_vote_message_id(self, game_id, message_id):
        self.conn.execute(
            "UPDATE mini_games SET vote_message_id = ? WHERE id = ?",
            (str(message_id), game_id),
        )
        self.conn.commit()

    def get_mini_vote_message_id(self, game_id):
        row = self.conn.execute(
            "SELECT vote_message_id FROM mini_games WHERE id = ?", (game_id,)
        ).fetchone()
        return row["vote_message_id"] if row else None

    def complete_mini_game(self, game_id):
        self.conn.execute(
            "UPDATE mini_games SET status = 'completed' WHERE id = ?", (game_id,)
        )
        self.conn.commit()
