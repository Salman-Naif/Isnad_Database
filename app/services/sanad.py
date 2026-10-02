"""
Sanad (chain of narration) formatting.

ChromaDB doesn't accept nested lists as metadata values, so the sanad is stored
as a single string in the form:  "النبي ﷺ (المصدر) > أبو هريرة (صحابي) > ..."
This module converts it back and forth.
"""

import re

from app.models.schemas import Narrator

SEPARATOR = " > "
# "name (grade)" — the grade is the last parenthesized group
GRADED = re.compile(r"^(?P<name>.*)\((?P<grade>[^()]*)\)\s*$")


def serialize(narrators: list[Narrator]) -> str:
    """Convert a list of narrators into a single string suitable for metadata storage."""
    parts = []
    for n in narrators:
        parts.append(f"{n.name} ({n.grade})" if n.grade else n.name)
    return SEPARATOR.join(parts)


def parse(sanad_str: str) -> list[Narrator]:
    """Convert a stored sanad string into a displayable list of narrators."""
    narrators = []
    for part in sanad_str.split(SEPARATOR):
        part = part.strip()
        if not part:
            continue
        match = GRADED.match(part)
        if match:
            narrators.append(Narrator(name=match["name"].strip(), grade=match["grade"].strip()))
        else:
            narrators.append(Narrator(name=part))
    return narrators
