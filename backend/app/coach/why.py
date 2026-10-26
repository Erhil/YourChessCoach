"""Reasons why a move is weak or why the best move is better. Pure python-chess, no engine.

Move-based detectors take the board BEFORE the move. `new_attacks` takes the board AFTER
the player's move and BEFORE the opponent's reply. Lines are lists of `chess.Move` from the engine.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import chess

from app.coach.motifs import SLIDERS, VALUE, _after, _gain, _net, _refuted, _sp, _val

CENTER = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])
HOME = {
    chess.WHITE: chess.SquareSet([chess.B1, chess.C1, chess.F1, chess.G1]),
    chess.BLACK: chess.SquareSet([chess.B8, chess.C8, chess.F8, chess.G8]),
}
OPENING_MOVES = 12


@dataclass
class Reason:
    kind: str
    squares: list[str] = field(default_factory=list)
    pieces: list[dict[str, str]] = field(default_factory=list)
    detail: str | None = None


def _reason(
    kind: str, board: chess.Board, squares: list[int], pieces: list[int], detail: str | None = None
) -> Reason:
    names = [chess.square_name(s) for s in squares]
    return Reason(kind, names, [_sp(board, s) for s in pieces], detail)


def _threatened(board: chess.Board, color: chess.Color) -> set[int]:
    """Pieces of `color` (not the king) that the opponent wins material on by capturing.

    Empty while `color` is in check: it has to answer the check, so it cannot recapture.
    """
    if board.turn == color and board.is_check():
        return set()
    foe = board.copy(stack=False)
    foe.turn, foe.ep_square = not color, None
    out = set()
    for sq in chess.SquareSet(board.occupied_co[color] & ~board.kings):
        if board.attackers_mask(not color, sq) and _gain(foe, sq) > 0:
            out.add(sq)
    return out


def _hits(after: chess.Board, sq: int, line: list[chess.Move]) -> bool:
    """In the first 3 plies the opponent captures the piece on `sq` and wins material."""
    piece = after.piece_at(sq)
    b = after.copy(stack=False)
    for ply, m in enumerate(line[:3]):
        if m not in b.legal_moves:
            return False
        if ply % 2 == 0:
            if m.to_square == sq and b.piece_at(sq) == piece and not b.is_en_passant(m):
                return _net(b, m) > 0
        elif sq in (m.from_square, m.to_square):
            return False
        b.push(m)
    return False


def removed_defence(
    board: chess.Board, move: chess.Move, refutation: list[chess.Move]
) -> Reason | None:
    if board.is_castling(move):
        return None
    me, to = board.turn, move.to_square
    after = _after(board, move)
    lost = [
        sq
        for sq in board.attacks(move.from_square)
        if sq != to
        and board.color_at(sq) == me
        and board.piece_type_at(sq) != chess.KING
        and sq not in after.attacks(to)
        and not after.is_attacked_by(me, sq)
        and _hits(after, sq, refutation)
    ]
    if not lost:
        return None
    sq = max(lost, key=lambda s: _val(board.piece_at(s)))
    return _reason("removed_defender", board, [sq], [move.from_square, sq])


def _in_shield(color: chess.Color, king: int, pawn: int) -> bool:
    home, step = (0, 1) if color == chess.WHITE else (7, -1)
    kf, pf = chess.square_file(king), chess.square_file(pawn)
    wing = (5, 6, 7) if kf >= 5 else (0, 1, 2) if kf <= 2 else ()
    ranks = (home + step, home + 2 * step)
    return (
        chess.square_rank(king) == home
        and chess.square_rank(pawn) in ranks
        and pf in wing
        and abs(kf - pf) <= 1
    )


def _opened_line(board: chess.Board, after: chess.Board, move: chess.Move) -> Reason | None:
    me = board.turn
    king = board.king(me)
    ring = chess.SquareSet(chess.BB_KING_ATTACKS[king]) | chess.SquareSet([king])
    for sq in chess.SquareSet(after.occupied_co[not me]):
        if after.piece_type_at(sq) not in SLIDERS:
            continue
        for t in (after.attacks(sq) - board.attacks(sq)) & ring:
            opened = move.from_square in chess.SquareSet(chess.between(sq, t))
            if opened and (t == king or after.piece_at(t) is None):
                return _reason("opened_line", after, [sq, t], [sq])
    return None


def king_weakening(board: chess.Board, move: chess.Move) -> list[Reason]:
    me = board.turn
    king = board.king(me)
    if king is None:
        return []
    after = _after(board, move)
    piece = board.piece_type_at(move.from_square)
    out = []
    if piece == chess.PAWN and _in_shield(me, king, move.from_square):
        file = chess.FILE_NAMES[chess.square_file(move.from_square)]
        out.append(
            _reason("pawn_shield", board, [move.from_square], [move.from_square], f"{file}-file")
        )
    if piece != chess.KING and (r := _opened_line(board, after, move)):
        out.append(r)
    centre = chess.square_file(after.king(me)) in (3, 4, 5)
    if board.has_castling_rights(me) and not after.has_castling_rights(me) and centre:
        out.append(_reason("lost_castling", after, [after.king(me)], [after.king(me)]))
    return out


def new_attacks(board: chess.Board, reply: chess.Move) -> Reason | None:
    """`board` is the position after the player's move; `reply` is the opponent's first move."""
    us = not board.turn
    post = _after(board, reply)
    if post.is_checkmate():  # the mate sentence says it all
        return None
    if _refuted(post, reply.to_square):  # we take the piece back without losing material
        return None
    # only what the replying piece itself attacks: a discovered attack has another attacker
    own = set(post.attacks(reply.to_square))
    hit = sorted(
        (_threatened(post, us) - _threatened(board, us)) & own,
        key=lambda s: (-_val(post.piece_at(s)), s),
    )
    king = post.king(us)
    check = reply.to_square in post.checkers()
    if check:
        hit.append(king)
    if not hit:
        return None
    return _reason(
        "reply_attacks",
        post,
        hit,
        [reply.to_square, *hit],
        "check" if check else None,
    )


def _ideas_attack(board: chess.Board, after: chess.Board, best: chess.Move) -> Reason | None:
    to, me = best.to_square, board.turn
    if _refuted(after, to):  # the piece is taken for free or traded: it attacks nothing for long
        return None
    new = after.attacks(to) - board.attacks(best.from_square)
    foes = [
        sq
        for sq in new
        if after.color_at(sq) == (not me)
        and 3 <= _val(after.piece_at(sq)) < VALUE[chess.KING]
        and (
            not after.is_attacked_by(not me, sq)
            or _val(after.piece_at(to)) < _val(after.piece_at(sq))
        )
    ]
    if after.is_check():
        foes.append(after.king(not me))
    if not foes:
        return None
    return _reason("best_attacks", after, foes, [to, *foes], "check" if after.is_check() else None)


def best_move_ideas(board: chess.Board, best: chess.Move) -> list[Reason]:
    me, after = board.turn, _after(board, best)
    piece = board.piece_at(best.from_square)
    out = []
    if r := _ideas_attack(board, after, best):
        out.append(r)
    now = _threatened(after, me)
    moved = {best.from_square: best.to_square}
    if board.is_castling(best):
        rank = chess.square_rank(best.from_square)
        kingside = chess.square_file(best.to_square) > 4
        moved = {chess.square(7 if kingside else 0, rank): chess.square(5 if kingside else 3, rank)}
    for sq in sorted(_threatened(board, me)):
        target = moved.get(sq, sq)
        if after.color_at(target) != me or (after.is_check() and target != best.to_square):
            continue  # after a check the other captures are not legal yet: the test is not valid
        if target not in now:
            detail = "retreat" if sq == best.from_square and not board.is_castling(best) else None
            r = _reason("best_defends", after, [target], [target], detail)
            out.insert(0, r) if detail else out.append(r)  # a retreat of a hanging piece leads
            break
    home = piece.piece_type in (chess.KNIGHT, chess.BISHOP) and best.from_square in HOME[me]
    if board.fullmove_number <= OPENING_MOVES and home:
        out.append(_reason("development", after, [best.to_square], [best.to_square]))
    if board.is_castling(best):
        side = "kingside" if chess.square_file(best.to_square) > 4 else "queenside"
        out.append(_reason("castles", after, [best.to_square], [best.to_square], side))
    pawn_in = piece.piece_type == chess.PAWN and best.to_square in CENTER
    minor = piece.piece_type in (chess.KNIGHT, chess.BISHOP)
    if pawn_in or (minor and len(after.attacks(best.to_square) & CENTER) >= 2):
        out.append(_reason("center", after, [best.to_square], [best.to_square]))
    return out


def opening_issues(board: chess.Board, move: chess.Move) -> list[Reason]:
    if board.fullmove_number > OPENING_MOVES or board.is_castling(move):
        return []
    me = board.turn
    piece = board.piece_at(move.from_square)
    frm, to = move.from_square, move.to_square
    minors = chess.SquareSet(board.occupied_co[me] & (board.knights | board.bishops))
    undeveloped = len(minors & HOME[me])
    capture = board.is_capture(move)
    out = []

    def add(kind: str) -> None:
        out.append(_reason(kind, board, [to], [frm]))

    queen_home = chess.D1 if me == chess.WHITE else chess.D8
    developed = len(minors) - undeveloped
    if (
        piece.piece_type == chess.QUEEN
        and frm == queen_home
        and not capture
        and developed < 2
        and not board.is_check()
    ):
        add("queen_early")
    if piece.piece_type in (chess.KNIGHT, chess.BISHOP) and not capture:
        moved_before = frm not in HOME[me] and not board.is_attacked_by(not me, frm)
        if moved_before and undeveloped >= 2:
            add("same_piece_twice")
    if piece.piece_type == chess.KNIGHT and chess.square_file(to) in (0, 7) and not capture:
        add("edge_knight")
    if piece.piece_type != chess.PAWN and not capture:
        home_rank, step = (1, 1) if me == chess.WHITE else (6, -1)
        for f in (3, 4):
            pawn = chess.square(f, home_rank)
            front = chess.square(f, home_rank + step)
            if to == front and board.piece_at(pawn) == chess.Piece(chess.PAWN, me):
                add("blocks_center_pawn")
    return out


def _pawn_faults(board: chess.Board, color: chess.Color) -> tuple[set[int], set[int]]:
    """Files with doubled pawns and squares of isolated pawns."""
    pawns = list(board.pieces(chess.PAWN, color))
    files = Counter(chess.square_file(sq) for sq in pawns)
    doubled = {f for f, n in files.items() if n >= 2}
    isolated = {
        sq
        for sq in pawns
        if not files[chess.square_file(sq) - 1] and not files[chess.square_file(sq) + 1]
    }
    return doubled, isolated


def pawn_structure(board: chess.Board, move: chess.Move, best: chess.Move) -> Reason | None:
    """The move makes a doubled or isolated pawn that neither the position before nor the best move has."""
    me = board.turn
    before, played, ideal = (
        _pawn_faults(b, me) for b in (board, _after(board, move), _after(board, best))
    )
    after = _after(board, move)
    for f in sorted(played[0] - before[0] - ideal[0]):
        squares = sorted(after.pieces(chess.PAWN, me) & chess.SquareSet(chess.BB_FILES[f]))
        return _reason("doubled_pawns", after, squares, squares, chess.FILE_NAMES[f])
    for sq in sorted(played[1] - before[1] - ideal[1]):
        return _reason("isolated_pawn", after, [sq], [sq])
    return None


def _reach(board: chess.Board, move: chess.Move, kinds: tuple[int, ...]) -> int | None:
    """Squares the moved piece attacks after `move`; None when it is not one of `kinds`."""
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type not in kinds:
        return None
    return len(_after(board, move).attacks(move.to_square))


def passive_piece(board: chess.Board, move: chess.Move, best: chess.Move) -> Reason | None:
    """A bishop, rook or queen lands where it attacks 4 squares or fewer; the best move
    puts a bishop, rook, queen or knight where it attacks at least 4 squares more."""
    k = _reach(board, move, (chess.BISHOP, chess.ROOK, chess.QUEEN))
    m = _reach(board, best, (chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KNIGHT))
    if k is None or m is None or k > 4 or m - k < 4:
        return None
    return _reason("passive_piece", _after(board, move), [move.to_square], [move.to_square], str(k))
