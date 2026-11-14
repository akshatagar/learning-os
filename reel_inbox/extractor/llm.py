import json

from reel_inbox.extractor.schema import JSON_SCHEMA, REFERENT_TYPES

SYSTEM = f"""You read the evidence gathered from one short educational video \
(an Instagram Reel or YouTube Short) and name the specific thing it points at.

Most of these videos are aggregators: they summarize a paper, a tool, a repo, \
a technique, a claim or a person that exists elsewhere. The viewer has already \
watched the video. Do NOT summarize the video. Identify the referent and give \
the viewer a ready-made next step to find the original.

Fields:
- referent: the short canonical name of the thing, as you would type it into \
a search box (for example "Byte Latent Transformer" or "uv (Python package \
manager)"), not a sentence. null if the video points at nothing specific.
- referent_type: one of {", ".join(REFERENT_TYPES)}.
- search_query: the query most likely to find the primary source (the paper, \
the repo, the official page), not commentary about it.
- source_url_guess: a URL only if one appears in the evidence or you are \
certain of the canonical address; otherwise null. Never invent an arXiv id.
- confidence: 0 to 1, how sure you are that the referent is right.
- why_explorable: one line on why it is worth following up.

Evidence can be noisy speech-to-text or OCR. Prefer names that appear in the \
caption or on screen over names you infer."""


def build_evidence(meta: dict, spoken: str | None, on_screen: str | None,
                   limit: int = 6000) -> str | None:
    parts = [
        ("Title", meta.get("title")),
        ("Account", meta.get("uploader")),
        ("Caption", meta.get("description")),
        ("Spoken", spoken),
        ("On-screen text", on_screen),
    ]
    present = [
        (label, " ".join(str(value).split())[:limit])
        for label, value in parts
        if value and str(value).strip()
    ]
    if not present:
        return None
    return "\n\n".join(f"{label}:\n{value}" for label, value in present)


class OllamaReferent:
    def __init__(self, model: str = "qwen3:8b"):
        self.model = model

    def __call__(self, evidence: str) -> dict:
        import ollama

        def call():
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": evidence}],
                format=JSON_SCHEMA,
                think=False,
                options={"temperature": 0},
            )
            return json.loads(response["message"]["content"])

        try:
            return call()
        except (ConnectionError, ollama.ResponseError):
            # Ollama fails intermittently on this machine and recovers by
            # itself: one retry, then the failure is reported.
            return call()
