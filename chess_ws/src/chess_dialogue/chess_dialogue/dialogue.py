"""Simple dialogue helper stub for future LLM integration."""

from __future__ import annotations


class DialogueService:
    def respond(self, user_text: str, fen: str | None = None) -> str:
        if fen:
            return f'현재 포지션을 기준으로 답변합니다: {user_text}'
        return f'체스에 대해 도와드릴게요: {user_text}'
