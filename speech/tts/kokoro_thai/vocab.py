"""Kokoro's shared IPA token vocabulary + the minimal Thai extension.

Kokoro-82M uses ONE 114-token IPA vocab shared across all 8 languages
(en/es/fr/hi/it/pt/ja/zh). Adding a language = feeding a G2P frontend whose
IPA output lands inside this token set.

Empirical finding (scripts/compare_engines.py over the PyThaiNLP corpus):
tltk.th2ipa's entire Thai inventory already lands in the shared vocab, EXCEPT:
  * it writes ɔ as U+1D10 'ᴐ'  -> normalize to U+0254 'ɔ' (already in vocab)
  * Thai has 5 lexical tones; the vocab has only 4 contour arrows (Kokoro uses
    them for Mandarin's 4 tones). So exactly ONE new token is needed, for the
    Thai LOW tone (no Mandarin analogue). The other 4 tones reuse the arrows,
    chosen by pitch-contour similarity to maximize weight transfer from zh.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

_CONFIG = os.path.join(os.path.dirname(__file__), "data", "kokoro_config.json")

# --- normalization: tltk symbol -> Kokoro vocab symbol ---
NORMALIZE = {"ᴐ": "ɔ"}  # U+1D10 -> U+0254

# --- tone design ---------------------------------------------------------
# tltk.th2ipa tone digit -> (Thai tone name, Kokoro token, Mandarin contour match)
#   1 mid     33   -> →  (zh T1 level)
#   2 low     21   -> ˩  (NEW: no Mandarin analogue)   U+02E9
#   3 falling 51   -> ↘  (zh T4 falling)
#   4 high    45   -> ↗  (zh T2 rising)
#   5 rising  214  -> ↓  (zh T3 dip-rise)
LOW_TONE_TOKEN = "˩"  # U+02E9 MODIFIER LETTER EXTRA-LOW TONE BAR (the one new token)
TONE_DIGIT_TO_TOKEN = {
    "1": "→",
    "2": LOW_TONE_TOKEN,
    "3": "↘",
    "4": "↗",
    "5": "↓",
}
# tokens we add on top of Kokoro's 114 (kept tiny on purpose):
NEW_TOKENS = [LOW_TONE_TOKEN]


@lru_cache(maxsize=1)
def get_vocab() -> dict:
    """Kokoro's original token(str) -> id(int)."""
    with open(_CONFIG, encoding="utf-8") as f:
        return json.load(f)["vocab"]


@lru_cache(maxsize=1)
def get_thai_vocab() -> dict:
    """Kokoro vocab EXTENDED with Thai's new token(s).

    Kokoro's embedding has n_token=178 rows but only 114 are used, so 64 ids are
    free. We map new Thai token(s) onto those FREE ids (id 0 is pad, so skip it).
    Result: the stock Kokoro weights run unchanged — Option A needs NO embedding
    resize. During Thai fine-tuning these rows simply get trained.
    """
    v = dict(get_vocab())
    n_token = _n_token()
    used = set(v.values())
    free = [i for i in range(1, n_token) if i not in used]  # skip 0 = pad
    for t in NEW_TOKENS:
        if t not in v:
            v[t] = free.pop(0)
    return v


@lru_cache(maxsize=1)
def _n_token() -> int:
    with open(_CONFIG, encoding="utf-8") as f:
        return json.load(f)["n_token"]


@lru_cache(maxsize=1)
def token_set() -> frozenset:
    return frozenset(get_vocab().keys())


def encode(phonemes: str, extended: bool = True) -> list:
    v = get_thai_vocab() if extended else get_vocab()
    return [v[c] for c in phonemes if c in v]


def oov(phonemes: str, extended: bool = True) -> list:
    v = get_thai_vocab() if extended else get_vocab()
    return [c for c in phonemes if c not in v and c != " "]


if __name__ == "__main__":
    base, ext = get_vocab(), get_thai_vocab()
    print(f"base vocab : {len(base)} tokens (max id {max(base.values())})")
    print(f"thai vocab : {len(ext)} tokens (+{len(ext)-len(base)} new: {NEW_TOKENS})")
