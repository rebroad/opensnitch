import subprocess
import os

version = '1.7.3'

def get_git_commit():
    """Get the current git commit hash (short form) for development versions."""
    try:
        # Get the directory where this file is located
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate up to the repository root (assuming standard structure)
        repo_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))

        # Get the short commit hash
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            commit = result.stdout.strip()

            # Check if there are uncommitted changes
            dirty_result = subprocess.run(
                ['git', 'diff-index', '--quiet', 'HEAD', '--'],
                cwd=repo_root,
                timeout=2
            )

            if dirty_result.returncode != 0:
                commit += '-dirty'

            return commit
    except Exception:
        pass

    return None

def get_version_string():
    """Get the version string, including git commit for development builds."""
    commit = get_git_commit()
    if commit:
        return f"{version} (git:{commit})"
    return version
