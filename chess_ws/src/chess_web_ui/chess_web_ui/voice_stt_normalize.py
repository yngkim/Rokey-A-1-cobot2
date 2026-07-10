"""Pre-normalize browser speech transcripts before chess parsing."""

from __future__ import annotations

import re

# Spoken ranks (STT often splits file and rank: "e 이" -> e2).
RANK_WORD_MAP: dict[str, str] = {
    '일': '1',
    '원': '1',
    '하나': '1',
    'one': '1',
    '투': '2',
    '둘': '2',
    'two': '2',
    '삼': '3',
    '쓰리': '3',
    '셋': '3',
    'three': '3',
    '사': '4',
    '포': '4',
    '넷': '4',
    'four': '4',
    '오': '5',
    '파이브': '5',
    '다섯': '5',
    'five': '5',
    '육': '6',
    '식스': '6',
    '여섯': '6',
    'six': '6',
    '칠': '7',
    '세븐': '7',
    '일곱': '7',
    'seven': '7',
    '팔': '8',
    '에이트': '8',
    '여덟': '8',
    'eight': '8',
}

# Spoken files (apply only when followed by rank digit or rank word).
FILE_WORD_MAP: dict[str, str] = {
    '에이': 'a',
    '알파': 'a',
    'ey': 'a',
    '비': 'b',
    '브라보': 'b',
    'bee': 'b',
    '씨': 'c',
    '시': 'c',
    'cee': 'c',
    '디': 'd',
    '델타': 'd',
    'dee': 'd',
    '이': 'e',
    '에프': 'f',
    'ef': 'f',
    '지': 'g',
    'gee': 'g',
    '에이치': 'h',
    '에치': 'h',
    'aitch': 'h',
}

_SPOKEN_SQUARE_PHRASES: tuple[tuple[str, str], ...] = (
    (r'\b에이\s*이\b', 'a2'),
    (r'\b에이\s*삼\b', 'a3'),
    (r'\b에이\s*사\b', 'a4'),
    (r'\b비\s*이\b', 'b2'),
    (r'\b씨\s*이\b', 'c2'),
    (r'\b씨\s*삼\b', 'c3'),
    (r'\b시\s*삼\b', 'c3'),
    (r'\b디\s*이\b', 'd2'),
    (r'\b디\s*삼\b', 'd3'),
    (r'\b이\s*이\b', 'e2'),
    (r'\b이\s*사\b', 'e4'),
    (r'\b에프\s*이\b', 'f2'),
    (r'\b에프\s*삼\b', 'f3'),
    (r'\b지\s*이\b', 'g2'),
    (r'\b에이치\s*이\b', 'h2'),
)

_COMPACT_FILE_DIGIT_RE = re.compile(
    r'\b(?:'
    + '|'.join(re.escape(word) for word in FILE_WORD_MAP)
    + r')(?=[1-8])',
    re.IGNORECASE,
)

_FILLER_RE = re.compile(
    r'(?:그리고|그냥|그|저|제|이거|이것|말야|말이야|봐|봐봐|좀|제발|'
    r'please|um|uh|음|어|아|야)\b',
    re.IGNORECASE,
)

_STEP_WORD_RE = re.compile(r'(?:한|하나|1)\s*칸|(?:두|둘|2)\s*칸|(?:세|3)\s*칸')


def _spoken_file_replacement(match: re.Match[str], file_ch: str) -> str:
    digit = match.group('digit')
    if digit:
        return f'{file_ch}{digit}'
    rank_word = (match.group('rank') or '').lower()
    return f'{file_ch}{RANK_WORD_MAP.get(rank_word, rank_word)}'


def preprocess_transcript(text: str) -> str:
    """Fix common Korean/English STT quirks before chess parsing."""
    lowered = (text or '').strip().lower()
    if not lowered:
        return ''

    lowered = lowered.replace('→', ' ').replace('->', ' ').replace('-', ' ')
    lowered = re.sub(r'[^\w\s가-힣]', ' ', lowered)
    lowered = _FILLER_RE.sub(' ', lowered)

    for pattern, square in _SPOKEN_SQUARE_PHRASES:
        lowered = re.sub(pattern, square, lowered, flags=re.IGNORECASE)

    def _compact_file(match: re.Match[str]) -> str:
        spoken = match.group(0).lower()
        for word, file_ch in FILE_WORD_MAP.items():
            if spoken.startswith(word):
                return f'{file_ch}{spoken[len(word):]}'
        return spoken

    lowered = _COMPACT_FILE_DIGIT_RE.sub(_compact_file, lowered)

    for spoken, digit in sorted(RANK_WORD_MAP.items(), key=lambda item: -len(item[0])):
        lowered = re.sub(
            rf'([a-h])\s*{re.escape(spoken)}\b',
            lambda match, rank_digit=digit: f'{match.group(1)}{rank_digit}',
            lowered,
            flags=re.IGNORECASE,
        )

    rank_alt = '|'.join(re.escape(word) for word in sorted(RANK_WORD_MAP, key=len, reverse=True))
    for spoken, file_ch in sorted(FILE_WORD_MAP.items(), key=lambda item: -len(item[0])):
        pattern = rf'\b{re.escape(spoken)}\s*(?:(?P<rank>{rank_alt})|(?P<digit>[1-8]))'
        lowered = re.sub(
            pattern,
            lambda match, ch=file_ch: _spoken_file_replacement(match, ch),
            lowered,
            flags=re.IGNORECASE,
        )

    lowered = re.sub(r'([a-h])([1-8])(?=([a-h])[1-8])', r'\1\2 ', lowered)

    # Spoken UCI-ish before per-square compaction merges tokens.
    lowered = re.sub(r'\be\s+2\s+e\s+4\b', 'e2e4', lowered)
    lowered = re.sub(r'\ba\s+2\s+a\s+3\b', 'a2a3', lowered)

    lowered = re.sub(r'([a-h])\s+([1-8])\b', r'\1\2', lowered)
    lowered = re.sub(r'\be2\s+e4\b', 'e2e4', lowered)
    lowered = re.sub(r'\ba2\s+a3\b', 'a2a3', lowered)

    lowered = _STEP_WORD_RE.sub(lambda match: match.group(0).replace(' ', ''), lowered)
    lowered = re.sub(r'([a-h][1-8])(?=[a-h][1-8])', r'\1 ', lowered)
    lowered = re.sub(r'\s+', ' ', lowered).strip()
    return lowered
