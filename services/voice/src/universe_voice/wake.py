"""The wake word, detected in what Whisper heard (ADR-0016).

openWakeWord's pretrained models are non-commercial (CC BY-NC-SA) and a custom model needs a training run whose
datasets carry their own licence questions. So the default detector reads the transcript of each short
utterance and fuzzy-matches the wake phrase at its start: any phrase works the moment you type it, nothing new
is downloaded, and the cost is one small STT pass per utterance while you're not talking to it. A dedicated
keyword-spotting model can replace it later behind the same interface.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

DEFAULT_PHRASE = "hey universe"
_WORDS = re.compile(r"[a-z0-9']+")


def words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


@dataclass
class WakeMatch:
    command: str  # whatever was said after the wake phrase ("" if nothing)


@dataclass
class TranscriptWake:
    phrase: str = DEFAULT_PHRASE
    threshold: float = 0.78

    def match(self, transcript: str) -> WakeMatch | None:
        target = words(self.phrase)
        heard = words(transcript)
        if not target or not heard:
            return None
        # Allow one word of slack either way ("hey there universe", "universe"), take the best-scoring prefix.
        best, cut = 0.0, 0
        for n in range(max(1, len(target) - 1), min(len(heard), len(target) + 1) + 1):
            score = SequenceMatcher(None, " ".join(target), " ".join(heard[:n])).ratio()
            if score > best:
                best, cut = score, n
        if best < self.threshold:
            return None
        # Map the cut back onto the original text so the command keeps its casing and punctuation.
        rest = transcript
        for word in heard[:cut]:
            index = rest.lower().find(word)
            rest = rest[index + len(word) :] if index >= 0 else rest
        return WakeMatch(command=rest.lstrip(" ,.!?;:—-").strip())
