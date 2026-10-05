import os
import sys
import json

import data
import workspaceFolders
import logging
import git
from typing import Optional
from git.exc import InvalidGitRepositoryError
from datetime import datetime




class GitVersion:
  """
  Class to handle git version information.
  """

  version_tag: Optional[str] = None
  def __init__(self, 
               file_path: str):
    # add the standard logger logic here
    self.logger = logging.getLogger(__name__)
    self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        

    self.file_path = str(file_path)
    self.logger.debug(f"GitVersion initialized for file: {self.file_path}")

  def createVersionTag(self, version_tag:Optional[str]=None) -> str:
    """
    Creates a version tag based on the current date and time.
    Format: YYYYMMDD-HHMMSS
    """
    if version_tag:
      self.version_tag=version_tag
    else:
      self.version_tag=datetime.now().strftime('%Y%m%d-%H%M%S')
    self.logger.debug(f"Generated version tag: {self.version_tag}")
    return self.version_tag

  def _workspace_folder(self) -> Optional[str]:
    """The workspace folder containing the file, or the current workspace folder."""
    folder = workspaceFolders.containingFolder(self.file_path) if self.file_path else None
    return folder or workspaceFolders.currentFolder()

  def _repo_candidate_paths(self) -> list:
    """Return possible paths that may belong to the target git repo."""
    candidates = []
    if self.file_path:
      candidates.append(os.path.abspath(self.file_path))
      candidates.append(os.path.dirname(os.path.abspath(self.file_path)))
    workspace_folder = self._workspace_folder()
    if workspace_folder:
      candidates.append(os.path.abspath(workspace_folder))

    # Preserve order while removing duplicates.
    ordered = []
    seen = set()
    for path in candidates:
      if path and path not in seen:
        ordered.append(path)
        seen.add(path)
    return ordered

  def _open_repository(self, create_if_missing: bool = False):
    """Open the repository for this file, searching parent directories."""
    for candidate in self._repo_candidate_paths():
      try:
        return git.Repo(candidate, search_parent_directories=True)
      except InvalidGitRepositoryError:
        continue
      except Exception as e:
        self.logger.debug(f"Ignoring repo lookup error for {candidate}: {e}")

    workspace_folder = self._workspace_folder()
    if create_if_missing and workspace_folder:
      ws = os.path.abspath(workspace_folder)
      self.logger.info(f"No git repository found. Initializing one in {ws}.")
      return git.Repo.init(ws)

    raise InvalidGitRepositoryError("No git repository found")
  

  def createGitVersionCommit(self, commit_message:Optional[str]=None) -> None:
    """
    Creates a git commit and tag for the currently saved file.
    Initializes a git repo in the workspace if one doesn't exist.
    """
    if not self.file_path:
      self.logger.warning("File path not set. Skipping git versioning.")
      return
    
    # Check for repo or initialize it
    try:
      repo = self._open_repository(create_if_missing=True)
    except Exception as e:
      self.logger.error(f"Unable to open git repository: {e}")
      return

    repo_root = repo.working_tree_dir
    if not repo_root:
      self.logger.error("Repository has no working tree")
      return

    rel_file_path = os.path.relpath(
      os.path.abspath(self.file_path),
      os.path.abspath(repo_root)
    )
    self.logger.debug(f"Using git repository at {repo_root}")
    # Add the file to the staging area


    try:
      repo.index.add([rel_file_path])
    except Exception as e:
      self.logger.error(f"Error adding file {self.file_path} to git staging area: {e}")
      return
    self.logger.debug(f"Added {self.file_path} to git staging area.")
    # Create version tag
    if not self.version_tag:
        self.createVersionTag(None)

    # Create the commit
    try:
      if commit_message is None:
        commit_message = f"Autosave version for {self.file_path}"
      repo.index.commit(commit_message)
    except Exception as e:
      self.logger.error(f"Error creating git commit for file {self.file_path}: {e}")
      return
    self.logger.debug(f"Created git commit with message: '{commit_message}'")
    # Create the tag
    try:
      repo.create_tag(self.version_tag, message=f"Version: {self.version_tag}")
    except Exception as e:
      self.logger.error(f"Error creating git tag '{self.version_tag}': {e}")
      return
    self.logger.info(f"Created git commit and tag '{self.version_tag}' for {self.file_path}")

  def plannedCommitCommand(self, commit_message: Optional[str] = None) -> str:
    """Return the git commit command that will be executed in a future phase."""
    if commit_message:
      safe_message = commit_message.replace('"', '\\"')
      return f'git commit -m "{safe_message}"'
    return "git commit"

  def plannedPushCommand(self) -> str:
    """Return the git push command that will be executed in a future phase."""
    return "git push"

  def plannedPullCommand(self) -> str:
    """Return the git pull command that will be executed in a future phase."""
    return "git pull"

  def _active_branch_name(self, repo) -> str:
    """Return current branch name, raising if HEAD is detached."""
    try:
      if repo.head.is_detached:
        raise RuntimeError("HEAD is detached; checkout a branch first")
      return repo.active_branch.name
    except RuntimeError:
      raise
    except Exception as e:
      raise RuntimeError(f"Unable to determine active branch: {e}")

  def pushCurrentBranch(self) -> dict:
    """Push the currently checked out branch to the default remote."""
    try:
      repo = self._open_repository(create_if_missing=False)
    except InvalidGitRepositoryError:
      raise RuntimeError("No git repository found")

    try:
      remote = repo.remote()
    except Exception as e:
      raise RuntimeError(f"No configured remote found: {e}")

    branch_name = self._active_branch_name(repo)

    try:
      push_results = remote.push(branch_name)
    except Exception as e:
      raise RuntimeError(f"Push failed for branch '{branch_name}': {e}")

    errors = []
    summaries = []
    for item in push_results:
      summary = getattr(item, 'summary', '')
      if summary:
        summaries.append(summary)
      flags = getattr(item, 'flags', 0)
      error_flag = getattr(item, 'ERROR', 0)
      if error_flag and (flags & error_flag):
        errors.append(summary or "Unknown push error")

    if errors:
      raise RuntimeError("; ".join(errors))

    self.logger.info(
      f"Pushed branch '{branch_name}' to remote '{remote.name}'"
    )
    return {
      'branch': branch_name,
      'remote': remote.name,
      'summary': "\n".join(summaries).strip(),
    }

  def pullCurrentBranch(self) -> dict:
    """Pull updates for the currently checked out branch from default remote."""
    try:
      repo = self._open_repository(create_if_missing=False)
    except InvalidGitRepositoryError:
      raise RuntimeError("No git repository found")

    try:
      remote = repo.remote()
    except Exception as e:
      raise RuntimeError(f"No configured remote found: {e}")

    branch_name = self._active_branch_name(repo)

    try:
      pull_results = remote.pull(branch_name)
    except Exception as e:
      raise RuntimeError(f"Pull failed for branch '{branch_name}': {e}")

    summaries = []
    for item in pull_results:
      note = getattr(item, 'note', '') or getattr(item, 'name', '')
      if note:
        summaries.append(str(note))

    self.logger.info(
      f"Pulled branch '{branch_name}' from remote '{remote.name}'"
    )
    return {
      'branch': branch_name,
      'remote': remote.name,
      'summary': "\n".join(summaries).strip(),
    }

  def listLocalBranches(self) -> dict:
    """List local branches and indicate the currently checked out branch."""
    result = {
      'branches': [],
      'current_branch': None,
    }

    try:
      repo = self._open_repository(create_if_missing=False)
    except InvalidGitRepositoryError:
      return result
    except Exception as e:
      self.logger.error(f"Error reading local branches: {e}")
      return result

    try:
      result['branches'] = [h.name for h in repo.heads]
    except Exception as e:
      self.logger.error(f"Error collecting branch names: {e}")
      result['branches'] = []

    try:
      if not repo.head.is_detached:
        result['current_branch'] = repo.active_branch.name
    except Exception:
      result['current_branch'] = None

    return result

  def commitFileToBranch(self, branch_name: str, commit_message: str) -> dict:
    """Commit only the current file to the selected local branch."""
    if not self.file_path:
      raise RuntimeError("File path is not set")
    if not branch_name:
      raise RuntimeError("No target branch selected")
    if not commit_message or not commit_message.strip():
      raise RuntimeError("Commit message cannot be empty")

    # Check for repo or initialize it
    try:
      repo = self._open_repository(create_if_missing=True)
    except InvalidGitRepositoryError:
      raise RuntimeError("No git repository found")

    repo_root = repo.working_tree_dir
    if not repo_root:
      raise RuntimeError("Repository has no working tree")

    abs_file_path = os.path.abspath(self.file_path)
    abs_repo_root = os.path.abspath(repo_root)
    try:
      common_path = os.path.commonpath([abs_repo_root, abs_file_path])
    except Exception as e:
      raise RuntimeError(f"Unable to validate file path in repository: {e}")

    if common_path != abs_repo_root:
      raise RuntimeError(
        f"File '{abs_file_path}' is outside repository root '{abs_repo_root}'"
      )

    rel_file_path = os.path.relpath(abs_file_path, abs_repo_root)

    branch_names = [h.name for h in repo.heads]
    if branch_name not in branch_names:
      raise RuntimeError(f"Selected branch '{branch_name}' does not exist")

    original_branch = None
    try:
      if not repo.head.is_detached:
        original_branch = repo.active_branch.name
    except Exception:
      original_branch = None

    try:
      if original_branch != branch_name:
        repo.heads[branch_name].checkout()
    except Exception as e:
      raise RuntimeError(f"Unable to checkout branch '{branch_name}': {e}")

    # Detect whether this file has changes before committing.
    status = repo.git.status('--porcelain', '--', rel_file_path).strip()
    if not status:
      raise RuntimeError(f"No changes to commit for '{rel_file_path}'")

    try:
      repo.index.add([rel_file_path])
    except Exception as e:
      raise RuntimeError(f"Unable to stage '{rel_file_path}': {e}")

    try:
      commit = repo.index.commit(commit_message.strip())
    except Exception as e:
      raise RuntimeError(f"Unable to create commit: {e}")

    self.logger.info(
      f"Committed file '{rel_file_path}' to branch '{branch_name}' as {commit.hexsha[:12]}"
    )
    return {
      'branch': branch_name,
      'file': rel_file_path,
      'commit': commit.hexsha,
    }

  def pushTagToRemote(self, tag_name: str, remote_name: str = None) -> dict:
    """Push a git tag to the remote repository.
    
    Pushes a specific git tag to the remote repository. If no remote is specified,
    defaults to 'origin'. Useful for sharing version tags created with createGitVersionCommit().
    
    Args:
        tag_name: The name of the tag to push (e.g., 'v0.1.0')
        remote_name: The remote name to push to (default: 'origin')
    
    Returns:
        Dictionary with keys:
        - tag: The tag name pushed
        - remote: The remote name used
        - summary: Human-readable push result summary
    
    Raises:
        RuntimeError: If the tag doesn't exist, repo has no remotes, or push fails
    """
    candidate_paths = self._repo_candidate_paths()
    repo = self._open_repository(candidate_paths)
    
    # Validate tag exists
    try:
      tag_ref = repo.tags[tag_name]
    except IndexError:
      raise RuntimeError(f"Tag '{tag_name}' does not exist in repository")
    
    # Determine remote
    if not repo.remotes:
      raise RuntimeError("No remotes configured in repository")
    
    if remote_name is None:
      remote_name = 'origin'
    
    try:
      remote = repo.remote(remote_name)
    except ValueError:
      available = [r.name for r in repo.remotes]
      raise RuntimeError(
          f"Remote '{remote_name}' not found. Available remotes: {', '.join(available)}"
      )
    
    # Push tag with explicit refspec
    try:
      push_result = remote.push(refspec=f'refs/tags/{tag_name}:refs/tags/{tag_name}')
    except Exception as e:
      raise RuntimeError(f"Failed to push tag '{tag_name}' to '{remote_name}': {str(e)}")
    
    # Parse push results for errors
    for result in push_result:
      if result.flags & git.remote.RemoteProgress.ERROR:
        raise RuntimeError(
            f"Push failed: {result.summary}"
        )
    
    summary = f"Tag '{tag_name}' pushed successfully to '{remote_name}'"
    self.logger.info(summary)
    
    return {
      'tag': tag_name,
      'remote': remote_name,
      'summary': summary,
    }
