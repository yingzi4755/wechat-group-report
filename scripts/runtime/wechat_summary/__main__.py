"""Local collector / renderer. Semantic summarization is done by Codex session."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import queue
import threading
import shutil
import subprocess
import sys
import time
from uuid import uuid4
from wechat_summary.session_client import request
from wechat_summary.messages import TZ

PROJECT=Path(__file__).resolve().parent.parent
DATA=Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'


def accounts(): return sorted(p for p in DATA.glob('*') if (p/'db_storage/contact/contact.db').is_file())


def write_export(data,out):
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    (out/'messages.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    meta=data['metadata'];entries=[]
    for m in data['messages']:
        text='[%s] %s %s (%s)\n%s'%(m['id'],m['time'],m['sender_name'],m['type'],m['text'])
        for field in ('quote','card','parse_warning'):
            if m.get(field): text+='\n'+field+': '+json.dumps(m[field],ensure_ascii=False)
        entries.append(text)
    header='%s | %s\n[%s, %s) %s\n消息 %s；发言人 %s\n%s\n%s\n\n'%(meta['group_name'],meta['group_id'],meta['start'],meta['end'],meta['timezone'],meta['message_count'],meta['speaker_count'],meta['scope'],'\n'.join(meta['warnings']))
    (out/'messages.txt').write_text(header+'\n\n'.join(entries)+'\n',encoding='utf-8')
    chunks=[];batch=[];count=0;folder=out/'review-batches';folder.mkdir()
    for m,text in zip(data['messages'],entries):
        if batch and count+len(text)>20000:
            chunks.append(batch);batch=[];count=0
        batch.append((m['id'],text));count+=len(text)
    if batch: chunks.append(batch)
    manifest=[]
    for i,batch in enumerate(chunks,1):
        name='%04d.txt'%i
        (folder/name).write_text('\n\n'.join(t for _,t in batch)+'\n',encoding='utf-8')
        manifest.append({'file':name,'message_ids':[mid for mid,_ in batch]})
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SUMMARIZE.md').write_text('请当前 Codex 会话读取 messages.json 和 review-batches/manifest.json 中全部批次后，生成 report.json。\n严格按此skill references/report-schema.md 的接口；每个重要结论关联实际消息ID，不把建议当决定、收到当同意、同意当完成，不描述未解析媒体。无负责人/期限填写“未明确”。coverage 必须列出全部已阅读消息ID。然后执行 python -m wechat_summary render 本目录。\n本命令只采集，不调用模型API，也不独立生成语义总结。\n',encoding='utf-8')


def prepare_app():
    private=PROJECT/'.private';private.mkdir(mode=0o700,exist_ok=True);private.chmod(0o700)
    app=private/'WeChat-capture.app'
    if not app.exists():
        subprocess.run(['ditto','--noextattr','--noqtn','/Applications/WeChat.app',str(app)],check=True)
        subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True,capture_output=True)
    return app


def remove_app(app):
    register='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
    if app.exists():
        subprocess.run([register,'-u',str(app)],capture_output=True)
        shutil.rmtree(app)


def collect(a):
    group=a.group or input('请输入微信群完整名称：').strip()
    if not group: raise ValueError('群名不能为空')
    roots=accounts()
    if a.account: roots=[p for p in roots if p.name==a.account]
    if len(roots)!=1: raise ValueError('需要用 --account 明确选择一个账号：'+', '.join(p.name for p in roots))
    if not a.allow_restart:
        if input('采集需短暂重启临时微信副本，完成后恢复原版；允许请输入 yes：').strip().lower()!='yes': raise ValueError('未允许临时重启')
    app=prepare_app();sock=PROJECT/'.private'/('session-'+uuid4().hex[:8]+'.sock')
    env=os.environ.copy();env['PYTHONPATH']=subprocess.check_output(['/usr/bin/lldb','-P'],text=True).strip()+os.pathsep+str(PROJECT)
    command=['/usr/bin/python3','-m','wechat_summary.capture_session','--account',str(roots[0]),'--app',str(app),'--socket',str(sock),'--timeout',str(a.timeout)]
    worker=None
    try:
        worker=subprocess.Popen(command,cwd=PROJECT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        ready=False;deadline=time.monotonic()+a.timeout+60
        lines=queue.Queue()
        def pump():
            for line in worker.stdout: lines.put(line)
            lines.put(None)
        thread=threading.Thread(target=pump,daemon=True);thread.start()
        while time.monotonic()<deadline:
            try: line=lines.get(timeout=1)
            except queue.Empty:
                if worker.poll() is not None: break
                continue
            if line is None: break
            print(line,end='',flush=True)
            if line.startswith('READY:'): ready=True;break
        if not ready: raise RuntimeError('捕获未成功；请检查微信登录状态。未生成消息报告。')
        cmd={'op':'export','group':group,'group_id':a.group_id,'hours':a.hours,'start':a.start,'end':a.end}
        data=request(cmd,sock)
        out=Path(a.out).resolve() if a.out else PROJECT/'outputs'/('run-'+datetime.now(TZ).strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6])
        write_export(data,out)
        print('已完整导出 %s 条本地消息，%s 位发言者。'%(data['metadata']['message_count'],data['metadata']['speaker_count']))
        print('输出目录：'+str(out));print('下一步：当前 Codex 会话读完全部批次后生成 report.json，再运行 render。')
        return out
    finally:
        if worker:
            if worker.poll() is None and sock.exists():
                try: request({'op':'stop'},sock)
                except (OSError,RuntimeError): worker.terminate()
            elif worker.poll() is None: worker.terminate()
            try: worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.kill();worker.wait()
                print('工作器未正常退出，请用 doctor 检查微信状态。',file=sys.stderr)
        sock.unlink(missing_ok=True);remove_app(app)


def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description='微信本地群聊采集和报告渲染（由当前Codex会话总结）')
    sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('collect');c.add_argument('--group');c.add_argument('--group-id');c.add_argument('--account');c.add_argument('--hours',type=int,choices=[24,48,72],default=24);c.add_argument('--start');c.add_argument('--end');c.add_argument('--out');c.add_argument('--allow-restart',action='store_true');c.add_argument('--timeout',type=int,default=180)
    r=sub.add_parser('render');r.add_argument('directory',type=Path);r.add_argument('--no-png',action='store_true')
    sub.add_parser('doctor');a=p.parse_args()
    try:
        if a.command=='collect': collect(a)
        elif a.command=='render':
            from wechat_summary.report import render_report
            render_report(json.loads((a.directory/'messages.json').read_text()),json.loads((a.directory/'report.json').read_text()),a.directory,png=not a.no_png)
            print('报告已生成：'+str(a.directory.resolve()))
        else:
            info=plistlib.loads(Path('/Applications/WeChat.app/Contents/Info.plist').read_bytes())
            print('微信版本：'+info['CFBundleShortVersionString']);print('账号目录：'+', '.join(p.name for p in accounts()))
            print('Python：'+sys.version.split()[0]);print('SQLCipher：'+str(Path('/opt/homebrew/opt/sqlcipher/lib/libsqlcipher.dylib').exists()))
            print('Chrome：'+str(Path('/Applications/Google Chrome.app').exists()))
            print('临时端点：'+', '.join(p.name for p in (PROJECT/'.private').glob('*.sock')))
    except (ValueError,RuntimeError,OSError) as e:
        print('错误：'+str(e),file=sys.stderr);raise SystemExit(1)

if __name__=='__main__': main()
