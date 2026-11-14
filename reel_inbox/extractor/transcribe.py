import os

from reel_inbox.paths import data_dir


class WhisperTranscriber:
    """faster-whisper, loaded on first use. The model is downloaded on that
    first use (huggingface_hub prints a progress bar), never bundled.
    CPU with int8 works everywhere; device="cuda" is the opt-in."""

    def __init__(self, model: str = "small", device: str = "cpu", compute_type: str = "int8"):
        self.model_name, self.device, self.compute_type = model, device, compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            # Windows without Developer Mode cannot symlink; the cache copies
            # instead, which is fine, so the warning is noise.
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type,
                download_root=str(data_dir() / "models" / "whisper"),
            )
        return self._model

    def __call__(self, path: str) -> str | None:
        # vad_filter: reels are often music under speech, and Whisper invents
        # words in long non-speech stretches.
        segments, _ = self._load().transcribe(path, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip() or None
