"""Conservative fixture grammar; live interpretation uses a streaming text model.

No fuzzy item matching at the consequential boundary. Explicit confirmations must
contain the item's exact name/alias and quantity, independent of model assertions.
"""

import re

from pickmate.domain.models import Intent
from pydantic import ValidationError

NUMBERS = dict(
    zip(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(),
        range(21),
    )
)


def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\- ]", " ", text.lower())).strip()


def quantity(text):
    for word in normalize(text).split():
        if word in NUMBERS:
            return NUMBERS[word]
        if re.fullmatch(r"-?\d+", word):
            return int(word)
    return None


def resolve(query, items):
    q = normalize(query)
    exact = [
        i for i in items if q in [normalize(i["sku"]), normalize(i["name"]), *map(normalize, i["aliases"])]
    ]
    if len(exact) == 1:
        return exact[0]
    tokens = set(q.split())
    matches = [i for i in items if tokens and tokens <= set(normalize(i["name"]).split())]
    return matches[0] if len(matches) == 1 else None


def fixture_intent(text, task=None):
    t = normalize(text)
    if t in ("", "uh", "um", "mhm", "uh huh", "okay", "ok", "thanks"):
        return Intent(action="backchannel")
    if t in ("pause", "pause session"):
        return Intent(action="pause")
    if t in ("resume", "resume session"):
        return Intent(action="resume")
    if t in ("cancel", "cancel this pick", "cancel the pick", "no"):
        return Intent(action="cancel")
    if t in ("yes", "yes please", "confirm"):
        return Intent(action="confirm")
    if t in ("i picked them", "picked them", "i picked it", "done", "finished"):
        return Intent(action="complete")
    if any(x in t for x in ("repeat", "location", "what are we picking", "status", "where")):
        return Intent(action="status")
    if any(x in t.split() for x in ("maybe", "perhaps", "negative", "not")):
        return Intent(action="clarify")
    q = quantity(t)
    query = re.sub(r"^(wait\s+)?(find|pick|make that|make it|change to|confirm)\s+", "", t)
    query = re.sub(r"^(?:-?\d+|" + "|".join(NUMBERS) + r")\s*", "", query).strip()
    if not query and task:
        query = task["item"]["name"]
    try:
        return Intent(
            action="confirm" if t.startswith("confirm ") else "request",
            query=query or None,
            quantity=q,
            explicit=t.startswith("confirm "),
        )
    except ValidationError:
        return Intent(action="clarify")


def exact_confirmation(text, item, count):
    t = normalize(text)
    if not t.startswith("confirm ") or quantity(t) != count:
        return False
    rest = re.sub(r"^(?:-?\d+|" + "|".join(NUMBERS) + r")\s+", "", t[8:])
    return rest in [normalize(item["name"]), *map(normalize, item["aliases"])]


def speaking_bin(location):
    aisle, number = location.split("-")
    return f"aisle {aisle}, bin {int(number)}"
