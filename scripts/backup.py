"""Create a verifiable local snapshot without copying the API key or Chroma live files."""
import os
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from app import config


def create_backup(destination=None):
    root = Path(destination) if destination else config.DATA / 'backups'
    folder = root / datetime.now(timezone.utc).strftime('farm-%Y%m%dT%H%M%S-%fZ')
    folder.mkdir(parents=True, exist_ok=False,mode=0o700)
    for name in ('chats.db','auth.db'):
        path=config.CHATS_DB if name=='chats.db' else config.DATA/name
        if not path.exists():continue
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as source, sqlite3.connect(folder/name) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise RuntimeError('Database integrity check failed')
        os.chmod(folder/name,0o600)
    for name in ('auth_credentials.json','farm_profile.json','library_manifest.json','site/summary.json'):
        path = config.DATA / name
        if path.exists():
            output=folder / name;output.parent.mkdir(parents=True,exist_ok=True)
            output.write_bytes(path.read_bytes());os.chmod(output,0o600)
    files = {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in folder.rglob('*') if p.is_file()}
    (folder/'checksums.json').write_text(json.dumps(files,indent=2))
    return folder


def verify(folder):
    folder=Path(folder)
    expected=json.loads((folder/'checksums.json').read_text())
    for name,digest in expected.items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Backup verification failed')
    for name in ('chats.db','auth.db'):
        if name not in expected:continue
        with sqlite3.connect(f'file:{folder/name}?mode=ro',uri=True) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('Database integrity check failed')
    return True


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Локальна копія чатів, фото та профілю. Без ключа API; книги й індекс не включено.')
    parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:
        verify(args.verify);print('Копію перевірено')
    else:
        folder=create_backup();verify(folder);print(f'Копію створено й перевірено: {folder}')
