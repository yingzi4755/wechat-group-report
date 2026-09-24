#!/usr/bin/env python3
"""Install only the skill's pinned Python dependencies in its own virtualenv."""
from pathlib import Path
import subprocess
import sys
import venv

if sys.version_info<(3,12):
    raise SystemExit('Use Python 3.12+ to set up the tested environment; Codex load_workspace_dependencies can locate it.')
root=Path(__file__).resolve().parents[1];env=root/'.venv'
venv.EnvBuilder(with_pip=True).create(env)
subprocess.run([str(env/'bin/python'),'-m','pip','install','-r',str(root/'scripts/requirements.lock')],check=True)
print('Ready:',env/'bin/python')
