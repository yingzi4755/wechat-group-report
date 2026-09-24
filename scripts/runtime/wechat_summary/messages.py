"""Conservative message normalization. No guesses about unseen media."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import hashlib
import re
import xml.etree.ElementTree as ET

TZ=ZoneInfo('Asia/Shanghai')

def time_window(hours=24,start=None,end=None,now=None):
    def parse(v):
        d=datetime.fromisoformat(v)
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d
    if start is not None:
        if end is None: raise ValueError('指定开始时间时必须同时指定结束时间')
        a,b=parse(start),parse(end)
    else:
        if hours not in (24,48,72): raise ValueError('只支持24、48、72小时或指定起止时间')
        b=parse(end) if end else now or datetime.now(TZ)
        a=b-timedelta(hours=hours)
    if a>=b: raise ValueError('开始时间必须早于结束时间')
    # Integer second DB boundaries use ceil: t >= start and t < end.
    import math
    return math.ceil(a.timestamp()),math.ceil(b.timestamp())

def normalize_timestamp(value):
    n=int(value)
    if n>=10**14: n=n/1_000_000
    elif n>=10**11: n=n/1000
    if not 946684800<=n<4102444800: raise ValueError('时间戳不在已验证范围 2000—2100')
    return n

def choose_group(rows,name,group_id=None):
    matches=[r for r in rows if r.get('nick_name')==name and r.get('username','').endswith('@chatroom')]
    if group_id: matches=[r for r in matches if r['username']==group_id]
    if not matches: raise ValueError('未找到完整群名：'+name)
    if len(matches)>1: raise ValueError('存在同名群，请使用稳定群ID选择：'+', '.join(r['username'] for r in matches))
    return matches[0]

def deduplicate(messages):
    seen={}; result=[]
    for m in messages:
        server=str(m.get('server_id') or '0')
        key=('server',server) if server!='0' else ('local',m['id'])
        if key in seen:
            previous=seen[key]
            for field in ('sender_id','timestamp','type','text'):
                if previous.get(field)!=m.get(field): raise ValueError('重复消息存在内容冲突：'+m['id'])
            previous.setdefault('duplicate_sources',[]).append(m['source'])
        else: seen[key]=m; result.append(m)
    return sorted(result,key=lambda m:(m['timestamp'],m.get('sort_seq',0),m['id']))

TYPES={1:'text',3:'image',34:'voice',43:'video',47:'emoji',48:'location',49:'app',50:'call',10000:'system',10002:'system'}
LABELS={'image':'图片','voice':'语音','video':'视频','emoji':'表情','location':'位置','call':'通话'}

def quote_preview(content, message_type):
    """Keep human-readable quoted content, never media transport XML."""
    try: kind=TYPES.get(int(message_type)&0xffffffff,'unknown')
    except (TypeError,ValueError): kind='unknown'
    if kind in LABELS: return '['+LABELS[kind]+'，未解析内容]'
    content=content or ''
    if kind=='app' or content.lstrip().startswith('<'):
        if '<!DOCTYPE' in content.upper() or '<!ENTITY' in content.upper(): return '[引用内容，未解析]'
        try: root=ET.fromstring(content)
        except ET.ParseError: return '[引用内容，未解析]'
        app=root if root.tag=='appmsg' else root.find('.//appmsg')
        return (app.findtext('title') or '[引用卡片]') if app is not None else '[引用内容，未解析]'
    return content

def parse_body(body,local_type):
    kind=TYPES.get(int(local_type)&0xffffffff,'unknown')
    result={'type':kind,'text':''}
    if isinstance(body,bytes):
        try: body=body.decode('utf-8')
        except UnicodeDecodeError: return dict(result,text='[二进制消息，未解析]',parse_warning='非UTF-8内容')
    body=body or ''
    if kind in ('text','system'):
        result['text']=body
        result['links']=re.findall(r'https?://[^\s<>"\x00]+',body)
        return result
    if kind in LABELS: result['text']='['+LABELS[kind]+'，未解析内容]'
    else: result['text']='[卡片，未解析]' if kind=='app' else '[未知消息类型]'
    if '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper():
        return dict(result,parse_warning='已拒绝DOCTYPE/ENTITY')
    xml=body[body.find('<'):] if '<' in body else ''
    try: root=ET.fromstring(xml)
    except ET.ParseError:
        return dict(result,parse_warning='消息XML不可解析') if xml else result
    def val(path): return root.findtext(path,default='')
    if kind=='app':
        app=root if root.tag=='appmsg' else root.find('.//appmsg')
        if app is None: return result
        get=lambda path: app.findtext(path,default='')
        result.update(text=get('title') or '[卡片]',card={'subtype':get('type'),'title':get('title'),'description':get('des'),'url':get('url'),'file_extension':get('appattach/fileext'),'file_size':get('appattach/totallen')})
        q=app.find('refermsg')
        if q is not None:
            result['quote']={'server_id':q.findtext('svrid',''),'sender_name':q.findtext('displayname',''),'text':quote_preview(q.findtext('content',''),q.findtext('type','')),'type':q.findtext('type','')}
    elif kind=='voice':
        # Only explicit transcript fields; never infer from voice bytes.
        transcript=root.find('.//voicetrans')
        if transcript is not None:
            text=transcript.get('transtext') or transcript.findtext('transtext')
            if text: result.update(text='[微信已有语音转写] '+text,transcript_source='message XML voicetrans/transtext')
    return result
