"""Rule-based bot banter for battle mode (chess.com-style trash talk)."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Literal

Difficulty = Literal['beginner', 'easy', 'medium', 'hard', 'master']
BanterKind = Literal[
    'greeting',
    'game_over',
    'check',
    'capture',
    'move',
    'illegal_move',
    'voice_move',
]

_RECENT_LINES: deque[str] = deque(maxlen=3)


@dataclass(frozen=True)
class BanterLine:
    text: str
    kind: BanterKind


def _pick_line(lines: list[str]) -> str:
    fresh = [line for line in lines if line not in _RECENT_LINES]
    pool = fresh or lines
    choice = random.choice(pool)
    _RECENT_LINES.append(choice)
    return choice


BOT_PROFILES: dict[Difficulty, dict[str, str]] = {
    'beginner': {
        'name': '연습 봇 지우',
        'avatar': 'beginner',
        'difficulty_label': '입문',
        'greeting': '안녕! 천천히 같이 연습해보자.',
    },
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
        'name': '고수 봇 하린',
        'avatar': 'hard',
        'difficulty_label': '상',
        'greeting': '실력 확인하러 왔어. 각오해.',
    },
    'master': {
        'name': '마스터 봇 이서',
        'avatar': 'master',
        'difficulty_label': '최상',
        'greeting': '…시작하지.',
    },
}

_PLAYER_RESPONSES: dict[Difficulty, dict[str, list[str]]] = {
    'beginner': {
        'brilliant': ['와, 정말 좋은 수다!', '오, 대단한데?', '이건 생각 못 했어!'],
        'good': ['괜찮은 수야.', '나쁘지 않네.', '음, 그럭저럭이야.'],
        'inaccuracy': ['조금 아쉬운 수인데?', '다른 수도 있었을 것 같아.', '음… 그것도 괜찮긴 해.'],
        'mistake': ['실수한 것 같아. 괜찮아!', '이건 내 기회인가?', '아, 그 수는 좀 아쉽다.'],
        'blunder': ['고마워! 유리해졌어.', '하하, 그 수 덕분이야.', '이건 선물이네!'],
        'capture': ['내 기물이?!', '앗, 잡혔다…', '아이고, 그건 아쉽다.'],
        'check': ['체크라니!', '조심해야겠다.', '체크네, 받아볼게.'],
    },
    'easy': {
        'brilliant': ['와, 좋은 수다!', '오, 생각보다 잘 두네?', '이건 예상 못 했어.'],
        'good': ['괜찮은 수야.', '음, 나쁘지 않네.', '그럭저럭이야.'],
        'inaccuracy': ['음… 그것도 있긴 하지.', '조금 아쉬운 수인데?', '더 좋은 수가 있었을 텐데.'],
        'mistake': ['실수한 것 같은데? 괜찮아!', '이건 내게 기회네!', '아, 그 수는 좀 아쉽다.'],
        'blunder': ['고마워! 그 수 덕분에 유리해졌어.', '하하, 그 수는 좀…', '이건 선물이네!'],
        'capture': ['내 기물을?!', '앗, 잡혔다…', '그건 좀 아프군.'],
        'check': ['체크라니!', '조심해야겠다.', '체크네.'],
    },
    'medium': {
        'brilliant': ['흠, 날카로운 수군.', '예상 밖이야.', '꽤 강한 수다.'],
        'good': ['무난한 수네.', '알겠어, 계속 가보자.', '그 정도면 됐어.'],
        'inaccuracy': ['그 수는 약간 아쉽지 않아?', '더 좋은 수가 있었을 텐데.', '허술한 면이 보이는군.'],
        'mistake': ['실수 포착!', '이제 내 차례야.', '그건 실수였어.'],
        'blunder': ['큰 실수다. 고맙다.', '이건 선물이네.', '치명적인 수였어.'],
        'capture': ['내 말을 잡다니.', '치명적이지는 않지만 아프군.', '포획? 받아줄게.'],
        'check': ['체크? 받아줄게.', '체크라…', '체크네, 어떻게 막을까.'],
    },
    'hard': {
        'brilliant': ['…인정하지.', '강한 수다.', '예리하군.'],
        'good': ['예상 범위.', '계속해.', '무난하군.'],
        'inaccuracy': ['허술하군.', '그게 최선이었나?', '약점이 보여.'],
        'mistake': ['실수다.', '기회를 줬군.', '그건 아쉬운 수야.'],
        'blunder': ['끝났다.', '치명적이야.', '큰 실수다.'],
        'capture': ['값을 치르게 될 거다.', '포획? 대가를 치러.', '잡았군.'],
        'check': ['체크 따위로는…', '체크.', '체크? 흥.'],
    },
    'master': {
        'brilliant': ['…훌륭하다.', '인정한다.', '강하군.'],
        'good': ['알겠다.', '계속해.', '…'],
        'inaccuracy': ['미세한 실수다.', '그게 최선인가.', '아쉽군.'],
        'mistake': ['실수다.', '틈을 보였군.', '기회다.'],
        'blunder': ['치명적이다.', '끝이다.', '결정적 실수군.'],
        'capture': ['대가를 치를 것이다.', '포획.', '잡았다.'],
        'check': ['체크.', '…체크.', '체크인가.'],
    },
}

_BOT_MOVE_LINES: dict[Difficulty, list[str]] = {
    'beginner': ['내 차례!', '이렇게 둘게.', '어때?', '한 수 둘게.', '이건 어떨까?'],
    'easy': ['내 차례!', '이렇게 둘게.', '어때?', '이 수는 어떠니?', '한번 봐봐.'],
    'medium': ['응수한다.', '이 수는 어떠니?', '받아라.', '이렇게 간다.', '맞받아볼게.'],
    'hard': ['이 수다.', '받아.', '계속 간다.', '응수.', '다음 수다.'],
    'master': ['…', '이 수다.', '끝내겠다.', '…', '다음.'],
}

_GAME_OVER_LINES: dict[Difficulty, dict[str, list[str]]] = {
    'beginner': {
        'human_win': ['체크메이트! 이번 판은 당신 승리예요.', '와, 이겼다! 잘했어!'],
        'robot_win': ['체크메이트. 이번 판은 내 승리야.', '이번엔 내가 이겼어. 다음엔 더 잘해보자!'],
        'draw': ['무승부네. 재밌었어!', '비겼다. 다음에 또 하자!'],
        'resign': ['기권하셨군요. 이번 판은 제 승리입니다.', '기권! 다음엔 더 힘내요.'],
    },
    'easy': {
        'human_win': ['체크메이트! 이번 판은 당신 승리입니다.', '이번엔 네가 이겼어!'],
        'robot_win': ['체크메이트. 이번 판은 내 승리다.', '이번 판은 내가 가져갈게.'],
        'draw': ['무승부로 게임이 끝났습니다.', '비겼네. 다음에 또 하자!'],
        'resign': ['기권하셨군요. 이번 판은 제 승리입니다.', '기권! 아쉽지만 다음 기회에.'],
    },
    'medium': {
        'human_win': ['체크메이트. 이번 판은 당신 승리.', '승리를 축하해.'],
        'robot_win': ['체크메이트. 이번 판은 내 승리다.', '이번 판은 내 것이다.'],
        'draw': ['스테일메이트. 무승부.', '무승부로 끝났다.'],
        'resign': ['기권. 이번 판은 내 승리다.', '기권하셨군. 승리는 내 것.'],
    },
    'hard': {
        'human_win': ['체크메이트. 이번엔 네 승리다.', '…이번 판은 네가 이겼다.'],
        'robot_win': ['체크메이트. 내 승리다.', '끝났다.'],
        'draw': ['무승부.', '비겼군.'],
        'resign': ['기권. 승리는 내 것.', '기권했군.'],
    },
    'master': {
        'human_win': ['체크메이트. …이번 판은 네 승리다.', '인정한다.'],
        'robot_win': ['체크메이트. 내 승리다.', '…끝.'],
        'draw': ['무승부.', '…비겼다.'],
        'resign': ['기권. 승리는 내 것.', '…기권.'],
    },
}

_ILLEGAL_MOVE_LINES: dict[Difficulty, list[str]] = {
    'beginner': [
        '그 수는 규칙에 어긋나요. 보드 수정이나 되돌리기를 선택하세요.',
        '불법 수예요. 다시 두거나 보드를 고쳐주세요.',
    ],
    'easy': [
        '그 수는 규칙에 어긋나요. 보드 수정 또는 자동 되돌리기를 선택하세요.',
        '불법 수야. 다시 두거나 보드를 수정해줘.',
    ],
    'medium': [
        '불법 수다. 보드 수정 또는 되돌리기를 선택해.',
        '그 수는 안 돼. 보드를 확인해봐.',
    ],
    'hard': [
        '불법 수다.',
        '그 수는 규칙 위반이다.',
    ],
    'master': [
        '불법 수.',
        '…규칙 위반.',
    ],
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
    return BanterLine(_pick_line(lines), kind)


def react_to_game_over(
    difficulty: Difficulty,
    *,
    result: str,
    winner: str,
) -> BanterLine:
    pools = _GAME_OVER_LINES[difficulty]
    if result == 'checkmate':
        key = 'human_win' if winner == 'human' else 'robot_win'
        return BanterLine(_pick_line(pools[key]), 'game_over')
    if result == 'stalemate':
        return BanterLine(_pick_line(pools['draw']), 'game_over')
    if result == 'resign':
        return BanterLine(_pick_line(pools['resign']), 'game_over')
    return BanterLine(_pick_line(pools['draw']), 'game_over')


def react_to_illegal_move(
    difficulty: Difficulty,
    *,
    from_sq: str,
    to_sq: str,
) -> BanterLine:
    del from_sq, to_sq
    return BanterLine(_pick_line(_ILLEGAL_MOVE_LINES[difficulty]), 'illegal_move')


def react_to_illegal_move_reverted(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': ['수를 되돌렸어요. 다시 두세요.', '원래대로 돌렸어요. 다시 해보세요.'],
        'easy': ['수를 되돌렸습니다. 다시 두세요.', '원위치로 돌렸어. 다시 해봐.'],
        'medium': ['수를 되돌렸다. 다시 두세요.', '되돌렸어. 다시.'],
        'hard': ['되돌렸다. 다시.', '원위치.'],
        'master': ['…되돌렸다.', '다시.'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'illegal_move')


def react_to_voice_parse_error(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': [
            '명령을 이해하지 못했어요. a2 a3처럼 출발 칸과 도착 칸을 말해주세요.',
            '잘 못 들었어요. 출발 칸과 도착 칸을 말해주세요.',
        ],
        'easy': [
            '명령을 이해하지 못했습니다. a2 a3처럼 출발 칸과 도착 칸을 말해주세요.',
            '다시 말해줘. a2 a3 형식으로.',
        ],
        'medium': [
            '이해 못 했어. a2 a3처럼 말해줘.',
            '다시 말해봐. 출발 칸과 도착 칸.',
        ],
        'hard': ['이해 못 했다.', '다시.'],
        'master': ['…', '다시 말해.'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_illegal(difficulty: Difficulty, *, from_sq: str, to_sq: str) -> BanterLine:
    lines = {
        'beginner': [f'불법 수예요. {from_sq}에서 {to_sq}로 둘 수 없어요.'],
        'easy': [f'불법 수입니다. {from_sq}에서 {to_sq}로 둘 수 없습니다.'],
        'medium': [f'불법 수. {from_sq}에서 {to_sq}로 안 돼.'],
        'hard': [f'불법. {from_sq}-{to_sq}.'],
        'master': [f'…불법. {from_sq}-{to_sq}.'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_success(difficulty: Difficulty, *, from_sq: str, to_sq: str) -> BanterLine:
    lines = {
        'beginner': [f'{from_sq}에서 {to_sq}로 옮겼어요.', f'알겠어요, {from_sq}에서 {to_sq}로.'],
        'easy': [f'{from_sq}에서 {to_sq}로 옮겼습니다.', f'좋아, {from_sq}에서 {to_sq}로.'],
        'medium': [f'{from_sq}에서 {to_sq}로.', f'알겠어, {from_sq}-{to_sq}.'],
        'hard': [f'{from_sq}-{to_sq}.', f'{from_sq}에서 {to_sq}.'],
        'master': [f'…{from_sq}-{to_sq}.', f'{from_sq}-{to_sq}.'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_empty(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': ['음성이 인식되지 않았어요. 다시 말해주세요.', '잘 못 들었어요. 다시요.'],
        'easy': ['음성이 인식되지 않았습니다. 다시 말해주세요.', '못 들었어. 다시.'],
        'medium': ['인식 실패. 다시.', '못 들었어.'],
        'hard': ['…인식 실패.', '다시.'],
        'master': ['…', '다시.'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_promotion_required(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': [
            '승격이 필요해요. 퀸, 룩, 비숍, 나이트 중 하나를 말해주세요.',
            '어떤 기물로 승격할지 말해주세요.',
        ],
        'easy': [
            '승격이 필요합니다. 퀸, 룩, 비숍, 나이트 중 하나를 말해주세요.',
            '승격 기물을 말해줘.',
        ],
        'medium': [
            '승격 필요. 퀸, 룩, 비숍, 나이트 중 하나.',
            '승격 기물을 말해.',
        ],
        'hard': ['승격.', '기물을 말해.'],
        'master': ['…승격.', '기물.'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_ambiguous(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': [
            '어느 수인지 잘 모르겠어요. 출발 칸과 기물을 다시 말해주세요.',
            '여러 수가 가능해요. 더 구체적으로 말해주세요.',
        ],
        'easy': [
            '어느 수인지 다시 말해주세요.',
            '여러 수가 가능합니다. 출발 칸을 포함해 말해주세요.',
        ],
        'medium': [
            '애매해. 어느 수인지 다시 말해.',
            '여러 수 가능. 더 구체적으로.',
        ],
        'hard': ['애매하다. 다시.', '여러 수.'],
        'master': ['…애매.', '다시.'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_confirm_success(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': ['확인했어요. 다음 차례를 기다릴게요.', '수 확인했어요.'],
        'easy': ['확인했습니다.', '수를 확인했습니다.'],
        'medium': ['확인.', '알겠어.'],
        'hard': ['확인.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_confirm_fail(difficulty: Difficulty, *, message: str = '') -> BanterLine:
    lines = {
        'beginner': [
            message or '수 확인에 실패했어요. 보드를 다시 확인해주세요.',
            '아직 확인할 수가 없어요.',
        ],
        'easy': [message or '수 확인에 실패했습니다.', '확인할 수가 없습니다.'],
        'medium': [message or '확인 실패.', '확인 불가.'],
        'hard': [message or '실패.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_undo_success(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': ['한 턴 되돌렸어요.', '이전 수로 돌아갔어요.'],
        'easy': ['한 턴 되돌렸습니다.', '이전 수로 되돌렸습니다.'],
        'medium': ['되돌렸어.', '한 턴 전으로.'],
        'hard': ['되돌림.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_undo_fail(difficulty: Difficulty, *, message: str = '') -> BanterLine:
    lines = {
        'beginner': [message or '되돌릴 수가 없어요.', '지금은 되돌릴 수 없어요.'],
        'easy': [message or '되돌릴 수 없습니다.', '되돌리기 불가입니다.'],
        'medium': [message or '되돌리기 불가.', '안 돼.'],
        'hard': [message or '불가.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_restore_success(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': ['보드를 정리할게요.', '보드 복구를 시작했어요.'],
        'easy': ['보드 복구를 시작했습니다.', '보드를 정리합니다.'],
        'medium': ['보드 복구.', '정리 시작.'],
        'hard': ['복구.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_restore_fail(difficulty: Difficulty, *, message: str = '') -> BanterLine:
    lines = {
        'beginner': [message or '보드 복구에 실패했어요.', '지금은 복구할 수 없어요.'],
        'easy': [message or '보드 복구에 실패했습니다.', '복구 불가입니다.'],
        'medium': [message or '복구 실패.', '안 돼.'],
        'hard': [message or '실패.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_resign_success(difficulty: Difficulty) -> BanterLine:
    lines = {
        'beginner': ['기권했어요. 수고하셨어요.', '게임을 포기했어요.'],
        'easy': ['기권했습니다.', '게임을 포기했습니다.'],
        'medium': ['기권.', '포기.'],
        'hard': ['기권.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_voice_resign_fail(difficulty: Difficulty, *, message: str = '') -> BanterLine:
    lines = {
        'beginner': [message or '기권할 수 없어요.', '지금은 기권할 수 없어요.'],
        'easy': [message or '기권할 수 없습니다.', '기권 불가입니다.'],
        'medium': [message or '기권 불가.', '안 돼.'],
        'hard': [message or '불가.'],
        'master': ['…'],
    }
    return BanterLine(_pick_line(lines[difficulty]), 'voice_move')


def react_to_bot_move(difficulty: Difficulty, *, is_capture: bool, is_check: bool) -> BanterLine:
    base = _pick_line(_BOT_MOVE_LINES[difficulty])
    if is_check and difficulty not in {'hard', 'master'}:
        return BanterLine(f'{base} 체크!', 'check')
    if is_check:
        return BanterLine(f'{base} 체크.', 'check')
    if is_capture and difficulty in {'beginner', 'easy'}:
        return BanterLine(f'{base} 잡았다!', 'capture')
    kind: BanterKind = 'check' if is_check else ('capture' if is_capture else 'move')
    return BanterLine(base, kind)
