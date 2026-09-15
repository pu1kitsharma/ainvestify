"""Explicit tenant reset with a verified, full SQLite backup. No automatic startup reset."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def reset(db_path, tenant_id, backup_dir):
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True,exist_ok=False)
    with sqlite3.connect(db_path) as source:
        for table in ('operating_workspaces','web_sourcing_runs'):
            for (raw,) in source.execute('SELECT data FROM '+table+' WHERE tenant_id=?',(tenant_id,)):
                data = json.loads(raw)
                job = data.get('automation') if table == 'operating_workspaces' else data
                if job and job.get('status') in {'queued','running','cancel_requested'}:
                    raise ValueError('Stop active company jobs before resetting their records.')
        tables = [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if row[0] != 'sqlite_sequence']
        counts = {table:source.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=?',(tenant_id,)).fetchone()[0] for table in tables}
        backup_path = backup_dir/'company-workspace.sqlite3'
        with sqlite3.connect(backup_path) as backup:
            source.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup integrity check failed; records were not cleared.')
            for table,count in counts.items():
                if backup.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=?',(tenant_id,)).fetchone()[0] != count:
                    raise ValueError('Backup row counts differ; records were not cleared.')
        source.execute('BEGIN IMMEDIATE')
        for table in tables:
            source.execute('DELETE FROM '+table+' WHERE tenant_id=?',(tenant_id,))
        source.commit()
        after = {table:source.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=?',(tenant_id,)).fetchone()[0] for table in tables}
    manifest = {'tenant':tenant_id,'at':datetime.now(timezone.utc).isoformat(),'backup':str(backup_path.resolve()),'before':counts,'after':after}
    (backup_dir/'reset.json').write_text(json.dumps(manifest,indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--tenant',required=True)
    parser.add_argument('--backup-dir',required=True)
    parser.add_argument('--confirm-reset',action='store_true',required=True)
    args = parser.parse_args()
    print(json.dumps(reset(args.database,args.tenant,args.backup_dir),indent=2))
