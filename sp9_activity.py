"""Read card discussions and page Updates through the existing guest browser.

All event identities are derived from source text, never an AI paraphrase.
Only read actions are used; no Notion integration or database edits are needed.
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import sp9_capture as capture

RESUME_MAX_AGE = timedelta(hours=2)
COMPLETE_FLAGS = ('content_complete', 'comments_complete', 'updates_complete')


def _atomic_record(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _capture_scope(since: date) -> dict[str, Any]:
    return {'version': 1, 'since': since.isoformat(),
            'profile': str(capture.DEFAULT_PROFILE_DIR.resolve())}


def _task_scope(task: dict[str, Any]) -> dict[str, Any]:
    return {'id': card_key(task.get('url')), 'status': task.get('status'),
            'due_date': task.get('due_date'), 'assignees': sorted(task.get('assignees') or [])}


def _resume_card(path: Path, task: dict[str, Any], since: date, now: datetime) -> dict[str, Any] | None:
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        captured_at = datetime.fromisoformat(record['captured_at'])
        key = card_key(task.get('url'))
        if (not re.fullmatch(r'[a-f0-9]{32}', key)
                or card_key(record.get('url')) != key
                or record.get('capture_scope') != _capture_scope(since)
                or record.get('task_scope') != _task_scope(task)
                or captured_at.tzinfo is None
                or captured_at.astimezone(capture.MOSCOW_TZ).date() != now.date()
                or not timedelta(0) <= now - captured_at <= RESUME_MAX_AGE
                or not record.get('identity_verified')
                or record.get('errors') != []
                or not all(record.get(flag) is True for flag in COMPLETE_FLAGS)
                or not all(isinstance(record.get(field), list) for field in ('content', 'comments', 'history'))):
            return None
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _save_card_attempt(destination: Path, filename: str, raw: dict[str, Any],
                       merged: dict[str, Any], since: date) -> dict[str, Any]:
    attempt_dir = destination / 'attempts' / filename
    attempt_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in attempt_dir.glob('*.json') if p.stem.isdigit())
    number = max((int(p.stem) for p in files), default=0) + 1
    raw = {**raw, 'capture_scope': _capture_scope(since)}
    _atomic_record(attempt_dir / f'{number:02d}.json', raw)
    history = []
    for path in sorted(attempt_dir.glob('*.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            history.append({'captured_at': record.get('captured_at'), 'errors': record.get('errors', []),
                            **{k: bool(record.get(k)) for k in COMPLETE_FLAGS}})
        except (OSError, ValueError, AttributeError):
            continue
    result = {**merged, 'capture_scope': _capture_scope(since), 'attempts': history}
    _atomic_record(destination / (filename + '.json'), result)
    return result


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def card_key(url: Any) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.hostname and (parsed.hostname == "notion.com" or parsed.hostname.endswith(".notion.com") or parsed.hostname.endswith(".notion.so")):
        path = parse_qs(parsed.query).get("p", [parsed.path])[-1]
        matches = re.findall(r"[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", path, re.I)
        if matches:
            return matches[-1].replace("-", "").lower()
    return str(url or "").split("?", 1)[0].rstrip("/")


def source_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def ui_date(label: Any, captured_at: datetime) -> date | None:
    """Resolve observed UI times; don't invent dates for unreadable labels."""
    text = clean(label).lower()
    if text in {"today", "сегодня", "just now", "now", "только что"}:
        return captured_at.date()
    if text in {"yesterday", "вчера"}:
        return captured_at.date() - timedelta(days=1)
    match = re.fullmatch(r"(\d+)\s*(m|min|minutes?|h|hours?|d|days?|w|weeks?|мин\w*|ч\w*|дн\w*|нед\w*)(?:\s+ago|\s+назад)?", text)
    if match:
        n, unit = int(match[1]), match[2]
        if unit.startswith(("m", "мин")):
            delta = timedelta(minutes=n)
        elif unit.startswith(("h", "ч")):
            delta = timedelta(hours=n)
        elif unit.startswith(("w", "нед")):
            delta = timedelta(weeks=n)
        else:
            delta = timedelta(days=n)
        return (captured_at - delta).date()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    # Notion's abbreviated dates omit the year. Choose the most recent past
    # occurrence, rather than assigning January's events to the coming December.
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d", "%d %b", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=captured_at.year)
                if parsed.date() > captured_at.date():
                    parsed = parsed.replace(year=captured_at.year - 1)
            return parsed.date()
        except ValueError:
            continue
    return None


_READ_JS = r"""() => {
  const stableLink = href => {const u=new URL(href,location.href);
    for(const k of [...u.searchParams.keys()])if(k==='t'||k==='pvs'||k.startsWith('utm_')||k.startsWith('X-Amz-')||['Expires','Signature','Key-Pair-Id'].includes(k))u.searchParams.delete(k);
    return u.href;};
  const discussion = document.querySelector('.notion-page-view-discussion');
  const direct = discussion ? [...discussion.querySelectorAll('[data-content-editable-leaf="true"][contenteditable="false"]')].map(e => {
    let p = e;
    while (p && p !== discussion && !p.querySelector('[aria-label="Comment actions"]')) p = p.parentElement;
    const lines = (p?.innerText || '').split('\n').filter(Boolean);
    return {author:lines[0] || '', time:lines[1] || '', text:e.innerText,
            source_text:p?.innerText || '', links:[...p.querySelectorAll('a[href]')].map(a=>({text:a.innerText,url:a.href}))};
  }) : [];
  const history = [...document.querySelectorAll('.notion-update-sidebar .notion-activity-section-header')].map(h => {
    let p = h.parentElement;
    while (p && !p.querySelector('.notion-activity-section-children')) p = p.parentElement;
    if (!p || p.querySelectorAll('.notion-activity-section-header').length !== 1) return null;
    const children = p.querySelector('.notion-activity-section-children');
    return {header:h.innerText, time:p.querySelector('.notion-activity-section-time')?.innerText || '',
      text:children?.innerText || '',
      items:[...children.querySelectorAll('a[href]')].filter(a=>!a.parentElement.closest('a')&&a.hostname===location.hostname&&a.pathname===location.pathname&&new URL(a.href).searchParams.has('d')).map(a=>{
        const text=a.innerText;
        const rich=a.querySelector('span[style*="white-space: pre-wrap"]');
        const attachments=[...new Set(text.match(/attachment:[a-f0-9-]+:[^\s]+/gi)||[])];
        let body=rich?.innerText || '';
        for(const attachment of attachments)if(!body.includes(attachment))body+='\n'+attachment;
        return {url:a.href,text,author:text.split('\n')[0],body_text:body.trim(),body_complete:!!rich||attachments.length>0};
      })};
  }).filter(Boolean);
  return {direct, discussion_present:!!discussion, history,
    panel_text:document.querySelector('.notion-update-sidebar')?.innerText || '',
    content:[...document.querySelectorAll('.notion-page-content [data-block-id]')]
      .filter(e=>!e.parentElement.closest('.notion-page-content [data-block-id]'))
      .map(e=>({id:e.getAttribute('data-block-id'), text:e.innerText,
          links:[...e.querySelectorAll('a[href]')].map(a=>({text:a.innerText,url:stableLink(a.href)}))}))};
}"""


def _wait_for_card_identity(page: Any, expected: str) -> str:
    """Identify the rendered page itself, never a similarly named sidebar link."""
    page.wait_for_function("""key => {
      const view = document.querySelector('.notion-page-content')?.closest('.notion-frame');
      return view &&
        [...view.querySelectorAll('.notion-page-block[data-block-id]')].some(e =>
          e.getAttribute('data-block-id').replaceAll('-', '').toLowerCase() === key && e.innerText.trim());
    }""", arg=expected, timeout=20000)
    if card_key(page.url) != expected:
        raise capture.BrowserCaptureError('Открыта карточка с другим ID')
    return page.evaluate("""key => [...document.querySelector('.notion-page-content')
      .closest('.notion-frame').querySelectorAll('.notion-page-block[data-block-id]')].find(e =>
        e.getAttribute('data-block-id').replaceAll('-', '').toLowerCase() === key && e.innerText.trim())?.innerText.trim() || ''
    """, expected)


def card_properties(record: dict[str, Any]) -> dict[str, Any]:
    """Read only explicitly bounded property values; missing is not empty."""
    body = record.get('page_text') or ''
    if 'Customize layout\n' not in body:
        return {}
    body = body.split('Customize layout\n', 1)[1]
    boundary = r'(?:Mailing Dates|Files & media(?: \d+)?|New section|Type|Status|Date of creation|Urgency|Deadline|Assignee|Created by|Parent item|Comments|\d+ more properties)'
    result: dict[str, Any] = {}
    for label, field in (('Status', 'status'), ('Assignee', 'assignees'), ('Deadline', 'due_date'), ('Date of creation', 'created_date')):
        match = re.search(r'(?m)^' + label + r'\n(.*?)(?=\n' + boundary + r'(?:\n|$))', body, re.S)
        if not match:
            continue
        value = match[1].strip()
        if field == 'status' and value in {'No Status', 'To Do', 'In Progress', 'Review', 'Completed', 'Empty'}:
            result[field] = 'No Status' if value == 'Empty' else value
        elif field == 'assignees' and value:
            names = [clean(line) for line in value.splitlines() if clean(line)]
            # One-letter avatar labels are presentation, not an extra person.
            names = [n for n in names if len(n) > 1]
            if value == 'Empty' or names:
                result[field] = [] if value == 'Empty' else names
        elif field in {'due_date', 'created_date'} and value == 'Empty':
            result[field] = None
        elif field in {'due_date', 'created_date'}:
            try:
                observed = datetime.fromisoformat(record['captured_at'])
            except (KeyError, ValueError):
                continue
            parsed = ui_date(value, observed)
            if parsed is not None:
                result[field] = parsed.isoformat()
    return result


def _history_readable(history: list[dict[str, Any]], since: date, now: datetime) -> bool:
    for entry in history:
        occurred = ui_date(entry.get('time'), now)
        if occurred is not None and occurred < since:
            continue
        if occurred is None or not clean(entry.get('text')):
            return False
    return True


def _open_history(page: Any) -> None:
    panel = page.locator('.notion-update-sidebar')
    if not (panel.count() and panel.first.is_visible()):
        failures = []
        for method in ('edited', 'actions'):
            try:
                if method == 'edited':
                    # The visible edited-time control opens Updates directly.
                    page.get_by_role('button', name=re.compile(r'^Edited', re.I)).first.click(timeout=5000)
                else:
                    page.get_by_role('button', name='Actions', exact=True).click(timeout=5000)
                    page.get_by_text('Updates & analytics', exact=True).click(timeout=5000)
                panel.wait_for(state='visible', timeout=8000)
                break
            except Exception as exc:
                failures.append(f'{method}: {exc}')
                try:
                    page.keyboard.press('Escape', timeout=1000)
                except Exception:
                    pass
        else:
            raise capture.BrowserCaptureError('Не удалось открыть Updates: ' + ' | '.join(failures))
    page.wait_for_function("""() => document.querySelector('.notion-update-sidebar .notion-activity-section-header') ||
      /no updates|no activity|нет обновлений/i.test(document.querySelector('.notion-update-sidebar')?.innerText || '')""", timeout=15000)


def _read_history(page: Any, since: date, now: datetime) -> tuple[dict[str, Any], bool]:
    """Page through recent history until the time boundary is actually reached."""
    _open_history(page)
    collected: dict[str, dict[str, Any]] = {}

    def accumulate(data: dict[str, Any]) -> dict[str, Any]:
        occurrences: dict[tuple[str, str], int] = {}
        for item in data['history']:
            # "View N more" can expand blocks within an existing edit rather
            # than add activity headers. Replace its partial text in place.
            observed_day = ui_date(item['time'], now)
            identity = (item['header'], observed_day.isoformat() if observed_day else item['time'])
            ordinal = occurrences.get(identity, 0)
            occurrences[identity] = ordinal + 1
            key = source_hash([*identity, ordinal])
            previous = collected.get(key)
            # Virtualized entries may lose their body while another page loads.
            # Keep the richer observation of the same event within this read.
            if previous is None or len(clean(item.get('text'))) >= len(clean(previous.get('text'))):
                collected[key] = item
        data['history'] = list(collected.values())
        return data

    for _ in range(20):
        data = accumulate(page.evaluate(_READ_JS))
        dates = [ui_date(item['time'], now) for item in data['history']]
        if not _history_readable(data['history'], since, now):
            # Activity headers render before their lazily loaded bodies.
            for _ in range(3):
                page.wait_for_timeout(800)
                loaded = accumulate(page.evaluate(_READ_JS))
                if _history_readable(loaded['history'], since, now):
                    data = loaded
                    dates = [ui_date(item['time'], now) for item in data['history']]
                    break
            else:
                return data, False
        if any(d is not None and d < since for d in dates):
            boundary = next(i for i, d in enumerate(dates) if d is not None and d < since)
            return data, all(d is not None for d in dates[:boundary + 1])
        panel = page.locator('.notion-update-sidebar')
        more = panel.get_by_text(re.compile(r'^(View|Show|Load) \d+ more$|^Показать ещё', re.I))
        if more.count():
            before = page.locator('.notion-update-sidebar').inner_text()
            more.first.click(timeout=5000)
            page.wait_for_timeout(800)
            page.wait_for_function("before => document.querySelector('.notion-update-sidebar')?.innerText !== before", arg=before, timeout=10000)
            continue
        # No history records means an explicit empty state is required.
        if not data['history']:
            return data, bool(re.search(r'no updates|no activity|нет обновлений', data['panel_text'], re.I))
        return data, all(d is not None for d in dates)
    return data, False


def comments_readable(history: list[dict[str, Any]], since: date, now: datetime) -> bool:
    for entry in history:
        if not re.search(r'commented|прокоммент', entry['header'], re.I):
            continue
        occurred = ui_date(entry.get('time'), now)
        if occurred is not None and occurred < since:
            continue
        if not entry.get('items') or not all(item.get('body_complete', True) for item in entry['items']):
            return False
    return True


def _card_error(record: dict[str, Any], stage: str, exc: Exception) -> None:
    message = str(exc)
    record['errors'].append(('Updates: ' if stage == 'history' else stage + ': ')
                            + message.splitlines()[0][:180])
    record.setdefault('failure_details', []).append({
        'stage': stage, 'type': type(exc).__name__, 'message': message[:6000],
    })


def _save_failure_diagnostics(page: Any, record: dict[str, Any], destination: Path) -> None:
    """Keep stage and call log; diagnostic failure must not mask the read error."""
    try:
        folder = destination / 'diagnostics'
        folder.mkdir(parents=True, exist_ok=True)
        key = card_key(record.get('url'))
        if not re.fullmatch(r'[a-f0-9]{32}', key):
            key = source_hash(record.get('url'))
        stem = key + '-' + datetime.now(capture.MOSCOW_TZ).strftime('%H%M%S%f')
        payload = {k: record.get(k) for k in (
            'title', 'url', 'captured_at', 'observed_title', 'identity_verified',
            'content_complete', 'comments_complete', 'updates_complete', 'errors', 'failure_details')}
        payload['observed_url'] = page.url
        _atomic_record(folder / (stem + '.json'), payload)
        page.screenshot(path=str(folder / (stem + '.jpg')), type='jpeg', quality=60, timeout=5000)
    except Exception:
        pass


def _capture_card(page: Any, task: dict[str, Any], destination: Path, since: date) -> dict[str, Any]:
    now = datetime.now(capture.MOSCOW_TZ)
    record: dict[str, Any] = {
        'title': task['title'], 'url': task.get('url'), 'captured_at': now.isoformat(),
        'task_scope': _task_scope(task),
        'content_complete': False, 'comments_complete': False, 'updates_complete': False,
        'content': [], 'comments': [], 'history': [], 'errors': [],
    }
    stage = 'navigation'
    try:
        if not task.get('url') or not re.fullmatch(r'[a-f0-9]{32}', card_key(task['url'])):
            raise capture.BrowserCaptureError('Нет надёжной ссылки на карточку Notion')
        expected = card_key(task['url'])
        record['retryable'] = True
        capture._open_notion_page(page, 'https://app.notion.com/p/' + expected)
        if capture._looks_logged_out(page):
            record['retryable'] = False
            raise capture.BrowserCaptureError('Гостевая сессия Notion не авторизована')
        stage = 'identity'
        record['observed_title'] = _wait_for_card_identity(page, expected)
        record['identity_verified'] = True
        stage = 'content'
        page.wait_for_timeout(600)
        body = page.locator('body').inner_text()
        record['page_text'] = body
        record['properties'] = card_properties(record)
        content: dict[str, dict[str, Any]] = {}
        # Walk the actual page scroller without sampling gaps. A cap is marked
        # incomplete and never becomes a new content baseline.
        page.evaluate("""() => { const e=document.querySelector('.notion-page-content');
          let p=e; while(p && p.scrollHeight<=p.clientHeight+10)p=p.parentElement;
          if(p){p.setAttribute('data-sp9-card-scroll','true');p.scrollTop=0;} }""")
        for _ in range(80):
            data = page.evaluate(_READ_JS)
            for block in data['content']:
                content[block['id']] = block
            scrolled = page.evaluate("""() => {const e=document.querySelector('[data-sp9-card-scroll]');
              if(!e)return false; if(e.scrollTop+e.clientHeight>=e.scrollHeight-5)return false;
              e.scrollTop+=Math.max(300,e.clientHeight*0.75);return true;}""")
            if not scrolled:
                record['content_complete'] = True
                break
            page.wait_for_timeout(150)
        record['content'] = list(content.values())
        record['content_hash'] = source_hash(record['content'])
        # Return to the top before opening the fixed page controls.
        page.evaluate("() => {const e=document.querySelector('[data-sp9-card-scroll]');if(e)e.scrollTop=0;}")
        page.wait_for_timeout(200)
        data = page.evaluate(_READ_JS)
        record['comments'] = data['direct']
        record['comments_complete'] = data['discussion_present']
        try:
            stage = 'history'
            history, complete = _read_history(page, since, now)
            record['history'] = history['history']
            record['updates_complete'] = complete
            # Updates supplies page and inline discussions, including resolved
            # threads. Completeness here always means the requested time window.
            record['comments_complete'] = complete and comments_readable(record['history'], since, now)
            if not record['comments_complete']:
                record['errors'].append('Не все комментарии в истории удалось прочитать')
            if not complete:
                record['errors'].append('Updates: история за нужный период прочитана не полностью')
        except Exception as exc:
            _card_error(record, 'history', exc)
            record['comments_complete'] = False
        if not record['content_complete']:
            record['errors'].append('Содержимое карточки превышает лимит прокрутки')
        stage = 'screenshot'
        page.screenshot(path=str(destination / (card_key(task['url']) + '.jpg')), type='jpeg', quality=70, timeout=5000)
    except Exception as exc:
        _card_error(record, stage, exc)
        if isinstance(exc, capture.BrowserCaptureError) and 'другим ID' in str(exc):
            record['retryable'] = False
    if record['errors']:
        _save_failure_diagnostics(page, record, destination)
    return record


def merge_card_attempts(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Keep verified components when a retry supplies only partial data."""
    merged = copy.deepcopy(after)
    components = {
        'content_complete': ('content', 'content_hash', 'page_text', 'properties', 'observed_title', 'identity_verified'),
        'comments_complete': ('comments',),
        'updates_complete': ('history',),
    }
    for flag, fields in components.items():
        if not after.get(flag) and (before.get(flag) or (before.get(fields[0]) and not after.get(fields[0]))):
            merged[flag] = bool(before.get(flag))
            for field in fields:
                if field in before:
                    merged[field] = copy.deepcopy(before[field])
    # Updates also governs whether all recent comments were checked.
    if before.get('comments_complete') and not after.get('comments_complete') and before.get('updates_complete'):
        merged['history'] = copy.deepcopy(before.get('history', []))
        merged['updates_complete'] = True
    merged['errors'] = list(dict.fromkeys(before.get('errors', []) + after.get('errors', [])))
    if all(merged.get(k) for k in components):
        merged['errors'] = []
    return merged


def capture_card_activity(tasks: list[dict[str, Any]], destination: Path, *, since: date, headless: bool = True) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    now = datetime.now(capture.MOSCOW_TZ)
    records = [_resume_card(destination / (card_key(t.get('url')) + '.json'), t, since, now)
               if re.fullmatch(r'[a-f0-9]{32}', card_key(t.get('url'))) else None for t in tasks]
    resumed = sum(record is not None for record in records)
    if resumed:
        print(f'S:P9: сохранённые карточки — {resumed}/{len(tasks)}', flush=True)
    if all(record is not None for record in records):
        return records
    with capture._playwright()() as playwright:
        context = capture._launch_context(playwright, capture.DEFAULT_PROFILE_DIR, headless=headless)
        def read(task: dict[str, Any]) -> dict[str, Any]:
            # Isolate page scroll, dialogs and the Updates sidebar for every
            # card and retry, while retaining the authenticated context.
            page = context.new_page()
            try:
                return _capture_card(page, task, destination, since)
            finally:
                page.close()
        try:
            for index, task in enumerate(tasks, 1):
                if records[index - 1] is not None:
                    continue
                print(f'S:P9: карточка {index}/{len(tasks)} — {task["title"]}', flush=True)
                record = read(task)
                filename = card_key(task.get('url'))
                if not re.fullmatch(r'[a-f0-9]{32}', filename):
                    filename = source_hash(task)
                records[index - 1] = _save_card_attempt(destination, filename, record, record, since)
            for index, record in enumerate(records):
                if all(record.get(k) for k in ('content_complete', 'comments_complete', 'updates_complete')):
                    continue
                if not record.get('retryable', any('timeout' in error.casefold() or 'timed out' in error.casefold() for error in record.get('errors', []))):
                    continue
                print(f'S:P9: повторное чтение — {tasks[index]["title"]}', flush=True)
                retried = read(tasks[index])
                filename = card_key(record.get('url'))
                if not re.fullmatch(r'[a-f0-9]{32}', filename):
                    filename = source_hash(tasks[index])
                records[index] = _save_card_attempt(destination, filename, retried, merge_card_attempts(record, retried), since)
        finally:
            context.close()
    return records


def targets(snapshot: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    # The visible Completed slice is already bounded by board capture. Also
    # check formerly active cards that vanished from that slice.
    result = {card_key(t.get('url')) or clean(t['title']): t for t in snapshot.get('tasks', [])}
    for task in (previous or {}).get('tasks', []):
        if task.get('status') != 'Completed':
            result.setdefault(card_key(task.get('url')) or clean(task['title']), task)
    return list(result.values())


def _history_actor(header: str) -> str:
    if not re.search(r'\s+(?:commented|edited|updated|прокоммент\w*|измен\w*)\b', header, re.I):
        return ''
    actor = re.split(r'\s+(?:commented|edited|updated|прокоммент\w*|измен\w*)\b', header, maxsplit=1, flags=re.I)[0].strip()
    if actor.lower() == 'you':
        return os.getenv('SP9_NOTION_SELF_NAME', 'Aleksei Gruzdev')
    if actor.lower() in {'someone', 'кто-то'}:
        return ''
    return actor


def source_updates(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn observed source records into dated, evidence-backed events."""
    now = datetime.fromisoformat(record['captured_at'])
    result: list[dict[str, Any]] = []
    direct = record.get('comments', [])
    # Use exact discussion links from Updates for page and inline comments.
    comments: list[dict[str, Any]] = []
    for entry in record.get('history', []):
        if re.search(r'commented|прокоммент', entry['header'], re.I):
            for item in entry.get('items', []):
                if card_key(item.get('url')) != card_key(record['url']) or not parse_qs(urlparse(item.get('url') or '').query).get('d'):
                    continue
                lines = item['text'].splitlines()
                if len(lines) < 2:
                    continue
                author = item.get('author') or lines[0].strip()
                text = item.get('body_text') if 'body_text' in item else '\n'.join(lines[1:]).strip()
                if not text:
                    continue
                match = next((c for c in direct if clean(c['author']) == clean(author) and clean(c['text']) in clean(text)), None)
                label = match['time'] if match and ui_date(match['time'], now) else entry['time']
                comments.append({'author': author, 'text': text, 'time': label, 'url': item['url']})
        else:
            actor = _history_actor(entry['header'])
            text = entry['text'].strip()
            if not text:
                continue
            lines = [clean(line) for line in text.splitlines() if clean(line)]
            if lines[0] == 'Status' and len(lines) == 3:
                details = f'{actor + ": " if actor else ""}статус: {lines[1]} → {lines[2]}'
                kind = 'property_update'
            else:
                fields = [name for name in ('Status', 'Assignee', 'Deadline', 'Urgency', 'Type') if name in lines]
                if fields:
                    details = f'{actor + ": " if actor else ""}обновлены свойства: ' + ', '.join(fields)
                    kind = 'property_update'
                else:
                    details = f'{actor + ": " if actor else ""}изменено содержимое: «{clean(text)[:160]}»'
                    kind = 'content'
            result.append({'kind': kind, 'author': actor, 'details': details, 'raw_text': text, 'time_label': entry['time'], 'occurred_at': (ui_date(entry['time'], now) or None), 'source': 'card_updates'})
    for comment in direct:
        if not any(clean(c['author']) == clean(comment['author']) and clean(comment['text']) in clean(c['text']) for c in comments):
            comments.append(comment)
    for comment in comments:
        actor, text = comment['author'], comment['text']
        quote = re.sub(r'https?://\S+', '', text)
        quote = re.sub(r'attachment:[a-f0-9-]+:([^\s]+)', lambda m: m[1].replace('_', ' '), quote, flags=re.I)
        quote = re.sub(r'(?m)^File$', 'файл', quote)
        quote = re.sub(r'(?m)^Video$', 'видео', quote)
        quote = clean(quote)
        result.append({'kind': 'comment', 'author': actor, 'details': f'{actor}: комментарий «{quote[:220]}{"…" if len(quote) > 220 else ""}»',
                       'raw_text': text, 'time_label': comment['time'], 'occurred_at': ui_date(comment['time'], now), 'source': 'card_comments',
                       'discussion_url': comment.get('url')})
    counts: dict[str, int] = {}
    # Page history is newest-first; assign occurrence numbers oldest-first.
    # Identical later edits/comments must not take the older event's identity.
    for update in reversed(result):
        update['occurred_at'] = update['occurred_at'].isoformat() if update['occurred_at'] else None
        # Keep day and narration out of the key: relative labels and translations
        # of surrounding UI must not cause repeat delivery.
        discussion = parse_qs(urlparse(update.get('discussion_url') or '').query).get('d', [''])[0]
        material = [card_key(record['url']), discussion, update['kind'], clean(update['author']).casefold(), clean(update['raw_text'])]
        group = source_hash(material)
        counts[group] = counts.get(group, 0) + 1
        update['fingerprint'] = source_hash(['card-source-v1', group, counts[group]])
        update['task_title'], update['task_url'] = record['title'], record['url']
    return result


def activity_events(snapshot: dict[str, Any], previous: dict[str, Any] | None, seen: set[str], since: date) -> list[dict[str, Any]]:
    old = {card_key(r.get('url')): r for r in (previous or {}).get('card_activity', [])}
    events: list[dict[str, Any]] = []
    for record in snapshot.get('card_activity', []):
        before = old.get(card_key(record['url']))
        old_sources = {u['fingerprint'] for u in source_updates(before)} if before else set()
        updates = source_updates(record)
        for update in updates:
            occurred = ui_date(update.get('occurred_at'), datetime.fromisoformat(record['captured_at']))
            if not occurred or occurred < since or update['fingerprint'] in seen or update['fingerprint'] in old_sources:
                continue
            events.append({'kind': 'update', 'title': record['title'], 'url': record['url'], 'details': update['details'],
                           'priority': 4 if update['kind'] == 'comment' else 3,
                           'fingerprint': update['fingerprint'], 'source': update['source'], 'source_kind': update['kind'],
                           'author': update['author'], 'occurred_at': update['occurred_at'], 'raw_text': update['raw_text'],
                           'discussion_url': update.get('discussion_url')})
        if before and before.get('content_complete') and record.get('content_complete') and before.get('content_hash') != record.get('content_hash'):
            # A verified content diff covers edits even when page history isn't
            # available. Actor attribution requires source evidence.
            if not any(e['source_kind'] == 'content' and card_key(e['url']) == card_key(record['url']) for e in events):
                fingerprint = source_hash(['card-content-v1', card_key(record['url']), before.get('content_hash'), record.get('content_hash')])
                if fingerprint not in seen:
                    events.append({'kind': 'content', 'title': record['title'], 'url': record['url'], 'details': 'изменено содержимое карточки', 'priority': 3,
                                   'fingerprint': fingerprint, 'source': 'card_diff', 'source_kind': 'content'})
    return events


def coverage(snapshot: dict[str, Any]) -> dict[str, Any]:
    records = snapshot.get('card_activity', [])
    return {'expected': len(records), 'content': sum(bool(r.get('content_complete')) for r in records),
            'comments': sum(bool(r.get('comments_complete')) for r in records), 'updates': sum(bool(r.get('updates_complete')) for r in records),
            'failed': [r['title'] for r in records if not all(r.get(k) for k in ('content_complete', 'comments_complete', 'updates_complete'))]}
