from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
import subprocess
import os
import sys

path = os.path.abspath(os.path.dirname(__file__))
sys.path.append(path)

# Import the base version
import importlib.util
spec = importlib.util.spec_from_file_location("version_module", os.path.join(path, "opensnitch", "version.py"))
version_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version_module)
base_version = version_module.version

def get_git_commit():
    """Get the current git commit hash during build."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
            # Check if there are uncommitted changes
            dirty_result = subprocess.run(
                ['git', 'diff-index', '--quiet', 'HEAD', '--'],
                cwd=path,
                timeout=2
            )
            if dirty_result.returncode != 0:
                commit += '-dirty'
            return commit
    except Exception as e:
        print(f"Warning: Could not get git commit: {e}")
    return None

def write_version_info(commit):
    """Write version info with hardcoded git commit to _version_info.py"""
    version_info_path = os.path.join(path, 'opensnitch', '_version_info.py')
    
    with open(version_info_path, 'w') as f:
        f.write(f'# Auto-generated during build - do not edit manually\n')
        f.write(f'build_commit = {repr(commit)}\n')

# Get git commit and create full version string
git_commit = get_git_commit()
if git_commit:
    full_version = f"{base_version}+git.{git_commit}"
else:
    full_version = base_version

class CustomBuildPyCommand(build_py):
    """Custom build_py command that records git commit during wheel build."""
    def run(self):
        write_version_info(git_commit)
        build_py.run(self)

setup(name='opensnitch-ui',
      version=full_version,
      description='Prompt service and UI for the opensnitch interactive firewall application.',
      cmdclass={
          'build_py': CustomBuildPyCommand,
      },
      long_description='GUI for the opensnitch interactive firewall application\n\
opensnitch-ui is a GUI for opensnitch written in Python.\n\
It allows the user to view live outgoing connections, as well as search\n\
to make connections.\n\
.\n\
The user can decide if block the outgoing connection based on properties of\n\
the connection: by port, by uid, by dst ip, by program or a combination\n\
of them.\n\
.\n\
These rules can last forever, until the app restart or just one time.',
      url='https://github.com/evilsocket/opensnitch',
      author='Simone "evilsocket" Margaritelli',
      author_email='evilsocket@protonmail.com',
      license='GPL-3.0',
      packages=find_packages(),
      include_package_data = True,
      package_data={'': ['*.*']},
      data_files=[('/usr/share/applications', ['resources/opensnitch_ui.desktop']),
               ('/usr/share/kservices5', ['resources/kcm_opensnitch.desktop']),
               ('/usr/share/icons/hicolor/scalable/apps', ['resources/icons/opensnitch-ui.svg']),
               ('/usr/share/icons/hicolor/48x48/apps', ['resources/icons/48x48/opensnitch-ui.png']),
               ('/usr/share/icons/hicolor/64x64/apps', ['resources/icons/64x64/opensnitch-ui.png']),
               ('/usr/share/metainfo', ['resources/io.github.evilsocket.opensnitch.appdata.xml'])],
      scripts = [ 'bin/opensnitch-ui' ],
      zip_safe=False)
