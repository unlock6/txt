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

    def test_review_markers_include_playback_time_and_limit(self):
        rows = [dict(start=45, end=50, text='다음 주에 전화 주세요.', avg_logprob=-0.2,
                     words=[dict(start=46, end=47, word='다음', probability=0.2)])]
        text, count = format_transcript(rows)
        self.assertEqual(1, count)
        self.assertIn('[확인 필요 00:45~00:50]', text)
        self.assertIn('다음 (00:46)', text)
        self.assertIn('표시가 없는 부분에도 오류', text)
        self.assertEqual('01:01:01', clock(3661))

    def test_non_flagged_text_is_not_claimed_correct(self):
        text, count = format_transcript([dict(start=0, end=1, text='예시', avg_logprob=-0.1)])
        self.assertEqual(0, count)
        self.assertIn('표시가 없는 부분에도 오류', text)


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
