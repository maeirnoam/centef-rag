from abc import ABC, abstractmethod
from typing import List, Dict, Any


class ASRClient(ABC):
    @abstractmethod
    def transcribe(self, uri: str, lang: str = "en") -> List[Dict[str, Any]]:
        """
        Returns a list of segments with timestamps:
        [
          {"text": "...", "start": 1.2, "end": 3.5},
          ...
        ]
        uri: typically a gs:// path pointing to audio or video
        """
        raise NotImplementedError
