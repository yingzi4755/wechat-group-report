from datetime import datetime
import pytest
from wechat_summary.messages import time_window, normalize_timestamp, deduplicate, parse_body, choose_group

def test_quote_omits_media_transport_credentials():
    from xml.sax.saxutils import escape
    from wechat_summary.messages import quote_preview
    media='<msg><videomsg aeskey="FAKE_SECRET" cdnurl="private-transport"/></msg>'
    xml='<msg><appmsg><title>赞</title><refermsg><type>43</type><content>'+escape(media)+'</content></refermsg></appmsg></msg>'
    result=parse_body(xml,49)
    assert result['quote']['text']=='[视频，未解析内容]'
    assert 'FAKE_SECRET' not in str(result)
    assert 'private-transport' not in str(result)
    assert quote_preview('<msg><appmsg><title>建议</title><extra>private</extra></appmsg></msg>','49')=='建议'
    assert quote_preview('正常引用文字','1')=='正常引用文字'

def test_half_open_and_timezone():
    start,end=time_window(hours=24,now=datetime.fromisoformat('2026-09-24T12:00:00+08:00'))
    assert end-start==86400
    assert normalize_timestamp(1790222400000)==1790222400
    with pytest.raises(ValueError): time_window(start='2026-09-24T12:00:00',end='2026-09-23T12:00:00')

def test_groups_and_dedup():
    rows=[{'username':'1@chatroom','nick_name':'同名群'},{'username':'2@chatroom','nick_name':'同名群'}]
    with pytest.raises(ValueError,match='同名'): choose_group(rows,'同名群')
    assert choose_group(rows,'同名群','2@chatroom')['username']=='2@chatroom'
    with pytest.raises(ValueError): choose_group(rows,'同名')
    data=[{'id':'a','server_id':'99','sender_id':'x','timestamp':1,'text':'消息','type':'text','source':{'database':'0'}},{'id':'b','server_id':'99','sender_id':'x','timestamp':1,'text':'消息','type':'text','source':{'database':'1'}},{'id':'c','server_id':'0','sender_id':'x','timestamp':1,'text':'消息','type':'text','source':{'database':'2'}}]
    assert len(deduplicate(data))==2
    data[1]['text']='冲突'
    with pytest.raises(ValueError): deduplicate(data)

def test_xml_types_are_not_media_hallucination():
    result=parse_body('<msg><appmsg><title>进度</title><type>57</type><refermsg><svrid>42</svrid><displayname>甲</displayname><content>计划周五上线</content></refermsg></appmsg></msg>',49)
    assert result['quote']['server_id']=='42'
    assert result['text']=='进度'
    assert parse_body('<msg><img/></msg>',3)['text']=='[图片，未解析内容]'
    assert parse_body('<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><msg>&x;</msg>',49)['parse_warning']


def test_zstd_and_xml_card():
    import zstandard
    from wechat_summary.reader import decode_content
    original='wxid_test:\n中文完整内容'
    assert decode_content(zstandard.ZstdCompressor().compress(original.encode()))==original
    card=parse_body('<msg><appmsg><title>文件.zip</title><type>6</type><appattach><fileext>zip</fileext><totallen>1234</totallen></appattach></appmsg></msg>',49)
    assert card['card']['file_extension']=='zip'
    assert card['card']['file_size']=='1234'
