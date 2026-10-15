"""
The messages of a validation run (cwltool and schema-salad) as problems, each with the line it is about.

Pure Python, no Qt: the Problems panel and the marks in the editor are built from these.

cwltool prints a message as ``path:line:column: text``, with the continuation lines indented
below it, and the messages of one error nest: a ``checking ...`` location leads to the one that
says what is wrong, so only the innermost one is kept::

    ERROR Tool definition failed validation:
    file:///tmp/tool.cwl:4:1: checking field 'inputs'
    file:///tmp/tool.cwl:6:5:     Field 'type' references unknown identifier
                                  'strin', tried
"""
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class Problem:
    message: str
    line: int | None = None      # 1-based line of the validated document; None when the message names none
    column: int | None = None
    path: str | None = None      # the file the location names, as the validator printed it


SEVERITY = re.compile(r'^(?P<level>ERROR|WARNING|CRITICAL|INFO|DEBUG)\s+(?P<text>.*)$')
LOCATION = re.compile(r'^(?P<path>\S.*?):(?P<line>\d+):(?P<column>\d+):\s*(?P<text>.*)$')
BANNER = re.compile(r'^Tool definition failed validation:?$')     # the heading of the list of errors
QUIET_LEVELS = ('INFO', 'DEBUG')


@dataclass
class _Entry:
    level: str | None
    path: str | None = None
    line: int | None = None
    column: int | None = None
    lines: list[str] = field(default_factory=list)


def _entries(output: str) -> list[_Entry]:
    """Split the output into messages: a severity or a location starts one, indented lines continue it."""
    entries: list[_Entry] = []
    current: _Entry | None = None
    for raw in output.splitlines():
        if not raw.strip():
            current = None
            continue
        if raw[0].isspace() and current is not None:
            current.lines.append(raw.strip())
            continue
        text = raw.strip()
        level = None
        severity = SEVERITY.match(text)
        if severity:
            level, text = severity.group('level'), severity.group('text')
        location = LOCATION.match(text)
        if location:
            current = _Entry(level, location.group('path'), int(location.group('line')),
                             int(location.group('column')), [location.group('text')])
            entries.append(current)
        elif severity or current is None:
            current = _Entry(level, lines=[text])
            entries.append(current)
        else:
            current.lines.append(text)
    return entries


def _text(lines: list[str]) -> str:
    return ' '.join(' '.join(lines).split())


def _fileName(path: str) -> str:
    """The name of the file a location names (``file:`` URIs and plain paths alike)."""
    if '://' in path:
        path = unquote(urlparse(path).path)
    return path.replace('\\', '/').rsplit('/', 1)[-1]


def parseProblems(output: str, source: str | None = None) -> list[Problem]:
    """
    The problems in the output of a validation run.

    Args:
        output: what the validator printed (its stderr).
        source: the path of the document that was validated. A message that names another file keeps
            its text (with the file in front) but no line, so that nothing jumps to a wrong line.

    Returns:
        One problem per message, in the order of the output. A message without a location is a
        problem without a line. The heading of the list of errors is not a problem; if nothing else
        is left, the whole output is one problem, so that a failed run never shows an empty list.
    """
    entries = [entry for entry in _entries(output) if entry.level not in QUIET_LEVELS]
    kept = []
    for index, entry in enumerate(entries):
        message = _text(entry.lines)
        if entry.line is None and BANNER.match(message):
            continue
        followed_by_location = index + 1 < len(entries) and entries[index + 1].line is not None
        if entry.line is not None and message.startswith('checking ') and followed_by_location:
            continue            # the trail of the message that follows it
        kept.append(entry)

    source_name = _fileName(source) if source else None
    problems = [_problem(entry, source_name) for entry in kept]
    if not problems and entries:
        problems = [Problem(' '.join(_text(entry.lines) for entry in entries))]
    return problems


def _problem(entry: _Entry, source_name: str | None) -> Problem:
    message = _text(entry.lines)
    if entry.line is None:
        return Problem(message)
    if source_name is not None and _fileName(entry.path) != source_name:
        return Problem(f'{entry.path}:{entry.line}:{entry.column}: {message}', path=entry.path)
    return Problem(message, entry.line, entry.column, entry.path)
