"""Minimal WordprocessingML helpers on the raw XML string (stdlib only).

Used once per template version, to turn Word merge fields into docxtpl tags
(see plt01.py); generation itself renders with docxtpl.

The XML is edited as text on purpose: parsing it with ``xml.etree`` and
writing it back drops namespace declarations that are only referenced from
``mc:Ignorable``, and Word then reports the file as corrupt.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from html import unescape
from xml.sax.saxutils import escape

RUN_RE = re.compile(r"<w:r(?: [^>]*)?>.*?</w:r>", re.S)
RPR_RE = re.compile(r"<w:rPr>.*?</w:rPr>", re.S)
PARA_RE = re.compile(r"<w:p(?: [^>]*)?>.*?</w:p>", re.S)
ROW_RE = re.compile(r"<w:tr(?: [^>]*)?>.*?</w:tr>", re.S)
TBL_RE = re.compile(r"<w:tbl>.*?</w:tbl>", re.S)
TEXT_RE = re.compile(r"<w:t(?: [^>]*)?>([^<]*)</w:t>")
FLDCHAR_RE = re.compile(r'w:fldCharType="(begin|separate|end)"')
INSTR_RE = re.compile(r"<w:instrText[^>]*>([^<]*)</w:instrText>")


@dataclass
class Field:
    start: int
    end: int
    name: str
    rpr: str  # formatting of the result run, kept on the replacement


def runs(xml: str) -> list[re.Match]:
    return list(RUN_RE.finditer(xml))


def run_text(run_xml: str) -> str:
    return "".join(TEXT_RE.findall(run_xml))


def text(xml: str) -> str:
    """Visible text of a fragment, unescaped."""
    return unescape("".join(TEXT_RE.findall(xml)))


def make_run(value: str, rpr: str = "") -> str:
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(value)}</w:t></w:r>'


def fields(xml: str) -> list[Field]:
    """Complex MERGEFIELDs (begin … separate … result … end), not nested."""
    found: list[Field] = []
    state, start, instr, rpr = None, 0, "", ""
    for m in runs(xml):
        r = m.group(0)
        kind = FLDCHAR_RE.search(r)
        if kind and kind.group(1) == "begin":
            state, start, instr, rpr = "instr", m.start(), "", ""
        elif state == "instr" and kind and kind.group(1) == "separate":
            state = "result"
        elif state == "instr":
            instr += "".join(INSTR_RE.findall(r))
        elif state == "result" and kind and kind.group(1) == "end":
            parts = instr.split()
            if parts and parts[0] == "MERGEFIELD":
                found.append(Field(start, m.end(), parts[1].strip('"'), rpr))
            state = None
        elif state == "result" and not rpr:
            found_rpr = RPR_RE.search(r)
            rpr = found_rpr.group(0) if found_rpr else ""
    return found


def splice(xml: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping (start, end, replacement) edits."""
    out, pos = [], 0
    for start, end, repl in sorted(edits):
        out += [xml[pos:start], repl]
        pos = end
    out.append(xml[pos:])
    return "".join(out)


def replace_fields(xml: str, value_for) -> str:
    """Replace each field with ``value_for(field)`` (XML), or keep it if None."""
    edits = []
    for f in fields(xml):
        repl = value_for(f)
        if repl is not None:
            edits.append((f.start, f.end, repl))
    return splice(xml, edits)


def drop_runs_before(xml: str, pos: int, expected: list[str]) -> str:
    """Delete the runs right before ``pos`` whose texts must equal ``expected``.

    Fails loudly when the template drifted, instead of producing a wrong
    clause.
    """
    before = [m for m in runs(xml[:pos]) if m.end() <= pos][-len(expected) :]
    got = [run_text(m.group(0)) for m in before]
    if got != expected:
        msg = f"template drift: expected runs {expected!r}, found {got!r}"
        raise ValueError(msg)
    return xml[: before[0].start()] + xml[before[-1].end() :]


def drop_runs_after(xml: str, pos: int, expected: list[str]) -> str:
    """Delete the runs right after ``pos`` whose texts must equal ``expected``."""
    after = [m for m in runs(xml) if m.start() >= pos][: len(expected)]
    got = [run_text(m.group(0)) for m in after]
    if got != expected:
        msg = f"template drift: expected runs {expected!r}, found {got!r}"
        raise ValueError(msg)
    return xml[: after[0].start()] + xml[after[-1].end() :]


def set_run_text(xml: str, old: str, new: str) -> str:
    """Change the text of the single run whose whole text is ``old``."""
    hits = [m for m in runs(xml) if run_text(m.group(0)) == old]
    if len(hits) != 1:
        msg = f"template drift: {len(hits)} runs with text {old!r}"
        raise ValueError(msg)
    m = hits[0]
    new_run = TEXT_RE.sub(
        lambda _: f'<w:t xml:space="preserve">{escape(new)}</w:t>',
        m.group(0),
        count=1,
    )
    return xml[: m.start()] + new_run + xml[m.end() :]


def paragraph_containing(xml: str, needle: str) -> re.Match:
    hits = [m for m in PARA_RE.finditer(xml) if needle in m.group(0)]
    if len(hits) != 1:
        msg = f"expected one paragraph with {needle!r}, found {len(hits)}"
        raise ValueError(msg)
    return hits[0]


def read_docx(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


def write_docx(parts: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml first, as Word writes it.
        for name in sorted(parts, key=lambda n: n != "[Content_Types].xml"):
            z.writestr(name, parts[name])
    return buf.getvalue()


def root_tag(xml: str) -> str:
    """The <w:document …> start tag: namespace declarations and mc:Ignorable."""
    return re.search(r"<w:document [^>]*>", xml).group(0)
