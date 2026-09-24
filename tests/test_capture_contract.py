"""Regression for observed LLDB launch flags and credential-free diagnostics."""
from pathlib import Path

def test_debug_flag_preserved_and_no_key_write():
    s=(Path(__file__).resolve().parents[1] / 'scripts/runtime/wechat_summary/capture_session.py').read_text()
    assert 'lldb.eLaunchFlagDebug | lldb.eLaunchFlagStopAtEntry' in s
    assert 'info.SetLaunchFlags(0)' not in s
    assert 'key.hex()' not in s
    assert 'keys.json' not in s
