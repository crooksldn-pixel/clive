"""How a name heard out loud is held against a name on an order.

Speech gives a name as it sounds, and a shop holds it as it was typed: "Alysa" said is Alicia,
Alcya, Alisya or Elissa written. The strict rule in app/tools/shopify_tools.py (`name_matches`)
is right for what it promises — a name that IS the name — and wrong for this, because it can only
say yes or no. This module says HOW LIKE, as a number between 0 and 1, with a word for why:

    exact      the same letters, case and accents aside ("zoe" and "Zoë")
    nickname   a name and its usual short form ("Kate" and "Katherine")
    sounds     the same sounds spelt differently ("Alysa" and "Alicia")
    spelt      close spellings that do not sound the same ("Alison" and "Alysa")
    initial    one letter that begins the name ("A." for Alicia)

What it never does is decide. A likeness is one fact among several (app/customers/match.py);
a name on its own is never enough to call an order his, however like it sounds.

The sound rules are a small, readable set for British and English-language names — soft "c"
before e, i and y is "s", "ph" is "f", "y" inside a word is "i", doubled letters are one, a
silent final "e" goes — and the key keeps the first sound (a vowel is any vowel, so "Elissa"
and "Alysa" share it) and the consonants after it. Nothing here is guessed from the shop's data.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Usual short forms, each group one name. Small and plain on purpose: a nickname table that
# knows every name makes every name like every other.
_NICKNAMES = (
    ("alex", "alexander", "alexandra", "alexa", "alexis", "lexi", "sandy"),
    ("abby", "abigail", "abi"),
    ("alfie", "alfred", "alf"),
    ("andy", "andrew", "drew"),
    ("becky", "rebecca", "becca", "bex"),
    ("ben", "benjamin", "benji", "benny"),
    ("beth", "elizabeth", "liz", "lizzie", "lizzy", "eliza", "libby", "betty"),
    ("bob", "robert", "rob", "robbie", "bobby", "bert"),
    ("cat", "catherine", "kate", "katie", "kathryn", "katherine", "kath", "kat", "cathy", "kathy"),
    ("charlie", "charles", "charlotte", "lottie", "chaz"),
    ("chris", "christopher", "christine", "christina", "kris", "christy"),
    ("dan", "daniel", "danny", "danielle", "dani"),
    ("ed", "edward", "eddie", "ted", "teddy", "ned"),
    ("ellie", "eleanor", "elle", "ella", "elena", "nell"),
    ("fred", "frederick", "freddie", "freddy"),
    ("georgie", "georgia", "george", "georgina"),
    ("harry", "henry", "hal", "hank"),
    ("izzy", "isabel", "isabella", "isobel", "isabelle", "bella"),
    ("jack", "john", "jon", "johnny", "jonathan", "jonny"),
    ("jamie", "james", "jim", "jimmy", "jamesy"),
    ("jess", "jessica", "jessie"),
    ("jo", "joanna", "joanne", "josephine", "jojo", "josie"),
    ("joe", "joseph", "joey"),
    ("josh", "joshua"),
    ("lou", "louise", "louisa", "louis", "lewis"),
    ("maddie", "madison", "madeleine", "madeline", "maddy"),
    ("matt", "matthew", "matty"),
    ("mike", "michael", "mick", "mikey", "micky"),
    ("millie", "amelia", "milly", "mia"),
    ("mo", "mohammed", "muhammad", "mohamed", "mohammad"),
    ("nat", "natalie", "nathan", "nathaniel", "natasha", "tash", "tasha"),
    ("nick", "nicholas", "nicky", "nicola", "nikki"),
    ("olly", "oliver", "ollie"),
    ("pat", "patrick", "patricia", "paddy", "trish"),
    ("rich", "richard", "rick", "ricky", "dick", "richie"),
    ("sam", "samuel", "samantha", "sammy", "sammie"),
    ("steve", "steven", "stephen", "stevie"),
    ("theo", "theodore", "ted"),
    ("tom", "thomas", "tommy"),
    ("tony", "anthony", "ant"),
    ("vic", "victoria", "vicky", "vikki", "tori"),
    ("will", "william", "bill", "billy", "liam", "willy"),
    ("zac", "zachary", "zack", "zak"),
)
NICKNAME_OF: dict[str, frozenset[int]] = {}
for _index, _group in enumerate(_NICKNAMES):
    for _name in _group:
        NICKNAME_OF[_name] = NICKNAME_OF.get(_name, frozenset()) | {_index}

# Words that are a title, not a name.
_TITLES = frozenset({"mr", "mrs", "ms", "miss", "mx", "dr", "sir", "madam"})
_VOWELS = frozenset("aeiou")

# How like two words must be to count, and below which they are said not to match. Between the
# two a name is "not sure": it adds a little, and is never what an answer rests on.
FITS = 0.78
DIFFERS = 0.6
# The vowels' likeness below which the same consonants are another name ("Ellis" for "Alicia",
# "Tim" for "Tom"), and the most such a word can score: not sure, never a fit.
VOWELS_FIT = 0.6
NOT_SURE = 0.7


def fold_letters(text: Any) -> str:
    """Letters only, lower case, accents set aside."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def tokens(text: Any) -> list[str]:
    """A name as its words, titles left out: "Mrs Zoë De-Witt" is ["zoe", "de", "witt"]."""
    return [w for w in re.split(r"[^a-z]+", fold_letters(text)) if w and w not in _TITLES]


def spelt(word: str) -> str:
    """The word as it sounds, written one way: the spelling differences speech cannot hear."""
    w = fold_letters(word)
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return ""
    w = re.sub(r"^kn", "n", w)
    w = re.sub(r"^wr", "r", w)
    w = w.replace("ph", "f").replace("ck", "k").replace("q", "k").replace("x", "ks").replace("z", "s")
    w = w.replace("th", "t")
    w = re.sub(r"c(?=[eiy])", "s", w)
    w = w.replace("c", "k")
    # "y" inside a word is a vowel ("Alysa"); at the front, before a vowel, it is a consonant.
    w = w[0] + w[1:].replace("y", "i") if len(w) > 1 else w
    # A final "e" after two consonants is silent ("Clarke", "Anne"). After one consonant that
    # follows a vowel it changes that vowel ("Jake" is not "Jack", "Mike" is not "Mick"), so it stays.
    if len(w) > 3 and w.endswith("e") and w[-2] not in _VOWELS and w[-3] not in _VOWELS:
        w = w[:-1]
    return re.sub(r"(.)\1+", r"\1", w)


def key(word: str) -> str:
    """The first sound and the consonants after it: "Alysa", "Alicia", "Alcya" and "Elissa"
    are all "als" — and so are "Ellis" and "Alice", which is why the vowels are held too
    (`vowels`, `word_likeness`)."""
    s = spelt(word)
    if not s:
        return ""
    first = "a" if s[0] in _VOWELS or s[0] == "y" and len(s) > 1 and s[1] not in _VOWELS else s[0]
    rest = [c for c in s[1:] if c not in _VOWELS and c not in "hwy"]
    out = first + "".join(rest)
    return re.sub(r"(.)\1+", r"\1", out)


def vowels(word: str) -> str:
    """The vowels of the word as it sounds, in order: "Alysa" is "aia", "Alicia" "aiia", "Ellis"
    "ei", "Tom" "o" and "Tim" "i"."""
    return "".join(c for c in spelt(word) if c in _VOWELS)


def jaro_winkler(a: str, b: str) -> float:
    """The Jaro-Winkler likeness of two strings, 0 to 1: kind to a shared beginning, which is
    where a misheard name is usually right."""
    if a == b:
        return 1.0 if a else 0.0
    if not a or not b:
        return 0.0
    reach = max(len(a), len(b)) // 2 - 1
    taken_b = [False] * len(b)
    matched_a: list[str] = []
    for i, ch in enumerate(a):
        for j in range(max(0, i - reach), min(len(b), i + reach + 1)):
            if not taken_b[j] and b[j] == ch:
                taken_b[j] = True
                matched_a.append(ch)
                break
    if not matched_a:
        return 0.0
    matched_b = [b[j] for j in range(len(b)) if taken_b[j]]
    transpositions = sum(1 for x, y in zip(matched_a, matched_b, strict=True) if x != y) / 2
    m = len(matched_a)
    jaro = (m / len(a) + m / len(b) + (m - transpositions) / m) / 3
    prefix = 0
    for x, y in zip(a, b, strict=False):
        if x != y or prefix == 4:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def edit_likeness(a: str, b: str) -> float:
    """1 less the share of the longer word that would have to change (Levenshtein)."""
    if not a or not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return 1.0 - previous[-1] / max(len(a), len(b))


def word_likeness(said: str, have: str) -> tuple[float, str]:
    """How like one word heard is one word of a name, and the word for why."""
    said, have = fold_letters(said), fold_letters(have)
    if not said or not have:
        return 0.0, ""
    if said == have:
        return 1.0, "exact"
    if NICKNAME_OF.get(said, frozenset()) & NICKNAME_OF.get(have, frozenset()):
        return 0.92, "nickname"
    if len(said) == 1:
        return (0.6, "initial") if have.startswith(said) else (0.0, "")
    s_spelt, h_spelt = spelt(said), spelt(have)
    if s_spelt and s_spelt == h_spelt:
        return 0.96, "sounds"
    s_key, h_key = key(said), key(have)
    same_key = s_key == h_key
    # The consonants carry most of a name, and speech blurs the vowels — but only so far:
    # "Alysa" heard is "Alicia" written (aia, aiia), while "Ellis" (ei), "Alice" (aie), "Tim"
    # for "Tom" and "Jack" for "Jake" share their consonants and are other names. A different
    # first sound is a different name far more often than a mishearing, so it costs a third.
    sound = 1.0 if same_key else edit_likeness(s_key, h_key)
    s_vowels, h_vowels = vowels(said), vowels(have)
    voiced = 1.0 if s_vowels == h_vowels else edit_likeness(s_vowels, h_vowels)
    score = 0.45 * sound + 0.35 * voiced + 0.2 * jaro_winkler(s_spelt, h_spelt)
    if s_key[:1] != h_key[:1]:
        score *= 0.7
    typo = edit_likeness(said, have)
    if typo >= 0.8 and voiced >= VOWELS_FIT:
        score = max(score, typo)
    if voiced < VOWELS_FIT:
        # Vowels this unlike are another name with the same consonants: never a full match.
        score = min(score, NOT_SURE)
    return round(min(score, 0.95), 3), "sounds" if same_key and voiced >= VOWELS_FIT else "spelt"


def name_likeness(said: Any, *names: Any) -> dict[str, Any]:
    """How like the name heard is the best of the names given (the customer's, the name on the
    parcel). Every word heard is paired with a different word of the name; a word with nothing
    to pair with counts as nothing. Run together, the letters may also be the same name ("De
    Witt", "Dewitt").

    Returns {"score": 0..1, "how": the weakest pairing's word, "name": the name it was held to,
    "exact": every word the same}."""
    heard = tokens(said)
    best: dict[str, Any] = {"score": 0.0, "how": "", "name": "", "exact": False}
    if not heard:
        return best
    for whole in names:
        have = tokens(whole)
        if not have:
            continue
        runs = {"".join(have[i:j]) for i in range(len(have)) for j in range(i + 1, len(have) + 1)}
        if "".join(heard) in runs:
            candidate = {"score": 1.0, "how": "exact", "name": str(whole), "exact": True}
        else:
            candidate = _paired(heard, have, str(whole))
        if candidate["score"] > best["score"]:
            best = candidate
    return best


def _paired(heard: list[str], have: list[str], whole: str) -> dict[str, Any]:
    """Each word heard with the most like unused word of the name, best pairs first."""
    pairs = sorted(((word_likeness(h, w), i, j) for i, h in enumerate(heard) for j, w in enumerate(have)),
                   key=lambda p: p[0][0], reverse=True)
    used_heard: set[int] = set()
    used_have: set[int] = set()
    scores: dict[int, tuple[float, str]] = {}
    for (score, how), i, j in pairs:
        if i in used_heard or j in used_have or score <= 0:
            continue
        used_heard.add(i)
        used_have.add(j)
        scores[i] = (score, how)
    values = [scores.get(i, (0.0, "")) for i in range(len(heard))]
    total = sum(v[0] for v in values) / len(heard)
    weakest = min(values, key=lambda v: v[0])[1] if values else ""
    return {"score": round(total, 3), "how": weakest, "name": whole,
            "exact": all(v[1] == "exact" for v in values)}


def heard_words(said: Any, likeness: dict[str, Any]) -> str:
    """The few words the owner reads beside a match: why the name counts, or that it does not."""
    heard = " ".join(str(said or "").split())
    score = float(likeness.get("score") or 0.0)
    if not heard:
        return ""
    if likeness.get("exact"):
        return ""
    if score >= FITS:
        return f"name heard as '{heard}'"
    if score >= DIFFERS:
        return f"name heard as '{heard}', not sure it is them"
    return f"the name is not '{heard}'"
