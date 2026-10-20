import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import sp9_digest as digest
from test_sp9_digest import TZ, task, snapshot

NOW = datetime(2026, 10, 12, 11, 30, tzinfo=TZ)


class EditorialTests(unittest.TestCase):
    def sample(self):
        item = task('Чекаут', 'In Progress')
        event = {**digest._event('update', item, 'Алексей: комментарий «Собрал макеты»', 4),
                 'source_kind': 'comment', 'author': 'Aleksei Gruzdev',
                 'raw_text': 'Собрал макеты и документацию.', 'occurred_at': '2026-10-12'}
        data = snapshot([item], captured_at=NOW.isoformat())
        evidence = digest._editorial_input(data, [event], NOW)
        editorial = {'rows': [{'section': 'progress', 'task_ids': [digest._task_key(item)],
                               'labels': ['Чекаут'], 'summary': 'Алексей собрал макеты и документацию.',
                               'source_ids': [event['fingerprint']]}], 'omitted': []}
        return data, event, evidence, editorial

    def test_approved_sections_one_post_and_own_work(self):
        data, event, evidence, editorial = self.sample()
        digest._validate_editorial(editorial, evidence)
        text = digest.render_editorial_digest(data, [event], editorial, current_time=NOW)
        self.assertIn('🛠 В работе', text)
        self.assertIn('Алексей собрал макеты', text)
        self.assertNotIn('Проверено:', text)
        self.assertNotIn('Требует внимания', text)
        self.assertEqual(len(digest.split_digest(text)), 1)

    def test_substantive_own_comment_cannot_be_silently_excluded(self):
        _, _, evidence, _ = self.sample()
        editorial = {'rows': [], 'omitted': [{'source_ids': [evidence['sources'][0]['id']], 'reason': 'priority_only'}]}
        with self.assertRaises(RuntimeError):
            digest._validate_editorial(editorial, evidence)

    def test_unknown_link_and_duplicate_task_are_rejected(self):
        _, _, evidence, editorial = self.sample()
        editorial['rows'][0]['task_ids'] = ['invented-page']
        with self.assertRaises(RuntimeError):
            digest._validate_editorial(editorial, evidence)
        _, _, evidence, editorial = self.sample()
        editorial['rows'].append(copy.deepcopy(editorial['rows'][0]))
        with self.assertRaises(RuntimeError):
            digest._validate_editorial(editorial, evidence)

    def test_missing_source_and_falsely_completed_task_are_rejected(self):
        _, _, evidence, editorial = self.sample()
        with self.assertRaises(RuntimeError):
            digest._validate_editorial({'rows': [], 'omitted': []}, evidence)
        editorial['rows'][0]['section'] = 'completed'
        with self.assertRaises(RuntimeError):
            digest._validate_editorial(editorial, evidence)

    def test_source_task_must_match_row(self):
        data, event, evidence, editorial = self.sample()
        other = task('Другая задача', 'In Progress')
        second = digest._event('new_task', other, 'новая задача', 1)
        data['tasks'].append(other)
        evidence = digest._editorial_input(data, [event, second], NOW)
        editorial['rows'][0]['source_ids'].append(second['fingerprint'])
        with self.assertRaises(RuntimeError):
            digest._validate_editorial(editorial, evidence)

    def test_technical_priority_can_be_omitted_without_inventing_progress(self):
        data, event, _, _ = self.sample()
        event['source_kind'] = 'property_update'
        event['details'] = 'обновлены свойства: Urgency'
        evidence = digest._editorial_input(data, [event], NOW)
        editorial = {'rows': [], 'omitted': [{'source_ids': [event['fingerprint']], 'reason': 'priority_only'}]}
        digest._validate_editorial(editorial, evidence)
        text = digest.render_editorial_digest(data, [event], editorial, current_time=NOW)
        self.assertNotIn('Urgency', text)
        self.assertIn('Значимых новых результатов', text)

    def test_completed_task_only_appears_in_completed_section(self):
        data, event, _, editorial = self.sample()
        data['tasks'][0]['status'] = 'Completed'
        evidence = digest._editorial_input(data, [event], NOW)
        with self.assertRaises(RuntimeError):
            digest._validate_editorial(editorial, evidence)
        editorial['rows'][0]['section'] = 'completed'
        editorial['rows'][0]['summary'] = 'Completed; макеты и документация готовы.'
        digest._validate_editorial(editorial, evidence)
        text = digest.render_editorial_digest(data, [event], editorial, current_time=NOW)
        self.assertEqual(text.count('>Чекаут</a>'), 1)
        self.assertIn('✅ Завершено', text)

    def test_local_editorial_saves_audit_without_sending_sources_to_external_process(self):
        data, event, _, _ = self.sample()
        with tempfile.TemporaryDirectory() as directory, patch.object(digest.subprocess, 'run') as external:
            root = Path(directory)
            text = digest.prepare_editorial_digest(data, [event], root, current_time=NOW)
            self.assertTrue((root / 'editorial.json').exists())
            self.assertTrue((root / 'editorial_sources.json').exists())
            self.assertIn('Алексей', text)
            self.assertIn('Собрал макеты и документацию', text)
            external.assert_not_called()

    def test_local_completed_row_drops_old_request_and_keeps_result(self):
        data, event, _, _ = self.sample()
        data['tasks'][0]['status'] = 'Completed'
        question = {**event, 'fingerprint': 'old-question', 'raw_text': 'Когда будут готовы материалы?'}
        evidence = digest._editorial_input(data, [question, event], NOW)
        editorial = digest._local_editorial(evidence, excerpt_limit=140)
        digest._validate_editorial(editorial, evidence)
        self.assertEqual(editorial['rows'][0]['section'], 'completed')
        self.assertNotIn('Когда будут', editorial['rows'][0]['summary'])

    def test_local_new_series_are_grouped_with_each_verified_link(self):
        tasks = [task(f'SMM видео (серия {i})', 'To Do', f'2026-10-{12+i:02d}') for i in range(1, 5)]
        events = [digest._event('new_task', item, 'новая задача в To Do', 1) for item in tasks]
        evidence = digest._editorial_input(snapshot(tasks), events, NOW)
        editorial = digest._local_editorial(evidence, excerpt_limit=140)
        digest._validate_editorial(editorial, evidence)
        self.assertEqual(len(editorial['rows']), 1)
        self.assertEqual(len(editorial['rows'][0]['task_ids']), 4)

    def test_local_questions_have_priority_over_progress_for_same_task(self):
        data, event, _, _ = self.sample()
        event['raw_text'] = 'Обновил тарифы. Сокращаем ли список до пяти?'
        evidence = digest._editorial_input(data, [event], NOW)
        editorial = digest._local_editorial(evidence, excerpt_limit=140)
        digest._validate_editorial(editorial, evidence)
        self.assertEqual(editorial['rows'][0]['section'], 'attention')
        self.assertEqual(len(editorial['rows']), 1)

    def test_link_query_is_not_an_open_question(self):
        data, event, _, _ = self.sample()
        event['raw_text'] = 'Добавил макет. https://figma.com/design/file?node-id=10'
        evidence = digest._editorial_input(data, [event], NOW)
        editorial = digest._local_editorial(evidence, excerpt_limit=140)
        digest._validate_editorial(editorial, evidence)
        self.assertEqual(editorial['rows'][0]['section'], 'progress')
        self.assertNotIn('node-id', editorial['rows'][0]['summary'])

    def test_due_date_change_is_not_filtered_out_as_a_technical_property(self):
        data, event, _, _ = self.sample()
        event['source_kind'] = 'due_date'
        event['raw_text'] = ''
        event['details'] = 'дедлайн: 05.10 → 15.10'
        evidence = digest._editorial_input(data, [event], NOW)
        editorial = digest._local_editorial(evidence, excerpt_limit=140)
        digest._validate_editorial(editorial, evidence)
        self.assertIn('05.10 → 15.10', editorial['rows'][0]['summary'])

    def test_local_source_mentions_do_not_leave_fragments_of_names(self):
        text = digest._source_excerpt({'raw_text': '@superpasha9 @Annaa Lobanova @Юлия Е.\nпомогите пожалуйста собрать письма'}, 140)
        self.assertEqual(text, 'собрать письма')

    def test_waits_even_when_ready_fifty_minutes_early(self):
        clock = [NOW.replace(hour=11, minute=0)]
        def sleep(seconds):
            clock[0] += timedelta(seconds=seconds)
        with patch.object(digest, '_now', side_effect=lambda: clock[0]), patch.object(digest.time, 'sleep', side_effect=sleep) as sleeper:
            digest._wait_until('11:50', now=clock[0])
        self.assertEqual(clock[0].strftime('%H:%M'), '11:50')
        self.assertEqual(sum(call.args[0] for call in sleeper.call_args_list), 3000)
        self.assertTrue(all(call.args[0] <= 60 for call in sleeper.call_args_list))


if __name__ == '__main__':
    unittest.main()
