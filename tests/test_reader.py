from pathlib import Path
import os,hashlib
from datetime import datetime
from wechat_summary.cipher import Database,snapshot
from wechat_summary.reader import export

def test_real_schema_fixture_boundaries_mapping_and_duplicates(tmp_path):
    root=tmp_path; cp=root/'db_storage/contact/contact.db'; cp.parent.mkdir(parents=True)
    group='123@chatroom'; table='Msg_'+hashlib.md5(group.encode()).hexdigest(); key=os.urandom(32)
    with Database(cp,key,False) as d:
        d.query('CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT,is_in_chat_room INTEGER)')
        d.query("INSERT INTO contact VALUES ('123@chatroom','测试群','',1)")
        d.query("INSERT INTO contact VALUES ('wxid_a','小甲','',0)")
    paths=[cp];keys={cp:key}
    for n in range(2):
        p=root/('db_storage/message/message_%s.db'%n); p.parent.mkdir(exist_ok=True);paths.append(p);keys[p]=key
        with Database(p,key,False) as d:
            d.query('CREATE TABLE Name2Id(user_name TEXT PRIMARY KEY,is_session INTEGER)')
            d.query("INSERT INTO Name2Id VALUES ('123@chatroom',1)")
            d.query("INSERT INTO Name2Id VALUES ('wxid_a',0)")
            d.query('CREATE TABLE '+table+'(local_id INTEGER,server_id INTEGER,local_type INTEGER,sort_seq INTEGER,real_sender_id INTEGER,create_time INTEGER,message_content TEXT,compress_content TEXT,WCDB_CT_message_content INTEGER)')
            for i,t in enumerate([1790222399,1790222400,1790308799,1790308800]):
                d.query('INSERT INTO '+table+' VALUES (?,?,1,?,2,?,?,NULL,NULL)',(i+1,100+i,i,t,'边界测试'+str(i)))
    with snapshot(paths) as copies:
        result=export(root,paths,copies,keys,{'group':'测试群','start_ts':1790222400,'end_ts':1790308800})
    assert result['metadata']['message_count']==2
    assert result['metadata']['speaker_count']==1
    assert result['metadata']['duplicates_removed']==2
    assert [m['server_id'] for m in result['messages']]==['101','102']
    assert result['messages'][0]['sender_name']=='小甲'
