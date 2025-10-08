version = '1.7.3'

def get_build_commit():
    """Get the commit hash that was hardcoded during installation."""
    try:
        from . import _version_info
        return _version_info.build_commit
    except (ImportError, AttributeError):
        return None

def get_version_string():
    """Get the version string, including git commit if it was hardcoded during installation.
    Does NOT fallback to dynamic git query to avoid misleading version info."""
    # Only use the build commit that was hardcoded during pip install
    commit = get_build_commit()
    
    if commit:
        return f"{version} (git:{commit})"
    return version
