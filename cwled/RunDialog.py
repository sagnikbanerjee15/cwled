"""
Run the open document with cwltool: Tools -> Run tool/workflow...

cwltool reads the document from disk, so the document is saved first. The dialog asks for the
job (the input values, as YAML or JSON: a file, or the template of the document) and for the
output folder, then runs cwltool in a process of its own (CWLRun.py): the log is shown as it
comes, Cancel stops the run, and a successful run lists the files it produced.
"""
import json
import logging
from datetime import datetime
from io import StringIO
from pathlib import Path

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QFontDatabase, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout
)
from ruamel.yaml import YAML

import data
from BaseDialog import BaseDialog
from CWLRun import CWLRun
from CWLtoolFactory import CWLRunner

JOB_FILTER = "Job files (*.yml *.yaml *.json);;All files (*)"
NO_FILES_TEXT = "(none: the outputs are values, not files)"


def startRunFromEditor(document):
    """
    Tools -> Run tool/workflow...: make sure the document is saved, then open the Run dialog for it.
    Returns the dialog, or None when the document was not saved (the user declined or cancelled).
    """
    if document.hasChanged or not _isFile(document.file_path):
        answer = document.questionCentered(
            title="Save Before Running?",
            text="cwltool runs the document as it is on disk. Save the document now?")
        if answer != QMessageBox.StandardButton.Yes:
            return None
        document.onToolbarSave()            # asks for a file name when the document has none
        if document.hasChanged or not _isFile(document.file_path):
            return None
    dialog = RunDialog(document)
    dialog.show()
    return dialog


def jobProblem(text: str):
    """Why the text is not a job (YAML or JSON that maps input names to values), or None when it is one."""
    if not text.strip():
        return None
    try:
        parsed = YAML().load(text)
    except Exception as error:      # the YAML parser raises its own exception types
        return str(error)
    if parsed is not None and not isinstance(parsed, dict):
        return "The job must map input names to their values."
    return None


def _isFile(path) -> bool:
    return path is not None and Path(path).is_file()


class RunDialog(BaseDialog):
    """
    Asks for the job and the output folder of a document, runs it with cwltool and shows the
    log, the result and the files it produced.
    """

    def __init__(self, document, parent=None):
        super().__init__(parent if parent is not None else document)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        self.document = document
        self.documentPath = Path(document.file_path)
        self.run = None
        self.jobSource = None       # the job file the text was loaded from (None when it was typed or generated)
        self.loadedJob = None       # the text of that file as it was loaded
        self.setWindowTitle(f"Run {self.documentPath.name}")
        self.resize(760, 760)
        self.initUI()
        self.outputEdit.setText(str(self.defaultOutputDirectory()))
        self.finished.connect(self.deleteLater)
        self.setStatus("Choose or generate the job, then press Run.")

    # -- layout -----------------------------------------------------------------------------------------------
    def initUI(self):
        monospace = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Run {self.documentPath.name} with cwltool on this computer."))

        jobBox = QGroupBox("Job (the input values)")
        jobLayout = QVBoxLayout(jobBox)
        sourceRow = QHBoxLayout()
        self.jobSourceEdit = QLineEdit()
        self.jobSourceEdit.setReadOnly(True)
        self.jobSourceEdit.setPlaceholderText("No file chosen: the job is the text below")
        chooseButton = QPushButton("Choose file...")
        chooseButton.clicked.connect(self.chooseJobFile)
        generateButton = QPushButton("Generate from template")
        generateButton.setToolTip("Fill the job with the template of the document (cwltool --make-template)")
        generateButton.clicked.connect(self.generateJob)
        sourceRow.addWidget(self.jobSourceEdit)
        sourceRow.addWidget(chooseButton)
        sourceRow.addWidget(generateButton)
        jobLayout.addLayout(sourceRow)
        self.jobText = QPlainTextEdit()
        self.jobText.setFont(monospace)
        self.jobText.setPlaceholderText("Input values in YAML or JSON, for example:  message: Hello")
        self.jobText.setMinimumHeight(120)
        self.jobText.setMaximumHeight(180)
        jobLayout.addWidget(self.jobText)
        self.saveJobCheck = QCheckBox(f"Save the job as {self.jobFileName()} next to the document when it runs")
        self.saveJobCheck.setChecked(True)
        self.saveJobCheck.setToolTip(
            "Used for a job that was generated or changed. A chosen file that was not changed is used as it is; "
            "without this box the job is written into the output folder.")
        jobLayout.addWidget(self.saveJobCheck)
        layout.addWidget(jobBox)

        outputBox = QGroupBox("Output folder")
        outputLayout = QHBoxLayout(outputBox)
        self.outputEdit = QLineEdit()
        browseButton = QPushButton("Browse...")
        browseButton.clicked.connect(self.chooseOutputFolder)
        outputLayout.addWidget(self.outputEdit)
        outputLayout.addWidget(browseButton)
        layout.addWidget(outputBox)

        buttons = QHBoxLayout()
        self.runButton = QPushButton("Run")
        self.runButton.setDefault(True)
        self.runButton.clicked.connect(self.startRun)
        self.cancelButton = QPushButton("Cancel run")
        self.cancelButton.clicked.connect(self.cancelRun)
        self.cancelButton.setEnabled(False)
        closeButton = QPushButton("Close")
        closeButton.clicked.connect(self.close)
        buttons.addWidget(self.runButton)
        buttons.addWidget(self.cancelButton)
        buttons.addStretch()
        buttons.addWidget(closeButton)
        layout.addLayout(buttons)

        self.statusLabel = QLabel()
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)

        logBox = QGroupBox("Log (what cwltool writes)")
        logLayout = QVBoxLayout(logBox)
        self.logView = QPlainTextEdit()
        self.logView.setReadOnly(True)
        self.logView.setFont(monospace)
        logLayout.addWidget(self.logView)
        layout.addWidget(logBox, 1)

        self.resultBox = QGroupBox("Result")
        resultLayout = QVBoxLayout(self.resultBox)
        self.resultView = QPlainTextEdit()
        self.resultView.setReadOnly(True)
        self.resultView.setFont(monospace)
        self.resultView.setMaximumHeight(160)
        resultLayout.addWidget(self.resultView)
        resultLayout.addWidget(QLabel("Produced files:"))
        self.filesList = QListWidget()
        self.filesList.setMaximumHeight(120)
        resultLayout.addWidget(self.filesList)
        openButton = QPushButton("Open output folder")
        openButton.clicked.connect(self.openOutputFolder)
        resultLayout.addWidget(openButton, 0, Qt.AlignmentFlag.AlignLeft)
        self.resultBox.setVisible(False)
        layout.addWidget(self.resultBox)

    def setStatus(self, text: str):
        self.statusLabel.setText(text)

    # -- the job and the output folder ----------------------------------------------------------------------
    def jobFileName(self) -> str:
        return f"{self.documentPath.stem}-job.yml"

    def defaultOutputDirectory(self) -> Path:
        """A new folder next to the document, named for the time of the run."""
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        return self.documentPath.parent / f"{self.documentPath.stem}-run-{stamp}"

    def outputFolder(self) -> Path:
        return Path(self.outputEdit.text().strip()).expanduser().absolute()

    def chooseJobFile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the job file", str(self.documentPath.parent), JOB_FILTER)
        if path:
            self.loadJobFile(path)

    def loadJobFile(self, path):
        """Show the text of a job file in the box; it is used as it is unless the text is changed."""
        text = Path(path).read_text(encoding='utf-8')
        self.jobSource = Path(path)
        self.loadedJob = text
        self.jobSourceEdit.setText(str(path))
        self.jobText.setPlainText(text)

    def generateJob(self):
        """Fill the box with the template of the document (cwltool --make-template)."""
        runner = CWLRunner()
        template = runner.makeTemplate(self.documentPath.read_text(encoding='utf-8'),
                                       source_path=str(self.documentPath))
        if template is None:
            self.logger.warning(f"No job template could be generated for {self.documentPath}")
            QMessageBox.warning(self, "Generate from template",
                                "The template could not be generated for this document.\n\n"
                                + (getattr(runner, 'stderr', '') or ""))
            return
        stream = StringIO()
        YAML().dump(template, stream)
        self.jobSource = None
        self.loadedJob = None
        self.jobSourceEdit.setText("Generated from the template (not saved yet)")
        self.jobText.setPlainText(stream.getvalue())

    def chooseOutputFolder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the output folder", str(self.outputFolder().parent))
        if folder:
            self.outputEdit.setText(folder)

    def jobForRun(self, text: str, outdir: Path) -> Path | None:
        """
        The job file cwltool reads. A chosen file whose text was not changed is used as it is; other
        text is written next to the document (when the box is ticked) or into the output folder.
        Returns None when the user does not replace a different file that is already there.
        """
        if self.jobSource is not None and text == self.loadedJob:
            return self.jobSource
        folder = self.documentPath.parent if self.saveJobCheck.isChecked() else outdir
        target = folder / self.jobFileName()
        if target != self.jobSource and target.exists() and target.read_text(encoding='utf-8') != text:
            answer = QMessageBox.question(
                self, "Replace the job file?",
                f"{target} exists and has other content. Replace it with the job shown here?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return None
        target.write_text(text if text.endswith('\n') else text + '\n', encoding='utf-8')
        self.logger.debug(f"Job written to {target}")
        return target

    # -- the run ---------------------------------------------------------------------------------------------
    def startRun(self):
        """Run the document with the job, into the output folder, in a process of its own."""
        if self.run is not None and self.run.isRunning():
            return
        if not self.outputEdit.text().strip():
            return self._warn("Output folder", "Choose the folder the results are written to.")
        outdir = self.outputFolder()
        if outdir.exists() and not outdir.is_dir():
            return self._warn("Output folder", f"{outdir} is not a folder.")
        text = self.jobText.toPlainText()
        problem = jobProblem(text)
        if problem:
            return self._warn("Job", f"The job is not YAML or JSON that names the inputs:\n\n{problem}")
        if not text.strip():
            text = "{}\n"
        try:
            outdir.mkdir(parents=True, exist_ok=True)
            job = self.jobForRun(text, outdir)
        except OSError as error:
            return self._warn("Run", f"The job could not be written:\n\n{error}")
        if job is None:
            return

        run = CWLRun(self.documentPath, job, outdir, self)
        run.output.connect(self._appendLog)
        run.runEnded.connect(self._onRunEnded)
        self.run = run
        self.logView.clear()
        self.resultBox.setVisible(False)
        self._setRunning(True)
        self.setStatus(f"Running... the results go to {outdir}")
        run.start()

    def cancelRun(self):
        """Stop the run that is going."""
        if self.run is not None and self.run.isRunning():
            self.setStatus("Stopping...")
            self.run.cancel()

    def _setRunning(self, running: bool):
        self.runButton.setEnabled(not running)
        self.cancelButton.setEnabled(running)

    def _appendLog(self, text: str):
        self.logView.moveCursor(QTextCursor.MoveOperation.End)
        self.logView.insertPlainText(text)

    def _onRunEnded(self, status: str):
        self._setRunning(False)
        run = self.run
        if status == 'finished':
            self.setStatus(f"Finished, exit code {run.exit_code}. The results are in {run.outdir}.")
            self._showResult(run)
        elif status == 'failed':
            self.setStatus(f"Failed, exit code {run.exit_code}. The log says what went wrong.")
        elif status == 'cancelled':
            self.setStatus("Cancelled.")
        else:
            self.setStatus("cwltool could not be started. The log says why.")

    def _showResult(self, run: CWLRun):
        if run.outputs is not None:
            self.resultView.setPlainText(json.dumps(run.outputs, indent=2))
        else:
            self.resultView.setPlainText(run.stdout_text.strip() or "(cwltool wrote no output)")
        self.filesList.clear()
        for path in run.output_files:
            try:
                name = str(path.resolve().relative_to(run.outdir.resolve()))
            except ValueError:
                name = str(path)
            self.filesList.addItem(name)
        if not run.output_files:
            self.filesList.addItem(NO_FILES_TEXT)
        self.resultBox.setVisible(True)

    def openOutputFolder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outputFolder())))

    def _warn(self, title: str, text: str):
        QMessageBox.warning(self, title, text)
        return None

    def done(self, result: int):
        """Closing the dialog (Close, Escape, the window's button) stops a run that is still going."""
        if self.run is not None and self.run.isRunning():
            self.run.stop()
        super().done(result)
