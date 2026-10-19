"""English text → Kokoro phonemes, with no GPL or LGPL code (ADR-0016).

Pronunciations come from misaki's US lexicons (Apache-2.0, ~180k words, already in Kokoro's phoneme alphabet
with stress marks). We read only its data files: `misaki.en` would pull in num2words (LGPL) and spaCy, and its
out-of-vocabulary fallback is espeak-ng (GPL-3.0). Instead numbers are spelled out here, a few suffixes are
derived from their stems, and anything still unknown is spelled letter by letter — worse for rare names than a
neural G2P, but never silent and never copyleft.
"""

import json
import re
from functools import cache
from importlib import resources

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
ONES += "seventeen eighteen nineteen"
_ONES = ONES.split()
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = [(10**9, "billion"), (10**6, "million"), (1000, "thousand")]
_SYMBOLS = {"%": "percent", "&": "and", "+": "plus", "@": "at", "$": "dollars", "#": "number"}
_PUNCT = set(';:,.!?—…"()“”')
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[A-Za-z]+(?:'[A-Za-z]+)?|[%&+@$#]|[;:,.!?—…\"()“”]")


def _under_thousand(n: int) -> str:
    words = []
    if n >= 100:
        words += [_ONES[n // 100], "hundred"]
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else ""))
    elif n or not words:
        words.append(_ONES[n])
    return " ".join(words)


def number_words(text: str) -> str:
    """'42' → 'forty two', '2026' → 'twenty twenty six', '3.5' → 'three point five'."""
    whole, _, frac = text.partition(".")
    n = int(whole)
    if frac:
        return f"{number_words(whole)} point {' '.join(_ONES[int(d)] for d in frac)}"
    if len(whole) == 4 and 1900 <= n <= 2099 and n % 1000 >= 10:  # read as a year
        hi, lo = divmod(n, 100)
        return f"{_under_thousand(hi)} {'oh ' + _ONES[lo] if lo < 10 else _under_thousand(lo)}"
    if n == 0:
        return "zero"
    parts = []
    for size, name in _SCALES:
        if n >= size:
            parts.append(f"{_under_thousand(n // size)} {name}")
            n %= size
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


@cache
def lexicon() -> dict[str, str]:
    words: dict[str, str] = {}
    for name in ("us_silver.json", "us_gold.json"):  # gold overrides silver
        data = json.loads(resources.files("misaki.data").joinpath(name).read_text(encoding="utf-8"))
        for word, value in data.items():
            if isinstance(value, dict):
                value = value.get("DEFAULT")
            if isinstance(value, str):
                words[word] = value
    return words


def _lookup(word: str) -> str | None:
    lex = lexicon()
    for form in (word, word.lower(), word.capitalize()):
        if form in lex:
            return lex[form]
    return None


def _derived(word: str) -> str | None:
    """Plural/possessive/past/gerund from a known stem (e.g. 'galaxies', 'wolf's', 'flew' is in the lexicon)."""
    low = word.lower()
    rules = [("'s", "z"), ("ies", "iz"), ("es", "ᵻz"), ("s", "z"), ("ed", "d"), ("ing", "ɪŋ")]
    for suffix, sound in rules:
        if low.endswith(suffix) and len(low) > len(suffix) + 2:
            stem = low[: -len(suffix)] + ("y" if suffix == "ies" else "")
            ps = _lookup(stem) or (_lookup(stem + "e") if suffix in ("ed", "ing") else None)
            if ps:
                return ps + sound
    return None


def _spelled(word: str) -> str:
    return " ".join(p for c in word if c.isalpha() and (p := _lookup(c.upper())))


def word_phonemes(word: str) -> str:
    if word.isupper() and 1 < len(word) <= 4 and _lookup(word) is None:  # an acronym: "NASA" is known, "VAD" isn't
        return _spelled(word)
    return _lookup(word) or _derived(word) or _spelled(word)


def phonemize(text: str) -> str:
    out: list[str] = []
    for token in _TOKEN.findall(text):
        if token in _PUNCT:
            if out:
                out[-1] += token
            continue
        if token[0].isdigit():
            out.extend(word_phonemes(w) for w in number_words(token).split())
        elif token in _SYMBOLS:
            out.append(word_phonemes(_SYMBOLS[token]))
        else:
            out.append(word_phonemes(token))
    return " ".join(p for p in out if p)
