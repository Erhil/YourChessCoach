"""Build CoachFacts for one played move. Chess claims come from the engine and motif detectors."""

from functools import lru_cache
from pathlib import Path

import chess

from app.coach import motifs as m
from app.coach.classify import classify, missed_leads, mover_view, score_win_chance, thresholds
from app.coach.schema import CoachFacts, Lesson, Material, Threat
from app.coach.why import (
    Reason,
    _hits,
    _threatened,
    best_move_ideas,
    king_weakening,
    new_attacks,
    opening_issues,
    passive_piece,
    pawn_structure,
    removed_defence,
)
from app.config import Settings
from app.config import settings as default_settings
from app.engines.pool import EnginePool
from app.lessons.loader import load_lesson

KIND_LESSON = {
    "hanging_piece": "blunder-check",
    "losing_exchange": "piece-values",
    "fork": "fork",
    "pin": "pin",
    "skewer": "skewer",
    "discovered_attack": "discovered-attack",
    "back_rank": "back-rank-mate",
}
MIN_PLIES = 4
MAX_PLIES = 16  # a hard cap: the line goes on past 10 plies only while the exchange is not over
MAX_REASONS = 3


@lru_cache
def _title(lessons_dir: Path, slug: str) -> str:
    (path,) = lessons_dir.glob(f"*-{slug}.md")
    return load_lesson(path)["title"]


def cut_line(board: chess.Board, ucis: list[str]) -> list[str]:
    """Plies to count: stop at a quiet position after at least MIN_PLIES, at most MAX_PLIES.

    Quiet: the last move is not a capture, there is no check, and no piece of either side hangs.
    """
    b = board.copy(stack=False)
    n = 0
    for uci in ucis[:MAX_PLIES]:
        move = chess.Move.from_uci(uci)
        capture = b.is_capture(move)
        b.push(move)
        n += 1
        if n >= MIN_PLIES and not capture and not b.is_check() and _quiet(b):
            break
    return ucis[:n]


def _quiet(b: chess.Board) -> bool:
    return not _threatened(b, chess.WHITE) and not _threatened(b, chess.BLACK)


def _quiet_prefix(board: chess.Board, line: list[str]) -> tuple[int, bool]:
    """(plies up to the last fully quiet position, whether the line ends mid-exchange)."""
    b = board.copy(stack=False)
    quiet_at, capture = 0, False
    for n, uci in enumerate(line, 1):
        move = chess.Move.from_uci(uci)
        capture = b.is_capture(move)
        b.push(move)
        # Settled: no check and nothing hangs (a capture that can be won back leaves a hanging piece).
        if not b.is_check() and _quiet(b):
            quiet_at = n
    # Open: the last ply took or checked and the piece that moved can be won back (2...Qh4 3.Nxh4
    # is over; ...Bxd2+ with Kxd2 to come is not).
    recapture = bool(_threatened(b, not b.turn))
    return quiet_at, bool(line) and not b.is_game_over() and (capture or b.is_check()) and recapture


def line_is_open(board: chess.Board, line: list[str]) -> bool:
    """The last ply is a capture or a check and no quiet position came before: no count is safe."""
    quiet_at, ends_open = _quiet_prefix(board, line)
    return ends_open and quiet_at == 0


def settled_material(board: chess.Board, line: list[str], color: chess.Color) -> Material:
    """Material change along a cut line, seen by `color`, counted only where the exchange is over.

    The end is open if the last ply is a capture or a check and the piece that moved can be won back.
    Then the count goes back to the last quiet position of the line; with none, nothing is claimed.
    A piece that merely hangs at the cut does not stop the claim: PVs of tactical lines rarely get quiet.
    """
    quiet_at, ends_open = _quiet_prefix(board, line)
    return line_material(board, line[:quiet_at] if ends_open else line, color)


def _counts(board: chess.Board, color: chess.Color) -> dict[str, int]:
    counts = {k: 0 for k in "PNBRQ"}
    for piece in board.piece_map().values():
        if piece.color == color and piece.symbol().upper() in counts:
            counts[piece.symbol().upper()] += 1
    return counts


def line_material(board: chess.Board, ucis: list[str], color: chess.Color) -> Material:
    """Material change along a line, seen by `color`: board before vs board at the end."""
    b = board.copy(stack=False)
    promoted = {chess.WHITE: [], chess.BLACK: []}
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        if move.promotion:
            promoted[b.turn].append(chess.piece_symbol(move.promotion).upper())
        b.push(move)
    diff = {}
    total = {}
    for side in (color, not color):
        before, after = _counts(board, side), _counts(b, side)
        d = {k: after[k] - before[k] for k in before}
        for t in promoted[side]:  # a promoted piece that is still there is not a gain
            if d[t] > 0:
                d[t] -= 1
                d["P"] += 1
        diff[side] = d
        total[side] = sum(
            m.VALUE[chess.Piece.from_symbol(k).piece_type] * (after[k] - before[k]) for k in before
        )
    lost, gained = [], []
    for k in "QRBNP":  # net per piece type: equal trades cancel out
        out, taken = max(0, -diff[color][k]), max(0, -diff[not color][k])
        lost.extend([k] * (out - min(out, taken)))
        gained.extend([k] * (taken - min(out, taken)))
    return Material(change=total[color] - total[not color], lost=lost, gained=gained)


def _detect(board: chess.Board, move: chess.Move) -> list[m.Motif]:
    found = [
        f(board, move) for f in (m.fork, m.pin, m.skewer, m.discovered_attack, m.back_rank_mate)
    ]
    return [x for x in found if x]


def _detect_line(after: chess.Board, ucis: list[str]) -> list[m.Motif]:
    """Motifs of the opponent's moves in the first 3 plies: a fork can come on the 2nd move."""
    found, b = [], after
    for ply, uci in enumerate(ucis[:3]):
        move = chess.Move.from_uci(uci)
        if ply % 2 == 0:
            found += [x for x in _detect(b, move) if x.kind not in {y.kind for y in found}]
        b = m._after(b, move)
    return found


SERIOUS = {"removed_defender", "reply_attacks", "opened_line", "pawn_shield"}  # mistake or worse
QUIET = {"lost_castling", "queen_early", "same_piece_twice", "edge_knight", "blocks_center_pawn"}


def _hits_king_area(after: chess.Board, line: list[chess.Move]) -> bool:
    """In the first 3 plies the opponent gives check or attacks a square next to our king."""
    king = after.king(not after.turn)
    ring = chess.SquareSet(chess.BB_KING_ATTACKS[king])
    b = after
    for ply, mv in enumerate(line[:3]):
        b = m._after(b, mv)
        if ply % 2 == 0 and (b.is_check() or any(b.is_attacked_by(not b.turn, sq) for sq in ring)):
            return True
    return False


def _reasons_against(
    board: chess.Board, move: chess.Move, ucis: list[str], best: chess.Move, cls: str, loss: int
) -> list[Reason]:
    """Why the move is weak, most important first: material, king, opening principles."""
    line = [chess.Move.from_uci(u) for u in ucis[:3]]
    after = m._after(board, move)
    out: list[Reason] = []
    if line:
        if r := removed_defence(board, move, line):
            out.append(r)
        if r := new_attacks(after, line[0]):
            out.append(r)
    out += king_weakening(board, move) + opening_issues(board, move)
    shared = {r.kind for r in king_weakening(board, best) + opening_issues(board, best)}
    allowed = SERIOUS | QUIET if cls != "inaccuracy" else QUIET

    def confirmed(r: Reason) -> bool:  # the line takes an attacked piece and wins material
        hit = zip(r.squares, r.pieces[1:])
        return r.kind == "reply_attacks" and any(
            p["piece"].upper() != "K" and _hits(after, chess.parse_square(s), line) for s, p in hit
        )

    out = [r for r in out if (r.kind in allowed or confirmed(r)) and r.kind not in shared]
    out = [
        r
        for r in out
        if r.kind != "reply_attacks" or loss < 0 or r.detail == "check" or confirmed(r)
    ]
    if not _hits_king_area(after, line):
        out = [r for r in out if r.kind != "pawn_shield"]
    return out[:MAX_REASONS]


def _reasons_missed(board: chess.Board, move: chess.Move, best: chess.Move) -> list[Reason]:
    """What the best move does that the played move does not."""
    shared = {r.kind for r in best_move_ideas(board, move)}
    piece = board.piece_type_at(best.from_square)
    taken = m._refuted(m._after(board, best), best.to_square) and not board.is_castling(best)
    out = [
        r
        for r in best_move_ideas(board, best)
        if r.kind not in shared
        and not (taken and r.kind in ("best_attacks", "center"))
        and not (r.kind == "center" and piece in (chess.QUEEN, chess.KING))
    ]
    return out[:MAX_REASONS]


def _captured_squares(board: chess.Board, ucis: list[str], color: chess.Color) -> set[str]:
    """Squares where `color` captures along the line."""
    b = board.copy(stack=False)
    squares = set()
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        if b.turn == color and b.is_capture(move):
            squares.add(chess.square_name(move.to_square))
        b.push(move)
    return squares


def _lesson(
    motifs: list,
    material: Material,
    allowed_mate: int | None,
    game_over: str | None,
    lessons_dir: Path,
) -> Lesson | None:
    """`motifs` is ordered by importance: the first one is the one the text talks about."""
    slug = KIND_LESSON[motifs[0].kind] if motifs else None
    if game_over == "stalemate":
        slug = "check-mate-stalemate"
    if allowed_mate:  # a mate is a mate: other motifs of the mating move are incidental
        slug = "back-rank-mate" if any(x.kind == "back_rank" for x in motifs) else "blunder-check"
    if slug is None and material.change < 0:
        slug = "blunder-check"
    return Lesson(slug=slug, title=_title(lessons_dir, slug)) if slug else None


def find_threat(pool: EnginePool, board: chess.Board, depth: int) -> tuple[str, Threat] | None:
    """Opponent's best reply if the side to move passed: (uci, Threat) only if it mates or wins material."""
    if board.is_check():
        return None
    null = board.copy(stack=False)
    null.push(chess.Move.null())
    _, tl = pool.analyse(null, depth)
    if not tl or not tl[0]["pv_uci"]:
        return None
    t_mate = mover_view(tl[0]["score"], not board.turn)["mate"]
    t_line = settled_material(null, cut_line(null, tl[0]["pv_uci"]), not board.turn)
    t_mat = t_line.change
    mate_in = t_mate if t_mate and t_mate > 0 else None
    if not mate_in and t_mat <= 0:  # a quiet reply is not a threat
        return None
    threat = Threat(
        move_san=tl[0]["pv_san"][0],
        mate_in=mate_in,
        material=max(t_mat, 0) or None,
        wins=t_line.gained if t_mat > 0 else [],
    )
    return tl[0]["pv_uci"][0], threat


def threat_missed(after: chess.Board, reply: chess.Move, threat: Threat, change: int) -> bool:
    """The played move left the threat alone. `after` is the board after the move."""
    # A capture the move already answers (it now loses material) is not a missed threat.
    if after.is_capture(reply) and m._net(after, reply) <= 0:
        return False
    # A move that cuts the loss below the threat has dealt with it, at least in part.
    return bool(threat.mate_in) or (threat.material or 0) <= -change


def build_facts(
    pool: EnginePool,
    board_before: chess.Board,
    move: chess.Move,
    settings: Settings = default_settings,
) -> CoachFacts:
    if move not in board_before.legal_moves:
        raise ValueError(f"illegal move {move.uci()}")
    depth = settings.coach_depth
    me = board_before.turn
    san = board_before.san(move)
    after = board_before.copy(stack=False)
    after.push(move)
    mated = after.is_checkmate()
    game_over = (
        "checkmate"
        if mated
        else "stalemate"
        if after.is_stalemate()
        else "draw"
        if after.is_insufficient_material() or after.is_fifty_moves()
        else None
    )

    _, lines = pool.analyse(board_before, depth, multipv=5)
    best = lines[0]
    best_uci = best["pv_uci"][0]
    eval_before = mover_view(best["score"], me)

    # One search scores the best moves, so equal moves get comparable scores (no search noise).
    played = next((x for x in lines if x["pv_uci"][0] == move.uci()), None)
    refutation: list[str] = []
    ref_uci: list[str] = []
    if mated:
        eval_after = {"cp": None, "mate": 0}
    elif played and not after.is_game_over():
        eval_after = mover_view(played["score"], me)
        ref_uci = played["pv_uci"][1:]
        refutation = played["pv_san"][1:]
    else:
        _, after_lines = pool.analyse(after, depth)
        if after_lines:
            eval_after = mover_view(after_lines[0]["score"], me)
            ref_uci = after_lines[0]["pv_uci"]
            refutation = after_lines[0]["pv_san"]
        else:  # stalemate or another draw
            eval_after = {"cp": 0, "mate": None}

    wc_before = score_win_chance(eval_before["cp"], eval_before["mate"])
    wc_after = 1.0 if mated else score_win_chance(eval_after["cp"], eval_after["mate"])
    mate_b, mate_a = eval_before["mate"], eval_after["mate"]
    classification = classify(
        wc_before,
        wc_after,
        move.uci() == best_uci or mated,
        mate_b,
        mate_a,
        thresholds(settings),
    )
    is_best = classification == "best"

    line = cut_line(board_before, [move.uci(), *ref_uci])
    ref_uci = line[1:]
    refutation = refutation[: len(ref_uci)]
    material = settled_material(board_before, line, me)
    best_ucis = cut_line(board_before, best["pv_uci"])
    best_line = best["pv_san"][: len(best_ucis)]
    missed = settled_material(board_before, best_ucis, me)

    against = []
    if ref_uci:
        against = _detect_line(after, ref_uci)
        taken = _captured_squares(after, ref_uci, not me)
        hanging = [h for h in m.hanging_pieces(after, me) if h.targets[0]["square"] in taken]
    else:
        hanging = []
    exchange = m.losing_exchange(board_before, move)
    exchange = [exchange] if exchange else []
    unknown = line_is_open(board_before, line)  # the exchange is not over: material is not claimed
    if material.change >= 0 and not unknown:  # no net loss on the engine line: no material motif
        hanging, exchange = [], []
    # A capture that loses material is a bad exchange; a quiet move is a hanging piece.
    if hanging and not board_before.is_capture(move):  # the lost piece is the main point
        against = hanging + against + exchange
    else:
        against += exchange + hanging if board_before.is_capture(move) else hanging + exchange
    missed_motifs = [] if is_best else _detect(board_before, chess.Move.from_uci(best_uci))

    already_mated = mate_b is not None and mate_b < 0
    allowed = -mate_a if mate_a is not None and mate_a < 0 and not already_mated else None
    lost_mate = mate_b and mate_b > 0 and not mated and not (mate_a and mate_a > 0)
    missed_mate = mate_b if lost_mate else None

    threat = None
    if classification in ("mistake", "blunder") and ref_uci:
        found = find_threat(pool, board_before, depth)
        if found and found[0] == ref_uci[0]:
            reply = chess.Move.from_uci(found[0])
            if threat_missed(after, reply, found[1], material.change):
                threat = found[1]

    reasons_against, reasons_missed = [], []
    if classification in ("inaccuracy", "mistake", "blunder") and not game_over:
        best_move = chess.Move.from_uci(best_uci)
        reasons_against = _reasons_against(
            board_before, move, ref_uci, best_move, classification, material.change
        )
        if best_move != move:
            reasons_missed = _reasons_missed(board_before, move, best_move)
        # Doubled or isolated pawns and a passive piece count only when nothing stronger is shown.
        weak = classification in ("inaccuracy", "mistake") and material.change >= 0
        if weak and not reasons_against and not against and best_move != move:
            r = pawn_structure(board_before, move, best_move) or passive_piece(
                board_before, move, best_move
            )
            reasons_against = [r] if r else []

    # The text leads with the missed chance when it is bigger than the loss: same rule here.
    lead_missed = missed_motifs and missed_leads(material.change, missed.change, missed_mate)
    motifs = missed_motifs + against if lead_missed else against + missed_motifs
    lesson = (
        None
        if classification in ("best", "good")
        else _lesson(motifs, material, allowed, game_over, settings.lessons_dir)
    )

    return CoachFacts(
        fen_before=board_before.fen(),
        side="white" if me == chess.WHITE else "black",
        player_move={"san": san, "uci": move.uci()},
        classification=classification,
        win_chance_drop=round(max(0.0, wc_before - wc_after), 3),
        eval_before=eval_before,
        eval_after=eval_after,
        best_move={"san": best["pv_san"][0], "uci": best_uci},
        best_line=best_line,
        refutation=refutation,
        material=material,
        missed_material=missed,
        motifs_against=against,
        motifs_missed=missed_motifs,
        reasons_against=reasons_against,
        reasons_missed=reasons_missed,
        allowed_mate_in=allowed,
        missed_mate_in=missed_mate,
        threat=threat,
        game_over=game_over,
        lesson=lesson,
    )
