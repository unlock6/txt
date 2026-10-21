# Third-party components

This repository contains an original GUI/CLI wrapper and review heuristics. It does not contain a copy of the inference engine, model weights, recordings, or user transcripts. The MIT license at the repository root covers this app's source; dependency and model licenses remain separate.

| Component | Source / license | Use |
| --- | --- | --- |
| faster-whisper | [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper), [MIT, copyright 2023 SYSTRAN](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) | Python inference API |
| Whisper | [openai/whisper](https://github.com/openai/whisper), [MIT, copyright 2022 OpenAI](https://github.com/openai/whisper/blob/main/LICENSE) | Original speech recognition models |
| Small CTranslate2 model | [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small) (model card: MIT) | Downloaded on request |
| Turbo CTranslate2 model | [dropbox-dash/faster-whisper-large-v3-turbo](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo) (model card: MIT) | Downloaded on request |
| CTranslate2 | [OpenNMT/CTranslate2](https://github.com/OpenNMT/CTranslate2), MIT | CPU inference runtime |
| PyAV | [PyAV-Org/PyAV](https://github.com/PyAV-Org/PyAV), BSD-3-Clause | Audio decoding, with FFmpeg libraries supplied by its wheel |
| FFmpeg | [FFmpeg legal information](https://ffmpeg.org/legal.html) | Its license depends on the distributed build and enabled components |

pip installs these and additional dependencies with their own notices. The repository does not redistribute their binaries. If you later distribute a bundled executable, include the applicable notices and satisfy the obligations for the exact packaged dependencies, including the FFmpeg build. Do not label the entire dependency bundle as MIT.
