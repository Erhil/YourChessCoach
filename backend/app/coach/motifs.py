"""Tactical motif detectors. Pure python-chess, no engine.

Move-based detectors take the board BEFORE the move and look at the position after it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import chess

VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}
SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)


@dataclass
class Motif:
    kind: str
    by: dict[str, str]
    targets: list[dict[str, str]]
    move_san: str | None = None
    material: int | None = None  # losing_exchange only


def _val(piece: chess.Piece | None) -> int:
    return VALUE[piece.piece_type] if piece else 0


def _sp(board: chess.Board, sq: int) -> dict[str, str]:
    return {"square": chess.square_name(sq), "piece": board.piece_at(sq).symbol()}


def _after(board: chess.Board, move: chess.Move) -> chess.Board:
    after = board.copy(stack=False)
    after.push(move)
    return after


def hanging_pieces(board: chess.Board, color: chess.Color) -> list[Motif]:
    out = []
    foe = board.copy(stack=False)  # the opponent to move: only legal captures count
    foe.turn, foe.ep_square = not color, None
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for sq in board.pieces(pt, color):
            takers = [m.from_square for m in foe.legal_moves if m.to_square == sq]
            if not takers:
                continue
            low = min(takers, key=lambda s: _val(board.piece_at(s)))
            if not board.is_attacked_by(color, sq) or _val(board.piece_at(low)) < VALUE[pt]:
                out.append(Motif("hanging_piece", _sp(board, low), [_sp(board, sq)]))
    return out


def fork(board: chess.Board, move: chess.Move) -> Motif | None:
    after = _after(board, move)
    me = after.piece_at(move.to_square)
    if me.piece_type == chess.KING or _refuted(after, move.to_square):
        return None
    enemy = not me.color
    hit = []
    for sq in after.attacks(move.to_square):
        p = after.piece_at(sq)
        if p and p.color == enemy:
            loose = _val(p) >= 3 and not after.is_attacked_by(enemy, sq)
            if _val(p) > _val(me) or loose:
                hit.append(sq)
    if len(hit) < 2:
        return None
    return Motif("fork", _sp(after, move.to_square), [_sp(after, s) for s in hit], board.san(move))


def _behind(board: chess.Board, a: int, b: int) -> int | None:
    """First occupied square on the line a -> b, beyond b."""
    df = (chess.square_file(b) > chess.square_file(a)) - (
        chess.square_file(b) < chess.square_file(a)
    )
    dr = (chess.square_rank(b) > chess.square_rank(a)) - (
        chess.square_rank(b) < chess.square_rank(a)
    )
    f, r = chess.square_file(b) + df, chess.square_rank(b) + dr
    while 0 <= f < 8 and 0 <= r < 8:
        sq = chess.square(f, r)
        if board.piece_at(sq):
            return sq
        f, r = f + df, r + dr
    return None


def _line_motif(
    board: chess.Board, move: chess.Move, kind: str, wins: Callable[[chess.Board, int, int], bool]
) -> Motif | None:
    after = _after(board, move)
    me = after.piece_at(move.to_square)
    if me.piece_type not in SLIDERS or _refuted(after, move.to_square):
        return None
    for front in after.attacks(move.to_square):
        p = after.piece_at(front)
        if not p or p.color == me.color:
            continue
        back = _behind(after, move.to_square, front)
        if back is None or after.color_at(back) == me.color:
            continue
        if wins(after, front, back):
            targets = [_sp(after, front), _sp(after, back)]
            return Motif(kind, _sp(after, move.to_square), targets, board.san(move))
    return None


def pin(board: chess.Board, move: chess.Move) -> Motif | None:
    """A real pin: the piece behind is the king, or worth more than the front piece and
    either worth more than the pinner or not defended."""

    def real(b: chess.Board, front: int, back: int) -> bool:
        behind, ahead = b.piece_at(back), b.piece_at(front)
        if behind.piece_type == chess.KING:
            return True
        return _val(behind) > _val(ahead) and (
            _val(behind) > _val(b.piece_at(move.to_square))
            or not b.is_attacked_by(behind.color, back)
        )

    return _line_motif(board, move, "pin", real)


def _wins_back(after: chess.Board, front: int, back: int) -> bool:
    """The mover wins material on `back` once the front piece has left the line."""
    b = after.copy(stack=False)
    b.remove_piece_at(front)
    b.turn, b.ep_square = not after.turn, None
    return _gain(b, back) > 0


def skewer(board: chess.Board, move: chess.Move) -> Motif | None:
    return _line_motif(
        board,
        move,
        "skewer",
        lambda b, front, back: (
            _val(b.piece_at(front)) > _val(b.piece_at(back)) and _wins_back(b, front, back)
        ),
    )


def discovered_attack(board: chess.Board, move: chess.Move) -> Motif | None:
    if board.is_castling(move):
        return None
    after = _after(board, move)
    me = board.turn
    for sq in chess.SquareSet(after.occupied_co[me]):
        if sq == move.to_square or after.piece_type_at(sq) not in SLIDERS:
            continue
        hit = []
        for t in after.attacks(sq) - board.attacks(sq):
            p = after.piece_at(t)
            opened = move.from_square in chess.SquareSet(chess.between(sq, t))
            if opened and p and p.color != me and (p.piece_type == chess.KING or _val(p) >= 3):
                hit.append(t)
        if hit:
            return Motif(
                "discovered_attack", _sp(after, sq), [_sp(after, t) for t in hit], board.san(move)
            )
    return None


def back_rank_mate(board: chess.Board, move: chess.Move) -> Motif | None:
    after = _after(board, move)
    me = after.piece_at(move.to_square)
    if not after.is_checkmate() or me.piece_type not in (chess.ROOK, chess.QUEEN):
        return None
    king = after.king(after.turn)
    home = 0 if after.turn == chess.WHITE else 7
    if chess.square_rank(king) != home or chess.square_rank(move.to_square) != home:
        return None
    row = 1 if home == 0 else 6  # the king must be boxed in by its own pieces
    for f in range(max(0, chess.square_file(king) - 1), min(7, chess.square_file(king) + 1) + 1):
        if after.color_at(chess.square(f, row)) != after.turn:
            return None
    return Motif("back_rank", _sp(after, move.to_square), [_sp(after, king)], board.san(move))


def _net(board: chess.Board, move: chess.Move) -> int:
    """Net material for the mover who plays capture/promotion `move`, with best recaptures."""
    cap_sq = move.to_square
    if board.is_en_passant(move):
        cap_sq = chess.square(
            chess.square_file(move.to_square), chess.square_rank(move.from_square)
        )
    got = _val(board.piece_at(cap_sq)) + (VALUE[move.promotion] - 1 if move.promotion else 0)
    return got - _gain(_after(board, move), move.to_square)


def _gain(board: chess.Board, sq: int) -> int:
    """Best net material the side to move gets by capturing on `sq`; 0 if it stops."""
    moves = [
        m for m in board.legal_moves if m.to_square == sq and m.promotion in (None, chess.QUEEN)
    ]
    if not moves:
        return 0
    m = min(moves, key=lambda m: _val(board.piece_at(m.from_square)))
    return max(0, _net(board, m))


def _refuted(after: chess.Board, sq: int) -> bool:
    """The opponent can take the piece on `sq` without losing material."""
    return any(_net(after, m) >= 0 for m in after.legal_moves if m.to_square == sq)


def losing_exchange(board: chess.Board, move: chess.Move) -> Motif | None:
    cap_sq = move.to_square
    if board.is_en_passant(move):
        cap_sq = chess.square(
            chess.square_file(move.to_square), chess.square_rank(move.from_square)
        )
    captured = board.piece_at(cap_sq)
    after = _after(board, move)
    material = _net(board, move)
    if material >= 0:
        return None
    targets = [_sp(board, cap_sq)] if captured else []
    return Motif("losing_exchange", _sp(after, move.to_square), targets, board.san(move), material)
