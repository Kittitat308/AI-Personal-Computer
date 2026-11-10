"""Word-level robustness for the Thai G2P: guarantee no WORD is ever silently
dropped.

(Symbol / number / punctuation normalization is handled in normalize.py; Latin
never reaches this module — g2p's segmenter routes it to the misaki-en branch.)

The hole this closes: tltk.th2ipa raises on some chunks and the caller used to
`except: continue`, silently losing the word. Fix: on failure, re-segment the
chunk with pythainlp and convert word-by-word, so a bad token can't take its
neighbours down with it.
"""
from __future__ import annotations

import os

import tltk.nlp as _tltk

# Optional fast path: exact Rust port of tltk.nlp.th2ipa (rust/th2ipa_rs). It is
# byte-identical to tltk on the frozen/pure-per-call semantics (~30x faster and
# thread/process-safe), so it drops in behind the Thai chunk converter. Set
# KOKORO_THAI_NO_RUST=1 to force the pure-tltk path.
_RUST = None
if not os.environ.get("KOKORO_THAI_NO_RUST"):
    try:
        import th2ipa_rs as _RUST
    except Exception:
        _RUST = None


# (The misaki-en English path lived here until 2026-07-19, when the monolingual-Thai
# router replaced it. The router was itself deleted 2026-07-29 — English is back, but
# it now lives in g2p._en_to_tokens, next to the Thai branch it is dispatched against.)

# tltk applies the native ทร -> /s/ rule (ทราบ = "ซาบ", ทรัพย์ = "ซับ") to loanwords,
# where the cluster is really /tʰr/: ทรัมป์ -> "ซัม", ทรู (True Corp) -> "ซู". There is no
# rule that separates the two classes — the native list is closed — so these are spelled
# out. tltk-format IPA (tone digit suffix, '.' between syllables); extend as they surface.
THAI_OVERRIDE = {
    "ทรัมป์": "tʰram1",
    "ทรู": "tʰruː1",
    "ทรานส์": "tʰraːn1",
}

# Preferred over THAI_OVERRIDE where it works: respell in Thai and let tltk assign the
# tones, instead of hand-writing IPA. tltk mis-syllabifies พยาธิ as "พะ-ยาด", dropping the
# final syllable; พะยาทิ -> pʰa4.jaː1.tʰi4 is right. (No respelling fixes ทรัมป์ — ทฺรัมป์
# yields nothing — so the ทร loanwords stay in THAI_OVERRIDE above.)
THAI_RESPELL = {
    "พยาธิ": "พะยาทิ",
    # Informal spellings tltk swallows MID-CHUNK (no exception, no truncation at the end,
    # so nothing detects it): "ขอบคุนมากนะ" -> kʰɔː + "มาก", losing บคุน entirely. Only
    # map spellings whose pronunciation is unchanged. ค้าบ/ครัช are NOT listed: they are
    # said differently from ครับ, so normalizing them would erase a real difference.
    # Grow from VISTEC-TP-TH-2021's linguist-annotated <msp='correct'>surface</msp> pairs.
    "ขอบคุน": "ขอบคุณ",
}
_OVERRIDE_RE = None

# Generated name readings (kokoro_thai/data/name_respell.tsv, written by
# `name_gate export-respell`). Kept SEPARATE from THAI_RESPELL above, and applied
# differently, because the two have different safety properties:
#
#   THAI_RESPELL is hand-curated and tiny, so substring replacement is fine and is what
#   you want — ขอบคุน should be corrected wherever it appears.
#
#   This table is generated and large. Thai has no word boundaries, so a substring rule
#   would corrupt every longer word containing a short name: `สิริ` fires inside
#   `สิริกิติ์`, `ประสิทธิ์` contains `สิทธิ`. So it replaces WHOLE TOKENS only, and only
#   after a cheap regex says a key is present at all — which keeps the tokenizer off the
#   hot path for the ~all chunks that contain no pinned name.
_NAME_RESPELL = None
_NAME_RESPELL_RE = None


def _name_respell():
    global _NAME_RESPELL, _NAME_RESPELL_RE
    if _NAME_RESPELL is None:
        import re
        from pathlib import Path

        _NAME_RESPELL = {}
        table = Path(__file__).parent / "data" / "name_respell.tsv"
        for line in table.read_text(encoding="utf-8").splitlines():
            columns = line.split("\t")
            if line.strip() and not line.startswith("#") and len(columns) >= 2:
                if columns[0] and columns[1]:
                    _NAME_RESPELL[columns[0]] = columns[1]
        _NAME_RESPELL_RE = re.compile(
            "|".join(re.escape(k) for k in
                     sorted(_NAME_RESPELL, key=len, reverse=True))) \
            if _NAME_RESPELL else None
    return _NAME_RESPELL, _NAME_RESPELL_RE


# A name is often several tokens to the segmenter — พฤกษ์ลดา splits as พฤกษ์|ลดา — so a
# token-by-token lookup silently misses most keys. Match the LONGEST run of consecutive
# tokens that forms a key instead. Still boundary-safe: only whole tokens are consumed, so
# a key can never match a fragment of one.
_MAX_NAME_TOKENS = 8


def _apply_name_respell(chunk: str) -> str:
    lex, rx = _name_respell()
    if not rx or not rx.search(chunk):
        return chunk
    toks = _words(chunk)
    if not toks:
        return chunk
    out, i = [], 0
    while i < len(toks):
        hit = None
        for j in range(min(len(toks), i + _MAX_NAME_TOKENS), i, -1):
            cand = "".join(toks[i:j])
            if cand in lex:
                hit = (j, lex[cand])
                break
        if hit:
            out.append(hit[1])
            i = hit[0]
        else:
            out.append(toks[i])
            i += 1
    return "".join(out)


def _override_re():
    global _OVERRIDE_RE
    if _OVERRIDE_RE is None:
        import re
        keys = sorted(THAI_OVERRIDE, key=len, reverse=True)
        _OVERRIDE_RE = re.compile("(" + "|".join(re.escape(k) for k in keys) + ")")
    return _OVERRIDE_RE


def _truncated(ipa: str) -> bool:
    """tltk mis-segments unknown spellings (ขอบคุน -> ขอ|บคุน) and returns a PARTIAL
    conversion with no exception: 'kʰᴐː5.' — a dangling syllable separator. It also
    returns '' outright. Neither raises, so the old per-word fallback never fired."""
    core = ipa.replace("<s/>", "").strip()
    return not core or core.endswith(".")


def _engine_ipa(engine, text: str) -> str:
    return engine.th2ipa(text)


def thai_chunk_to_ipa(chunk: str, drops=None) -> str:
    """th2ipa on a pure-Thai run, with overrides and a syllable-level fallback.

    Failure is not only an exception: tltk silently emits '' or a truncated string
    for informal spellings. Both are detected (`_truncated`) and retried per syllable,
    which recovers ขอบคุน -> kʰᴐːp2 kʰun1. If `drops` is a list, append any Thai word
    that still yields nothing.
    """
    engine = _RUST if _RUST is not None else _tltk

    for bad, good in THAI_RESPELL.items():       # let tltk tone the corrected spelling
        if bad in chunk:
            chunk = chunk.replace(bad, good)
    chunk = _apply_name_respell(chunk)           # generated table, whole tokens only

    # loanwords tltk gets wrong go through verbatim; the rest hits the engine
    if any(k in chunk for k in THAI_OVERRIDE):
        parts = []
        for piece in _override_re().split(chunk):
            if not piece:
                continue
            if piece in THAI_OVERRIDE:
                parts.append(THAI_OVERRIDE[piece])
            else:
                parts.append(thai_chunk_to_ipa(piece, drops))
        return " ".join(p for p in parts if p.strip())

    try:
        out = _engine_ipa(engine, chunk)
    except Exception:
        out = ""
    if out and not _truncated(out):
        return out

    for tokenize in (_syllables, _words):
        pieces = tokenize(chunk)
        if len(pieces) < 2:
            continue
        got = []
        for w in pieces:
            w = w.strip()
            if not w:
                continue
            try:
                p = _engine_ipa(engine, w)
            except Exception:
                continue
            if p and not _truncated(p):
                got.append(p)
        if got:
            return " ".join(got)

    if drops is not None and chunk.strip():
        drops.append(("th", chunk))
    return ""


def _syllables(chunk: str) -> list:
    try:
        from pythainlp.tokenize import syllable_tokenize
        return syllable_tokenize(chunk)
    except Exception:
        return [chunk]


def _words(chunk: str) -> list:
    try:
        from pythainlp.tokenize import word_tokenize
        return word_tokenize(chunk)
    except Exception:
        return [chunk]
