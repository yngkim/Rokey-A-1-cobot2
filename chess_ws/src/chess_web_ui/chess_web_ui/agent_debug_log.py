"""NDJSON debug trace for agent debug sessions (folded in call sites)."""

from __future__ import annotations

import json
import time
from typing import Any

_LOG_PATH = '/home/rokey/Rokey-A-1-cobot2/.cursor/debug-df2946.log'
_SESSION_ID = 'df2946'


def agent_log(
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    *,
    hypothesis_id: str = '',
    run_id: str = '',
) -> None:
    # #region agent log
    payload = {
        'sessionId': _SESSION_ID,
        'timestamp': int(time.time() * 1000),
        'location': location,
        'message': message,
        'data': data or {},
        'hypothesisId': hypothesis_id,
        'runId': run_id,
    }
    try:
        with open(_LOG_PATH, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except OSError:
        import sys
        print(f'[agent_debug] {json.dumps(payload, ensure_ascii=False)}', file=sys.stderr, flush=True)
    # #endregion
