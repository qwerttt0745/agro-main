"""Regression tests for model-cache symlinks during pre-migration backup."""
import json
import sqlite3
import pytest
from scripts.migrate_users import snapshot, verify, migrate


def test_snapshot_prunes_huggingface_cache_and_keeps_private_files(tmp_path):
    profile=tmp_path/'farm_profile.json'
    profile.write_text('{"crops":["corn"]}')
    (tmp_path/'site').mkdir()
    (tmp_path/'site/summary.json').write_text('{"point":{"latitude":49,"longitude":29}}')
    cache=tmp_path/'hf-cache/models--example/snapshots/revision'
    cache.mkdir(parents=True)
    (cache/'config.json').symlink_to(tmp_path/'model-blob')
    (tmp_path/'model-blob').write_text('not a JSON document')
    # Even a symlinked directory inside the excluded cache must never be visited.
    (cache/'another-directory').symlink_to(tmp_path/'site',target_is_directory=True)
    folder=snapshot(tmp_path)
    manifest=verify(folder)
    assert 'chats.db' in manifest['files']
    assert 'farm_profile.json' in manifest['files']
    assert 'site/summary.json' in manifest['files']
    assert not (folder/'hf-cache').exists()
    assert (folder/'farm_profile.json').read_bytes()==profile.read_bytes()


def test_private_json_symlink_is_still_rejected(tmp_path):
    (tmp_path/'original').write_text('{}')
    (tmp_path/'farm_profile.json').symlink_to(tmp_path/'original')
    with pytest.raises(ValueError,match='farm_profile.json'):snapshot(tmp_path)


def test_private_directory_symlink_is_still_rejected(tmp_path):
    real=tmp_path/'original';real.mkdir()
    (real/'summary.json').write_text('{}')
    (tmp_path/'site').symlink_to(real,target_is_directory=True)
    with pytest.raises(ValueError,match='site'):snapshot(tmp_path)


def test_backup_verification_rejects_symlink_even_inside_backup(tmp_path):
    (tmp_path/'farm_profile.json').write_text('{}')
    folder=snapshot(tmp_path)
    profile=folder/'farm_profile.json'
    profile.rename(folder/'original')
    profile.symlink_to(folder/'original')
    with pytest.raises(ValueError,match='checksum'):verify(folder)


def test_full_legacy_migration_accepts_model_cache_symlinks(tmp_path):
    from test_multiuser import legacy
    legacy(tmp_path)
    cache=tmp_path/'hf-cache/models--test/snapshots/revision'
    cache.mkdir(parents=True)
    (cache/'tokenizer.json').symlink_to(tmp_path/'not-needed-model-blob')
    folder=migrate(tmp_path)
    assert verify(folder)
    with sqlite3.connect(tmp_path/'auth.db') as c:
        assert c.execute('SELECT username FROM users').fetchone()[0]=='owner'
    with sqlite3.connect(tmp_path/'chats.db') as c:
        assert c.execute('SELECT content FROM messages').fetchone()[0]=='private-question'
