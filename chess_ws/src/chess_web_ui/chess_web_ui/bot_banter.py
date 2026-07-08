"""Rule-based bot banter for battle mode (chess.com-style trash talk)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

Difficulty = Literal['easy', 'medium', 'hard']
BanterKind = Literal['greeting', 'game_over', 'check', 'capture', 'move']


@dataclass(frozen=True)
class BanterLine:
    text: str
    kind: BanterKind


BOT_PROFILES: dict[Difficulty, dict[str, str]] = {
    'easy': {
        'name': '초보 봇 철수',
        'avatar': 'easy',
        'difficulty_label': '하',
        'greeting': '안녕! 같이 천천히 두자. 실수해도 괜찮아!',
    },
    'medium': {
        'name': '아마추어 봇 민수',
        'avatar': 'medium',
        'difficulty_label': '중',
        'greeting': '준비됐어? 이번엔 진지하게 간다.',
    },
    'hard': {
        'name': '마스터 봇 이서',
        'avatar': 'hard',
        'difficulty_label': '상',
        'greeting': '…시작하지.',
    },
}

_PLAYER_RESPONSES: dict[Difficulty, dict[str, list[str]]] = {
    'easy': {
        'brilliant': ['와, 좋은 수다!', '오, 생각보다 잘 두네?'],
        'good': ['괜찮은 수야.', '음, 나쁘지 않네.'],
        'inaccuracy': ['음… 그것도 있긴 하지.', '조금 아쉬운 수인데?'],
        'mistake': ['실수한 것 같은데? 괜찮아!', '이건 내게 기회네!'],
        'blunder': ['고마워! 그 수 덕분에 유리해졌어.', '하하, 그 수는 좀…'],
        'capture': ['내 기물을?!', '앗, 잡혔다…'],
        'check': ['장군이라니!', '조심해야겠다.'],
    },
    'medium': {
        'brilliant': ['흠, 날카로운 수군.', '예상 밖이야.'],
        'good': ['무난한 수네.', '알겠어, 계속 가보자.'],
        'inaccuracy': ['그 수는 약간 아쉽지 않아?', '더 좋은 수가 있었을 텐데.'],
        'mistake': ['실수 포착!', '이제 내 차례야.'],
        'blunder': ['큰 실수다. 고맙다.', '이건 선물이네.'],
        'capture': ['내 말을 잡다니.', '치명적이지는 않지만 아프군.'],
        'check': ['장군? 받아줄게.', '체크라…'],
    },
    'hard': {
        'brilliant': ['…인정하지.', '강한 수다.'],
        'good': ['예상 범위.', '계속해.'],
        'inaccuracy': ['허술하군.', '그게 최선이었나?'],
        'mistake': ['실수다.', '기회를 줬군.'],
        'blunder': ['끝났다.', '치명적이야.'],
        'capture': ['값을 치르게 될 거다.', '포획? 대가를 치러.'],
        'check': ['장군 따위로는…', '체크.'],
    },
}

_BOT_MOVE_LINES: dict[Difficulty, list[str]] = {
    'easy': ['내 차례!', '이렇게 둘게.', '어때?'],
    'medium': ['응수한다.', '이 수는 어떠니?', '받아라.'],
    'hard': ['…', '이 수다.', '끝내겠다.'],
}


def get_bot_profile(difficulty: Difficulty) -> dict[str, str]:
    return dict(BOT_PROFILES[difficulty])


def greeting(difficulty: Difficulty) -> BanterLine:
    return BanterLine(BOT_PROFILES[difficulty]['greeting'], 'greeting')


def react_to_player_move(
    difficulty: Difficulty,
    *,
    quality: str,
    is_capture: bool,
    is_check: bool,
    san: str,
) -> BanterLine:
    del san
    pool_key = quality if quality in ('brilliant', 'good', 'inaccuracy', 'mistake', 'blunder') else 'good'
    kind: BanterKind = 'move'
    if is_check:
        pool_key = 'check'
        kind = 'check'
    elif is_capture and quality in ('mistake', 'blunder', 'inaccuracy'):
        pool_key = 'capture'
        kind = 'capture'
    lines = _PLAYER_RESPONSES[difficulty].get(pool_key, _PLAYER_RESPONSES[difficulty]['good'])
    return BanterLine(random.choice(lines), kind)


def react_to_game_over(
    difficulty: Difficulty,
    *,
    result: str,
    winner: str,
) -> BanterLine:
    del difficulty
    if result == 'checkmate':
        if winner == 'human':
            return BanterLine('체크메이트! 이번 판은 당신 승리입니다.', 'game_over')
        if winner == 'robot':
            return BanterLine('체크메이트. 이번 판은 내 승리다.', 'game_over')
    if result == 'stalemate':
        return BanterLine('스테일메이트. 무승부입니다.', 'game_over')
    if result == 'resign':
        return BanterLine('기권하셨군요. 이번 판은 제 승리입니다.', 'game_over')
    return BanterLine('무승부로 게임이 끝났습니다.', 'game_over')


def react_to_bot_move(difficulty: Difficulty, *, is_capture: bool, is_check: bool) -> BanterLine:
    base = random.choice(_BOT_MOVE_LINES[difficulty])
    if is_check and difficulty != 'hard':
        return BanterLine(f'{base} 장군!', 'check')
    if is_capture and difficulty == 'easy':
        return BanterLine(f'{base} 잡았다!', 'capture')
    kind: BanterKind = 'check' if is_check else ('capture' if is_capture else 'move')
    return BanterLine(base, kind)
