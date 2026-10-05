"""The command line: the options that open or create documents."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURES

PROBE = Path(__file__).resolve().parent / 'run_main_probe.py'


def run_application(*arguments) -> dict:
    process = subprocess.run([sys.executable, str(PROBE), *arguments], capture_output=True, text=True, timeout=180,
                             cwd=str(FIXTURES.parent))
    lines = [line for line in process.stdout.splitlines() if line.startswith('RESULT ')]
    assert lines, f"the application did not start:\n{process.stdout[-1500:]}\n{process.stderr[-1500:]}"
    return json.loads(lines[-1][len('RESULT '):])


@pytest.mark.parametrize('option, cwl_class', [
    ('--new-workflow', 'Workflow'),
    ('--new-commandline', 'CommandLineTool'),
    ('--new-expression', 'ExpressionTool'),
])
def test_a_new_document_gets_the_name_given_on_the_command_line(option, cwl_class):
    result = run_application('--workspace', str(FIXTURES), option, 'MyDocument')
    assert result['class'] == cwl_class
    assert result['id'] == 'MyDocument'
    assert result['tabs'][-1].startswith('MyDocument') and not result['tabs'][-1].startswith('*'), result['tabs']
    assert result['changed'] is False, "the name is part of the new document, not an edit of it"


def test_a_file_given_on_the_command_line_is_opened():
    result = run_application('--workspace', str(FIXTURES), '--input-file', str(FIXTURES / 'echo.cwl'))
    assert result['tabs'] == ['Welcome', 'echo.cwl'] and result['class'] == 'CommandLineTool'
