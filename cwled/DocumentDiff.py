"""
Comparing CWL documents.

A document is compared in a *canonical* form: whatever its source (a document
that is open, a file, a revision of the file in git), it is parsed by the same
parser as when it is opened, written as a dictionary and then as YAML in the
order the Code tab uses. Two documents that mean the same therefore give the
same text, and the differences that are left are real ones.

The comparison itself is in three parts:

* ``alignedLines``: the two texts side by side, line by line, padded where a
  side has no counterpart, which a viewer can show and scroll in step;
* ``structuralChanges``: what changed in the parts of the document: the
  inputs, outputs, steps, requirements and the other fields;
* ``stepStates``: which steps of a workflow were added, removed or changed.
"""
import difflib
import logging
import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from cwl_utils.parser import save
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

logger = logging.getLogger(__name__)

# The order of the fields in the Code tab (TabCodeEditor.CodeWindow.populateFromCWL)
TOP_ORDER = ['cwlVersion', 'class', 'id', 'label', 'doc', 'baseCommand', 'arguments', 'inputs', 'outputs',
             'steps', 'requirements', 'hints']
FIELD_ORDER = ['id', 'label', 'doc', 'type', 'in', 'out']
# Sections made of entries that have an id, and sections made of entries that have a class
BY_ID = ('inputs', 'outputs', 'steps')
BY_CLASS = ('requirements', 'hints')

# line kinds of the aligned texts
EQUAL, CHANGED, ADDED, REMOVED, PAD = 'equal', 'changed', 'added', 'removed', 'pad'


@dataclass
class DocumentSource:
    """One side of a comparison."""
    label: str                      # what the user sees: a file name, "Git: HEAD"...
    cwl: dict                       # the document as a dictionary
    window: Any = None              # the document, when it is one that is open
    detail: str = ''                # more about the source (path, commit)

    def text(self) -> str:
        return canonicalYaml(self.cwl)


@dataclass
class Line:
    text: str
    kind: str                       # EQUAL, CHANGED, ADDED, REMOVED or PAD (a gap, opposite a line)


@dataclass
class Change:
    """A difference in a part of the documents (see ``structuralChanges``)."""
    kind: str                       # ADDED, REMOVED or CHANGED
    section: str                    # inputs, outputs, steps, requirements, hints or the name of a field
    name: Optional[str] = None      # the id or class of the entry, None for a field
    row: int = 0                    # where to look in the aligned texts

    def describe(self) -> str:
        what = f"{self.section} {self.name}" if self.name else self.section
        return {ADDED: '+ ', REMOVED: '− ', CHANGED: '~ '}[self.kind] + what


# ---------------------------------------------------------------------------------------------
# canonical form
# ---------------------------------------------------------------------------------------------
def _literal(value):
    """Strings with several lines as YAML literal blocks, like the Code tab and the files."""
    if isinstance(value, dict):
        return {key: _literal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_literal(item) for item in value]
    if isinstance(value, str) and '\n' in value:
        return LiteralScalarString(value)
    return value


def canonicalDict(document: dict) -> dict:
    """The fields of a document in the order of the Code tab, and those of its inputs, outputs, steps and arguments."""
    ordered = dict(sorted(document.items(),
                          key=lambda item: TOP_ORDER.index(item[0]) if item[0] in TOP_ORDER else float('inf')))
    for key in ('inputs', 'outputs', 'steps', 'arguments'):
        if isinstance(ordered.get(key), list):
            ordered[key] = [
                dict(sorted(entry.items(),
                            key=lambda item: FIELD_ORDER.index(item[0]) if item[0] in FIELD_ORDER else float('inf')))
                if isinstance(entry, dict) else entry
                for entry in ordered[key]]
    return ordered


def canonicalYaml(document: dict) -> str:
    """The text of a document as the Code tab shows it."""
    yaml = YAML()
    yaml.preserve_quotes = False
    yaml.default_flow_style = False
    yaml.default_style = None
    yaml.width = 4096
    output = StringIO()
    yaml.dump(_literal(canonicalDict(document)), output)
    return output.getvalue()


def entryId(entry: Any) -> str:
    """The short id of an input, output or step; the class of a requirement or hint."""
    if not isinstance(entry, dict):
        return str(entry)
    value = entry.get('id', entry.get('class', ''))
    return str(value).split('#')[-1].split('/')[-1]


def localised(document: dict) -> dict:
    """
    The document without the address of its own file. The ids inside a document
    that was loaded from a file start with it (``file:///dir/wf.cwl#step/out``), so
    two documents in two files would differ everywhere. Its own ``id`` is dropped
    (it is the address) and in the others only the part from the ``#`` is kept.
    """
    own = document.get('id')
    if not isinstance(own, str) or '://' not in own:
        return document

    def strip(value):
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items()}
        if isinstance(value, list):
            return [strip(item) for item in value]
        if isinstance(value, str) and value.startswith(own + '#'):
            return value[len(own):]
        return value

    return strip({key: value for key, value in document.items() if key != 'id'})


# ---------------------------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------------------------
def sourceFromWindow(window) -> DocumentSource:
    """A document that is open, as it is now (with the changes that are not saved)."""
    label = Path(str(window.file_path)).name if getattr(window, 'file_path', None) else window.windowTitle()
    return DocumentSource(label, localised(save(window.getCWL(), relative_uris=True)), window=window,
                          detail=str(getattr(window, 'file_path', '') or ''))


def sourceFromFile(path, label: Optional[str] = None) -> DocumentSource:
    """A file, parsed as it is when it is opened."""
    from CWLparser import Parser
    path = Path(path)
    parser = Parser(path)
    return DocumentSource(label or path.name, localised(save(parser.getCWL(), relative_uris=True)), detail=str(path))


def _repository(path):
    from gitVersion import GitVersion
    return GitVersion(str(path))._open_repository()


def gitRevisions(path, limit: int = 8) -> List[Tuple[str, str]]:
    """
    The last revisions of a file in git, newest first, as (revision, description).
    Empty when the file is not in a git repository or has no history.
    """
    try:
        repository = _repository(path)
        relative = Path(path).resolve().relative_to(Path(repository.working_tree_dir).resolve())
        revisions = []
        for commit in repository.iter_commits(paths=str(relative), max_count=limit):
            revisions.append((commit.hexsha, f"{commit.hexsha[:7]} {commit.summary}"))
        return revisions
    except Exception as e:
        logger.debug(f"No git history for {path}: {e}")
        return []


def sourceFromGit(path, revision: str, description: Optional[str] = None) -> DocumentSource:
    """A file as it was in a revision of git."""
    from CWLparser import Parser
    repository = _repository(path)
    path = Path(path).resolve()
    relative = path.relative_to(Path(repository.working_tree_dir).resolve())
    blob = repository.commit(revision).tree / str(relative)
    text = blob.data_stream.read().decode('utf-8')
    parser = Parser('CommandLineTool')       # an empty document, to load the text into
    parser.loadString(text, path)
    label = f"{path.name} ({description or revision[:7]})"
    return DocumentSource(label, localised(save(parser.getCWL(), relative_uris=True)), detail=revision)


# ---------------------------------------------------------------------------------------------
# the comparison
# ---------------------------------------------------------------------------------------------
def alignedLines(left_text: str, right_text: str) -> Tuple[List[Line], List[Line]]:
    """
    The two texts line by line, side by side: the lines are the same in number, a
    line that has no counterpart is opposite a PAD line (a gap). Lines that differ
    are CHANGED when they face another line, REMOVED (left) or ADDED (right) when
    they face a gap.
    """
    left, right = left_text.splitlines(), right_text.splitlines()
    left_lines: List[Line] = []
    right_lines: List[Line] = []
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == 'equal':
            for text in left[a1:a2]:
                left_lines.append(Line(text, EQUAL))
                right_lines.append(Line(text, EQUAL))
            continue
        old, new = left[a1:a2], right[b1:b2]
        paired = min(len(old), len(new))
        for index in range(paired):
            left_lines.append(Line(old[index], CHANGED))
            right_lines.append(Line(new[index], CHANGED))
        for text in old[paired:]:
            left_lines.append(Line(text, REMOVED))
            right_lines.append(Line('', PAD))
        for text in new[paired:]:
            left_lines.append(Line('', PAD))
            right_lines.append(Line(text, ADDED))
    return left_lines, right_lines


def changeBlocks(lines: List[Line]) -> List[Tuple[int, int]]:
    """The runs of lines that differ, as (first row, last row)."""
    blocks = []
    start = None
    for row, line in enumerate(lines):
        if line.kind != EQUAL and start is None:
            start = row
        elif line.kind == EQUAL and start is not None:
            blocks.append((start, row - 1))
            start = None
    if start is not None:
        blocks.append((start, len(lines) - 1))
    return blocks


def _entries(document: dict, section: str) -> Dict[str, Any]:
    entries = document.get(section) or []
    if isinstance(entries, dict):        # id: type maps, in case the document was not normalised
        return {str(key): value for key, value in entries.items()}
    return {entryId(entry): entry for entry in entries}


def _find_row(lines: List[Line], section: str, name: Optional[str], by_class: bool = False) -> int:
    """The row of an entry (or of a section, or of a field) in a text."""
    key = 'class' if by_class else 'id'
    in_section = False
    section_row = 0
    for row, line in enumerate(lines):
        text = line.text
        if re.match(rf'^{re.escape(section)}\s*:', text):
            in_section, section_row = True, row
            if name is None:
                return row
            continue
        if in_section and text and not text[0].isspace() and not text.startswith('-'):
            in_section = False
        if in_section and name is not None:
            if re.match(rf'^\s*-?\s*{key}\s*:\s*[\'"]?(?:[^\'"\s]*[#/])?{re.escape(name)}[\'"]?\s*$', text):
                return row
    return section_row


def structuralChanges(left: dict, right: dict, left_lines: List[Line], right_lines: List[Line]) -> List[Change]:
    """
    What differs between two documents, by part: entries of the inputs, outputs
    and steps (by id) and of the requirements and hints (by class) that were added,
    removed or changed, and the other fields that changed. ``row`` tells where to
    look in the aligned texts.
    """
    changes: List[Change] = []
    sections = [key for key in TOP_ORDER if key in left or key in right]
    sections += sorted(key for key in set(left) | set(right) if key not in TOP_ORDER)
    for section in sections:
        old, new = left.get(section), right.get(section)
        if old == new:
            continue
        if section in BY_ID or section in BY_CLASS:
            old_entries, new_entries = _entries(left, section), _entries(right, section)
            by_class = section in BY_CLASS
            for name in sorted(set(old_entries) | set(new_entries), key=lambda n: (n not in new_entries, n)):
                if name not in old_entries:
                    changes.append(Change(ADDED, section, name, _find_row(right_lines, section, name, by_class)))
                elif name not in new_entries:
                    changes.append(Change(REMOVED, section, name, _find_row(left_lines, section, name, by_class)))
                elif old_entries[name] != new_entries[name]:
                    changes.append(Change(CHANGED, section, name, _find_row(right_lines, section, name, by_class)))
        else:
            row = _find_row(right_lines if new is not None else left_lines, section, None)
            kind = ADDED if old is None else REMOVED if new is None else CHANGED
            changes.append(Change(kind, section, None, row))
    return changes


def stepStates(left: dict, right: dict) -> Dict[str, Dict[str, str]]:
    """
    Which steps of two workflows differ: {'left': {step: state}, 'right': {step: state}}
    where the state is REMOVED (only in the left one), ADDED (only in the right one) or
    CHANGED (in both, different). Steps that are the same are not listed.
    """
    old, new = _entries(left, 'steps'), _entries(right, 'steps')
    states = {'left': {}, 'right': {}}
    for name in old:
        if name not in new:
            states['left'][name] = REMOVED
        elif old[name] != new[name]:
            states['left'][name] = states['right'][name] = CHANGED
    for name in new:
        if name not in old:
            states['right'][name] = ADDED
    return states
