import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from recording_to_text.processing_options import transcription_segments


class Model:
    def __init__(self):
        self.calls = []

    def transcribe(self, source, **kwargs):
        self.calls.append((source, kwargs))
        return iter(()), SimpleNamespace(duration=1)


class FakePipeline:
    instances = []

    def __init__(self, model):
        self.model = model
        self.calls = []
        self.instances.append(self)

    def transcribe(self, source, **kwargs):
        self.calls.append((source, kwargs))
        return iter(()), SimpleNamespace(duration=1)


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        FakePipeline.instances.clear()

    def test_default_preserves_original_model_options(self):
        model = Model()
        transcription_segments(model, Path('example.wav'))
        self.assertEqual(1, len(model.calls))
        source, kwargs = model.calls[0]
        self.assertEqual('example.wav', source)
        self.assertEqual('ko', kwargs['language'])
        self.assertEqual(5, kwargs['beam_size'])
        self.assertTrue(kwargs['word_timestamps'])
        self.assertTrue(kwargs['vad_filter'])
        self.assertFalse(kwargs['condition_on_previous_text'])
        self.assertNotIn('batch_size', kwargs)

    def test_fast_mode_preserves_word_timestamps_and_isolates_files(self):
        model = Model()
        module = SimpleNamespace(BatchedInferencePipeline=FakePipeline)
        with patch.dict(sys.modules, {'faster_whisper': module}):
            transcription_segments(model, Path('first.wav'), speed='fast')
            transcription_segments(model, Path('second.wav'), speed='fast')
        self.assertEqual(2, len(FakePipeline.instances))
        self.assertIsNot(FakePipeline.instances[0], FakePipeline.instances[1])
        self.assertEqual([], model.calls)
        for wrapper in FakePipeline.instances:
            self.assertIs(model, wrapper.model)
            _, kwargs = wrapper.calls[0]
            self.assertEqual(2, kwargs['batch_size'])
            self.assertEqual(5, kwargs['beam_size'])
            self.assertFalse(kwargs['without_timestamps'])
            self.assertTrue(kwargs['word_timestamps'])
            self.assertTrue(kwargs['vad_filter'])

    def test_invalid_speed_rejected_before_processing(self):
        model = Model()
        with self.assertRaises(ValueError):
            transcription_segments(model, Path('example.wav'), speed='other')
        self.assertEqual([], model.calls)


if __name__ == '__main__':
    unittest.main()
