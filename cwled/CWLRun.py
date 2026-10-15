"""
Runs a CWL document with cwltool in a process of its own, for the Run dialog (RunDialog.py).

The run is started with QProcess, so the editor keeps working while it runs: the output of
cwltool is handed over as it arrives, and the run can be stopped at any time.
"""
import codecs
import json
import logging
import os
import signal
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

import data

# Makes the process it runs in the leader of a process group of its own, then becomes the
# program given after it: stopping the group stops cwltool and the tools it started.
GROUP_LEADER = "import os, sys; os.setpgid(0, 0); os.execv(sys.argv[1], sys.argv[1:])"
STOP_GRACE_MS = 1000         # after a stop request (SIGTERM), the group is killed if it has not ended by then:
                             # a tool may ignore or be stopped by SIGTERM, but not by SIGKILL
STOP_WAIT_MS = 4000          # the dialog waits this long for a run to stop when it is closed


def commandLine(document: Path, job: Path, outdir: Path) -> tuple[str, list[str]]:
    """
    The program and its arguments that run the document with cwltool: the same Python that runs
    CWLed or, in the packaged application, CWLed's own `--run-module` entry (see configuration.py).
    `cwltool.main` rather than `cwltool`: `python -m cwltool` does not pass cwltool's exit code on,
    so a failed run would look like a successful one.
    """
    if getattr(sys, 'frozen', False):
        prefix = ['--run-module', 'cwltool']
    else:
        prefix = ['-m', 'cwltool.main']
    return sys.executable, prefix + ['--disable-color', '--outdir', str(outdir), str(document), str(job)]


def localPath(location: str) -> Path:
    """The file or folder a location of cwltool (file:///...) names."""
    parsed = urlparse(location)
    if parsed.scheme == 'file':
        return Path(unquote(parsed.path))
    return Path(location)


def producedFiles(outputs) -> list[Path]:
    """The files and folders that the outputs of a run name (the object cwltool prints as JSON)."""
    found = []

    def collect(value):
        if isinstance(value, dict):
            if value.get('class') in ('File', 'Directory') and value.get('location'):
                found.append(localPath(value['location']))
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(outputs)
    return sorted(set(found))


def parseOutputs(text: str):
    """The output object cwltool prints when a run succeeds, or None when the text is not JSON."""
    try:
        return json.loads(text)
    except ValueError:
        return None


class CWLRun(QObject):
    """
    One run of a document with cwltool, in a process of its own.

    Signals:
        output(str): text cwltool wrote (standard output or standard error), as it arrives
        runEnded(str): the run is over; the argument is its status (see `status`)

    Attributes, once the run is over:
        status: 'finished', 'failed' (cwltool reported an error), 'cancelled' or 'error' (cwltool could not start)
        exit_code: the exit code of cwltool (None when it did not run)
        outputs: the output object of a finished run (None when its output is not JSON)
        output_files: the files and folders the outputs name
        stdout_text, stderr_text: everything cwltool wrote
    """
    output = pyqtSignal(str)
    runEnded = pyqtSignal(str)

    def __init__(self, document: Path, job: Path, outdir: Path, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        self.document = Path(document)
        self.job = Path(job)
        self.outdir = Path(outdir)
        self.process = None
        self.status = 'not started'
        self.exit_code = None
        self.outputs = None
        self.output_files = []
        self.stdout_text = ''
        self.stderr_text = ''
        self.ended = False
        self._cancelled = False
        self._own_group = False     # True when cwltool runs as the leader of its own process group
        self._group = 0            # the id of that group (the pid of the leader); QProcess forgets its pid once it ends
        self._decoders = {}
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._killIfRunning)

    def isRunning(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning

    def start(self):
        """Start cwltool. Raises OSError when the output folder cannot be created."""
        self.outdir.mkdir(parents=True, exist_ok=True)
        program, arguments = commandLine(self.document, self.job, self.outdir)
        # a packaged application cannot run Python code with -c, so only a source run gets its own group
        self._own_group = os.name == 'posix' and not getattr(sys, 'frozen', False)
        if self._own_group:
            arguments = ['-c', GROUP_LEADER, program] + arguments
            program = sys.executable
        self.logger.info(f"Running {self.document.name} with cwltool into {self.outdir}")
        self.logger.debug(f"Command: {program} {' '.join(arguments)}")

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(self.document.parent))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONUNBUFFERED', '1')     # the log shows what cwltool writes as it writes it
        self.process.setProcessEnvironment(environment)
        self._decoders = {channel: codecs.getincrementaldecoder('utf-8')(errors='replace')
                          for channel in ('stdout', 'stderr')}
        self.process.readyReadStandardOutput.connect(lambda: self._read('stdout'))
        self.process.readyReadStandardError.connect(lambda: self._read('stderr'))
        self.process.errorOccurred.connect(self._onError)
        self.process.finished.connect(self._onFinished)
        self.status = 'running'
        self.process.start(program, arguments)
        self._group = self.process.processId() if self._own_group else 0

    def cancel(self):
        """Stop the run. cwltool and the tools it started are asked to stop and killed after a moment if they do not."""
        if not self.isRunning() or self._cancelled:
            return
        self._cancelled = True
        self.logger.info("Stopping the cwltool run")
        self._signal(signal.SIGTERM)
        self._stop_timer.start(STOP_GRACE_MS)

    def stop(self):
        """Stop the run and wait until it has ended (used when the dialog closes)."""
        self.cancel()
        if self.isRunning() and not self.process.waitForFinished(STOP_WAIT_MS):
            self._signal(signal.SIGKILL)
            self.process.waitForFinished(STOP_WAIT_MS)
        if self.process is not None and not self.ended and not self.isRunning():
            self._onFinished(self.process.exitCode(), self.process.exitStatus())   # waiting may not have reported it

    def _killIfRunning(self):
        if self.isRunning():
            self.logger.warning("cwltool did not stop when asked, killing it")
            self._signal(signal.SIGKILL)

    def _signal(self, number: int):
        """Send a signal to the run: to its process group, or to cwltool alone when it has none."""
        if self._group > 0 and hasattr(os, 'killpg'):
            try:
                os.killpg(self._group, number)
                return
            except OSError:
                pass        # the group is already gone; cwltool alone is handled below
        if number == signal.SIGTERM:
            self.process.terminate()
        else:
            self.process.kill()

    def _read(self, channel: str):
        if self.process is None:
            return
        raw = self.process.readAllStandardOutput() if channel == 'stdout' else self.process.readAllStandardError()
        self._take(channel, bytes(raw), final=False)

    def _take(self, channel: str, raw: bytes, final: bool):
        text = self._decoders[channel].decode(raw, final)
        if not text:
            return
        if channel == 'stdout':
            self.stdout_text += text
        else:
            self.stderr_text += text
        self.output.emit(text)

    def _onError(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._take('stderr', f"Could not start cwltool: {self.process.errorString()}\n".encode(), final=True)
            self._end('error')

    def _onFinished(self, exit_code: int, exit_status):
        self._read('stdout')
        self._read('stderr')
        self._take('stdout', b'', final=True)
        self._take('stderr', b'', final=True)
        self.exit_code = exit_code
        if self._cancelled:
            self._signal(signal.SIGKILL)      # a tool that ignored SIGTERM may still be running in the group
            self._end('cancelled')
        elif exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self.outputs = parseOutputs(self.stdout_text)
            self.output_files = producedFiles(self.outputs) if self.outputs else []
            self._end('finished')
        else:
            self._end('failed')

    def _end(self, status: str):
        if self.ended:
            return
        self.ended = True
        self._stop_timer.stop()
        self.status = status
        if status in ('failed', 'error'):
            self.logger.warning(f"cwltool run {status}, exit code {self.exit_code}")
        else:
            self.logger.info(f"cwltool run {status}, exit code {self.exit_code}")
        self.runEnded.emit(status)
