"""Text normalization that MUST run before tltk.th2ipa.

Two jobs:
  1) Fix what tltk mangles (numbers, ฿, abbreviations, ฯ, ๆ) — see audit_tltk.py.
  2) Handle every SYMBOL deliberately so nothing meaning-bearing is silently
     ignored:
       * meaning-bearing symbols  -> SPOKEN Thai words   (%, +, =, °, ×, >, $, ½…)
       * prosodic punctuation     -> kept / folded to Kokoro's punct tokens
       * formatting / emoji / foreign-script -> dropped, but RECORDED (pass a set
         to `dropped=`) so the coverage harness can prove drops are all non-lexical.

`dropped` is optional so the production caller (g2p.normalize_text(text)) is
unaffected; only the harness passes it.

Embedded ENGLISH words are NOT handled here: they pass through untouched (bar the
accent fold below) and g2p's segmenter hands them to misaki-en.
"""
from __future__ import annotations

import re
import unicodedata as ud

from pythainlp.util import maiyamok, num_to_thaiword, thai_digit_to_arabic_digit

# ---------- fixed word expansions (longest first) ----------
ABBREV = {
    "ม.ค.": "มกราคม", "ก.พ.": "กุมภาพันธ์", "มี.ค.": "มีนาคม", "เม.ย.": "เมษายน",
    "พ.ค.": "พฤษภาคม", "มิ.ย.": "มิถุนายน", "ก.ค.": "กรกฎาคม", "ส.ค.": "สิงหาคม",
    "ก.ย.": "กันยายน", "ต.ค.": "ตุลาคม", "พ.ย.": "พฤศจิกายน", "ธ.ค.": "ธันวาคม",
    "พ.ศ.": "พุทธศักราช", "ค.ศ.": "คริสต์ศักราช",
    "กทม.": "กรุงเทพมหานคร", "ดร.": "ด็อกเตอร์", "น.ส.": "นางสาว",
    "โทร.": "โทรศัพท์", "จ.": "จังหวัด", "อ.": "อำเภอ", "ต.": "ตำบล",
    "ฯลฯ": "และอื่นๆ", "กรุงเทพฯ": "กรุงเทพมหานคร",
}

# ---------- meaning-bearing symbols -> spoken Thai ----------
SYMBOL_WORDS = {
    "%": "เปอร์เซ็นต์", "＋": "บวก", "+": "บวก", "=": "เท่ากับ", "≈": "ประมาณ",
    "~": "ประมาณ", "≠": "ไม่เท่ากับ", "≥": "มากกว่าหรือเท่ากับ",
    "≤": "น้อยกว่าหรือเท่ากับ", ">": "มากกว่า", "<": "น้อยกว่า",
    "×": "คูณ", "÷": "หาร", "±": "บวกลบ", "°": "องศา", "§": "มาตรา",
    "∞": "อนันต์", "∆": "เดลตา", "&": "และ", "@": "แอท", "#": "แฮชแท็ก",
    "½": "เศษหนึ่งส่วนสอง", "¼": "เศษหนึ่งส่วนสี่", "¾": "เศษสามส่วนสี่",
    "⅓": "เศษหนึ่งส่วนสาม", "⅔": "เศษสองส่วนสาม",
    "²": "กำลังสอง", "³": "กำลังสาม",   # superscripts (m² etc.)
}
# currency symbol -> spoken unit (number placed before it)
CURRENCY = {"฿": "บาท", "$": "ดอลลาร์", "€": "ยูโร", "£": "ปอนด์", "¥": "เยน", "₩": "วอน"}

# ---------- prosodic punctuation kept (folded to Kokoro's vocab tokens) ----------
KEEP_PUNCT = set(' ;:,.!?—…"()“”')
PUNCT_MAP = {
    "–": "—", "―": "—", "‒": "—", "⎯": "—", "-": " ",   # dashes/hyphen -> em-dash / pause
    "«": '"', "»": '"', "„": '"', "‟": '"', "❝": '"', "❞": '"', "″": '"', "′": "'",
    "‘": "", "’": "", "`": "", "´": "", "'": "",          # stray single quotes -> drop
    "、": ",", "，": ",", "。": ".", "｡": ".", "．": ".",   # CJK / fullwidth
    "（": "(", "）": ")", "［": "(", "］": ")", "[": "(", "]": ")",
    "{": "(", "}": ")", "〈": "(", "〉": ")", "⌈": "(", "⌋": ")",
    "•": " ", "●": " ", "▪": " ", "◦": " ", "►": " ", "▶": " ", "★": " ",
    "♦": " ", "◆": " ", "·": " ", "‧": " ", "⦁": " ", "⧫": " ", "*": " ", "|": " ",
    # non-lexical ASCII / technical marks -> pause (no standard spoken form)
    "\\": " ", "_": " ", "^": " ", "¬": " ", "†": " ", "‡": " ", "¤": " ", "¯": " ",
    "□": " ", "■": " ",
    # arrows (structural "leads to"/bullets) -> pause
    "→": " ", "←": " ", "↑": " ", "↓": " ", "↔": " ", "⇒": " ", "⇐": " ",
    "⇔": " ", "➡": " ", "➔": " ", "➜": " ", "⟶": " ",
    "‼": "!", "⁉": "?", "‽": "?",       # doubled/variant terminals
}
# circled / dingbat number "bullets" (①②…, ❶❷…, ➀➁…, ➊➋…) -> pause (list markers)
for _lo, _hi in ((0x2460, 0x2473), (0x2776, 0x277F), (0x2780, 0x2789), (0x278A, 0x2793)):
    for _cp in range(_lo, _hi + 1):
        PUNCT_MAP[chr(_cp)] = " "

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_RANGE = re.compile(r"(\d)\s*[-–—]\s*(\d)")
_CUR = re.compile(r"([" + "".join(map(re.escape, CURRENCY)) + r"])\s*(\d[\d,]*(?:\.\d+)?)")


def _digits_to_words(m: re.Match) -> str:
    s = m.group(0).replace(",", "")
    if "." in s:
        intp, frac = s.split(".", 1)
        head = num_to_thaiword(int(intp)) if intp else ""
        return head + "จุด" + "".join(num_to_thaiword(int(d)) for d in frac)
    try:
        return num_to_thaiword(int(s))
    except Exception:
        return s


def _fold_latin(text: str) -> str:
    """Fold accented LATIN letters to ASCII (é->e, café->cafe, Ú->U) so they reach
    misaki-en instead of being dropped. Leaves Thai (and its combining marks!) and
    every other script untouched — we must NOT blanket-strip Mn, since Thai vowels
    and tones ARE Mn."""
    out = []
    for c in text:
        if c.isascii() or not c.isalpha():
            out.append(c)
            continue
        try:
            nm = ud.name(c)
        except ValueError:
            out.append(c)
            continue
        if nm.startswith("LATIN"):
            d = ud.normalize("NFKD", c)
            out.append("".join(ch for ch in d if not ud.combining(ch)))
        else:
            out.append(c)
    return "".join(out)


# Thai internet laughter: 555 = "ห้าห้าห้า", not "ห้าร้อยห้าสิบห้า". But 555 บาท is a
# real price, so a following unit noun vetoes the reading. Ambiguity is irreducible
# here — "ได้ 555" could be either; laughter is the far more common intent online.
_UNITS = ("บาท", "คน", "ครั้ง", "ชิ้น", "ปี", "เดือน", "วัน", "เมตร", "กิโล", "กรัม",
          "ลิตร", "ชั่วโมง", "นาที", "เปอร์เซ็นต์", "อัน", "ตัว", "หน้า", "ล้าน", "แสน", "พัน")
_LAUGH = re.compile(r"(?<![0-9])5{3,}(?![0-9])(?!\s*(?:" + "|".join(_UNITS) + r"))")

# ---------- identifiers: digit STRINGS, not cardinals ----------
# `_digits_to_words` reads every run as a cardinal. That is right for a quantity and
# catastrophic for an identifier: `0643126660` came out as "six hundred forty-three
# million one hundred twenty-six thousand six hundred sixty". Measured against the 4,498
# human-authored readings in the NE tracker sheet (`ne_tracker score-verbalization`,
# 2026-07-24) the frontend agreed on 0% of phone numbers, account numbers, national IDs,
# card digits, CVCs, passports, chassis and postal codes.
#
# Every threshold below is measured over that sheet, not guessed:
#   * a leading zero is never a cardinal — 044, 0160, 0643126660
#   * every real grouped ID carries >= 3 groups (observed shapes: 1-4-5-2-1, 3-1-5-1,
#     3-1-5-3). 2-group patterns are adjacent quantities or a year range, so they are
#     left to `_RANGE`/`_NUM` — this is why `2020-2021` still reads as two years.
#   * bare runs of >= 6 digits are identifiers: run lengths in the sheet cluster at
#     1-5 (mixed) and then 9/10/13 (pure IDs), with nothing legitimate in between.
# A following unit noun still vetoes the reading — `_UNITS` already encodes "this is a
# quantity" for the 555-laughter rule, so `100000 บาท` stays a cardinal.
#
# Deliberately NOT handled: bare 3-4 digit identifiers (CVC 407, card 6666, service
# number 1690). They are formally identical to a price or a year, so they need a context
# cue rather than a shape rule; scoring them in isolation is not possible and the sheet
# gives no carrier. See `ne_tracker` for the residual.
_DIGIT_WORD = {str(d): num_to_thaiword(d) for d in range(10)}
# 5, not 4: at 4 a Buddhist year breaks (`ปี 2566` -> "สองห้าหกหก"). At 5 every observed
# year survives and postal codes — always 5 digits — read correctly. Measured on the sheet,
# 5 gains 139 rows over 6 and loses nothing.
_ID_MIN_DIGITS = 5
_ID_MIN_GROUPS = 3

# A quantity cue on either side vetoes the identifier reading. `_UNITS` above is the
# laughter rule's list and is deliberately left alone; this is the wider one, because
# `จำนวน 15000 หน่วย` misread while `หน่วย` was missing from it.
_QTY_UNITS = _UNITS + (
    "หน่วย", "ราย", "แห่ง", "เครื่อง", "คัน", "ใบ", "ที่นั่ง", "ห้อง", "ชั้น", "รอบ", "เท่า",
    "วินาที", "สัปดาห์", "กิโลเมตร", "กม.", "ตารางเมตร", "ตร.ม.", "ไร่", "องศา",
    "ดอลลาร์", "ยูโร", "เยน", "หยวน", "วอน", "ปอนด์", "ครัวเรือน", "จุด", "สตางค์",
)
_QTY_CUES = ("ราคา", "จำนวน", "มูลค่า", "ประมาณ", "กว่า", "ทั้งหมด", "รวม", "เพียง",
             "ราว", "ยอด", "เงิน", "ลด", "เพิ่ม")
# …and an identifier cue FORCES it, at any length. This is the only way a 3-4 digit
# identifier can be read correctly — `407` and `6666` are formally a price and a year, so
# shape alone can never resolve them; `CVC 407` and `บัตรลงท้าย 6666` can.
# NB: `เลขที่` is deliberately absent. A house number after it is a CARDINAL
# (`บ้านเลขที่ 34` = "สามสิบสี่"), and only the part after a slash is a digit string —
# see `read_house_numbers`. `บัญชี` already covers `เลขที่บัญชี`.
_ID_CUES = ("เบอร์", "โทร", "โทรศัพท์", "หมายเลข", "รหัส", "บัญชี", "ลงท้าย",
            "บัตรประชาชน", "ประจำตัว", "ทะเบียน", "พาสปอร์ต", "หนังสือเดินทาง",
            "ไปรษณีย์", "ตู้ ป.ณ.", "CVC", "CVV", "PIN", "OTP")
# `สาขา` is NOT a cue: "มีสาขาแค่ 26" is a count of branches, not a branch number, and a
# real branch code carries a leading zero (`สาขา 0160`) which is already handled.

_QTY_AFTER = re.compile(r"\s*(?:" + "|".join(map(re.escape, _QTY_UNITS)) + r")")
_QTY_BEFORE = re.compile(r"(?:" + "|".join(map(re.escape, _QTY_CUES)) + r")\s*$")
# allow a few non-digit chars between the cue and the number ("บัตรเครดิตลงท้ายด้วย 6666")
_ID_BEFORE = re.compile(r"(?:" + "|".join(map(re.escape, _ID_CUES)) + r")[^\d]{0,6}$")
_HYPHENS = "-–—"
# `ขีด` is how the sheet reads the separator in an account/ID number. `_RANGE` would
# otherwise turn it into `ถึง` ("to"), which says the wrong thing entirely.
_SEP_WORD = "ขีด"

_ID_GROUPED = re.compile(
    r"(?<![\d.,])\d+(?:[" + _HYPHENS + r" ]\d+){" + str(_ID_MIN_GROUPS - 1) + r",}(?![\d.,])")
_ID_BARE = re.compile(r"(?<![\d.,])\d+(?![\d.,])")
_ID_SPLIT = re.compile(r"[" + _HYPHENS + r" ]")


def _spell_digits(run: str) -> str:
    """Digit words joined by SPACES, not concatenated.

    tltk re-segments whatever it is given, and `ศูนย์หกสี่` parses the ห of หก as a leading
    consonant on ก — `suːn↓ka˩siː˩`, so `0643…` would still have been mispronounced with
    the text now correct. Spaced, it reads `suːn↓ hok˩ siː˩`. The sheet writes these runs
    solid and `score_verbalization` compares despaced, so this costs nothing there.
    """
    return " ".join(_DIGIT_WORD[c] for c in run)


# ---------- Thai licence plates ----------
# A plate's consonants are read by their ACROPHONY — `ษร` is "ษ ฤๅษี ร เรือ", never the
# syllable "สอน". pythainlp's `thai_consonant_to_spelling` gives the letter-sound form
# (ษ -> "ษอ"), which is a different convention, so the table is here.
#
# The hazard is false positives: `รถ 500 คัน` is the same SHAPE as a plate. Two guards,
# and a cluster needs only one of them — a leading digit (`3ษร`, which no Thai word has)
# or absence from the pythainlp dictionary (`ษร`/`ยญ`/`งณ` are not words; `รถ`/`กก` are).
_CONSONANT_NAME = {
    "ก": "ไก่", "ข": "ไข่", "ฃ": "ขวด", "ค": "ควาย", "ฅ": "คน", "ฆ": "ระฆัง",
    "ง": "งู", "จ": "จาน", "ฉ": "ฉิ่ง", "ช": "ช้าง", "ซ": "โซ่", "ฌ": "เฌอ",
    "ญ": "หญิง", "ฎ": "ชฎา", "ฏ": "ปฏัก", "ฐ": "ฐาน", "ฑ": "มณโฑ", "ฒ": "ผู้เฒ่า",
    "ณ": "เณร", "ด": "เด็ก", "ต": "เต่า", "ถ": "ถุง", "ท": "ทหาร", "ธ": "ธง",
    "น": "หนู", "บ": "ใบไม้", "ป": "ปลา", "ผ": "ผึ้ง", "ฝ": "ฝา", "พ": "พาน",
    "ฟ": "ฟัน", "ภ": "สำเภา", "ม": "ม้า", "ย": "ยักษ์", "ร": "เรือ", "ล": "ลิง",
    "ว": "แหวน", "ศ": "ศาลา", "ษ": "ฤๅษี", "ส": "เสือ", "ห": "หีบ", "ฬ": "จุฬา",
    "อ": "อ่าง", "ฮ": "นกฮูก",
}
# not preceded by any Thai letter or mark => the cluster starts a token, so we cannot be
# looking at the tail of a longer word
# {2,3}, never a single consonant: all 850 plates in the sheet carry 2 or 3, while a lone
# consonant before a number is overwhelmingly the preposition ณ ("ณ 4/12/2019" was being
# read as "ณ เณร") or ฯ — and neither is in the dictionary, so the word veto cannot see it.
_PLATE = re.compile(r"(?<![ก-๎\d])(\d)?([ก-ฮ]{2,3})\s+(\d{1,4})(?![\d.,])")

_THAI_WORDS = None


def _is_thai_word(s: str) -> bool:
    global _THAI_WORDS
    if _THAI_WORDS is None:
        try:
            from pythainlp.corpus.common import thai_words
            _THAI_WORDS = set(thai_words())
        except Exception:                       # noqa: BLE001 — no dict: keep the digit guard
            _THAI_WORDS = set()
    return s in _THAI_WORDS


_PLATE_CUE = re.compile(r"(?:ทะเบียน|ป้ายทะเบียน|ป้าย)[^\d]{0,8}$")


def read_plates(text: str) -> str:
    """`3ษร 5090` -> `สาม ษ ฤๅษี ร เรือ ห้าศูนย์เก้าศูนย์`."""
    def _one(m: re.Match) -> str:
        lead, cons, num = m.group(1), m.group(2), m.group(3)
        # A cluster that is also a real word (`งก`, `นภ`, `ศศ`) is only a plate when
        # something says so — otherwise `รถ 500 คัน` would be spelled out letter by letter.
        if not lead and _is_thai_word(cons) and not _PLATE_CUE.search(text[:m.start()]):
            return m.group(0)                   # an ordinary word next to a quantity
        if any(c not in _CONSONANT_NAME for c in cons):
            return m.group(0)
        spelled = " ".join(f"{c} {_CONSONANT_NAME[c]}" for c in cons)
        head = f"{_DIGIT_WORD[lead]} " if lead else ""
        return f" {head}{spelled} {_spell_digits(num)} "

    return _PLATE.sub(_one, text)


# ---------- clock times ----------
# A bare colon survives into the phoneme string as punctuation, so `14:00 นาฬิกา` read as
# "สิบสี่: ศูนย์ศูนย์ นาฬิกา". The unit word also MOVES: `8:30 นาฬิกา` is spoken
# "แปดนาฬิกาสามสิบนาที", so the pattern has to consume a following นาฬิกา/น. and re-emit it
# between the hour and the minute.
_TIME = re.compile(
    r"(?<![\d.,])([01]?\d|2[0-3]):([0-5]\d)(?:\s*(?:นาฬิกา|น\.))?(?![\d.,])")


def read_times(text: str) -> str:
    def _one(m: re.Match) -> str:
        hh, mm = int(m.group(1)), int(m.group(2))
        out = f" {num_to_thaiword(hh)}นาฬิกา"
        if mm:
            out += f"{num_to_thaiword(mm)}นาที"
        return out + " "

    return _TIME.sub(_one, text)


# ---------- address house numbers ----------
# `บ้านเลขที่ 6/97` is "หกทับเก้าเจ็ด": the part after the slash is a digit STRING, while the
# part before it stays a cardinal (`287/104` -> "สองร้อยแปดสิบเจ็ดทับหนึ่งศูนย์สี่"). Gated on
# the เลขที่ cue because the same shape means something else elsewhere — the insurance plan
# `90/20` is "เก้าสิบทับยี่สิบ", both sides cardinal.
_HOUSE_NO = re.compile(r"((?:บ้าน|ห้อง)?เลขที่\s*)(\d+)/(\d+)")


def read_house_numbers(text: str) -> str:
    return _HOUSE_NO.sub(
        lambda m: f"{m.group(1)}{num_to_thaiword(int(m.group(2)))}ทับ{_spell_digits(m.group(3))} ",
        text)


def read_identifiers(text: str) -> str:
    """Rewrite identifier-shaped digit runs as digit strings, before `_NUM` reads them
    as cardinals. Quantities are left untouched for `_NUM`."""
    def _grouped(m: re.Match) -> str:
        parts = _ID_SPLIT.split(m.group(0))
        if len(parts) < _ID_MIN_GROUPS or not all(parts):
            return m.group(0)
        sep = f" {_SEP_WORD} " if any(c in m.group(0) for c in _HYPHENS) else " "
        return " " + sep.join(_spell_digits(p) for p in parts) + " "

    text = _ID_GROUPED.sub(_grouped, text)

    def _bare(m: re.Match) -> str:
        run, before = m.group(0), text[:m.start()]
        if _ID_BEFORE.search(before):            # an explicit cue wins at any length
            return " " + _spell_digits(run) + " "
        if not (len(run) > 1 and run[0] == "0"):
            if len(run) < _ID_MIN_DIGITS:
                return run
            if _QTY_AFTER.match(text, m.end()) or _QTY_BEFORE.search(before):
                return run                       # it is a quantity, not an identifier
        return " " + _spell_digits(run) + " "

    return _ID_BARE.sub(_bare, text)

# Chat-Thai elongation. tltk returns an EMPTY string for จ้าา and truncates มากกก to
# "มา", so these must be collapsed before it ever sees them.
#   vowels/tone marks: a doubled mark is never legal orthography -> collapse any run.
#   consonants: runs of 2 ARE legal across a syllable boundary (นกกระจอก, ธรรม, กรรมกร),
#              so only collapse runs of 3+.
_REPEAT_MARK = re.compile(r"([ะัาำิีึืุูเแโใไ็่้๊๋์])\1+")
_REPEAT_CONS = re.compile(r"([ก-ฮ])\1{2,}")


def collapse_repeats(text: str) -> str:
    text = _REPEAT_MARK.sub(lambda m: m.group(1), text)
    return _REPEAT_CONS.sub(lambda m: m.group(1), text)


def _is_formatting(c: str) -> bool:
    """True for chars it is correct to drop unspoken: control, format, private-use,
    surrogates, variation selectors, emoji/pictographs, non-Thai combining marks —
    AND letters from scripts we cannot voice (CJK/Japanese/Arabic/Devanagari/…):
    anything alphabetic that is neither Thai nor ASCII-Latin (accents already folded)."""
    if ud.category(c) in ("Cc", "Cf", "Co", "Cs", "Mn", "Mc", "Me", "Sk", "So"):
        return True
    if c.isalpha() and not ("฀" <= c <= "๿") and not c.isascii():
        return True  # unsupported script (no G2P) -> drop, but logged
    return ord(c) >= 0x1F000  # emoji planes


def normalize_text(text: str, dropped: set | None = None) -> str:
    text = thai_digit_to_arabic_digit(text)
    text = _LAUGH.sub(lambda m: "ห้า" * len(m.group(0)), text)   # 555 = laughter, not 555
    text = collapse_repeats(text)                     # จ้าา -> จ้า (tltk returns NOTHING for จ้าา)
    text = _fold_latin(text)                          # é->e so misaki-en handles it
    for k in sorted(ABBREV, key=len, reverse=True):
        text = text.replace(k, ABBREV[k])
    # shape-specific readings first: each consumes its own digits, so the generic
    # identifier/cardinal rules below never see them.
    text = read_plates(text)                              # 3ษร 5090 -> ษ ฤๅษี ร เรือ …
    text = read_times(text)                               # 8:30 นาฬิกา -> แปดนาฬิกาสามสิบนาที
    text = read_house_numbers(text)                       # เลขที่ 6/97 -> หกทับเก้าเจ็ด
    text = read_identifiers(text)                         # IDs -> digit strings, before
    text = _RANGE.sub(r"\1 ถึง \2", text)                 # 10-20 -> 10 ถึง 20  reads them
    text = _CUR.sub(lambda m: f" {m.group(2)} {CURRENCY[m.group(1)]} ", text)
    for sym, word in CURRENCY.items():
        text = text.replace(sym, f" {word} ")             # bare currency
    text = text.replace("/", " ทับ ")                     # slash -> "ทับ"
    for sym, word in SYMBOL_WORDS.items():
        if sym in text:
            text = text.replace(sym, f" {word} ")
    text = _NUM.sub(_digits_to_words, text)               # numbers -> Thai words
    text = "".join(maiyamok(text))                        # ๆ -> repeat previous word
    for k, v in PUNCT_MAP.items():                        # fold punctuation variants
        if k in text:
            text = text.replace(k, v)

    # final pass: keep Thai/Latin/space/kept-punct; drop the rest, but RECORD it
    out = []
    for c in text:
        if "฀" <= c <= "๿" or (c.isascii() and c.isalpha()) or c in KEEP_PUNCT:
            out.append(c)
        elif c.isspace():
            out.append(" ")
        elif dropped is not None:
            dropped.add(c)
    return re.sub(r"\s+", " ", "".join(out)).strip()
