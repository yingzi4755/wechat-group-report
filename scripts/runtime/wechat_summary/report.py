"""Validated, offline report documents and optional browser-rendered PNGs."""
from __future__ import annotations

import html
import json
import math
import shutil
from pathlib import Path

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
SECTIONS = [('topics', '主要话题'), ('todos', '待办事项'), ('confirmed', '已确认事项'), ('unresolved', '未解决问题'), ('other', '其他信息')]


def validate_report(messages: dict, report: dict) -> None:
    try:
        if messages['schema_version'] != 1 or report['schema_version'] != 1:
            raise ValueError('Unsupported schema version')
        rows = messages['messages']
        ids = [m['id'] for m in rows]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
            raise ValueError('Message IDs must be unique nonempty strings')
        meta = messages['metadata']
        if meta['message_count'] != len(rows):
            raise ValueError('message_count does not match messages')
        if meta['speaker_count'] != len({m['sender_id'] for m in rows}):
            raise ValueError('speaker_count does not match messages')
        reviewed = report['coverage']['reviewed_message_ids']
        if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(ids):
            raise ValueError('Review coverage must include every message exactly once')
        if report['coverage']['method'] not in ('Codex session', 'synthetic fixture'):
            raise ValueError('Unknown review method')
        if report['coverage']['method'] == 'synthetic fixture' and not meta.get('synthetic'):
            raise ValueError('Synthetic review requires synthetic messages')
        if not rows and any(report[key] for key, _ in SECTIONS):
            raise ValueError('Empty message data cannot support conclusion sections')
        entries = [report['overview']]
        for section, _ in SECTIONS:
            entries.extend(report[section])
        for entry in entries:
            refs = entry['refs']
            if not isinstance(refs, list) or any(ref not in ids for ref in refs):
                raise ValueError('Each reference must identify an existing message')
            if ids and not refs:
                raise ValueError('Every report conclusion requires source references')
    except (KeyError, TypeError) as exc:
        raise ValueError(f'Invalid messages/report schema: {exc}') from exc


def _text(value) -> str:
    return html.escape(str(value), quote=True)


def _documents(messages: dict, report: dict) -> tuple[str, str]:
    meta = messages['metadata']
    ids = {m['id']: n for n, m in enumerate(messages['messages'])}
    def refs(entry):
        return '<div class="refs">来源：' + ' '.join(f'<a href="#source-{ids[r]}">[{ids[r]+1}]</a>' for r in entry['refs']) + '</div>'
    def mdrefs(entry):
        return ' '.join(f'[{ids[r]+1}](index.html#source-{ids[r]})' for r in entry['refs'])
    label = '虚构演示 · 非真实聊天记录' if meta.get('synthetic') else '本地群聊记录总结'
    scope = str(meta.get('scope', '仅当前账号本机已同步记录'))
    period = f"{meta['start']} — {meta['end']} · {meta['timezone']}"
    chunks = [f'<header class="block"><div class="eyebrow">{_text(label)}</div><h1>{_text(meta["group_name"])}</h1><p>{_text(period)}</p><p>群 ID：{_text(meta["group_id"])}</p><div class="stats"><b>{len(ids)}<span>条消息</span></b><b>{meta["speaker_count"]}<span>位发言者</span></b><b>{len(report["topics"])}<span>个话题</span></b></div></header>', f'<aside class="block scope"><strong>数据范围</strong><p>{_text(scope)}</p><p>已逐条覆盖 {len(ids)} / {len(ids)} 条消息。媒体内容仅依据可读取文字，不推断未读取的图片、语音或附件。</p></aside>']
    md = [f'# {_text(meta["group_name"])}', label, period, f'群 ID：{_text(meta["group_id"])}', f'消息：{len(ids)} 条 · 发言者：{meta["speaker_count"]} 位', f'数据范围：{_text(scope)}', f'逐条覆盖：{len(ids)} / {len(ids)} 条消息']
    for warning in meta.get('warnings', []):
        chunks.append(f'<aside class="block warning">{_text(warning)}</aside>')
        md.append(f'提示：{_text(warning)}')
    chunks.append(f'<section class="block overview"><h2>内容概览</h2><p>{_text(report["overview"]["text"])}</p>{refs(report["overview"])}</section>')
    md.extend(['## 内容概览', _text(report['overview']['text']), mdrefs(report['overview'])])
    for key, title in SECTIONS:
        chunks.append(f'<h2 class="section-title block">{title}</h2>')
        md.append(f'## {title}')
        if not report[key]:
            chunks.append('<div class="block empty">记录中暂无此类信息。</div>')
            md.append('记录中暂无此类信息。')
        for entry in report[key]:
            heading = f'<h3>{_text(entry["title"])}</h3>' if key == 'topics' else ''
            text = entry['item'] if key == 'todos' else entry['text']
            extra = ''
            if key == 'todos':
                extra = '<div class="todo-meta">' + ' · '.join(_text(f'{label}：{entry.get(field) or "未明确"}') for field, label in [('owner','负责人'), ('deadline','截止时间'), ('status','状态')]) + '</div>'
            chunks.append(f'<article class="block card">{heading}<p>{_text(text)}</p>{extra}{refs(entry)}</article>')
            if key == 'topics': md.append(f'### {_text(entry["title"])}')
            md.append(_text(text))
            if key == 'todos': md.append(' · '.join(f'{label}：{_text(entry.get(field) or "未明确")}' for field, label in [('owner','负责人'), ('deadline','截止时间'), ('status','状态')]))
            md.append(mdrefs(entry))
    sources = []
    for n, row in enumerate(messages['messages']):
        parsed = ''
        for field, label in [('quote', '引用消息（解析内容）'), ('card', '卡片（解析内容）')]:
            if row.get(field):
                parsed += f'<div><strong>{label}</strong><p>{_text(json.dumps(row[field], ensure_ascii=False, indent=2))}</p></div>'
        sources.append(f'<article class="source block" id="source-{n}"><h3>[{n+1}] {_text(row["sender_name"])} <small>{_text(row["time"])}</small></h3><p>{_text(row["text"])}</p>{parsed}<small>类型：{_text(row["type"])} · ID：{_text(row["id"])} · {_text(row.get("source", {}).get("database", ""))} / {_text(row.get("source", {}).get("table", ""))}</small></article>')
    chunks.append(f'<details id="sources" class="block"><summary>原始消息与引用依据（{len(ids)} 条，点击展开）</summary>{"".join(sources)}</details>')
    chunks.append('<footer class="block">本报告基于本机已同步记录。来源引用用于核对，未同步或已删除内容不在范围内。</footer>')
    css = '''*{box-sizing:border-box}html{background:#eef3f4;color:#163333;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}body{margin:0}main{max-width:1040px;margin:0 auto;padding:44px 42px 28px}header{background:#143e3c;color:#fff;padding:38px;border-radius:22px}h1{font-size:34px;line-height:1.4;margin:12px 0}h2{font-size:23px;margin:0 0 14px}h3{font-size:19px;margin:0 0 12px}p{line-height:1.85;white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}.eyebrow{font-size:13px;letter-spacing:2px;color:#bde1d8}.stats{display:flex;gap:54px;margin-top:28px}.stats b{font-size:32px}.stats span{font-size:13px;font-weight:400;margin-left:10px}.block{break-inside:avoid}.scope,.warning,.overview,.card,.empty,details{padding:24px 28px;margin-top:16px;border-radius:14px;background:white}.scope{background:#dfece7;font-size:14px}.warning{background:#fff1d6;color:#704d15}.overview{border-left:5px solid #338677}.section-title{margin:32px 0 0}.refs,.todo-meta{font-size:13px;color:#5b7470;margin-top:14px}a{color:#176a60;text-decoration:none;margin-right:6px}.empty{color:#657e79}summary{cursor:pointer;font-weight:600}.source{padding:22px 0;border-bottom:1px solid #dbe4e1}.source:target{background:#fff1d6}small{font-size:12px;font-weight:400;color:#627c77}footer{font-size:12px;line-height:1.8;color:#617973;margin:26px 0 0}@media(max-width:600px){main{padding:16px}header{padding:24px}h1{font-size:27px}.stats{gap:20px}.stats b{font-size:25px}.stats span{display:block;margin:5px 0}.scope,.warning,.overview,.card,.empty,details{padding:20px}}'''
    script = "function reveal(){let e=document.getElementById(location.hash.slice(1));if(e&&e.closest('details')){e.closest('details').open=true;e.scrollIntoView()}}addEventListener('hashchange',reveal);reveal();"
    document = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_text(meta["group_name"])} · 群聊总结</title><style>{css}</style></head><body><main>{"".join(chunks)}</main><script>{script}</script></body></html>'
    return document, '\n\n'.join(md) + '\n'


def _png(out: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        try:
            page = browser.new_page(viewport={'width':1100, 'height':900}, device_scale_factor=1)
            page.goto((out/'index.html').resolve().as_uri(), wait_until='load')
            page.evaluate('document.fonts.ready')
            height = math.ceil(page.evaluate('document.documentElement.scrollHeight'))
            if height <= 14000:
                page.screenshot(path=str(out/'report.png'), full_page=True)
                return
            boundaries = page.eval_on_selector_all('main > .block', '(els) => els.map(e => Math.floor(e.getBoundingClientRect().bottom + scrollY))')
            # Also expose paragraph line boundaries for a single unusually large card.
            lines = page.evaluate('''() => {let out=[];for(let e of document.querySelectorAll('main > .card p, main > .overview p')){let t=e.firstChild;if(!t||t.nodeType!==3)continue;let r=document.createRange();for(let i=0;i<t.length;i++){r.setStart(t,i);r.setEnd(t,i+1);for(let b of r.getClientRects())out.push(Math.ceil(b.bottom+scrollY));}}return [...new Set(out)]}''')
            parts=[]
            top=0
            while top < height:
                cap=min(top+14000,height)
                choices=[b for b in boundaries if top+100 < b <= cap]
                if cap == height: bottom=height
                elif choices: bottom=max(choices)
                else: bottom=max([b for b in lines if top+100 < b <= cap] or [cap])
                name=f'report-{len(parts)+1:03d}.png'
                page.screenshot(path=str(out/name), full_page=True, clip={'x':0,'y':top,'width':1100,'height':bottom-top})
                parts.append({'file':name,'top':top,'height':bottom-top})
                top=bottom
            shutil.copyfile(out/parts[0]['file'],out/'report.png')
            (out/'report-manifest.json').write_text(json.dumps({'reason':'报告高度超过 14000 像素，优先在内容块边界分图；超长单块按文字行分图。report.png 为首张副本。','total_height':height,'parts':parts}, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            browser.close()


def render_report(messages: dict, report: dict, out: Path, png: bool = True) -> None:
    validate_report(messages, report)
    document, markdown = _documents(messages, report)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out/'index.html').write_text(document, encoding='utf-8')
    (out/'summary.md').write_text(markdown, encoding='utf-8')
    if png:
        _png(out)
