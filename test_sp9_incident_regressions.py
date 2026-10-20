"""Regressions from 13 October, using bounded fixtures and no external calls."""
import copy
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import sp9_activity as activity
import sp9_digest as digest
from test_sp9_digest import task, snapshot, TZ
from test_sp9_activity import record

KEY = '3e341fd053ce8063adb8ee9517fe86d4'
URL = 'https://app.notion.com/p/' + KEY
NOW = datetime(2026, 10, 14, 11, 30, tzinfo=TZ)


def properties(names='Pasha\nIlmira', status='To Do'):
    return ('Customize layout\nActual title\nStatus\n' + status +
            '\nDeadline\nOctober 15, 2026\nAssignee\n' + names +
            '\nCreated by\nAuthor\nComments\n')


class CaptureRegressions(unittest.TestCase):
    def test_actual_title_can_differ_from_ocr_when_dom_id_matches(self):
        page = MagicMock()
        page.url = URL
        page.locator.return_value.inner_text.return_value = properties()
        data = {'content': [{'id': 'block', 'text': 'Brief', 'links': []}],
                'direct': [], 'discussion_present': True, 'history': []}
        def evaluate(js, *args, **kwargs):
            if js == activity._READ_JS:
                return copy.deepcopy(data)
            if args and args[0] == KEY:
                return '[ALL] Промо Free Challenge Retry Promo'
            return False
        page.evaluate.side_effect = evaluate
        with tempfile.TemporaryDirectory() as folder, patch.object(activity, '_read_history', return_value=({'history': []}, True)):
            result = activity._capture_card(page, {'title': '[ALL] Promo Free Challenge Retry Promo', 'url': URL}, Path(folder), date(2026,10,13))
        self.assertTrue(result['identity_verified'])
        self.assertTrue(result['content_complete'])
        self.assertEqual(result['observed_title'], '[ALL] Промо Free Challenge Retry Promo')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['properties']['assignees'], ['Pasha', 'Ilmira'])
        self.assertIn('.notion-frame', page.wait_for_function.call_args.args[0])

    def test_different_page_id_is_rejected_even_with_matching_title(self):
        page = MagicMock()
        page.url = 'https://app.notion.com/p/' + 'a' * 32
        with self.assertRaisesRegex(activity.capture.BrowserCaptureError, 'другим ID'):
            activity._wait_for_card_identity(page, KEY)

    def test_lazy_history_body_is_not_complete_in_current_window(self):
        h = [{'header': 'Author edited Task', 'time': 'October 13, 2026', 'text': ''}]
        self.assertFalse(activity._history_readable(h, date(2026,10,13), NOW))
        h[0]['text'] = 'Status\nReview\nCompleted'
        self.assertTrue(activity._history_readable(h, date(2026,10,13), NOW))
        h[0].update(time='September 16, 2026', text='')
        self.assertTrue(activity._history_readable(h, date(2026,10,13), NOW))

    def test_retry_saves_both_failures_and_partial_data(self):
        first = {**record(), 'url': URL, 'content_complete': True,
                 'comments_complete': False, 'updates_complete': False,
                 'errors': ['Updates: Timeout'], 'retryable': True}
        second = {**first, 'content_complete': False, 'content': [],
                  'errors': ['Page.goto: Timeout'], 'retryable': True}
        with tempfile.TemporaryDirectory() as folder, patch.object(activity.capture, '_playwright', return_value=MagicMock()), patch.object(activity.capture, '_launch_context', return_value=MagicMock()), patch.object(activity, '_capture_card', side_effect=[first, second]) as capture:
            dest = Path(folder)
            result = activity.capture_card_activity([{'title': 'Task', 'url': URL}], dest, since=date(2026,10,13))
            saved = json.loads((dest/(KEY+'.json')).read_text())
            self.assertEqual(capture.call_count, 2)
            self.assertEqual(len(saved['attempts']), 2)
            self.assertEqual(len(list(dest.glob('*.json'))), 1)
            self.assertTrue((dest/'attempts'/KEY/'01.json').exists())
            self.assertTrue((dest/'attempts'/KEY/'02.json').exists())
            self.assertEqual(saved['content'], first['content'])
            self.assertEqual(saved['errors'], ['Updates: Timeout', 'Page.goto: Timeout'])
            self.assertEqual(result[0], saved)

    def test_history_lazy_reload_preserves_previously_read_event(self):
        first = {'header': 'A commented Task', 'time': 'October 13, 2026', 'text': 'Ready', 'items': []}
        pending = {'header': 'B edited Task', 'time': 'October 12, 2026', 'text': '', 'items': []}
        old = {'header': 'A edited Task', 'time': 'September 16, 2026', 'text': '', 'items': []}
        page = MagicMock()
        page.evaluate.side_effect = [
            {'history': [first, pending], 'panel_text': ''},
            {'history': [{**pending, 'text': 'Status\nTo Do\nReview'}, old], 'panel_text': ''},
        ]
        with patch.object(activity, '_open_history'):
            data, complete = activity._read_history(page, date(2026, 10, 12), NOW)
        self.assertTrue(complete)
        self.assertEqual(len(data['history']), 3)
        self.assertEqual(data['history'][0]['text'], 'Ready')

    def test_history_missing_body_stays_incomplete_when_virtualized_away(self):
        page = MagicMock()
        page.evaluate.side_effect = [
            {'history': [{'header': 'A edited Task', 'time': 'October 13, 2026', 'text': ''}], 'panel_text': ''},
            *[{'history': [], 'panel_text': 'No updates'} for _ in range(3)],
        ]
        with patch.object(activity, '_open_history'):
            data, complete = activity._read_history(page, date(2026, 10, 12), NOW)
        self.assertFalse(complete)
        self.assertEqual(len(data['history']), 1)

    def test_retry_can_complete_other_components_without_erasing_content(self):
        first = {**record(), 'comments_complete': False, 'updates_complete': False, 'errors': ['Timeout']}
        second = {**record(), 'content_complete': False, 'content': [], 'errors': ['Content timeout']}
        merged = activity.merge_card_attempts(first, second)
        self.assertTrue(all(merged[k] for k in ('content_complete','comments_complete','updates_complete')))
        self.assertEqual(merged['content'], first['content'])
        self.assertEqual(merged['errors'], [])

    def test_empty_retry_preserves_partial_content_without_claiming_completeness(self):
        first = {**record(), 'content_complete': False, 'comments_complete': False, 'updates_complete': False, 'errors': ['Partial']}
        second = {**first, 'content': [], 'comments': [], 'history': [], 'errors': ['Timeout']}
        merged = activity.merge_card_attempts(first, second)
        self.assertEqual(merged['content'], first['content'])
        self.assertEqual(merged['history'], first['history'])
        self.assertFalse(merged['content_complete'])


class FactRegressions(unittest.TestCase):
    def test_warning_identifies_the_unread_component(self):
        data = {'activity_coverage': {'failed': ['Task']}, 'card_activity': [
            {'title': 'Task', 'url': URL, 'content_complete': True, 'comments_complete': True, 'updates_complete': False}]}
        lines = digest._activity_warning_lines(data)
        self.assertIn(' — Updates', lines[1])
        self.assertNotIn('комментарии', lines[1])
        self.assertNotIn('содержимое', lines[1])

    def boards(self, current_names, body):
        before = snapshot([task('Task', 'To Do', '2026-10-15', URL)], captured_at='2026-10-13T12:00:00+03:00')
        before['tasks'][0]['assignees'] = ['Pasha', 'Ilmira']
        current = copy.deepcopy(before)
        current['captured_at'] = NOW.isoformat()
        current['tasks'][0]['assignees'] = current_names
        current['card_activity'] = [{**record(), 'url': URL, 'page_text': body}]
        baseline = [{**record(), 'url': URL, 'page_text': properties()}]
        old = digest._verified_comparison(current, before, baseline)
        return old, current

    def test_ocr_omission_does_not_remove_a_directly_read_assignee(self):
        old, current = self.boards(['Ilmira'], properties())
        self.assertEqual(digest.diff_tasks(old, current), [])
        self.assertEqual(current['tasks'][0]['assignees'], ['Pasha','Ilmira'])

    def test_explicit_empty_assignment_still_produces_a_real_removal(self):
        old, current = self.boards(['Ilmira'], properties('Empty'))
        changes = digest.diff_tasks(old,current)
        self.assertEqual([c['kind'] for c in changes], ['assignees'])
        self.assertIn('не назначены', changes[0]['details'])

    def test_unread_properties_do_not_erase_the_verified_previous_values(self):
        old, current = self.boards([], '')
        self.assertEqual(digest.diff_tasks(old,current), [])
        self.assertEqual(current['tasks'][0]['assignees'], ['Pasha','Ilmira'])

    def test_newly_read_property_is_not_a_change_when_old_value_was_unverified(self):
        before=snapshot([task('Task','To Do','2026-10-15',URL)])
        current=copy.deepcopy(before)
        current['card_activity']=[{**record(),'url':URL,'page_text':properties()}]
        old=digest._verified_comparison(current,before,[])
        self.assertEqual(digest.diff_tasks(old,current),[])
        self.assertEqual(current['tasks'][0]['assignees'],['Pasha','Ilmira'])

    def test_property_parser_distinguishes_unread_and_empty(self):
        self.assertNotIn('assignees', activity.card_properties({'page_text':'Customize layout\nStatus\nTo Do\nComments\n'}))
        self.assertEqual(activity.card_properties({'page_text':properties('Empty'),'captured_at':NOW.isoformat()})['assignees'], [])

    def test_verified_completion_outside_visible_archive_is_compared(self):
        previous = snapshot([task('Task', 'To Do', '2026-10-15', URL)])
        current = snapshot([])
        current['card_activity'] = [{**record(), 'url': URL, 'page_text': properties(status='Completed')}]
        baseline = [{**record(), 'url': URL, 'page_text': properties()}]
        old = digest._verified_comparison(current, previous, baseline)
        self.assertEqual(current['tasks'][0]['status'], 'Completed')
        self.assertEqual([c['kind'] for c in digest.diff_tasks(old, current)], ['status'])

    def test_unverified_completion_does_not_restore_archived_task(self):
        previous = snapshot([task('Task', 'To Do', '2026-10-15', URL)])
        current = snapshot([])
        current['card_activity'] = [{'url': URL, 'page_text': properties(status='Completed')}]
        digest._verified_comparison(current, previous, [])
        self.assertEqual(current['tasks'], [])

    def test_future_due_date_with_explicit_year_is_preserved(self):
        self.assertEqual(activity.card_properties({'page_text':properties(),'captured_at':NOW.isoformat()})['due_date'], '2026-10-15')

    def test_verified_assignment_summary_preserves_the_actual_change(self):
        old,current=self.boards([],properties('Ilmira'))
        changes=digest.diff_tasks(old,current)
        evidence=digest._editorial_input(current,changes,NOW)
        editorial=digest._local_editorial(evidence,excerpt_limit=240)
        digest._validate_editorial(editorial,evidence)
        self.assertIn('сняты с задачи: Pasha',editorial['rows'][0]['summary'])
        self.assertNotIn('Ilmira →',editorial['rows'][0]['summary'])


class EditorialRegressions(unittest.TestCase):
    def evidence(self,status='In Progress',kind='content',raw='',details='',day='2026-10-13'):
        return {'today':'2026-10-14','since':'2026-10-13',
                'tasks':[{'id':KEY,'title':'Task','status':status,'assignees':['Pasha'],'due_date':'2026-10-15'}],
                'sources':[{'id':'source','task_id':KEY,'kind':kind,'raw_text':raw,'details':details,'date':day,'author':'Pasha'}]}

    def test_old_completed_content_diff_is_not_a_new_completion(self):
        e=self.evidence(status='Completed',raw='',details='изменено содержимое карточки',day=None)
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertEqual(result['rows'],[])
        invented={'rows':[{'section':'completed','task_ids':[KEY],'labels':['Task'],'summary':'Completed','source_ids':['source']}],'omitted':[]}
        with self.assertRaisesRegex(RuntimeError,'Нет подтверждённого'):
            digest._validate_editorial(invented,e)

    def test_old_transition_is_excluded_but_recent_completion_is_kept(self):
        e=self.evidence(status='Completed',kind='property_update',details='статус: Review → Completed',day='2026-09-16')
        self.assertEqual(digest._local_editorial(e,excerpt_limit=240)['rows'],[])
        e['sources'][0]['date']='2026-10-13'
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertIn('13.10',result['rows'][0]['summary'])

    def test_actual_completion_date_wins_over_later_observation(self):
        e=self.evidence(status='Completed',kind='property_update',details='статус: Review → Completed',day='2026-10-13')
        e['sources'].append({**e['sources'][0],'id':'observed','kind':'status','date':None,'observed_date':'2026-10-14'})
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertIn('Completed (13.10)',result['rows'][0]['summary'])
        self.assertNotIn('Completed (14.10)',result['rows'][0]['summary'])

    def test_observed_transition_does_not_invent_actual_completion_date(self):
        e=self.evidence(status='Completed',kind='status',details='статус: Review → Completed',day=None)
        e['sources'][0]['observed_date']='2026-10-14'
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertIn('проверено 14.10',result['rows'][0]['summary'])

    def test_icon_change_is_omitted_without_inventing_progress(self):
        e=self.evidence(raw='Task\nPage icon')
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertEqual(result['rows'],[])

    def test_all_numbered_requests_survive_a_long_introduction(self):
        raw=('Context '*100+'\n1. Launch message with conditions\n2. Neutral trigger template\n3. Follow-up after failure\n4. Reminder to participants who did not start')
        e=self.evidence(kind='comment',raw=raw)
        result=digest._local_editorial(e,excerpt_limit=140)
        digest._validate_editorial(result,e)
        summary=result['rows'][0]['summary']
        for value in ('1. Launch','2. Neutral','3. Follow-up','4. Reminder'):
            self.assertIn(value,summary)

    def test_two_substantive_comments_are_both_displayed(self):
        e=self.evidence(kind='comment',raw='Макеты готовы.')
        e['sources'].append({**e['sources'][0],'id':'question','raw_text':'Можно сократить тарифы до пяти?'})
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertIn('Макеты готовы',result['rows'][0]['summary'])
        self.assertIn('сократить тарифы',result['rows'][0]['summary'])
        self.assertEqual(result['rows'][0]['section'], 'attention')

    def test_video_attachment_is_an_update_without_claiming_completion(self):
        e=self.evidence(raw='Video\nattachment:abc-def:clip.mp4')
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertIn('добавлен видеофайл',result['rows'][0]['summary'])
        self.assertEqual(result['rows'][0]['section'],'progress')

    def test_deleted_video_is_not_claimed_as_added(self):
        e=self.evidence(raw='Deleted\nVideo\nattachment:abc-def:clip.mp4')
        result=digest._local_editorial(e,excerpt_limit=240)
        digest._validate_editorial(result,e)
        self.assertEqual(result['rows'],[])

    def test_period_context_keeps_a_previously_observed_comment(self):
        r=record(time='October 13, 2026')
        r['captured_at']=NOW.isoformat()
        data=snapshot([task(r['title'],'In Progress',url=r['url'])],captured_at=NOW.isoformat())
        data.update(card_activity=[r],activity_since='2026-10-13')
        before=copy.deepcopy(data)
        evidence=digest._editorial_input(data,[],NOW)
        self.assertTrue(any(s['kind']=='comment' for s in evidence['sources']))
        self.assertEqual(data,before)

    def test_scenario_excerpt_preserves_requirements_without_ui_noise(self):
        text=digest._source_excerpt({'kind':'content','raw_text':'Важно добавить субтитры\nФормат видео 9:16\nDeleted\nVideo\nattachment:abc-def:clip.mp4\nСерия 4. «News Trader»\nJAY: Example dialogue'},240)
        for word in ('News Trader','субтитры','9:16'):
            self.assertIn(word,text)
        for noise in ('Deleted','clip.mp4','JAY:'):
            self.assertNotIn(noise,text)


if __name__=='__main__':
    unittest.main()
