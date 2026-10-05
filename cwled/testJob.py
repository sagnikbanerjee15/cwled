"""
Test values of tool inputs (Rabix Composer "Test Value").

The value typed for an input in the side panel replaces its sample value in
the command line preview and in the Expression Editor. Like Composer, the
values are kept outside the CWL document (so setting them does not modify
it), per document file, in CWLed's user data folder.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from platformdirs import user_data_path
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class TestJobs(QObject):
    """The stored test values: {document path: {input id: text}}."""

    changed = pyqtSignal(str)       # document path

    def __init__(self):
        super().__init__()
        self._file = user_data_path('cwled', ensure_exists=True) / 'test_jobs.json'
        try:
            self._jobs = json.loads(self._file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self._jobs = {}

    def values(self, document: Optional[str]) -> dict:
        """Test values (as typed) of a document's inputs."""
        return dict(self._jobs.get(_key(document), {})) if document else {}

    def setValue(self, document: Optional[str], input_id: str, text: Optional[str]):
        """Set (or, with an empty text, clear) the test value of an input."""
        if not document:
            return
        job = self._jobs.setdefault(_key(document), {})
        if text is None or text.strip() == '':
            if job.pop(input_id, None) is None:
                return
        elif job.get(input_id) == text:
            return
        else:
            job[input_id] = text
        if not job:
            self._jobs.pop(_key(document), None)
        try:
            self._file.write_text(json.dumps(self._jobs, indent=2), encoding='utf-8')
        except OSError as e:
            logger.warning(f"Could not store the test values: {e}")
        self.changed.emit(_key(document))


_jobs = None


def testJobs() -> TestJobs:
    global _jobs
    if _jobs is None:
        _jobs = TestJobs()
    return _jobs


def _key(document: Any) -> str:
    return os.path.abspath(str(document)) if document else ''


def documentPath(widget) -> Optional[str]:
    """The file of the document (ChildWindow) a widget belongs to."""
    while widget is not None:
        if widget.__class__.__name__ == "ChildWindow":
            path = getattr(widget, 'file_path', None)
            return _key(path) if path else None
        widget = widget.parent()
    return None


# ---------------------------------------------------------------------------
# typed text -> job value
# ---------------------------------------------------------------------------
def _shortId(value: Any) -> str:
    return str(value).split('#')[-1].split('/')[-1]


def _schema(cwl_type: Any) -> Any:
    if isinstance(cwl_type, list):
        types = [t for t in cwl_type if t != 'null']
        return types[0] if types else None
    return cwl_type


def _typeName(schema: Any) -> Optional[str]:
    if isinstance(schema, str):
        name = _shortId(schema).rstrip('?')
        return 'array' if name.endswith('[]') else name
    return getattr(schema, 'type_', None)


def _itemSchema(schema: Any) -> Any:
    if isinstance(schema, str):
        return _shortId(schema).rstrip('?')[:-2]
    return _schema(getattr(schema, 'items', None))


def fileValue(path: str, kind: str = 'File') -> dict:
    """A File / Directory object with the properties expressions use."""
    basename = Path(path).name
    if kind == 'Directory':
        return {'class': 'Directory', 'path': path, 'basename': basename}
    nameroot, nameext = os.path.splitext(basename)
    return {'class': 'File', 'path': path, 'basename': basename, 'nameroot': nameroot,
            'nameext': nameext, 'size': 0, 'contents': '', 'secondaryFiles': [], 'metadata': {}}


def jobValue(text: str, cwl_type: Any) -> Any:
    """The job value of a test value typed for an input of type ``cwl_type``.
    JSON is accepted everywhere; arrays also take comma separated values."""
    schema = _schema(cwl_type)
    kind = _typeName(schema)
    text = text.strip()
    if kind == 'array':
        if text.startswith('['):
            try:
                items = json.loads(text)
            except ValueError:
                items = [part for part in text.strip('[]').split(',')]
        else:
            items = text.split(',')
        item_schema = _itemSchema(schema)
        return [_scalar(item, item_schema) if isinstance(item, str) else item
                for item in items if not (isinstance(item, str) and item.strip() == '')]
    return _scalar(text, schema)


def _scalar(text: str, schema: Any) -> Any:
    kind = _typeName(schema)
    text = text.strip()
    if kind in ('File', 'Directory', 'stdin'):
        return fileValue(text, 'Directory' if kind == 'Directory' else 'File')
    if kind in ('int', 'long'):
        return int(text) if re.fullmatch(r'[+-]?\d+', text) else text
    if kind in ('float', 'double'):
        try:
            return int(text) if re.fullmatch(r'[+-]?\d+', text) else float(text)
        except ValueError:
            return text
    if kind == 'boolean':
        return text.lower() in ('true', 'yes', '1', 'on')
    if kind in ('record', 'map', 'Any'):
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def applyTestValues(job: dict, inputs: list, values: dict) -> dict:
    """``job`` with the test values of ``inputs`` in place of sample values."""
    job = dict(job)
    for parameter in inputs or []:
        input_id = _shortId(parameter.id)
        if input_id in values:
            try:
                job[input_id] = jobValue(values[input_id], getattr(parameter, 'type_', None))
            except Exception as e:
                logger.debug(f"Ignoring the test value of {input_id}: {e}")
    return job
