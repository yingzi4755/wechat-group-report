#!/usr/bin/env python3
"""Portable skill entry point; never generates an unreviewed semantic summary."""
from pathlib import Path
import json
import os
import sys
from datetime import datetime
from uuid import uuid4

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'runtime'))

def main():
    args=sys.argv[1:]
    if args and args[0]=='read':
        import argparse
        p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--offset',type=int,default=0);p.add_argument('--limit',type=int,default=5000)
        a=p.parse_args(args[1:]);text=(a.directory/'messages.txt').read_text(encoding='utf-8')
        if a.offset<0 or not 1<=a.limit<=5000 or a.offset>len(text): p.error('Invalid offset/limit')
        end=min(len(text),a.offset+a.limit)
        print(json.dumps({'offset':a.offset,'next_offset':end,'total_chars':len(text),'done':end==len(text),'text':text[a.offset:end]},ensure_ascii=False))
        return
    if args and args[0]=='validate':
        from wechat_summary.report import validate_report
        p=Path(args[1]);messages=json.loads((p/'messages.json').read_text());report=json.loads((p/'report.json').read_text());validate_report(messages,report)
        print(json.dumps({'valid':True,'message_count':len(messages['messages']),'required_files':{n:(p/n).is_file() for n in ['messages.json','messages.txt','report.json','summary.md','index.html','report.png']}},ensure_ascii=False))
        return
    if args and args[0]=='collect' and '--out' not in args and not any(x.startswith('--out=') for x in args):
        out=Path.cwd()/'wechat-reports'/('run-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6])
        args+=['--out',str(out.resolve())]
    from wechat_summary.__main__ import main as application
    sys.argv=[sys.argv[0]]+args;application()

if __name__=='__main__': main()
