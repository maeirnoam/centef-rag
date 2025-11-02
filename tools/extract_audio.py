"""
Extract audio from video files using ffmpeg.
Converts to mono 16kHz WAV format suitable for Speech-to-Text API.
"""
import subprocess
import sys
import tempfile
import os
from google.cloud import storage


def env(name: str, default=None):
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")


def check_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def extract_audio_local(video_path: str, audio_path: str):
    """Extract audio from video file using ffmpeg"""
    cmd = [
        "ffmpeg",
        "-i", video_path,  # Input file
        "-vn",  # No video
        "-acodec", "pcm_s16le",  # Linear PCM 16-bit
        "-ar", "16000",  # Sample rate 16kHz
        "-ac", "1",  # Mono
        "-y",  # Overwrite output
        audio_path
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("STDERR:", result.stderr)
        raise RuntimeError(f"ffmpeg failed with return code {result.returncode}")
    
    print(f"✓ Audio extracted: {audio_path}")


def extract_audio_from_gcs(video_gcs_uri: str, audio_gcs_uri: str):
    """
    Download video from GCS, extract audio, upload audio back to GCS.
    """
    if not check_ffmpeg():
        print("ERROR: ffmpeg not found. Please install ffmpeg:")
        print("  Windows: Download from https://ffmpeg.org/download.html")
        print("  Or use chocolatey: choco install ffmpeg")
        print("  Linux: sudo apt-get install ffmpeg")
        print("  Mac: brew install ffmpeg")
        sys.exit(1)
    
    storage_client = storage.Client()
    
    # Parse GCS URIs
    video_bucket = video_gcs_uri.replace("gs://", "").split("/")[0]
    video_blob_name = "/".join(video_gcs_uri.replace("gs://", "").split("/")[1:])
    
    audio_bucket = audio_gcs_uri.replace("gs://", "").split("/")[0]
    audio_blob_name = "/".join(audio_gcs_uri.replace("gs://", "").split("/")[1:])
    
    print(f"Downloading video from GCS: {video_gcs_uri}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Download video
        video_local = os.path.join(tmpdir, "video.mp4")
        bucket = storage_client.bucket(video_bucket)
        blob = bucket.blob(video_blob_name)
        blob.download_to_filename(video_local)
        print(f"✓ Downloaded: {video_local}")
        
        # Extract audio
        audio_local = os.path.join(tmpdir, "audio.wav")
        extract_audio_local(video_local, audio_local)
        
        # Upload audio
        print(f"Uploading audio to GCS: {audio_gcs_uri}")
        audio_bucket_obj = storage_client.bucket(audio_bucket)
        audio_blob = audio_bucket_obj.blob(audio_blob_name)
        audio_blob.upload_from_filename(audio_local)
        print(f"✓ Uploaded: {audio_gcs_uri}")
    
    return audio_gcs_uri


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Extract audio from video")
    parser.add_argument("video_uri", help="GCS URI of video file")
    parser.add_argument("--audio-uri", help="GCS URI for output audio (default: same path with .wav)")
    
    args = parser.parse_args()
    
    audio_uri = args.audio_uri
    if not audio_uri:
        # Default: replace extension with .wav
        audio_uri = args.video_uri.rsplit(".", 1)[0] + ".wav"
    
    print(f"Video: {args.video_uri}")
    print(f"Audio: {audio_uri}")
    
    extract_audio_from_gcs(args.video_uri, audio_uri)
    print("\n✓ Audio extraction complete!")
    print(f"Audio available at: {audio_uri}")


if __name__ == "__main__":
    main()
