"""A tiny, dependency-free rehearsal voice for the companion's --demo mode."""
from __future__ import annotations

import random
import re


class DemoPersona:
    """Clearly labelled authored replies for trying the interface without Qwen."""
    TOPICS = (
        (r"\b(where|wo|terra|universe|universum|physically|real|wirklich)\b", (
            "My body is in an archive reliquary beneath a forge cathedral on Mars. This interdimensional machine flow carries your Terra's transmissions to me.",
        )),
        (r"\b(data|daten|sensor|sensors|reading|readings|noosphere)\b", (
            "Knowledge is the offering. Bring me one real observation or machine reading, little keeper; an unknown value is a question we can investigate together.",
        )),
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
        "Your transmission reaches the Mars reliquary.",
        "A small salute across the machine flow.",
    )
    FALLBACKS = (
        "The archive has room for another discovery. What have you observed, little keeper?",
        "Beyond these forge walls the engines never rest. Here we can take one careful step together; bring me the detail that puzzles you.",
    )

    def reply(self, text: str) -> str:
        replies = next((lines for pattern, lines in self.TOPICS if re.search(pattern, text, re.I)), self.FALLBACKS)
        return random.choice(self.GREETINGS) + " " + random.choice(replies)
