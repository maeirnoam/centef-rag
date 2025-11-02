"""
Download audio from a YouTube URL (yt-dlp + ffmpeg), upload audio to GCS,
then call the existing video ingestion pipeline (transcribe -> translate -> chunk -> upload JSONL).

Usage example:
python tools/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID" \
  --language ar-SA --translate en --window 30
"""
import os
import re
import sys
import tempfile
import argparse
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yt_dlp
except Exception:
    yt_dlp = None

from google.cloud import storage

# We reuse process_video from tools/ingest_video.py
# It must be importable; running from repo root should work: `python tools/ingest_youtube.py ...`
try:
    from tools.ingest_video import process_video
except Exception:
    # If import fails, we'll fallback to calling ingest_video.py as a subprocess later
    process_video = None


def env(name: str, default: str = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v

SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")


def extract_video_id(youtube_url: str) -> str:
    # Try common patterns
    u = urlparse(youtube_url)
    if u.hostname in ("www.youtube.com", "youtube.com"):
        qs = parse_qs(u.query)
        if "v" in qs:
            return qs["v"][0]
    # youtu.be short link
    if u.hostname == "youtu.be":
        return u.path.lstrip('/')
    # Fallback: last path segment
    return Path(u.path).name


def download_audio_local(youtube_url: str, out_dir: str) -> str:
    """
    Download best audio and convert to mono 16k WAV using yt-dlp + ffmpeg.
    Returns local path to the WAV file.
    """
    if yt_dlp is None:
        raise RuntimeError("yt-dlp Python package not available. Please install yt-dlp (pip install yt-dlp).")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "audio.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            },
            {
                "key": "FFmpegMetadata"
            }
        ],
        # Ensure ffmpeg converts sample rate / channels: we'll run a second pass if needed
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        # find the downloaded wav path
        # yt-dlp uses extension 'wav' after postprocessing
        wav_path = None
        for ext in ("wav", "m4a", "mp3", "webm", "opus"):
            candidate = os.path.join(out_dir, f"audio.{ext}")
            if os.path.exists(candidate):
                wav_path = candidate
                break

        if not wav_path:
            raise RuntimeError("Failed to find downloaded audio file")

        # If not wav, convert to 16k mono wav with ffmpeg
        if not wav_path.lower().endswith('.wav'):
            final_wav = os.path.join(out_dir, "audio.wav")
            cmd = [
                "ffmpeg", "-y", "-i", wav_path,
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                final_wav
            ]
            import subprocess
            subprocess.run(cmd, check=True)
            wav_path = final_wav
        else:
            # Ensure sample rate/channels - re-encode to 16k mono wav to be safe
            reencoded = os.path.join(out_dir, "audio_16k_mono.wav")
            import subprocess
            cmd = [
                "ffmpeg", "-y", "-i", wav_path,
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                reencoded
            ]
            subprocess.run(cmd, check=True)
            wav_path = reencoded

    return wav_path


def upload_to_gcs(local_path: str, bucket_name: str, dest_path: str) -> str:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(dest_path)
    blob.upload_from_filename(local_path)
    return f"gs://{bucket_name}/{dest_path}"


def main():
    parser = argparse.ArgumentParser(description="Ingest a YouTube link: download audio, upload to GCS, transcribe+chunk")
    parser.add_argument("url", help="YouTube URL to ingest")
    parser.add_argument("--bucket", help="GCS bucket to upload audio (default SOURCE_BUCKET)", default=SOURCE_BUCKET)
    parser.add_argument("--prefix", help="Destination prefix in bucket (default data)", default=os.environ.get('SOURCE_DATA_PREFIX','data').strip('/'))
    parser.add_argument("--language", default="ar-SA", help="Source language code for STT (default: ar-SA)")
    parser.add_argument("--translate", default="en", help="Target translation language (default: en). Use 'none' to skip translation.")
    parser.add_argument("--window", type=float, default=30.0, help="Chunk window seconds (default 30)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Downloading audio for: {args.url}")
        wav_local = download_audio_local(args.url, tmpdir)
        print(f"Audio downloaded: {wav_local}")

        vid_id = extract_video_id(args.url)
        dest_blob = f"{args.prefix}/youtube_{vid_id}.wav"
        print(f"Uploading to gs://{args.bucket}/{dest_blob} ...")
        audio_gs = upload_to_gcs(wav_local, args.bucket, dest_blob)
        print(f"Uploaded: {audio_gs}")

        # Create a pseudo video URI for provenance
        video_uri = f"youtube://{vid_id}"

        # If process_video is importable, call it directly
        translate_target = None if args.translate.lower() in ('none', '') else args.translate
        if process_video:
            process_video(video_uri, audio_gcs_uri=audio_gs, language_code=args.language, translate_to=translate_target, window_seconds=args.window)
        else:
            # Fallback: call ingest_video.py as subprocess
            cmd = [sys.executable, os.path.join('tools','ingest_video.py'), video_uri, '--audio-uri', audio_gs, '--language', args.language, '--window', str(args.window)]
            if translate_target:
                cmd += ['--translate', translate_target]
            print("Calling ingest_video.py subprocess:", ' '.join(cmd))
            import subprocess
            subprocess.run(cmd, check=True)

if __name__ == '__main__':
    main()
