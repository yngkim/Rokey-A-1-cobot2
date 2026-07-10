"""SQLite persistence for in-progress chess games."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_graveyard_slots() -> list[str | None]:
    return [None] * 16


@dataclass
class GameRecord:
    id: str
    created_at: str
    updated_at: str
    is_active: bool
    fen: str
    human_color: str
    difficulty: str
    game_phase: str
    game_result: str
    winner: str
    eval_cp: int
    bot_status: str
    graveyard_slots: list[str | None] = field(default_factory=empty_graveyard_slots)
    human_graveyard_slots: list[str | None] = field(default_factory=empty_graveyard_slots)
    human_captures: list[str] = field(default_factory=list)
    robot_captures: list[str] = field(default_factory=list)
    move_history: list[dict[str, Any]] = field(default_factory=list)
    ply_counter: int = 0
    last_bot_move: str = ''
    bot_message: str = ''
    board_orientation: str = 'standard'

    def to_row(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'is_active': int(self.is_active),
            'fen': self.fen,
            'human_color': self.human_color,
            'difficulty': self.difficulty,
            'board_orientation': self.board_orientation,
            'game_phase': self.game_phase,
            'game_result': self.game_result,
            'winner': self.winner,
            'eval_cp': self.eval_cp,
            'bot_status': self.bot_status,
            'graveyard_slots_json': json.dumps(self.graveyard_slots),
            'human_graveyard_slots_json': json.dumps(self.human_graveyard_slots),
            'human_captures_json': json.dumps(self.human_captures),
            'robot_captures_json': json.dumps(self.robot_captures),
            'move_history_json': json.dumps(self.move_history),
            'ply_counter': self.ply_counter,
            'last_bot_move': self.last_bot_move,
            'bot_message': self.bot_message,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'GameRecord':
        return cls(
            id=row['id'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            is_active=bool(row['is_active']),
            fen=row['fen'],
            human_color=row['human_color'],
            difficulty=row['difficulty'],
            board_orientation=(
                row['board_orientation']
                if 'board_orientation' in row.keys()
                else 'standard'
            ),
            game_phase=row['game_phase'],
            game_result=row['game_result'] or '',
            winner=row['winner'] or '',
            eval_cp=int(row['eval_cp']),
            bot_status=row['bot_status'] or 'idle',
            graveyard_slots=_decode_slots(row['graveyard_slots_json']),
            human_graveyard_slots=_decode_slots(
                row['human_graveyard_slots_json']
                if 'human_graveyard_slots_json' in row.keys()
                else None
            ),
            human_captures=json.loads(row['human_captures_json'] or '[]'),
            robot_captures=json.loads(row['robot_captures_json'] or '[]'),
            move_history=json.loads(row['move_history_json'] or '[]'),
            ply_counter=int(row['ply_counter'] or 0),
            last_bot_move=row['last_bot_move'] or '',
            bot_message=row['bot_message'] or '',
        )


def _decode_slots(raw: str | None) -> list[str | None]:
    if not raw:
        return empty_graveyard_slots()
    values = json.loads(raw)
    slots = [value if value else None for value in values]
    if len(slots) < 16:
        slots.extend([None] * (16 - len(slots)))
    return slots[:16]


class GameStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS games (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    fen TEXT NOT NULL,
                    human_color TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    game_phase TEXT NOT NULL,
                    game_result TEXT NOT NULL DEFAULT '',
                    winner TEXT NOT NULL DEFAULT '',
                    eval_cp INTEGER NOT NULL DEFAULT 0,
                    bot_status TEXT NOT NULL DEFAULT 'idle',
                    graveyard_slots_json TEXT NOT NULL,
                    human_captures_json TEXT NOT NULL,
                    robot_captures_json TEXT NOT NULL,
                    move_history_json TEXT NOT NULL,
                    ply_counter INTEGER NOT NULL DEFAULT 0,
                    last_bot_move TEXT NOT NULL DEFAULT '',
                    bot_message TEXT NOT NULL DEFAULT ''
                )
                '''
            )
            cols = {row[1] for row in conn.execute('PRAGMA table_info(games)')}
            if 'human_graveyard_slots_json' not in cols:
                conn.execute(
                    "ALTER TABLE games ADD COLUMN human_graveyard_slots_json "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            if 'board_orientation' not in cols:
                conn.execute(
                    "ALTER TABLE games ADD COLUMN board_orientation "
                    "TEXT NOT NULL DEFAULT 'standard'"
                )
            conn.commit()

    def load_active_game(self) -> GameRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM games WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1'
            ).fetchone()
        if row is None:
            return None
        return GameRecord.from_row(row)

    def deactivate_all(self) -> None:
        with self._connect() as conn:
            conn.execute('UPDATE games SET is_active = 0')
            conn.commit()

    def save_game(self, record: GameRecord) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                'SELECT created_at FROM games WHERE id = ?',
                (record.id,),
            ).fetchone()
            if existing and not record.created_at:
                record.created_at = existing['created_at']
            elif not record.created_at:
                record.created_at = _utc_now()
        record.updated_at = _utc_now()
        row = record.to_row()
        columns = ', '.join(row.keys())
        placeholders = ', '.join(f':{key}' for key in row.keys())
        updates = ', '.join(f'{key}=excluded.{key}' for key in row.keys() if key != 'id')
        with self._connect() as conn:
            conn.execute(
                f'''
                INSERT INTO games ({columns}) VALUES ({placeholders})
                ON CONFLICT(id) DO UPDATE SET {updates}
                ''',
                row,
            )
            conn.commit()

    def create_new_game(
        self,
        *,
        fen: str = START_FEN,
        human_color: str = 'white',
        difficulty: str = 'medium',
        board_orientation: str = 'standard',
        game_phase: str = 'playing',
        bot_message: str = '',
    ) -> GameRecord:
        self.deactivate_all()
        now = _utc_now()
        record = GameRecord(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            is_active=True,
            fen=fen,
            human_color=human_color,
            difficulty=difficulty,
            board_orientation=board_orientation,
            game_phase=game_phase,
            game_result='',
            winner='',
            eval_cp=0,
            bot_status='idle',
            graveyard_slots=empty_graveyard_slots(),
            human_graveyard_slots=empty_graveyard_slots(),
            human_captures=[],
            robot_captures=[],
            move_history=[],
            ply_counter=0,
            last_bot_move='',
            bot_message=bot_message,
        )
        self.save_game(record)
        return record
