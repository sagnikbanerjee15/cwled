"""
Folders with a space (macOS: ``Application Support``, where the copies of remote folders are kept), a percent sign or an accent
in their names: the workflows in them load with their steps and are saved as they were. The ``file:`` URIs of the loader have
these characters as %XX, and a path made from them with ``urlparse`` does not exist.
"""
import shutil
from pathlib import Path

import pytest

from conftest import FIXTURES
from helperFunctions import uriToPath
from qt_helpers import pump


def test_a_file_uri_is_turned_into_the_path_it_names():
    assert uriToPath('file:///Users/me/Library/Application%20Support/cwled/x.cwl') == '/Users/me/Library/Application Support/cwled/x.cwl'
    assert uriToPath('file:///a/100%25%20pure/d%C3%A9j%C3%A0.cwl') == '/a/100% pure/déjà.cwl'
    assert uriToPath('file:///a/b.cwl#step') == '/a/b.cwl', "the fragment is not part of the path"
    assert uriToPath('/plain/100% path/x.cwl') == '/plain/100% path/x.cwl', "a plain path is left alone, also with a %"
    assert uriToPath('relative/dir/x.cwl') == 'relative/dir/x.cwl'
    assert uriToPath('https://example.org/a%20b/x.cwl') == '/a%20b/x.cwl', "other schemes: as urlparse gives it"
    assert uriToPath(None) is None


@pytest.mark.parametrize('folder', ['Application Support', 'a%20b', '100% pure', 'dossier é', 'plain'])
def test_a_workflow_in_such_a_folder_loads_with_its_steps_and_is_saved_as_it_was(make_window, tmp_path, folder, caplog):
    root = tmp_path / folder / 'pipeline-assets'
    (root / 'workflows/V/1.0.2').mkdir(parents=True)
    (root / 'tools').mkdir()
    for name in ('echo.cwl', 'uppercase.cwl'):
        shutil.copy(FIXTURES / name, root / 'tools' / name)
    text = (FIXTURES / '50-workflow.cwl').read_text().replace('run: echo.cwl', 'run: ../../../tools/echo.cwl') \
        .replace('run: uppercase.cwl', 'run: ../../../tools/uppercase.cwl')
    workflow = root / 'workflows/V/1.0.2/wf.cwl'
    workflow.write_text(text)
    window = make_window(workspace=root)
    with caplog.at_level('CRITICAL'):
        window.openDocument(str(workflow), host=window)
        pump(14)
    assert not [r for r in caplog.records if r.levelname == 'CRITICAL'], [r.getMessage()[:300] for r in caplog.records]
    document = next(doc for doc in window.open_windows.values() if doc.file_path)
    assert [str(step.run) for step in document.cwl_tool.steps] == ['../../../tools/echo.cwl', '../../../tools/uppercase.cwl'], \
        "the steps refer to their tools relative to the workflow, as written"
    # the graph has found the tools (it reads them from their files)
    nodes = document.workflow_editor.graph.graph.all_nodes()
    assert any(getattr(node, 'cwl_filename', None) and Path(node.cwl_filename).is_file() for node in nodes), \
        [getattr(node, 'cwl_filename', None) for node in nodes]
    # saving writes the paths as they were
    document.saveFile(file_path=str(workflow))
    pump(4)
    saved = [line.strip() for line in workflow.read_text().splitlines() if line.strip().startswith('run:')]
    assert saved == ['run: ../../../tools/echo.cwl', 'run: ../../../tools/uppercase.cwl'], saved
