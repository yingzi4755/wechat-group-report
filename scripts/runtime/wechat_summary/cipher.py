"""SQLCipher C API: keys never enter argv, logs or persistent configuration.

Only open private encrypted snapshots in read-only mode. Native SQLCipher checks
page HMACs on reads and SQLite resolves committed WAL frames. No plaintext DB.
"""
import ctypes as C
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import tempfile
from contextlib import contextmanager

LIB = os.environ.get('WECHAT_SQLCIPHER_LIB', '/opt/homebrew/opt/sqlcipher/lib/libsqlcipher.dylib')

def _library():
    lib=C.CDLL(LIB)
    definitions={
      'sqlite3_open_v2':([C.c_char_p,C.POINTER(C.c_void_p),C.c_int,C.c_char_p],C.c_int),
      'sqlite3_close_v2':([C.c_void_p],C.c_int),
      'sqlite3_key':([C.c_void_p,C.c_void_p,C.c_int],C.c_int),
      'sqlite3_prepare_v2':([C.c_void_p,C.c_char_p,C.c_int,C.POINTER(C.c_void_p),C.c_void_p],C.c_int),
      'sqlite3_step':([C.c_void_p],C.c_int),
      'sqlite3_finalize':([C.c_void_p],C.c_int),
      'sqlite3_column_count':([C.c_void_p],C.c_int),
      'sqlite3_column_name':([C.c_void_p,C.c_int],C.c_char_p),
      'sqlite3_column_type':([C.c_void_p,C.c_int],C.c_int),
      'sqlite3_column_int64':([C.c_void_p,C.c_int],C.c_int64),
      'sqlite3_column_double':([C.c_void_p,C.c_int],C.c_double),
      'sqlite3_column_blob':([C.c_void_p,C.c_int],C.c_void_p),
      'sqlite3_column_bytes':([C.c_void_p,C.c_int],C.c_int),
      'sqlite3_bind_int64':([C.c_void_p,C.c_int,C.c_int64],C.c_int),
      'sqlite3_bind_text':([C.c_void_p,C.c_int,C.c_char_p,C.c_int,C.c_void_p],C.c_int),
      'sqlite3_bind_null':([C.c_void_p,C.c_int],C.c_int),
    }
    for name,(args,res) in definitions.items():
        f=getattr(lib,name); f.argtypes=args; f.restype=res
    return lib

class Database:
    def __init__(self,path,key,readonly=True):
        if len(key)!=32: raise ValueError('Expected 32-byte verified encryption key')
        self.lib=_library(); self.db=C.c_void_p()
        rc=self.lib.sqlite3_open_v2(os.fsencode(path),C.byref(self.db),1 if readonly else 6,None)
        if rc:
            self.close(); raise RuntimeError('Cannot open SQLCipher database (code %s)'%rc)
        raw=C.create_string_buffer(("x'"+bytes(key).hex()+"'").encode())
        try:
            if self.lib.sqlite3_key(self.db,raw,len(raw.value)):
                raise RuntimeError('SQLCipher key setup failed')
            self.query('PRAGMA cipher_compatibility=4')
            self.query('PRAGMA cipher_memory_security=ON')
            self.query('PRAGMA temp_store=MEMORY')
            if readonly: self.query('PRAGMA query_only=ON')
            self.query('SELECT count(*) FROM sqlite_master')
        except BaseException:
            self.close(); raise
        finally: C.memset(raw,0,len(raw))
    def query(self,sql,params=()):
        stmt=C.c_void_p()
        rc=self.lib.sqlite3_prepare_v2(self.db,sql.encode(),-1,C.byref(stmt),None)
        if rc: raise RuntimeError('SQLCipher prepare failed (code %s)'%rc)
        try:
            for i,v in enumerate(params,1):
                if v is None: rc=self.lib.sqlite3_bind_null(stmt,i)
                elif isinstance(v,int): rc=self.lib.sqlite3_bind_int64(stmt,i,v)
                else:
                    b=str(v).encode(); rc=self.lib.sqlite3_bind_text(stmt,i,b,len(b),C.c_void_p(-1))
                if rc: raise RuntimeError('SQLCipher bind failed')
            result=[]
            while True:
                rc=self.lib.sqlite3_step(stmt)
                if rc==101: break
                if rc!=100: raise RuntimeError('SQLCipher read failed (code %s)'%rc)
                row={}
                for i in range(self.lib.sqlite3_column_count(stmt)):
                    name=self.lib.sqlite3_column_name(stmt,i).decode(); kind=self.lib.sqlite3_column_type(stmt,i)
                    if kind==1: val=self.lib.sqlite3_column_int64(stmt,i)
                    elif kind==2: val=self.lib.sqlite3_column_double(stmt,i)
                    elif kind==5: val=None
                    else:
                        size=self.lib.sqlite3_column_bytes(stmt,i); ptr=self.lib.sqlite3_column_blob(stmt,i)
                        val=C.string_at(ptr,size) if size else b''
                        if kind==3: val=val.decode('utf-8','strict')
                    row[name]=val
                result.append(row)
            return result
        finally: self.lib.sqlite3_finalize(stmt)
    def close(self):
        if self.db: self.lib.sqlite3_close_v2(self.db); self.db=None
    def __enter__(self): return self
    def __exit__(self,*exc): self.close()

def verify_key(path,key):
    with open(path,'rb') as f: page=f.read(4096)
    if len(page)!=4096 or len(key)!=32: return False
    mk=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in page[:16]),2,32)
    return hmac.compare_digest(hmac.new(mk,page[16:4032]+(1).to_bytes(4,'little'),hashlib.sha512).digest(),page[4032:])

@contextmanager
def snapshot(paths):
    """Caller MUST quiesce database writer across entire copy (SIGSTOP/closed).
    Copy encrypted DB+WAL only; SHM rebuilt by SQLite in private writable dir.
    Metadata checks reject observed movement, not a replacement for quiescing.
    """
    paths=list(paths)
    with tempfile.TemporaryDirectory(prefix='wechat-summary-') as folder:
        os.chmod(folder,0o700); copies={}
        for i,path in enumerate(paths):
            path=Path(path); dest=Path(folder)/str(i)/path.name; dest.parent.mkdir(mode=0o700)
            for suffix in ('','-wal'):
                src=Path(str(path)+suffix)
                if not src.exists(): continue
                before=src.stat(); shutil.copyfile(src,str(dest)+suffix); after=src.stat()
                os.chmod(str(dest)+suffix,0o600)
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                    raise RuntimeError('Database changed during snapshot; writer must be stopped')
            copies[path]=dest
        yield copies
