import concurrent.futures
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from recording_to_text import models
from recording_to_text.review import clock, format_transcript
from recording_to_text.ui import save_corrected
from recording_to_text.transcribe import save_result, transcribe, validate_source


class TranscriptTests(unittest.TestCase):
    def test_parallel_saves_preserve_source_and_old_results(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'example.wav'
            source.write_bytes(b'original audio')
            old = source.with_name('example.음성변환.txt')
            old.write_bytes(b'old result')
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                paths = list(pool.map(lambda n: save_result(source, f'result {n}'), range(12)))
            self.assertEqual(12, len(set(paths)))
            self.assertEqual(b'original audio', source.read_bytes())
            self.assertEqual(b'old result', old.read_bytes())
            self.assertEqual({f'result {n}\n' for n in range(12)},
                             {p.read_text(encoding='utf-8-sig') for p in paths})
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_failed_write_has_no_final_or_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'example.wav'
            source.write_bytes(b'original')
            with patch('recording_to_text.transcribe.os.fsync', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    save_result(source, 'unfinished')
            self.assertEqual([source], list(Path(folder).iterdir()))

    def test_no_speech_creates_no_txt(self):
        model = SimpleNamespace(transcribe=lambda *args, **kwargs: (iter([]), SimpleNamespace(duration=2)))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'empty-speech.wav'
            source.write_bytes(b'test fixture')
            with self.assertRaisesRegex(ValueError, '말소리'):
                transcribe(source, model=model)
            self.assertEqual([source], list(Path(folder).iterdir()))

    def test_empty_and_unsupported_files_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'example.wav'
            source.touch()
            with self.assertRaises(ValueError):
                validate_source(source)
            source = Path(folder) / 'example.exe'
            source.write_bytes(b'test')
            with self.assertRaises(ValueError):
                validate_source(source)

    def test_low_confidence_speech_is_preserved_without_review_annotations(self):
        rows = [dict(start=45, end=50, text='확인 필요하다고 말씀하셨어요.', avg_logprob=-3,
                     words=[dict(start=46, end=47, word='말씀', probability=0.2)])]
        text, count = format_transcript(rows)
        self.assertEqual(0, count)
        self.assertIn('[00:45~00:50] 확인 필요하다고 말씀하셨어요.', text)
        self.assertNotIn('[확인 필요', text)
        self.assertNotIn('확인 이유:', text)
        self.assertNotIn('다시 들을 표현:', text)
        self.assertEqual('01:01:01', clock(3661))

    def test_corrected_copies_do_not_overwrite_original_or_prior_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'example.음성변환.txt'
            original.write_text('first draft', encoding='utf-8')
            first = save_corrected(original, '수정한 문장')
            second = save_corrected(original, '다시 수정한 문장')
            self.assertNotEqual(first, second)
            self.assertEqual('first draft', original.read_text(encoding='utf-8'))
            self.assertEqual('수정한 문장\n', first.read_text(encoding='utf-8-sig'))
            self.assertEqual('다시 수정한 문장\n', second.read_text(encoding='utf-8-sig'))

    def test_failed_corrected_save_does_not_leave_partial_file(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'example.음성변환.txt'
            original.write_text('first draft', encoding='utf-8')
            with patch('recording_to_text.ui.os.fsync', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    save_corrected(original, 'unfinished')
            self.assertEqual([original], list(Path(folder).iterdir()))

    def test_blank_segments_are_ignored(self):
        text, count = format_transcript([dict(start=0, end=1, text=' '), dict(start=1, end=2, text='예시')])
        self.assertEqual(0, count)
        self.assertIn('[00:01~00:02] 예시', text)
        self.assertNotIn('[00:00~00:01]', text)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = b'verified model fixture'
        self.item = dict(name='model.bin', size=len(self.data), sha256=hashlib.sha256(self.data).hexdigest())
        self.spec = dict(repo='example/model', revision='a' * 40, files=[self.item])
        self.enterContext(patch.dict(models.os.environ, RECORDING_TO_TEXT_HOME=self.temp.name))
        self.enterContext(patch.dict(models.MANIFEST, fixture=self.spec))

    def test_missing_model_does_not_contact_network_without_consent(self):
        with patch.object(models.urllib.request, 'urlopen') as request:
            with self.assertRaises(RuntimeError):
                models.ensure_model('fixture')
            request.assert_not_called()

    def test_verified_download_is_atomic_and_reusable_offline(self):
        with patch.object(models.urllib.request, 'urlopen', return_value=io.BytesIO(self.data)) as request:
            path = models.ensure_model('fixture', download=True)
            self.assertIn('/' + 'a' * 40 + '/model.bin', request.call_args.args[0].full_url)
        with patch.object(models.urllib.request, 'urlopen') as request:
            self.assertEqual(path, models.ensure_model('fixture'))
            request.assert_not_called()
        self.assertEqual(self.data, (path / 'model.bin').read_bytes())
        self.assertFalse(list(path.glob('*.part')))

    def test_corrupt_download_is_never_published(self):
        # Same length, wrong hash: size alone must not authorize model loading.
        with patch.object(models.urllib.request, 'urlopen', return_value=io.BytesIO(b'x' * len(self.data))):
            with self.assertRaises(ValueError):
                models.ensure_model('fixture', download=True)
        self.assertFalse((models.model_path('fixture') / 'model.bin').exists())
        self.assertFalse(list(models.model_path('fixture').glob('*.part')))

    def test_interrupted_download_is_not_a_ready_model(self):
        class Broken(io.BytesIO):
            def read(self, *args):
                raise TimeoutError('interrupted')
        with patch.object(models.urllib.request, 'urlopen', return_value=Broken()):
            with self.assertRaises(TimeoutError):
                models.ensure_model('fixture', download=True)
        self.assertTrue(models.needs_download('fixture'))
        self.assertFalse(list(models.model_path('fixture').glob('*.part')))

    def test_published_manifest_uses_safe_paths_and_pinned_revisions(self):
        for name, spec in models.MANIFEST.items():
            if name == 'fixture':
                continue
            self.assertRegex(spec['revision'], r'^[0-9a-f]{40}$')
            for item in spec['files']:
                self.assertEqual(Path(item['name']).name, item['name'])
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
                self.assertGreater(item['size'], 0)


if __name__ == '__main__':
    unittest.main()
