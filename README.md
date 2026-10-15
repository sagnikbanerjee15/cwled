
<p align="center">
  <img src="resources/icons/CWL-Logo.png" alt="CWLed Logo" width="150">
</p>

<h1 align="center">CWLed</h1>

<p align="center">
  A graphical editor for Common Workflow Language (CWL) documents
</p>

<p align="center">
  <a href="#key-features">Key Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#license">License</a>
</p>

---

## What is CWLed?

CWLed is a desktop application for creating and editing [CWL](https://www.commonwl.org/) tools and workflows through an intuitive graphical interface. It eliminates the need to write verbose CWL code by hand, allowing scientists and developers to focus on the logic of their analysis rather than the intricacies of CWL syntax.

Inspired by [Rabix Composer](https://github.com/rabix/composer) (an excellent CWL editor by Seven Bridges, now discontinued), CWLed brings modern tooling to the CWL ecosystem with a PyQt6-based interface.

## Key Features

- **Dual-view editing** — Seamlessly switch between a graphical form-based editor and a raw CWL code editor (YAML/JSON). Changes in one view are instantly reflected in the other.
- **Visual workflow builder** — Build pipelines by connecting tool nodes in an interactive graph view.
- **Support for all CWL types** — Create and edit CommandLineTools, ExpressionTools, and Workflows.
- **Built-in validation** — Validate your CWL documents against the specification using `cwltool --validate`.
- **Template generation** — Auto-generate input templates from your CWL tools.
- **LLM integration** — Draft CommandLineTools from documentation and troubleshoot tools/workflows using ChatGPT, Google Gemini, or Anthropic models.
- **Git version tracking** — Automatically tag saved documents with git version tags.
- **Workspace browser** — Browse and manage CWL files in your project workspace.
- **CWL version upgrade** — Upgrade documents to CWL v1.2 with a single click.
- **Workflow packaging** — Pack multi-file workflows into a single file or restructure them with all referenced tools.

## Prerequisites

Before using CWLed, make sure the following are installed on your system:

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.10+ | [python.org](https://www.python.org/) or via `uv` / conda |
| uv | 0.1+ | `curl -LsSf https://astral.sh/uv/install.sh | sh` or [astral.sh](https://astral.sh/) |
| Node.js | 24+ | [nodejs.org](https://nodejs.org/) |


> **Note:** When installing from source (see below), Python dependencies are managed and installed automatically via `uv` using the `pyproject.toml` file. The macOS `.dmg` bundle and Linux executable do **not** include `cwltool`, `node` — install them separately and make sure they are included in the PATH of the system.

`cwltool` is necessary to run workflows and tools for testing and debugging purposes. It uses `node` to run and validate tools with JavaScript expressions (the Expression Editor does not need it).


## Installation

### macOS (pre-built app)

Use the provided `.dmg` file to install the application.

If macOS reports that it cannot verify the developer, either:
- Go to **System Preferences → Security & Privacy → General** and click **Open Anyway**, or
- Run:
```bash
xattr -d com.apple.quarantine /path/to/CWLed.app
```

### Linux (pre-build app)
Use the provided `.tar.gz` file.

- Run:
```bash
tar -xvzf CWLed-Linux.tar.gz
```
This will create a couple of files, you can use the wrapper script `run.sh` to start the application.

### From source

```bash
# Clone the repository
git clone https://github.com/kmavrommatis/cwled.git
cd cwled

# Sync dependencies and set up the virtual environment automatically with uv
uv sync
```

## Usage

### Launch the application

```bash
# Run the launcher via uv (which manages the virtual environment)
uv run python cwled.py
# or run the registered project script
uv run cwled
```

### Command-line options

```
python cwled.py --help

usage: cwled.py [-h] [--input-file INPUT_FILE [INPUT_FILE ...]]
                [--new-workflow NEW_WORKFLOW]
                [--new-commandline NEW_COMMANDLINE]
                [--new-expression NEW_EXPRESSION]
                [--workspace WORKSPACE] [--version]

options:
  -h, --help            Show this help message and exit
  --input-file FILE     Path(s) to input file(s), separated by spaces
  --new-workflow NAME   Create a new Workflow
  --new-commandline NAME
                        Create a new CommandLineTool
  --new-expression NAME
                        Create a new ExpressionTool
  --workspace DIR       Default location for CWL tools
  --version             Show the version of the tool
```

### Quick start

1. Launch CWLed — the main window shows buttons to create a new **CommandLineTool**, **ExpressionTool**, or **Workflow**.
2. Use **File → Open** or the **Open Workspace** button to load existing CWL files.
3. Edit using the **Info**, **App**, or **Code** tabs.
4. Save with **File → Save** (Ctrl/Cmd+S). Documents are automatically tagged with a git version.

For detailed instructions, see the built-in **Help → User Guide**.

## Configuration

Configuration files are stored in the standard OS config directory:

| OS | Location |
|----|----------|
| macOS | `~/Library/Application Support/cwled/` |
| Linux | `~/.config/cwled/` |

Two files control the application:

- **`cwled.yaml`** — Main configuration (workspace path, tool paths, logging levels, editor settings). You may need to set the workspace location and tool paths before the first run.
- **`cwl_env`** — Environment variables for LLM API keys.

### LLM integration

To enable LLM features (draft tools from docs, troubleshooting):

1. Set the `LLModel` entry in `cwled.yaml` to the desired model (using [LangChain](https://python.langchain.com/) model names). OpenAI, Google, and Anthropic models are supported.
2. Create a `cwled.env` file in the config directory with your API key:

```bash
OPENAI_API_KEY=sk-...
# or
GOOGLE_API_KEY=...
# or
ANTHROPIC_API_KEY=...
```

## License

This project is licensed under the [GNU General Public License v3.0 or later](cwled/COPYING).

Copyright (C) 2026 K. Mavrommatis

Third-party code, data, and assets bundled with or required by CWLed are listed
in [ATTRIBUTION.md](ATTRIBUTION.md), along with their own licenses.