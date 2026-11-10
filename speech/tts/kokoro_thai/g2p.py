"""Bilingual G2P frontend for Kokoro: Thai through tltk, English through misaki-en.

Pipeline:  text ──normalize (Thai numbers/abbrev/ๆ/฿/%)──► segment
             ├─ Thai run  ──tltk.th2ipa──► Thai IPA + tone tokens
             └─ Latin run ──misaki-en───► Kokoro's English IPA, verbatim
           ──► one Kokoro phoneme string ──encode──► token ids

Both branches land inside Kokoro's shared 114-token vocab, so a code-switched
sentence comes out as a single phoneme string with no script left in it. The model
is unchanged (one free-slot tone token, see vocab.LOW_TONE_TOKEN).

2026-07-29 — this REPLACES the monolingual-Thai router (pinned lexicon + Thai
letter-name fallback). That router rewrote every Latin span into Thai text, which is
right for a true acronym (AOT -> เอโอที) and gibberish for an ordinary English word:

    text to speech -> ทีอีเอกซ์ที ทีโอ เอสพีอีอีซีเอช   (T-E-X-T T-O S-P-E-E-C-H)
    Chrome         -> ซีเอชอาร์โอเอ็มอี                  Apple -> เอพีพีแอลอี

Measured on the 1,550-sentence eval with the lexicon the HF bundle actually ships:
29.3% of sentences reached the fallback, and 88% of the runs that did were
word-shaped, not acronyms. Growing the lexicon does not close it (405 -> 1,802
entries moved the pin rate 49% -> 52%) because the tail is open-ended English
vocabulary, not a finite entity list. English is now handled where it was already
learned — Kokoro's own English inventory, which the 82M init brought in and the
one-token Thai extension never displaced.
"""
from __future__ import annotations

import re

import tltk.nlp as _tltk

from .normalize import normalize_text
from .vocab import NORMALIZE, TONE_DIGIT_TO_TOKEN, encode, get_thai_vocab

_TAG = re.compile(r"<[^>]*>")  # strip <s/>, <tr/>, etc.
# Segment into: Thai run | Latin run | whitespace | single other char.
# The Latin branch spans WHOLE PHRASES (interior spaces, hyphens and apostrophes)
# because misaki is a sentence-level G2P: it needs the neighbours to weight function
# words and homographs (`to` -> tə before a consonant but tu in isolation, `read`,
# `live`). Feeding it one word at a time throws that away. It must still end on a
# letter so the run cannot swallow the space in front of the next Thai word.
_SEG = re.compile(r"([฀-๿]+)|([A-Za-z][A-Za-z'\- ]*[A-Za-z]|[A-Za-z])|(\s+)|(.)")

_EN = None


def _en_g2p():
    """misaki-en — Kokoro's own English G2P — with the espeak-ng fallback for OOV.

    Lazy on purpose: misaki lives only in kokoro-train, and this module is imported by
    tooling that has no use for the English branch. The fallback is what makes the path
    total: misaki's bundled dictionaries cover ordinary vocabulary but return '❓' for
    unlisted proper nouns (`Sony`, `Hitachi`, `Evergrande`), which is exactly the class
    a Thai corpus is full of. Without espeak those would phonemize to nothing.
    """
    global _EN
    if _EN is None:
        from misaki import en
        try:
            from misaki.espeak import EspeakFallback
            fb = EspeakFallback(british=False)
        except Exception:   # no espeak-ng: OOV becomes '❓', filtered out and reported
            fb = None
        _EN = en.G2P(trf=False, british=False, fallback=fb)
    return _EN


class ThaiG2P:
    """Callable: text -> Kokoro phoneme string (and token ids)."""

    def __init__(self) -> None:
        self.vocab = get_thai_vocab()

    # ---- Thai ----
    def _th2ipa(self, text: str, drops=None) -> str:
        # tltk.th2ipa chokes on multi-chunk whitespace input; drive per chunk,
        # with a per-word fallback so a bad token can't drop its neighbours.
        from .word_level import thai_chunk_to_ipa
        return " ".join(thai_chunk_to_ipa(chunk, drops) for chunk in text.split())

    def _thai_to_tokens(self, s: str, drops=None) -> str:
        raw = _TAG.sub(" ", self._th2ipa(s, drops))
        out = []
        for ch in raw:
            if ch.isdigit():
                # tltk tone digit -> tone token, but ONLY in a tone position
                # (right after a phoneme). A digit at a boundary is a leaked
                # number, not a tone -> drop (never emit a spurious tone arrow).
                if out and out[-1] != " ":
                    tok = TONE_DIGIT_TO_TOKEN.get(ch)
                    if tok:
                        out.append(tok)
            elif ch in ".+":              # tltk syllable-sep / artifact
                continue
            elif ch.isspace():
                if out and out[-1] != " ":
                    out.append(" ")
            else:
                # keep ONLY valid Kokoro tokens; drop any other tltk artifact
                # (e.g. '-' it emits for reduplications) so the Thai path can
                # never leak an out-of-vocab char.
                tok = NORMALIZE.get(ch, ch)
                if tok in self.vocab:
                    out.append(tok)
        res = "".join(out)
        # A non-empty Thai run that phonemizes to nothing IS a dropped word. This used
        # to pass silently: word_level only reported *exceptions*, and the vocab filter
        # above can empty a string that tltk already truncated.
        if drops is not None and s.strip() and not res.strip() and ("th", s) not in drops:
            drops.append(("th", s))
        return res

    # ---- English ----
    def _en_to_tokens(self, s: str, drops=None) -> str:
        """misaki-en output, filtered to the vocab. misaki already emits Kokoro tokens
        (it is Kokoro's reference G2P), so the filter only catches the '❓' it writes for
        a word no dictionary and no fallback could reach — never a real phoneme."""
        ps, _ = _en_g2p()(s)
        res = re.sub(r" +", " ", "".join(
            c for c in (ps or "") if c == " " or c in self.vocab)).strip()
        if drops is not None and s.strip() and not res and ("en", s) not in drops:
            drops.append(("en", s))
        return res

    # ---- driver ----
    def _render(self, text: str, drops=None) -> str:
        """Segment normalized text and phonemize each run in its own language."""
        out = []
        for thai, latin, ws, other in _SEG.findall(text):
            if thai:
                out.append(self._thai_to_tokens(thai, drops))
            elif latin:
                out.append(self._en_to_tokens(latin, drops))
            elif ws:
                out.append(" ")
            elif other and other in self.vocab:   # keep , . ! ? etc.
                out.append(other)
        return re.sub(r" +", " ", "".join(out)).strip()

    def phonemize(self, text: str) -> str:
        """Return a Kokoro-compatible phoneme string for `text`."""
        return self._render(normalize_text(text))

    def phonemize_report(self, text: str):
        """Like phonemize, but also returns (word_drops, symbol_drops) for
        validation. word_drops = [(lang, token)] a Thai/English word that could
        not be converted; symbol_drops = set of chars normalize discarded."""
        sym_drops: set = set()
        word_drops: list = []
        ph = self._render(normalize_text(text, dropped=sym_drops), word_drops)
        return ph, word_drops, sym_drops

    def __call__(self, text: str):
        ph = self.phonemize(text)
        return ph, encode(ph, extended=True)

    def coverage(self, text: str):
        """Debug helper: (phoneme_str, list_of_out_of_vocab_chars)."""
        ph = self.phonemize(text)
        bad = [c for c in ph if c not in self.vocab and c != " "]
        return ph, bad


_default = None


def phonemize(text: str) -> str:
    global _default
    if _default is None:
        _default = ThaiG2P()
    return _default.phonemize(text)
