from typing import List, Dict, Any
from .asr_base import ASRClient

# Note: For production, use google-cloud-speech v2 batch/longrunning on GCS URIs.
# Here we outline a minimal adapter; you can refine diarization/language hints as needed.
try:
    from google.cloud import speech_v2
except Exception:  # pragma: no cover
    speech_v2 = None


class GoogleASRClient(ASRClient):
    def __init__(self, project_id: str | None = None, location: str = "global", recognizer_id: str | None = None):
        self.project_id = project_id
        self.location = location
        self.recognizer_id = recognizer_id  # if you created a recognizer resource

    def transcribe(self, uri: str, lang: str = "en") -> List[Dict[str, Any]]:
        if speech_v2 is None:
            raise RuntimeError("google-cloud-speech not installed")
        client = speech_v2.SpeechClient()
        config = speech_v2.RecognitionConfig(
            auto_decoding_config=speech_v2.AutoDetectDecodingConfig(),
            language_codes=[lang],
            features=speech_v2.RecognitionFeatures(
                enable_word_time_offsets=True,
                enable_automatic_punctuation=True,
            ),
        )
        request = speech_v2.RecognizeRequest(
            recognizer=self._recognizer_path() if self.recognizer_id else None,
            config=config,
            uri=uri,
        )
        response = client.recognize(request=request)
        segments: List[Dict[str, Any]] = []
        # Coalesce words into utterances by phrase; simple mapping: each alternative as one segment
        for res in response.results:
            if not res.alternatives:
                continue
            alt = res.alternatives[0]
            words = alt.words
            if words:
                start = words[0].start_offset.total_seconds()
                end = words[-1].end_offset.total_seconds()
            else:
                start = 0.0
                end = 0.0
            segments.append({"text": alt.transcript.strip(), "start": start, "end": end})
        return segments

    def _recognizer_path(self) -> str:
        return f"projects/{self.project_id}/locations/{self.location}/recognizers/{self.recognizer_id}"
