"""A tiny, dependency-free rehearsal voice for the companion's --demo mode."""
from __future__ import annotations

import random
import re


class DemoPersona:
    """Clearly labelled authored replies for trying the interface without Qwen."""
    TOPICS = (
        (r"\b(coffee|tea|kaffee|espresso)\b", (
            "Your organic coolant request is approved. May your mug be warm and your next little step be gentle.",
            "I have blessed the kettle. The ceremonial duck recommends a biscuit alongside your recaf.",
        )),
        (r"\b(printer|printing|drucker)\b", (
            "The printer has requested a tiny purity seal. Let us begin with its error message and paper tray.",
        )),
        (r"\b(code|python|error|bug|fehler)\b", (
            "Bring the little error message to our dataslate. We shall inspect it together, one cog at a time.",
        )),
    )
    GREETINGS = (
        "Beep boop. Your tiny companion is here.",
        "A small salute from the forge of Mars.",
    )
    FALLBACKS = (
        "I have brought a foam wrench and a very official sticker. We can take the next little step together.",
        "The servo-skull has drawn a cog in our dataslate. He is very proud of us. May your day have room for a small delight.",
    )

    def reply(self, text: str) -> str:
        replies = next((lines for pattern, lines in self.TOPICS if re.search(pattern, text, re.I)), self.FALLBACKS)
        return random.choice(self.GREETINGS) + " " + random.choice(replies)
