"""Ephemeral LLDB session for the current owner's WeChat; never persists keys.
PBKDF argument mapping and HMAC verification adapted from MIT wxkey, pinned in
THIRD_PARTY.md. Only launches the explicitly supplied private app copy.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import threading

from wechat_summary.cipher import Database, snapshot, verify_key

def capture(debugger,exe,paths,timeout):
    import lldb
    salts={}; macsalts={}
    for p in paths:
        with p.open('rb') as f: salt=f.read(16)
        salts.setdefault(salt,[]).append(p)
        macsalts.setdefault(bytes(x^0x3a for x in salt),[]).append(p)
    target=debugger.CreateTarget(str(exe)); bp=target.BreakpointCreateByName('CCKeyDerivationPBKDF')
    print('Target architecture: '+target.GetTriple()+'; breakpoint locations: '+str(bp.GetNumLocations()),flush=True)
    info=lldb.SBLaunchInfo([]); info.SetLaunchFlags(lldb.eLaunchFlagDebug | lldb.eLaunchFlagStopAtEntry)
    info.AddSuppressFileAction(1,False,True); info.AddSuppressFileAction(2,False,True)
    error=lldb.SBError(); process=target.Launch(info,error)
    if error.Fail(): raise RuntimeError('Cannot launch debug copy: '+str(error))
    found={}; deadline=time.monotonic()+timeout; hits=0; last_state=None
    timer=threading.Timer(timeout,lambda: process.Stop()); timer.daemon=True; timer.start()
    def read(addr,n):
        err=lldb.SBError(); value=process.ReadMemory(addr,n,err)
        return bytes(value) if err.Success() and len(value)==n else b''
    try:
        while time.monotonic()<deadline:
            state=process.GetState()
            if state!=last_state:
                print('Debug state: '+str(state)+'; breakpoint locations: '+str(bp.GetNumLocations()),flush=True); last_state=state
            if state==lldb.eStateStopped:
                for ti in range(process.GetNumThreads()):
                    thread=process.GetThreadAtIndex(ti)
                    if thread.GetStopReason() not in (lldb.eStopReasonBreakpoint,lldb.eStopReasonNone): print('Stop reason: '+str(thread.GetStopReason())+' '+str(thread.GetStopDescription(160)),flush=True)
                    if thread.GetStopReason()!=lldb.eStopReasonBreakpoint: continue
                    frame=thread.GetFrameAtIndex(0)
                    r=lambda n: frame.FindRegister('x'+str(n)).GetValueAsUnsigned()
                    alg,pwdptr,pwdlen,saltptr,saltlen,prf,rounds=[r(n) for n in range(7)]
                    hits+=1
                    if alg!=2 or prf!=5 or saltlen!=16 or not 0<pwdlen<=256: continue
                    salt=read(saltptr,16)
                    matches=salts.get(salt,[]) if rounds==256000 else macsalts.get(salt,[]) if rounds==2 and pwdlen==32 else []
                    if not matches: continue
                    value=read(pwdptr,pwdlen)
                    if len(value)!=pwdlen: continue
                    key=hashlib.pbkdf2_hmac('sha512',value,salt,256000,32) if rounds==256000 else value
                    for p in matches:
                        if p not in found and verify_key(p,key):
                            found[p]=bytearray(key)
                            print('Verified database key: '+p.parent.name+'/'+p.name,flush=True)
                if len(found)==len(paths): break
                process.Continue()
            elif state in (lldb.eStateExited,lldb.eStateCrashed,lldb.eStateDetached):
                raise RuntimeError('Debug copy exited before capture completed')
            time.sleep(.015)
        if process.GetState()!=lldb.eStateStopped: process.Stop()
        if len(found)!=len(paths):
            missing=[p.name for p in paths if p not in found]
            raise RuntimeError('Missing verified keys: '+', '.join(missing)+'; PBKDF calls='+str(hits))
        timer.cancel()
        return process,found
    except BaseException:
        timer.cancel()
        process.Kill()
        for value in found.values(): value[:]=b'\0'*len(value)
        raise

def inventory(root):
    return [root/'db_storage/contact/contact.db']+sorted((root/'db_storage/message').glob('message_[0-9]*.db'))


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--account',required=True); ap.add_argument('--app',required=True); ap.add_argument('--socket',required=True); ap.add_argument('--timeout',type=int,default=180)
    a=ap.parse_args(); signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    root=Path(a.account).resolve(); app=Path(a.app).resolve(); sockpath=Path(a.socket).resolve()
    if not (app.parent.name=='.private' and app.name=='WeChat-capture.app'): raise RuntimeError('Refusing unmanaged app path')
    paths=inventory(root)
    if len(paths)<2 or not all(p.is_file() for p in paths): raise RuntimeError('Missing account DB files')
    import lldb
    debugger=None; process=None; keys={}; server=None; bound=False; restart=False
    original=Path('/Applications/WeChat.app/Contents/MacOS/WeChat')
    def restore():
        if restart and not subprocess.run(['pgrep','-f','^'+str(original)+'$'],capture_output=True).stdout:
            subprocess.Popen([str(original)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)
    try:
        oldpids=subprocess.run(['pgrep','-x','WeChat'],capture_output=True,text=True).stdout.split()
        if len(oldpids)>1: raise RuntimeError('Multiple WeChat processes; refuse account ambiguity')
        for pid in oldpids:
            command=subprocess.check_output(['ps','-p',pid,'-o','comm='],text=True).strip()
            if command!=str(original): raise RuntimeError('Other WeChat instance detected; refusing to mix accounts')
        server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        server.bind(str(sockpath)); bound=True; os.chmod(sockpath,0o600); server.listen(1)
        debugger=lldb.SBDebugger.Create(); debugger.SetAsync(False)
        restart=True
        for pid in oldpids: os.kill(int(pid),signal.SIGTERM)
        until=time.monotonic()+15
        for pid in oldpids:
            while time.monotonic()<until:
                try: os.kill(int(pid),0)
                except ProcessLookupError: break
                time.sleep(.2)
            else: raise RuntimeError('Original WeChat did not exit normally')
        process,keys=capture(debugger,app/'Contents/MacOS/WeChat',paths,a.timeout)
        if inventory(root)!=paths: raise RuntimeError('Shard inventory changed during startup; retry after sync settles')
        snapshot_at=int(time.time())
        with snapshot(paths) as copies:
            process.Kill(); process=None; restore()
            print('READY: encrypted snapshots available; original WeChat relaunched',flush=True)
            session_end=time.monotonic()+900
            while time.monotonic()<session_end:
                server.settimeout(max(.1,session_end-time.monotonic()))
                try: conn,_=server.accept()
                except socket.timeout: break
                with conn:
                    conn.settimeout(min(15,max(.1,session_end-time.monotonic())))
                    try:
                        request=b''
                        while b'\n' not in request:
                            piece=conn.recv(65536)
                            if not piece: raise ValueError('Incomplete request')
                            request+=piece
                            if len(request)>1_000_000: raise ValueError('Request too large')
                        cmd=json.loads(request)
                        if cmd['op']=='stop': conn.sendall(b'{"ok":true}\n'); break
                        if cmd['op']=='schema':
                            data={}
                            for p in paths:
                                with Database(copies[p],keys[p]) as db:
                                    data[str(p.relative_to(root))]=db.query("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                        elif cmd['op']=='export':
                            from wechat_summary import reader
                            importlib.reload(reader)
                            cmd['_snapshot_at']=snapshot_at
                            if 'start_ts' not in cmd:
                                from wechat_summary.messages import time_window
                                from datetime import datetime
                                from wechat_summary.messages import TZ
                                cmd['start_ts'],cmd['end_ts']=time_window(hours=cmd.get('hours',24),start=cmd.get('start'),end=cmd.get('end'),now=datetime.fromtimestamp(snapshot_at,TZ))
                            data=reader.export(root,paths,copies,keys,cmd)
                        else: raise ValueError('Unknown operation')
                        conn.sendall(json.dumps({'ok':True,'data':data},ensure_ascii=False).encode()+b'\n')
                    except Exception as e:
                        try: conn.sendall(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False).encode()+b'\n')
                        except OSError: pass
    finally:
        if process: process.Kill()
        for value in keys.values(): value[:]=b'\0'*len(value)
        keys.clear()
        if server: server.close()
        if bound: sockpath.unlink(missing_ok=True)
        restore()
        if debugger: lldb.SBDebugger.Destroy(debugger)
        print('Session ended; keys cleared and snapshots removed',flush=True)

if __name__=='__main__': main()
