class FrameOCR:
    """Text drawn on a few evenly spaced frames. Many reels name the paper
    or tool only on screen, over music."""

    def __init__(self, frames: int = 4, min_score: float = 0.6):
        self.frames, self.min_score = frames, min_score
        self._engine = None

    def __call__(self, path: str) -> str | None:
        import av

        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        seen: list[str] = []
        with av.open(path) as container:
            if not container.streams.video:
                return None
            stream = container.streams.video[0]
            duration = (container.duration or 0) / av.time_base
            for i in range(self.frames):
                at = duration * (i + 1) / (self.frames + 1)
                container.seek(int(at / stream.time_base), stream=stream)
                frame = next(container.decode(stream), None)
                if frame is None:
                    continue
                result, _ = self._engine(frame.to_ndarray(format="bgr24"))
                for _, text, score in result or []:
                    text = text.strip()
                    if float(score) >= self.min_score and text and text not in seen:
                        seen.append(text)
        return " | ".join(seen) or None
