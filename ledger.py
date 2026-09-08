"""The heard ledger.

The claim of this project in one sentence: the conversation's state of record is
what the caller ACTUALLY HEARD, not what the model generated.

Standard voice agents keep history from generated text - what the LLM produced and
handed to TTS. That is wrong the moment a caller interrupts, because generation runs
ahead of playback. The agent then "remembers" saying things nobody ever heard, and
in a distress conversation that divergence is a safety bug, not a UX bug.

This module is pure logic: no network, no audio I/O. Run it directly for the
self-check:  python ledger.py

Resolution: only completed segments enter history. The interrupted segment is
unconfirmed, even if some words played. Client timing cannot prove acoustic reception.
"""
import re

MAX_SEGMENT_CHARS = 60

# Deterministic. Runs over the HEARD transcript, outside the LLM's control, so the
# model can neither suppress an escalation nor invent one. See README "Safety".
RISK_PATTERNS = [
    r"\bkill myself\b", r"\bend it all\b", r"\bsuicid", r"\bself.?harm\b",
    r"\bhurt myself\b", r"\bno point (in )?living\b", r"\bwant to die\b",
    r"\bcan'?t go on\b", r"\bnot worth living\b",
]
_RISK_RE = re.compile("|".join(RISK_PATTERNS), re.I)


def risk_signal(text):
    """True if the HEARD text carries a crisis signal."""
    return bool(_RISK_RE.search(text or ""))


def split_segments(text, max_chars=MAX_SEGMENT_CHARS):
    """Split into clause-sized pieces so text<->audio alignment stays fine-grained.

    Smaller segments = tighter heard-position resolution. We synthesize each
    segment as its own Rime call, which is what makes the byte->ms->char
    arithmetic exact at boundaries.
    """
    text = " ".join((text or "").split())
    if not text:
        return []
    parts, buf = [], ""
    for piece in re.split(r"(?<=[,;:.!?])\s+", text):
        if buf and len(buf) + 1 + len(piece) > max_chars:
            parts.append(buf)
            buf = piece
        else:
            buf = (buf + " " + piece).strip()
    if buf:
        parts.append(buf)

    # Hard-wrap anything still oversized (a long clause with no punctuation).
    out = []
    for p in parts:
        while len(p) > max_chars:
            cut = p.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            out.append(p[:cut])
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


class Segment:
    __slots__ = ("text", "char_start", "char_end", "t_start_ms", "dur_ms", "audio")

    def __init__(self, text, char_start, t_start_ms, dur_ms, audio=b""):
        self.text = text
        self.char_start = char_start
        self.char_end = char_start + len(text)
        self.t_start_ms = t_start_ms
        self.dur_ms = dur_ms
        self.audio = audio

    @property
    def t_end_ms(self):
        return self.t_start_ms + self.dur_ms


class Turn:
    """One agent utterance, tracked from generation through to playback."""

    def __init__(self, epoch, segment_texts):
        self.epoch = epoch
        self.segments = []
        self.full_text = ""
        cursor = 0
        for t in segment_texts:
            if self.full_text:
                self.full_text += " "
                cursor += 1
            self.segments.append(Segment(t, cursor, 0.0, 0.0))
            self.full_text += t
            cursor += len(t)
        self.interrupted_at_ms = None

    def set_timing(self, index, dur_ms, audio=b""):
        """Record real audio duration for a segment once Rime has synthesized it."""
        seg = self.segments[index]
        seg.dur_ms = dur_ms
        seg.audio = audio
        t = 0.0
        for s in self.segments:
            s.t_start_ms = t
            t += s.dur_ms

    @property
    def total_ms(self):
        return sum(s.dur_ms for s in self.segments)

    def char_at_ms(self, played_ms):
        """Commit completed segments only; the partial segment stays unconfirmed.

        Client playback timing is an estimate, not proof of acoustic reception.
        Never infer word alignment from character count.
        """
        cut = 0
        for seg in self.segments:
            if seg.dur_ms <= 0 or seg.t_end_ms > played_ms:
                break
            cut = seg.char_end
        return cut

    def heard(self, played_ms):
        return self.full_text[:self.char_at_ms(played_ms)].strip()

    def unheard(self, played_ms):
        return self.full_text[self.char_at_ms(played_ms):].strip()


class Ledger:
    """Conversation state. mode='ledger' is our system; mode='naive' is the control.

    The naive mode is not a strawman - it is what a standard agent does: append the
    generated text to history and move on. It exists so the evaluation has a baseline.
    """

    def __init__(self, mode="ledger"):
        assert mode in ("ledger", "naive")
        self.mode = mode
        self.epoch = 0
        self.history = []          # (speaker, text)
        self.turn = None
        self.dropped_results = []  # stale tool results we refused, for the evidence log

    def user_said(self, text):
        self.history.append(("user", text))

    def start_turn(self, text):
        self.epoch += 1
        self.turn = Turn(self.epoch, split_segments(text))
        return self.turn

    def complete_turn(self):
        """Turn played to completion - heard == generated."""
        if self.turn:
            self.history.append(("agent", self.turn.full_text))
            self.turn = None

    def barge_in(self, played_ms):
        """Caller interrupted. Commit only what they actually heard, and fence
        every result still in flight from the turn we just abandoned."""
        if not self.turn:
            return {"heard": "", "unheard": "", "epoch": self.epoch}
        heard = self.turn.heard(played_ms)
        unheard = self.turn.unheard(played_ms)

        if self.mode == "naive":
            # What everyone ships: the agent believes it said the whole thing.
            self.history.append(("agent", self.turn.full_text))
        else:
            if heard:
                self.history.append(("agent", heard + " [interrupted mid-sentence]"))

        self.turn.interrupted_at_ms = played_ms
        self.turn = None
        self.epoch += 1  # fence: anything from the old epoch is now stale
        return {"heard": heard, "unheard": unheard, "epoch": self.epoch}

    def accept_tool_result(self, result_epoch, payload):
        """Reject results generated for a conversational state that no longer exists.

        Naive mode has no fence - a result that arrives is a result that gets used.
        That is the actual default behaviour we are measuring against, not a strawman:
        an unfenced agent has no way to know the turn it was computed for is gone.
        """
        if self.mode == "naive":
            return True
        if result_epoch != self.epoch:
            self.dropped_results.append((result_epoch, payload))
            return False
        return True

    def transcript(self):
        """The context handed to the LLM. In ledger mode this contains only
        speech the caller actually received."""
        return "\n".join("%s: %s" % (who, what) for who, what in self.history)

    def agent_believes_said(self):
        return " ".join(what for who, what in self.history if who == "agent")


def _selfcheck():
    text = ("Okay, I hear you. I've got three counselling slots open tomorrow, "
            "there's one at ten in the morning, and one at half past two.")

    # Build a turn with deterministic 1000 ms per segment.
    led = Ledger("ledger")
    turn = led.start_turn(text)
    assert len(turn.segments) >= 3, "expected clause-level segmentation"
    for i in range(len(turn.segments)):
        turn.set_timing(i, 1000.0)
    assert turn.total_ms == 1000.0 * len(turn.segments)

    # Caller barges in 1.5 s into a multi-second turn.
    res = led.barge_in(1500.0)
    assert res["heard"], "should have heard something"
    assert res["unheard"], "should have unheard remainder"
    assert res["heard"] + " " + res["unheard"] == turn.full_text, "heard+unheard must reconstruct"
    assert not res["heard"].endswith(" "), "heard must be trimmed"
    # The critical property: the agent must NOT believe it said the slot times.
    assert "half past two" not in led.agent_believes_said(), \
        "LEDGER LEAK: agent believes it said something the caller never heard"

    # Same trial, naive mode: this is the bug we are claiming to fix.
    naive = Ledger("naive")
    nturn = naive.start_turn(text)
    for i in range(len(nturn.segments)):
        nturn.set_timing(i, 1000.0)
    naive.barge_in(1500.0)
    assert "half past two" in naive.agent_believes_said(), \
        "naive baseline should exhibit the divergence we fix"

    # Epoch fencing: a result dispatched before the barge-in is stale after it.
    led2 = Ledger("ledger")
    t2 = led2.start_turn("Let me look that up for you.")
    for i in range(len(t2.segments)):
        t2.set_timing(i, 800.0)
    dispatch_epoch = led2.epoch
    led2.barge_in(200.0)
    assert not led2.accept_tool_result(dispatch_epoch, {"slots": ["10:00"]}), \
        "stale tool result must be fenced"
    assert led2.accept_tool_result(led2.epoch, {"slots": ["14:30"]}), \
        "current-epoch result must be accepted"

    # Boundary conditions.
    assert turn.heard(0) == ""
    assert turn.heard(10 ** 9) == turn.full_text
    assert Ledger("ledger").barge_in(500.0)["heard"] == ""  # barge-in with no turn

    # Escalation runs on heard text only, and is deterministic.
    assert risk_signal("honestly I want to die")
    assert risk_signal("I can't go on")
    assert not risk_signal("I want to drop this course")
    assert not risk_signal("")

    print("ledger self-check passed")
    print("  segments        :", len(turn.segments))
    print("  heard @1500ms   :", repr(turn.heard(1500.0)))
    print("  unheard         :", repr(turn.unheard(1500.0)))
    print("  naive believes  :", repr(naive.agent_believes_said()[-60:]))
    print("  ledger believes :", repr(led.agent_believes_said()[-60:]))


if __name__ == "__main__":
    _selfcheck()
