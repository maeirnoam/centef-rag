import os
from typing import List, Dict, Any
import requests
from .asr_base import ASRClient

ELEVENLABS_ASR_URL = os.getenv("ELEVENLABS_ASR_URL")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")


class ElevenLabsASRClient(ASRClient):
    def transcribe(self, uri: str, lang: str = "en") -> List[Dict[str, Any]]:
        if not ELEVENLABS_ASR_URL or not ELEVENLABS_API_KEY:
            raise RuntimeError("ELEVENLABS_ASR_URL/ELEVENLABS_API_KEY not configured")
        payload = {"audio_url": uri, "language": lang}
        resp = requests.post(
            ELEVENLABS_ASR_URL,
            json=payload,
            headers={"Authorization": f"Bearer {ELEVENLABS_API_KEY}", "Content-Type": "application/json"},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        segments: List[Dict[str, Any]] = []
        for seg in data.get("segments", []):
            segments.append({
                "text": seg.get("text", "").strip(),
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
            })
        return segments
