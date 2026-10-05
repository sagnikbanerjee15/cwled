"""The Workspace panel: hidden folders, following the open document, live refresh, caching and speed."""
import shutil
import time

import pytest
from PyQt6.QtCore import QModelIndex, Qt

from conftest import FIXTURES
from qt_helpers import open_documents, park_cursor, pump
from WorkspaceContents import ROLE_PATH, WorkspaceContents


@pytest.fixture
def project(tmp_path):
    """A workspace with a hidden folder (.steps), a version control folder (.git) and ordinary ones."""
    root = tmp_path / 'project'
    for name in ('flows', '.steps', '.git', 'tools'):
        (root / name).mkdir(parents=True)
    shutil.copy(FIXTURES / '50-workflow.cwl', root / 'flows' / 'wf.cwl')
    shutil.copy(FIXTURES / 'echo.cwl', root / '.steps' / 'echo.cwl')
    shutil.copy(FIXTURES / 'echo.cwl', root / '.git' / 'hook.cwl')
    shutil.copy(FIXTURES / 'uppercase.cwl', root / 'tools' / 'uppercase.cwl')
    shutil.copy(FIXTURES / '01-hello-world.cwl', root / 'tools' / 'hello.cwl')
    return root.resolve()


def top_level(panel):
    root = panel.model.item(0)
    return [root.child(row).text() for row in range(root.rowCount())]


def children_of(panel, folder):
    root = panel.model.item(0)
    item = root.child(top_level(panel).index(folder))
    return [item.child(row).text() for row in range(item.rowCount())]


def test_hidden_folders_are_listed_only_when_asked_for(make_window, project):
    window = make_window(project)
    panel = window.sidebar.workspace_panel
    assert top_level(panel) == ['flows', 'tools'] and not panel.show_hidden and panel.follow_btn.isChecked()
    panel.setShowHidden(True)
    pump(3)
    assert top_level(panel) == ['.steps', 'flows', 'tools'], "never .git, whatever the setting"
    assert panel.hidden_btn.isChecked()
    panel.setShowHidden(False)
    pump(3)
    assert top_level(panel) == ['flows', 'tools'] and not panel.hidden_btn.isChecked()
    # showing a file of a hidden folder turns the setting on; a folder that is never listed cannot be shown
    assert panel.revealFile(str(project / '.steps' / 'echo.cwl'))
    assert panel.show_hidden and panel._selectedPath() == str(project / '.steps' / 'echo.cwl')
    assert not panel.revealFile(str(project / '.git' / 'hook.cwl'))


def test_the_panel_follows_the_open_document(make_window, project):
    window = make_window(project)
    panel = window.sidebar.workspace_panel
    park_cursor()
    window.openDocument(str(project / 'tools' / 'uppercase.cwl'))
    pump(15)
    assert panel._selectedPath() == str(project / 'tools' / 'uppercase.cwl')
    window.openDocument(str(project / 'tools' / 'hello.cwl'))
    pump(15)
    assert panel._selectedPath() == str(project / 'tools' / 'hello.cwl')
    window.tabs.setCurrentIndex(1)
    pump(5)
    assert panel._selectedPath() == str(project / 'tools' / 'uppercase.cwl'), "back to the first document"
    # the user picks something else: a title refresh (typing) does not take the selection back
    panel.tree_view.setCurrentIndex(panel._indexOfPath(str(project / 'tools' / 'hello.cwl'), expand=False))
    window._refreshDocumentTab(window.tabs.currentWidget())
    pump(3)
    assert panel._selectedPath() == str(project / 'tools' / 'hello.cwl')
    # off: tabs are not followed; on: the shown document is selected at once
    panel.follow_btn.click()
    assert not panel.follow_document
    window.tabs.setCurrentIndex(2)
    pump(4)
    window.tabs.setCurrentIndex(1)
    pump(4)
    assert panel._selectedPath() == str(project / 'tools' / 'hello.cwl')
    panel.follow_btn.click()
    pump(3)
    assert panel.follow_document and panel._selectedPath() == str(project / 'tools' / 'uppercase.cwl')
    # the Recent page and a search in progress are left alone
    window.sidebar.tabs.setCurrentIndex(1)
    window.tabs.setCurrentIndex(2)
    pump(4)
    assert panel._selectedPath() == str(project / 'tools' / 'uppercase.cwl')
    window.sidebar.tabs.setCurrentIndex(0)
    panel.search_box.setText('hello')
    panel.on_search_clicked()
    pump(3)
    window.tabs.setCurrentIndex(1)
    pump(4)
    assert panel._showing_search and panel.search_box.text() == 'hello'


def test_the_tree_follows_files_that_are_added_and_removed(make_window, project):
    window = make_window(project)
    panel = window.sidebar.workspace_panel
    panel.tree_view.expand(panel._indexOfPath(str(project / 'tools'), expand=True))
    panel.revealFile(str(project / 'tools' / 'hello.cwl'), allow_hidden=False)
    pump(3)
    assert str(project / 'tools') in panel._watcher.directories(), "the folders that are shown are watched"
    shutil.copy(FIXTURES / 'echo.cwl', project / 'tools' / 'newtool.cwl')
    panel._watcher.directoryChanged.emit(str(project / 'tools'))      # what the file watcher of the system sends
    deadline = time.time() + 6
    while time.time() < deadline and 'newtool.cwl' not in children_of(panel, 'tools'):
        pump(5)
    assert children_of(panel, 'tools') == ['hello.cwl', 'newtool.cwl', 'uppercase.cwl']
    assert panel._selectedPath() == str(project / 'tools' / 'hello.cwl'), "the selection is kept"
    (project / 'tools' / 'newtool.cwl').unlink()
    panel._watcher.directoryChanged.emit(str(project / 'tools'))
    deadline = time.time() + 6
    while time.time() < deadline and 'newtool.cwl' in children_of(panel, 'tools'):
        pump(5)
    assert children_of(panel, 'tools') == ['hello.cwl', 'uppercase.cwl']


def test_a_changed_file_is_read_again(make_window, project):
    window = make_window(project)
    panel = window.sidebar.workspace_panel
    panel.tree_view.expand(panel._indexOfPath(str(project / 'tools'), expand=True))

    def tooltip():
        tools = panel.model.item(0).child(top_level(panel).index('tools'))      # the model is rebuilt by a refresh
        return next(tools.child(r).toolTip() for r in range(tools.rowCount()) if tools.child(r).text() == 'hello.cwl')

    assert 'Class: CommandLineTool' in tooltip()
    target = project / 'tools' / 'hello.cwl'
    target.write_text(target.read_text().replace('class: CommandLineTool', 'class: ExpressionTool'))
    panel.refresh()
    pump(3)
    assert 'Class: ExpressionTool' in tooltip()


def test_a_large_workspace_expands_quickly(cwled_config, tmp_path):
    """Measuring the width of the name column after every folder made this quadratic: 20 s for this tree."""
    tmp_path = tmp_path / 'big'
    for a in range(25):
        for b in range(8):
            for c in range(4):
                folder = tmp_path / f'proj{a:02d}' / f'group{b}' / f'tool{c}'
                (folder / 'data').mkdir(parents=True)
                for k in range(4):
                    (folder / f't{k}.cwl').write_text('cwlVersion: v1.2\nclass: CommandLineTool\ninputs: []\noutputs: []\n')
    panel = WorkspaceContents(workspace_path=[str(tmp_path)], sidebar=True)

    def expand(index):
        panel.tree_view.expand(index)
        for row in range(panel.model.rowCount(index)):
            child = panel.model.index(row, 0, index)
            if panel.model.data(child, Qt.ItemDataRole.UserRole + 2):       # a folder
                expand(child)

    started = time.perf_counter()
    for row in range(panel.model.rowCount()):
        expand(panel.model.index(row, 0))
    elapsed = time.perf_counter() - started
    files = sum(1 for _ in tmp_path.rglob('*.cwl'))
    shown = 0

    def count(item):
        nonlocal shown
        for row in range(item.rowCount()):
            child = item.child(row)
            shown += 0 if child.data(Qt.ItemDataRole.UserRole + 2) else 1
            count(child)

    for row in range(panel.model.rowCount()):
        count(panel.model.item(row))
    assert shown == files == 3200, "every document is listed"
    assert elapsed < 10, f"expanding the whole workspace took {elapsed:.1f}s"
    started = time.perf_counter()
    panel.refresh()
    assert time.perf_counter() - started < 10, "a refresh restores the expanded folders"
    panel.deleteLater()
