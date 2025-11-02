"""
Ingest video files: extract audio, transcribe with timestamps, translate, and chunk.
Supports Arabic transcription with translation to English.
"""
import json
import os
import sys
import tempfile
from typing import List, Dict, Optional
import re

from google.cloud import storage
from google.cloud import speech_v1 as speech
from google.cloud import translate_v2 as translate


def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# ====== ENV ======
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")
TARGET_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")
SOURCE_DATA_PREFIX = os.environ.get("SOURCE_DATA_PREFIX", "data").strip("/")
# =================================


def get_storage_client():
    return storage.Client()


def get_speech_client():
    return speech.SpeechClient()


def get_translate_client():
    return translate.Client()


def extract_audio_to_gcs(video_gcs_uri: str, audio_gcs_uri: str) -> str:
    """
    Extract audio from video and save to GCS.
    Note: This requires ffmpeg. For production, you might want to use a Cloud Function
    or Cloud Run job with ffmpeg installed, or use a service like Video Intelligence API.
    
    For now, this is a placeholder - you'll need to handle audio extraction separately
    or upload the audio directly.
    """
    print(f"NOTE: Audio extraction requires external processing.")
    print(f"Please extract audio from {video_gcs_uri} and upload to {audio_gcs_uri}")
    print(f"Or use the audio file directly if available.")
    return audio_gcs_uri


def transcribe_audio_with_timestamps(audio_gcs_uri: str, language_code: str = "ar-SA") -> List[Dict]:
    """
    Transcribe audio with word-level timestamps using Google Speech-to-Text.
    Returns list of segments with timestamps and text.
    """
    print(f"Transcribing audio: {audio_gcs_uri}")
    print(f"Language: {language_code}")
    
    client = get_speech_client()
    
    audio = speech.RecognitionAudio(uri=audio_gcs_uri)
    
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code=language_code,
        enable_word_time_offsets=True,
        enable_automatic_punctuation=True,
        model="default",  # or "video" for video content
    )
    
    # Use long_running_recognize for files > 1 minute
    operation = client.long_running_recognize(config=config, audio=audio)
    
    print("Waiting for transcription to complete...")
    response = operation.result(timeout=600)  # 10 minute timeout
    
    segments = []
    
    for result in response.results:
        alternative = result.alternatives[0]
        
        # Get the full transcript for this segment
        transcript = alternative.transcript
        
        # Get timing from word offsets
        if alternative.words:
            start_time = alternative.words[0].start_time.total_seconds()
            end_time = alternative.words[-1].end_time.total_seconds()
        else:
            # Fallback if no word timings
            start_time = 0.0
            end_time = 0.0
        
        segments.append({
            'text': transcript,
            'start_sec': start_time,
            'end_sec': end_time,
            'language': language_code
        })
    
    print(f"Transcribed {len(segments)} segments")
    return segments


def translate_segments(segments: List[Dict], target_language: str = "en") -> List[Dict]:
    """
    Translate text segments to target language.
    Adds translated_text field to each segment.
    """
    print(f"Translating {len(segments)} segments to {target_language}...")
    
    client = get_translate_client()
    
    for seg in segments:
        # Translate the text
        result = client.translate(
            seg['text'],
            target_language=target_language,
            source_language=seg.get('language', 'ar')[:2]  # Just language code, not locale
        )
        
        seg['translated_text'] = result['translatedText']
        seg['detected_source_language'] = result.get('detectedSourceLanguage', '')
    
    print("Translation complete")
    return segments


def window_segments(segments: List[Dict], window_seconds: float = 30.0) -> List[Dict]:
    """
    Combine segments into time windows similar to SRT processing.
    """
    if not segments:
        return []
    
    windowed = []
    current_window = []
    window_start = segments[0]['start_sec']
    
    for seg in segments:
        # Check if adding this segment would exceed the window
        if current_window and (seg['end_sec'] - window_start) > window_seconds:
            # Finalize current window
            windowed.append({
                'text': ' '.join(s['text'] for s in current_window),
                'translated_text': ' '.join(s.get('translated_text', '') for s in current_window),
                'start_sec': window_start,
                'end_sec': current_window[-1]['end_sec'],
                'language': current_window[0].get('language', ''),
                'segment_count': len(current_window)
            })
            
            # Start new window
            current_window = [seg]
            window_start = seg['start_sec']
        else:
            current_window.append(seg)
    
    # Finalize last window
    if current_window:
        windowed.append({
            'text': ' '.join(s['text'] for s in current_window),
            'translated_text': ' '.join(s.get('translated_text', '') for s in current_window),
            'start_sec': window_start,
            'end_sec': current_window[-1]['end_sec'],
            'language': current_window[0].get('language', ''),
            'segment_count': len(current_window)
        })
    
    return windowed


def segments_to_chunks(segments: List[Dict], source_uri: str) -> List[Dict]:
    """Convert windowed segments to Discovery Engine chunks"""
    chunks = []
    base_name = source_uri.split("/")[-1].replace(".mp4", "").replace(".m4a", "").replace(".wav", "")
    # Sanitize base_name
    base_name = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
    
    for i, seg in enumerate(segments, 1):
        chunk = {
            "id": f"{base_name}_chunk_{i}",
            "structData": {
                "text": seg.get('translated_text', seg['text']),  # Use translated if available
                "text_original": seg['text'],  # Keep original
                "source_uri": source_uri,
                "start_sec": seg['start_sec'],
                "end_sec": seg['end_sec'],
                "duration_sec": seg['end_sec'] - seg['start_sec'],
                "language": seg.get('language', ''),
                "segment_count": seg.get('segment_count', 1),
                "type": "video_transcript",
                "extractor": "speech_to_text"
            }
        }
        chunks.append(chunk)
    
    return chunks


def upload_jsonl(records: List[Dict], target_blob: str):
    """Upload chunks as JSONL to GCS"""
    storage_client = get_storage_client()
    bucket = storage_client.bucket(TARGET_BUCKET)
    blob = bucket.blob(target_blob)
    ndjson = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")
    print(f"[OK] Uploaded {len(records)} chunks → gs://{TARGET_BUCKET}/{target_blob}")


def process_video(video_gcs_uri: str, audio_gcs_uri: Optional[str] = None, 
                  language_code: str = "ar-SA", translate_to: str = "en",
                  window_seconds: float = 30.0):
    """
    Process a video: transcribe audio, translate, and create chunks.
    
    Args:
        video_gcs_uri: GCS URI of the video file
        audio_gcs_uri: GCS URI of extracted audio (or None to derive from video URI)
        language_code: Language code for transcription (e.g., "ar-SA" for Arabic)
        translate_to: Target language for translation (e.g., "en" for English)
        window_seconds: Time window for chunking
    """
    print(f"\n== Processing video: {video_gcs_uri}")
    print(f"Window size: {window_seconds}s")
    
    # If no audio URI provided, assume audio needs extraction or is provided separately
    if not audio_gcs_uri:
        # For now, user must provide audio separately
        audio_gcs_uri = video_gcs_uri.replace(".mp4", ".wav")
        print(f"\nNOTE: Please ensure audio is available at: {audio_gcs_uri}")
        print(f"You can extract audio using ffmpeg:")
        print(f"  ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output.wav")
        print(f"Then upload to GCS.\n")
    
    # Transcribe with timestamps
    segments = transcribe_audio_with_timestamps(audio_gcs_uri, language_code)
    
    if not segments:
        print("ERROR: No transcription segments generated")
        return
    
    # Translate if target language is different
    if translate_to and translate_to != language_code[:2]:
        segments = translate_segments(segments, translate_to)
    
    # Window the segments
    windowed = window_segments(segments, window_seconds)
    print(f"Created {len(windowed)} time windows from {sum(w['segment_count'] for w in windowed)} segments")
    
    # Convert to chunks
    chunks = segments_to_chunks(windowed, video_gcs_uri)
    
    # Show preview
    if chunks:
        first = chunks[0]
        print(f"\nFirst chunk preview:")
        print(f"  Duration: {first['structData']['duration_sec']:.1f}s")
        print(f"  Original: {first['structData']['text_original'][:100]}...")
        print(f"  Translated: {first['structData']['text'][:100]}...")
    
    # Upload
    rel_path = video_gcs_uri.replace(f"gs://{SOURCE_BUCKET}/", "")
    # Sanitize path: replace :// with _ to avoid GCS path issues (e.g., youtube://id -> youtube_id)
    rel_path = rel_path.replace("://", "_")
    target_blob = f"{rel_path}.jsonl"
    upload_jsonl(chunks, target_blob)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest video with transcription and translation")
    parser.add_argument("video_uri", help="GCS URI of video file (gs://bucket/path/video.mp4)")
    parser.add_argument("--audio-uri", help="GCS URI of audio file (if extracted separately)")
    parser.add_argument("--language", default="ar-SA", help="Source language code (default: ar-SA)")
    parser.add_argument("--translate", default="en", help="Target language for translation (default: en)")
    parser.add_argument("--window", type=float, default=30.0, help="Time window in seconds (default: 30)")
    
    args = parser.parse_args()
    
    process_video(
        video_gcs_uri=args.video_uri,
        audio_gcs_uri=args.audio_uri,
        language_code=args.language,
        translate_to=args.translate,
        window_seconds=args.window
    )


if __name__ == "__main__":
    main()
