"""Conversation pacing signals, without inferring a diagnosis or a user's emotions."""

import re


def words(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def is_voice_fragment(text):
    # Deliberately narrow: never discard 'no', 'yes', 'help', or substantive
    # unfinished disclosures. These exact fillers ask for space to continue.
    return words(text) in {"like", "um", "uh", "erm", "well", "so", "i mean", "you know", "hmm"}


def connection_reply(history, mode):
    if mode != "live" or not history or history[-1]["role"] != "user":
        return None
    latest = words(history[-1]["content"])
    if re.fullmatch(
        r"(?:(?:hello|hey|hi) )?(?:can i )?(?:can|could|do) you (?:hear|listen) me(?: now)?",
        latest,
    ) or latest in {"am i audible", "is my microphone working", "is my mic working"}:
        # Receipt of a final transcript supports this acknowledgement; it says
        # nothing about audio quality, emotion, or the user's physical presence.
        return "Yes, your words are coming through. Take your time."
    return None


def pacing_guidance(history):
    recent = [m["content"] for m in history if m["role"] == "assistant"][-3:]
    if sum("?" in text for text in recent) >= 2:
        return (
            "Recent replies have already asked several questions. Prefer a direct answer, "
            "a specific reflection or a brief summary now. Ask another question only if "
            "needed for immediate safety or to answer an explicit request accurately."
        )
    return ""
