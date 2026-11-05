"""Configured Windows launch must not fork the migrated durable database."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows migration guard')
def test_worker_migration_guard_precedes_store_import(tmp_path):
    database=tmp_path/'must-not-exist.db'
    config=tmp_path/'server.env'
    config.write_text('LOCAL_API_RUNTIME=wsl\nINVESTIFY_DB_PATH='+str(database)+'\n')
    result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve().parents[2]/'scripts/run_room_worker.py'),
                           '--env-file',str(config)],capture_output=True,text=True,timeout=10)
    assert result.returncode==2
    assert 'migrated to Investify WSL' in result.stderr
    assert not database.exists()
