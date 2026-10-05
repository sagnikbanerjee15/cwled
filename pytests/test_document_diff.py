"""Comparing documents: the canonical text, the alignment, the changes, git revisions and the comparison tab."""
import copy
import os
import shutil
import subprocess

import pytest
from PyQt6.QtCore import Qt

import DocumentDiff as DD
import GraphItems
from conftest import FIXTURES
from qt_helpers import documents_by_name, pump, titles


@pytest.fixture
def project(tmp_path, window):
    """A copy of the workflow of the test documents and of the tools it runs, in the workspace."""
    folder = tmp_path.resolve()
    for name in ('echo.cwl', 'uppercase.cwl', '50-workflow.cwl'):
        shutil.copy(FIXTURES / name, folder / name)
    window.workspace.addFolder(str(folder))
    window.updateWorkspaceViews()
    return folder


def git(folder, *arguments):
    environment = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                   'GIT_COMMITTER_EMAIL': 't@t', 'HOME': str(folder)}
    subprocess.run(['git', '-C', str(folder), *arguments], check=True, capture_output=True, env=environment)


def test_the_same_document_gives_the_same_text_from_every_source(window, project):
    window.openDocument(str(project / '50-workflow.cwl'))
    pump(15)
    document = list(window.open_windows.values())[-1]
    live, disk = DD.sourceFromWindow(document), DD.sourceFromFile(project / '50-workflow.cwl')
    assert live.text() == disk.text()
    left, right = DD.alignedLines(disk.text(), live.text())
    assert all(line.kind == DD.EQUAL for line in left) and DD.changeBlocks(left) == []
    assert DD.structuralChanges(disk.cwl, live.cwl, left, right) == []
    assert not any(line.startswith('id:') for line in disk.text().splitlines()), "the address of the file is not a difference"


@pytest.mark.skipif(shutil.which('git') is None, reason="git is not installed")
def test_revisions_in_git(window, project):
    git(project, 'init', '-q')
    git(project, 'add', '.')
    git(project, 'commit', '-q', '-m', 'first version')
    text = (project / '50-workflow.cwl').read_text()
    (project / '50-workflow.cwl').write_text(text.replace('uppercase.cwl', 'echo.cwl', 1))
    git(project, 'commit', '-qam', 'second step runs echo')
    revisions = DD.gitRevisions(project / '50-workflow.cwl')
    assert [description.split(' ', 1)[1] for _sha, description in revisions] == ['second step runs echo', 'first version']
    old = DD.sourceFromGit(project / '50-workflow.cwl', revisions[1][0], 'first')
    new = DD.sourceFromFile(project / '50-workflow.cwl')
    left, right = DD.alignedLines(old.text(), new.text())
    changes = DD.structuralChanges(old.cwl, new.cwl, left, right)
    assert [change.describe() for change in changes] == ['~ steps uppercase']
    assert DD.stepStates(old.cwl, new.cwl) == {'left': {'uppercase': 'changed'}, 'right': {'uppercase': 'changed'}}
    assert 'uppercase' in left[changes[0].row].text or 'uppercase' in right[changes[0].row].text
    blocks = DD.changeBlocks(right)
    assert blocks and all(any(line.kind != DD.EQUAL for line in left[first:last + 1]) for first, last in blocks)
    assert DD.gitRevisions(project / 'echo.cwl')[0][1].endswith('first version'), "the history of another file of the repository"
    assert DD.gitRevisions(project / 'not-there.cwl') == [], "a file that was never committed has no revisions"


def test_added_removed_and_changed_parts(window, project):
    window.openDocument(str(project / '50-workflow.cwl'))
    pump(15)
    base = DD.sourceFromFile(project / '50-workflow.cwl')
    other = copy.deepcopy(base.cwl)
    other['steps'] = [s for s in other['steps'] if DD.entryId(s) != 'echo'] + [{'id': 'extra', 'run': 'echo.cwl', 'in': [], 'out': []}]
    other['inputs'] = list(other['inputs']) + [{'id': 'more', 'type': 'int'}]
    other['label'] = 'A label'
    del other['cwlVersion']
    left, right = DD.alignedLines(base.text(), DD.canonicalYaml(other))
    assert len(left) == len(right), "the two sides have the same number of lines (gaps where there is nothing)"
    changes = DD.structuralChanges(base.cwl, other, left, right)
    assert {change.describe() for change in changes} == {'+ steps extra', '− steps echo', '+ inputs more', '+ label', '− cwlVersion'}
    assert DD.stepStates(base.cwl, other) == {'left': {'echo': 'removed'}, 'right': {'extra': 'added'}}


def test_the_comparison_tab(window, project):
    modified = (project / '50-workflow.cwl').read_text()
    (project / 'v2-workflow.cwl').write_text(
        modified.replace('  uppercase:\n    run: uppercase.cwl', '  uppercase:\n    label: Shout it\n    run: uppercase.cwl')
                .replace('inputs:\n  message: string', 'inputs:\n  message: string\n  extra: int'))
    for name in ('50-workflow.cwl', 'v2-workflow.cwl'):
        window.openDocument(str(project / name))
        pump(15)
    docs = documents_by_name(window)
    old, new = docs['50-workflow.cwl'], docs['v2-workflow.cwl']

    view = window.showComparison(window, lambda: DD.sourceFromWindow(old), lambda: DD.sourceFromWindow(new))
    pump(8)
    assert titles(window.tabs)[-1] == '50-workflow.cwl ↔ v2-workflow.cwl' and window.tabs.currentWidget() is view
    entries = [view.change_list.item(row).text() for row in range(view.change_list.count())]
    assert entries == ['inputs extra', 'steps uppercase']
    assert view.left_edit.document().blockCount() == view.right_edit.document().blockCount() == len(view.left_lines)
    assert view.left_edit.extraSelections() and view.right_edit.extraSelections()
    assert (view.left_title.text(), view.right_title.text()) == ('50-workflow.cwl', 'v2-workflow.cwl')

    # the two panes scroll together
    view.resize(900, 200)
    view.show()
    pump(5)
    view.left_edit.verticalScrollBar().setValue(view.left_edit.verticalScrollBar().maximum() // 2)
    pump(2)
    assert view.right_edit.verticalScrollBar().value() == view.left_edit.verticalScrollBar().value() > 0
    view.right_edit.verticalScrollBar().setValue(0)
    pump(2)
    assert view.left_edit.verticalScrollBar().value() == 0

    # next / previous difference, and a click on a change
    starts = [first for first, _last in view.blocks]
    view.goToRow(0)
    view.goToBlock(1)
    first = view.currentRow()
    view.goToBlock(1)
    second = view.currentRow()
    view.goToBlock(-1)
    assert first == starts[0] and second == (starts[1] if len(starts) > 1 else starts[0]) and view.currentRow() == first
    step = next(view.change_list.item(row) for row in range(view.change_list.count()) if view.change_list.item(row).text() == 'steps uppercase')
    view._onChangeClicked(step)
    assert 'uppercase' in view.right_lines[view.currentRow()].text

    # the steps that differ are marked in the graphs of both documents; the marks survive a redraw
    def marks(document):
        return {node.name(): node.view._diff
                for node in document.workflow_editor.graph.graph.get_nodes_by_type('cwled.step.StepNode')}

    assert marks(old) == marks(new) == {'echo': None, 'uppercase': 'changed'}
    view.highlight_check.setChecked(False)
    assert marks(old) == marks(new) == {'echo': None, 'uppercase': None}
    view.highlight_check.setChecked(True)
    new.workflow_editor.graph.makeGraph()
    pump(5)
    assert marks(new)['uppercase'] == 'changed'

    # swap the sides; refresh after an edit that is not saved
    view.swap()
    pump(3)
    assert view.title() == 'v2-workflow.cwl ↔ 50-workflow.cwl'
    view.swap()
    new.cwl_tool.label = 'A new label'
    view.refresh()
    pump(3)
    assert 'label' in [view.change_list.item(row).text() for row in range(view.change_list.count())]

    # a document with itself: nothing differs
    same = window.showComparison(window, lambda: DD.sourceFromWindow(old), lambda: DD.sourceFromFile(project / '50-workflow.cwl'))
    pump(5)
    assert same.summary.text() == 'The documents are the same' and same.change_list.item(0).text() == 'No changes' and not same.blocks

    # closing the comparison clears the marks
    window.closeTab(window.tabs, window.tabs.indexOf(view))
    pump(5)
    assert view not in window.tabs.widgets() and marks(old) == marks(new) == {'echo': None, 'uppercase': None}
    window.closeTab(window.tabs, window.tabs.indexOf(same))

    # a comparison can be torn off like any tab; it is not a document of the session
    detached_view = window.showComparison(window, lambda: DD.sourceFromWindow(old), lambda: DD.sourceFromWindow(new))
    pump(5)
    window.tabs.detachTab(detached_view)
    pump(10)
    detached = window.detached_windows[0]
    assert detached_view in detached.tabs.widgets() and not window.sessionData()['windows']
    detached.close()
    pump(8)
    assert not window.detached_windows
