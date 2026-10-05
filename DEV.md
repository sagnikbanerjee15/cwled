
## Manage dependencies with uv

To sync the dependencies:
```bash
uv sync
```

To add a new dependency:
```bash
uv add <package_name>
```

To add a dev dependency:
```bash
uv add --group dev <package_name>
```

## Create a release build

Production releases are automated using GitHub Actions.

Create the public repo (once)
```bash
git remote add public https://github.com/kmavrommatis/cwled.git
```

### Automated Release Process

To trigger an automated production release:
1. Update the version and write your release notes in `NOTES.txt`.
2. Run `make release` with your GitHub Personal Access Token (`GITHUB_PAT`):
   ```bash
   export GITHUB_PAT=your_token_here
   make release
   ```

The Makefile will automatically:
- Read the version from `NOTES.txt`.
- Update internal version numbers in the source files.
- Commit the version update, create a release branch (`v<version>`), tag it, and push both to the public GitHub repository.
- Switch back to `main`.

Once pushed, the **GitHub Actions** workflow (`Build and Release`) will:
- Spin up macOS and Linux runners to compile production bundles.
- Build the macOS DMG installer and Linux tarball.
- Parse `NOTES.txt` to populate the GitHub Release body.
- Create a new draft/published release on GitHub and attach both build artifacts.


## Local Debugging Builds

Local builds are supported **exclusively for debugging purposes**. For production, always use the automated GitHub Actions release workflow.

Ensure dev dependencies are synced:
```bash
uv sync --group dev
```

### Local macOS Debug Build
To build and package the application as a macOS `.app` and `.dmg` locally for debugging:
```bash
make debug-mac
```
This runs PyInstaller, structures the distribution folder, and packages it into `dist/CWLed-Installer.dmg` using `hdiutil`.

### Local Linux Debug Build
To build and package the application as a Linux executable and tarball locally for debugging:
```bash
make debug-linux
```
This runs PyInstaller, sets up a wrapper script (`run.sh`), and creates `dist/CWLed-Linux.tar.gz`.



## Automated tests

The GUI is tested without a display: the tests run the application on Qt's `offscreen` platform and drive it with simulated mouse and key events (`pytests/conftest.py` explains the setup: the configuration, logs and caches are temporary, nothing of the user's is read or written).

```bash
uv sync --group dev
uv run pytest                      # everything, about a minute
uv run pytest pytests/test_graph_canvas.py -k pan    # a part of it
```

The test code is in `pytests/`; `tests/` holds only CWL documents, which are the fixtures the tests (and the manual checks) open. The tests are run by GitHub Actions on every push to `main` and on pull requests (`.github/workflows/tests.yml`).

What the automated tests cannot see (a real screen, trackpad, native menus, the operating system's file watcher) is listed, feature by feature, in [docs/MANUAL-TESTS.md](docs/MANUAL-TESTS.md): go through it by hand before a release.

## Tests to run 

```
cd cwled
uv run ./cwled.py

# Opens the application
```

### Test the Workspace buttons
Click 'Set' and set the workspace. A file dialog should open confirming the new directory.
Click 'Open Workspace' and verify the workspace opens.
Click 'Sort by Name' and 'Sort by Date' and verify the file list is sorted accordingly.
Click 'Rescan' and verify the file list is refreshed.
Click 'Close' and verify the Dialog closes.
Select a file from the list and click 'Open Selected File'.

### Test the Editor buttons
Click 'Create CommandLineTool' and verify the command line editor opens.

Go to App
 add an argument and verify it is added to the command line.
 add an input file and verify it is added to the command line. Type File, with secondary files, of certain format.
 add an output file and verify it is added to the command line. Type File, with secondary files, of certain format.

## The logo

The mark is described once, in `cwled/logo.py` (SVG text), and the files of `resources/logo` and the icon of the application (`resources/icons/cwled.png` and `cwled.icns`) are made from it:

```bash
uv run python resources/logo/make_logo.py
```

Run it again after changing `cwled/logo.py` (a test fails when the files are not the ones the code describes). The window that shows while the application starts is `cwled/SplashScreen.py`; `cwled.py` starts it before importing the rest, and `main.main()` reports the steps. Turn it off with `--no-splash`, `CWLED_NO_SPLASH=1` or `show_splash: false`.
