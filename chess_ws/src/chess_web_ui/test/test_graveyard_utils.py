"""Tests for graveyard fill order and placement helpers."""

from chess_web_ui.graveyard_utils import (
    BLACK_GRAVEYARD_FILL_ORDER,
    WHITE_GRAVEYARD_FILL_ORDER,
    graveyard_slot_index,
    place_in_graveyard,
)


def _slot_names(side: str) -> list[str]:
    from chess_web_ui.graveyard_utils import graveyard_fill_order

    order = graveyard_fill_order(side)
    if side == 'white':
        return [
            f'{chr(ord("a") + col)}{0 if row == 0 else -1}'
            for col, row in order
        ]
    return [f'{chr(ord("a") + col)}{9 + row}' for col, row in order]


def test_black_fill_order_row2_same_direction():
    names = _slot_names('black')
    assert names[:8] == ['h9', 'g9', 'f9', 'e9', 'd9', 'c9', 'b9', 'a9']
    assert names[8:] == ['h10', 'g10', 'f10', 'e10', 'd10', 'c10', 'b10', 'a10']


def test_white_fill_order_row2_same_direction():
    names = _slot_names('white')
    assert names[:8] == ['a0', 'b0', 'c0', 'd0', 'e0', 'f0', 'g0', 'h0']
    assert names[8:] == ['a-1', 'b-1', 'c-1', 'd-1', 'e-1', 'f-1', 'g-1', 'h-1']


def test_place_in_graveyard_black_ninth_slot_is_h10():
    slots = [None] * 16
    for _ in range(8):
        slots = place_in_graveyard(slots, 'black', 'p')
    slots = place_in_graveyard(slots, 'black', 'r')
    col, row = BLACK_GRAVEYARD_FILL_ORDER[8]
    assert graveyard_slot_index(col, row) == 15
    assert slots[15] == 'r'


def test_place_in_graveyard_white_ninth_slot_is_a_minus1():
    slots = [None] * 16
    for _ in range(8):
        slots = place_in_graveyard(slots, 'white', 'P')
    slots = place_in_graveyard(slots, 'white', 'R')
    col, row = WHITE_GRAVEYARD_FILL_ORDER[8]
    assert graveyard_slot_index(col, row) == 8
    assert slots[8] == 'R'
