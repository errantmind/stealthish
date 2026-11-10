"""Opaque references bound to the current snapshot and document."""
import re
import secrets

from .errors import StealthishError


class References:
    def __init__(self):
        self.values = {}

    def invalidate(self, tab):
        self.values.pop(tab, None)

    def snapshot(self, tab, text):
        table = {}

        def replace(match):
            ref = secrets.token_hex(16)
            table[ref] = match[1]
            return "[ref=" + ref + "]"

        output = re.sub(r"\[ref=([A-Za-z0-9_.-]+)\]", replace, text)
        self.values[tab] = table
        return output

    def resolve(self, tab, ref):
        if not isinstance(ref, str) or ref not in self.values.get(tab, {}):
            raise StealthishError("STALE_REFERENCE")
        return self.values[tab][ref]


def redact_fields(text):
    # Do not return current editable values in an observation. Labels and refs stay.
    # The driver emits these values after a colon or as a nested text item.
    lines, redact_indent = [], None
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        if redact_indent is not None and indent <= redact_indent:
            redact_indent = None
        if re.search(r"^- (textbox|searchbox|spinbutton|combobox)\b", line.lstrip()):
            line = re.sub(r'(:).*$', r'\1 [value omitted]', line)
            redact_indent = indent
        elif redact_indent is not None:
            line = " " * indent + "- [value omitted]"
        lines.append(line)
    return "\n".join(lines)
