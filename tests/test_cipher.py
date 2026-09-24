from pathlib import Path
import os
import pytest
from wechat_summary.cipher import Database, snapshot, verify_key


def test_encrypted_wal_readonly_and_cleanup(tmp_path):
    path=tmp_path/'source.db'; key=os.urandom(32)
    with Database(path,key,readonly=False) as db:
        db.query('CREATE TABLE items(id INTEGER, text TEXT)')
        db.query('PRAGMA journal_mode=WAL')
        db.query('PRAGMA wal_autocheckpoint=0')
        db.query("INSERT INTO items VALUES (1, '已提交中文')")
        db.query('BEGIN')
        db.query("INSERT INTO items VALUES (2, '未提交')")
        before=path.read_bytes()
        assert verify_key(path,key)
        assert not verify_key(path,os.urandom(32))
        with snapshot([path]) as copies:
            location=copies[path]
            with Database(location,key) as read:
                assert read.query('SELECT * FROM items')==[{'id':1,'text':'已提交中文'}]
                with pytest.raises(RuntimeError):
                    read.query('DELETE FROM items')
            assert path.read_bytes()==before
        assert not location.exists()
        db.query('ROLLBACK')
    with pytest.raises(ValueError):
        with snapshot([path]) as copies:
            location=copies[path]
            raise ValueError('test failure')
    assert not location.exists()


def test_wrong_key_fails_without_secret(tmp_path):
    p=tmp_path/'a.db'; k=os.urandom(32)
    with Database(p,k,readonly=False) as d: d.query('CREATE TABLE a(x)')
    bad=os.urandom(32)
    with pytest.raises(RuntimeError) as e:
        with Database(p,bad) as d: d.query('SELECT * FROM a')
    assert bad.hex() not in str(e.value)


def test_spilled_uncommitted_wal_and_authenticated_page(tmp_path):
    p=tmp_path/'spill.db';k=os.urandom(32)
    with Database(p,k,False) as db:
        db.query('CREATE TABLE data(id INTEGER PRIMARY KEY, body TEXT)')
        db.query('PRAGMA journal_mode=WAL');db.query('PRAGMA wal_autocheckpoint=0')
        db.query('INSERT INTO data(body) VALUES (?)',('committed',))
        wal=Path(str(p)+'-wal');before=wal.stat().st_size
        db.query('PRAGMA cache_size=5');db.query('PRAGMA cache_spill=ON');db.query('BEGIN')
        for n in range(80): db.query('INSERT INTO data(body) VALUES (?)',('x'*3000,))
        assert wal.stat().st_size>before, 'Test must actually spill uncommitted frames'
        with snapshot([p]) as files:
            with Database(files[p],k) as read:
                assert read.query('SELECT count(*) AS n FROM data')==[{'n':1}]
        db.query('ROLLBACK')
    data=bytearray(p.read_bytes());data[4200]^=1;p.write_bytes(data)
    with pytest.raises(RuntimeError):
        with Database(p,k) as read: read.query('SELECT * FROM data')
