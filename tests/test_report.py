import copy
import json
import struct
from pathlib import Path

import pytest
from wechat_summary import report as renderer


def fixture():
    messages = {'schema_version': 1, 'metadata': {'group_name':'虚构测试群<script>x</script>', 'group_id':'demo', 'account_id':'synthetic', 'start':'2026-09-24 09:00', 'end':'2026-09-24 10:00', 'timezone':'Asia/Shanghai', 'message_count':2, 'speaker_count':2, 'scope':'仅本机已同步消息', 'warnings':['虚构示例'], 'synthetic':True}, 'messages':[]}
    for n in range(2):
        messages['messages'].append({'id':f'm{n}', 'server_id':str(n), 'local_id':n, 'timestamp':n, 'time':f'09:0{n}', 'sender_id':f'u{n}', 'sender_name':f'示例成员{n}', 'type':'text', 'text':'<img src=x onerror=alert(1)>', 'source':{'database':'synthetic','table':'synthetic'}})
    report = {'schema_version':1, 'overview':{'text':'虚构概览<script>x</script>', 'refs':['m0']}, 'topics':[{'title':'讨论', 'text':'正文', 'refs':['m0','m1']}], 'todos':[], 'confirmed':[], 'unresolved':[], 'other':[], 'coverage':{'reviewed_message_ids':['m0','m1'], 'method':'synthetic fixture'}}
    return messages, report


def test_html_escapes_all_text_and_has_working_sources(tmp_path):
    messages, report = fixture()
    renderer.render_report(messages, report, tmp_path, png=False)
    html = (tmp_path/'index.html').read_text()
    assert '<script>x</script>' not in html
    assert '<img src=x' not in html
    assert '&lt;img src=x' in html
    assert '<details' in html and '<details open' not in html
    assert 'id="source-0"' in html and 'href="#source-0"' in html
    assert 'http://' not in html and 'https://' not in html
    assert '仅本机已同步消息' in html
    assert (tmp_path/'summary.md').exists()


@pytest.mark.parametrize('mutation', ['duplicate','count','speakers','missing_ref','coverage','duplicate_coverage','empty_ref'])
def test_invalid_report_rejected_before_writing(tmp_path, mutation):
    messages, report = fixture()
    if mutation == 'duplicate': messages['messages'][1]['id']='m0'
    if mutation == 'count': messages['metadata']['message_count']=3
    if mutation == 'speakers': messages['metadata']['speaker_count']=1
    if mutation == 'missing_ref': report['overview']['refs']=['unknown']
    if mutation == 'coverage': report['coverage']['reviewed_message_ids']=['m0']
    if mutation == 'duplicate_coverage': report['coverage']['reviewed_message_ids'].append('m0')
    if mutation == 'empty_ref': report['overview']['refs']=[]
    with pytest.raises(ValueError): renderer.render_report(messages, report, tmp_path, png=False)
    assert not list(tmp_path.iterdir())


def test_png_tall_report_split_and_dimensions(tmp_path):
    messages, report = fixture()
    report['topics'] = [{'title':f'虚构主题 {n}', 'text':'这是一段用于验证分页的虚构内容。'*35, 'refs':['m0']} for n in range(85)]
    renderer.render_report(messages, report, tmp_path)
    manifest = json.loads((tmp_path/'report-manifest.json').read_text())
    assert len(manifest['parts']) > 1
    assert manifest['reason']
    for part in manifest['parts']:
        data=(tmp_path/part['file']).read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        width,height=struct.unpack('>II',data[16:24])
        assert width == 1100 and 0 < height <= 14000
    assert (tmp_path/'report.png').read_bytes() == (tmp_path/manifest['parts'][0]['file']).read_bytes()


def test_sources_open_on_citation_and_mobile_has_no_horizontal_scroll(tmp_path):
    from playwright.sync_api import sync_playwright
    messages, report = fixture()
    renderer.render_report(messages, report, tmp_path, png=False)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=renderer.CHROME, headless=True)
        try:
            page=browser.new_page(viewport={'width':390,'height':844})
            requests=[]
            page.on('request', lambda request: requests.append(request.url))
            page.goto((tmp_path/'index.html').as_uri())
            assert not page.locator('#sources').evaluate('(e)=>e.open')
            page.locator('a[href="#source-0"]').first.click()
            assert page.locator('#sources').evaluate('(e)=>e.open')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert all(url.startswith('file:') for url in requests)
        finally:
            browser.close()


def test_unspecified_todo_fields_and_stable_group_id(tmp_path):
    messages, report = fixture()
    messages['metadata']['group_id'] = 'stable-group<&>'
    report['todos'] = [{'item':'执行事项', 'owner':'', 'deadline':None, 'status':'待处理', 'refs':['m0']}]
    renderer.render_report(messages, report, tmp_path, png=False)
    for filename in ('index.html','summary.md'):
        text = (tmp_path/filename).read_text()
        assert '负责人：未明确' in text
        assert '截止时间：未明确' in text
        assert '群 ID：stable-group&lt;&amp;&gt;' in text


def test_original_sources_include_escaped_quote_and_card_fields(tmp_path):
    messages, report = fixture()
    messages['messages'][0]['quote'] = {'server_id':'quoted-123','sender_name':'被引用者','text':'引用正文<script>bad</script>','type':'1'}
    messages['messages'][0]['card'] = {'title':'卡片标题','description':'说明内容','url':'https://example.invalid/<unsafe>','subtype':'5','file_extension':'pdf','file_size':'12345'}
    renderer.render_report(messages, report, tmp_path, png=False)
    html = (tmp_path/'index.html').read_text()
    for expected in ('quoted-123','被引用者','引用正文&lt;script&gt;bad&lt;/script&gt;','卡片标题','说明内容','https://example.invalid/&lt;unsafe&gt;','pdf','12345'):
        assert expected in html
    assert '<script>bad</script>' not in html
    assert 'href="https://' not in html


def test_empty_messages_reject_nonempty_conclusion_sections(tmp_path):
    messages, report = fixture()
    messages['messages']=[]
    messages['metadata'].update(message_count=0, speaker_count=0)
    report['coverage']['reviewed_message_ids']=[]
    report['overview']={'text':'此范围内无消息', 'refs':[]}
    report['topics']=[{'title':'凭空话题','text':'无证据结论','refs':[]}]
    with pytest.raises(ValueError):
        renderer.render_report(messages, report, tmp_path, png=False)
    report['topics']=[]
    renderer.render_report(messages, report, tmp_path, png=False)
