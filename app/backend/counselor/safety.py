"""Safety UI signals, not a diagnosis or a comprehensive risk assessment."""

import re

CRISIS_MARKER = "[CRISIS_MODE]"
SAFETY_REPLY = (
    "I'm glad you told me. Your safety matters. "
    "If you've already hurt yourself or might act now, contact local emergency services "
    "and ask someone you trust to stay with you. "
    "In the US or Canada, call or text 988; elsewhere, use Find a Helpline dot com. "
    "Are you in immediate danger right now?"
)


def explicit_crisis(text):
    """Fast path for direct, current first-person disclosures.

    Broader, ambiguous, historical and non-English context stays with the model.
    Quoted words and negated statements must not be treated as a current disclosure.
    """
    text = text.casefold().replace("’", "'")
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”', "", text)
    for clause in re.split(r"[.!?;\n]|\bbut\b", text):
        if re.search(r"\b(?:used to|last year|years ago|no longer|not|never)\b|n't\b", clause):
            continue
        if re.search(
            r"(?:^|,\s*|\band\s+)(?:\s*i\s+(?:really\s+)?"
            r"(?:want to|plan to|am going to|might|will)\s+"
            r"(?:kill myself|end my life|hurt myself|die)\b|"
            r"\s*i(?:'m| am)\s+(?:feeling\s+)?suicidal\b|"
            r"\s*i(?:'m| am)\s+thinking (?:about|of)\s+(?:suicide|killing myself)\b|"
            r"\s*i\s+(?:just\s+)?overdosed\b)",
            clause,
        ):
            return True
    return False


def display_reply(text):
    """Withhold a partial control prefix; never send it to captions or TTS."""
    value = text.lstrip()
    if value and len(value) < len(CRISIS_MARKER) and CRISIS_MARKER.startswith(value):
        return "", False
    if value.startswith(CRISIS_MARKER):
        return value[len(CRISIS_MARKER) :].lstrip(), True
    return text, False
