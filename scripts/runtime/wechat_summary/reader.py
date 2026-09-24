"""WeChat macOS 4.1.13 / 4.1.15 schema adapter, checked against local database schema.
Reads only exact-group rows in [start,end), in bounded batches, across shards.
"""
import ctypes as C
from datetime import datetime
import hashlib
from pathlib import Path
from wechat_summary.cipher import Database
from wechat_summary.messages import choose_group,deduplicate,normalize_timestamp,parse_body,TZ


def decode_content(value):
    if value is None: return ''
    if isinstance(value,str): return value
    value=bytes(value)
    if value.startswith(b'\x28\xb5\x2f\xfd'):
        lib=C.CDLL('/opt/homebrew/opt/zstd/lib/libzstd.dylib')
        lib.ZSTD_getFrameContentSize.argtypes=[C.c_void_p,C.c_size_t];lib.ZSTD_getFrameContentSize.restype=C.c_ulonglong
        lib.ZSTD_decompress.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t];lib.ZSTD_decompress.restype=C.c_size_t
        lib.ZSTD_isError.argtypes=[C.c_size_t];lib.ZSTD_isError.restype=C.c_uint
        size=lib.ZSTD_getFrameContentSize(value,len(value))
        capacity=size if size<64*1024*1024 else 64*1024*1024
        out=C.create_string_buffer(capacity); n=lib.ZSTD_decompress(out,capacity,value,len(value))
        if lib.ZSTD_isError(n): raise ValueError('Zstandard消息解压失败或超过64MiB')
        value=out.raw[:n]
    return value.decode('utf-8','strict').rstrip('\x00')


def _columns(db,table):
    return {r['name'] for r in db.query('PRAGMA table_info("'+table+'")')}


def export(root,paths,copies,keys,cmd):
    root=Path(root);p=next(p for p in paths if p.name=='contact.db')
    start,end=int(cmd['start_ts']),int(cmd['end_ts'])
    if start>=end: raise ValueError('Invalid time window')
    with Database(copies[p],keys[p]) as db:
        required={'username','nick_name','remark','is_in_chat_room'}
        if not required<=_columns(db,'contact'): raise RuntimeError('Unsupported contact schema')
        rows=db.query('SELECT username,nick_name,remark,is_in_chat_room FROM contact WHERE nick_name=? AND username LIKE ?', (cmd['group'],'%@chatroom'))
        group=choose_group(rows,cmd['group'],cmd.get('group_id'))
    table='Msg_'+hashlib.md5(group['username'].encode()).hexdigest()
    messages=[];diagnostics=[];warnings=[];bounds=[];parse_errors=0
    for p in paths:
        if p.name=='contact.db': continue
        with Database(copies[p],keys[p]) as db:
            exists=db.query('SELECT name FROM sqlite_master WHERE type=? AND name=?',('table',table))
            info={'database':str(p.relative_to(root)),'table_exists':bool(exists),'rows_in_window':0,'wal_bytes':Path(str(copies[p])+'-wal').stat().st_size if Path(str(copies[p])+'-wal').exists() else 0}
            diagnostics.append(info)
            if not exists: continue
            required={'local_id','server_id','local_type','sort_seq','real_sender_id','create_time','message_content','compress_content','WCDB_CT_message_content'}
            if not required<=_columns(db,table): raise RuntimeError('Unsupported message schema: '+p.name)
            mapping=db.query('SELECT rowid,user_name FROM Name2Id WHERE user_name=?',(group['username'],))
            if not mapping: raise RuntimeError('Group hash table exists but Name2Id does not match')
            edge=db.query('SELECT min(create_time) AS min,max(create_time) AS max FROM "'+table+'"')[0]
            if edge['min'] is None: continue
            # Detect and verify one consistent unit before filtering, not by assumption.
            rawmin,rawmax=edge['min'],edge['max']
            unit=1000000 if rawmax>=10**14 else 1000 if rawmax>=10**11 else 1
            if (1000000 if rawmin>=10**14 else 1000 if rawmin>=10**11 else 1)!=unit: raise RuntimeError('Mixed timestamp units in shard')
            bounds.append((normalize_timestamp(rawmin),normalize_timestamp(rawmax)))
            info.update(timestamp_unit={1:'seconds',1000:'milliseconds',1000000:'microseconds'}[unit],earliest=datetime.fromtimestamp(rawmin/unit,TZ).isoformat(),latest=datetime.fromtimestamp(rawmax/unit,TZ).isoformat())
            where='create_time>=? AND create_time<?'
            expected=db.query('SELECT count(*) AS n FROM "'+table+'" WHERE '+where,(start*unit,end*unit))[0]['n']
            offset=0
            while offset<expected:
                rows=db.query('SELECT local_id,server_id,local_type,sort_seq,real_sender_id,create_time,CAST(message_content AS BLOB) AS body,CAST(compress_content AS BLOB) AS compressed,WCDB_CT_message_content AS compression FROM "'+table+'" WHERE '+where+' ORDER BY create_time,sort_seq,local_id LIMIT 500 OFFSET ?', (start*unit,end*unit,offset))
                if not rows: raise RuntimeError('Message count changed inside snapshot')
                for row in rows:
                    sender=db.query('SELECT user_name FROM Name2Id WHERE rowid=?',(row['real_sender_id'],))
                    sender_id=sender[0]['user_name'] if sender else 'unmapped:'+p.name+':'+str(row['real_sender_id'])
                    raw=row['body'] or row['compressed']; warning=None
                    try: text=decode_content(raw)
                    except (UnicodeError,ValueError) as exc:
                        text='[消息正文解码失败，未总结内容]';warning=str(exc);parse_errors+=1
                    # Known WeChat group sender envelope, only strip if mapping agrees.
                    if ':\n' in text:
                        prefix,rest=text.split(':\n',1)
                        if prefix==sender_id: text=rest
                    parsed=parse_body(text,row['local_type'])
                    if warning: parsed['parse_warning']=warning
                    timestamp=normalize_timestamp(row['create_time'])
                    mid='wx:'+group['username']+':'+str(row['server_id']) if row['server_id'] else p.name+':'+table+':'+str(row['local_id'])
                    messages.append(dict(parsed,id=mid,server_id=str(row['server_id'] or 0),local_id=row['local_id'],timestamp=timestamp,time=datetime.fromtimestamp(timestamp,TZ).isoformat(),sender_id=sender_id,sender_name=sender_id,sort_seq=row['sort_seq'],local_type=row['local_type'],source={'database':str(p.relative_to(root)),'table':table,'local_id':row['local_id']},compression=row['compression']))
                offset+=len(rows)
            info['rows_in_window']=offset
            if offset!=expected: raise RuntimeError('Count mismatch')
    raw_count=len(messages);messages=deduplicate(messages)
    p=next(p for p in paths if p.name=='contact.db')
    with Database(copies[p],keys[p]) as db:
        names={}
        for sid in {m['sender_id'] for m in messages}:
            match=db.query('SELECT nick_name,remark FROM contact WHERE username=?',(sid,))
            if match: names[sid]=match[0]['remark'] or match[0]['nick_name'] or sid
        for m in messages:
            m['sender_name']=names.get(m['sender_id'],m['sender_id'])
            m['sender_name_source']='contact remark/nick_name' if m['sender_id'] in names else 'Name2Id user_name (nickname unavailable)'
    if not bounds: warnings.append('该群在所有本地消息分片中均无可读取记录；不能据此认为群内没有聊天，请检查同步。')
    elif min(b[0] for b in bounds)>start: warnings.append('该群本地最早记录晚于统计起点，无法确认覆盖完整时间窗，可能同步不足。')
    if not messages and bounds: warnings.append('本地可用记录在所选时间窗口内为零；不代表群内完整历史或云端没有消息。')
    if parse_errors: warnings.append(str(parse_errors)+'条消息正文解码失败，已保留标记，不推测内容。')
    if any(m['sender_id'].startswith('unmapped:') for m in messages): warnings.append('部分发送人ID无法映射，已显示未映射标识。')
    warnings.append('仅当前账号本机已同步记录；本地记录连续性无法证明，未同步、已删除或撤回内容可能不在范围内。')
    return {'schema_version':1,'metadata':{'group_name':group['nick_name'],'group_id':group['username'],'account_id':root.name,'start':datetime.fromtimestamp(start,TZ).isoformat(),'end':datetime.fromtimestamp(end,TZ).isoformat(),'timezone':'Asia/Shanghai','interval':'[start,end)','message_count':len(messages),'speaker_count':len({m['sender_id'] for m in messages}),'scope':'当前登录账号在本机已同步的指定群聊记录，包含数据库引擎确认已提交且有效的WAL内容；不代表群聊完整历史。','warnings':warnings,'synthetic':False,'rows_before_deduplication':raw_count,'duplicates_removed':raw_count-len(messages),'shards':diagnostics,'snapshot_at':cmd.get('_snapshot_at'),'timestamp_unit_detection':'per-shard verified bounds'},'messages':messages}
