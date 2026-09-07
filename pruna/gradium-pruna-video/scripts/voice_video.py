#!/usr/bin/env python3
"""Text -> Gradium TTS -> Pruna video. Tested against both live APIs.

Requires: pip install requests 'urllib3>=2.2,<3', and ffprobe on PATH.
Env: GRADIUM_API_KEY, PRUNA_API_KEY.

Usage:
  python voice_video.py "Welcome to the demo!" --image portrait.png --out talking.mp4
  python voice_video.py --audio narration.wav --image portrait.png --out talking.mp4
  python voice_video.py "text" --image scene.png --mode scene \
      --prompt "the character gestures while speaking" --out scene.mp4
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urljoin, urlparse

import requests

GRADIUM = "https://api.gradium.ai/api"
PRUNA = "https://api.pruna.ai/v1"
TIMEOUT = 120  # seconds per HTTP call; renders are polled, not awaited
MAX_BYTES = 512 * 1024 * 1024


def is_pruna_host(url: str) -> bool:
    u = urlparse(url)
    return (u.scheme == "https" and u.hostname == "api.pruna.ai"
            and u.port in (None, 443) and u.username is None and u.password is None)


def media_duration(path: str, video: bool = False) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,format_name:stream=codec_type", "-of", "json", path],
        capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(result.stdout)
    kinds = {s["codec_type"] for s in info["streams"]}
    duration = float(info["format"]["duration"])
    if (not math.isfinite(duration) or duration <= 0 or "audio" not in kinds
            or (video and ("video" not in kinds
                           or "mp4" not in info["format"]["format_name"].split(",")))):
        raise ValueError("expected nonempty audio" + (" and MP4 video" if video else ""))
    return duration


def save_media(response, path: str, deadline: float, video: bool = False,
               expected_duration: float | None = None) -> int:
    """Bound reads and validate a private temporary file before replacing output."""
    if response.status_code != 200:
        raise ValueError(f"media request failed: HTTP {response.status_code}")
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(path))) as tmp:
        staged = os.path.join(tmp, "media")
        size = 0
        with open(staged, "wb") as f:
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("media download deadline exceeded")
                # read1 returns available data instead of waiting to fill a chunk.
                chunk = response.raw.read1(1 << 16, decode_content=True)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("media exceeds 512 MiB")
                f.write(chunk)
        duration = media_duration(staged, video)
        if expected_duration is not None and abs(duration - expected_duration) > max(1, expected_duration * .05):
            raise ValueError("video duration does not match source audio")
        os.replace(staged, path)
    return size


def download(url: str, key: str, path: str, expected_duration: float | None = None) -> int:
    """Fetch a render; only the exact Pruna API origin receives the API key."""
    deadline = time.monotonic() + 300
    for _ in range(5):
        u = urlparse(url)
        if (u.scheme != "https" or not u.hostname or u.username is not None
                or u.password is not None or u.port not in (None, 443)):
            raise ValueError("refusing unsafe download URL")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("download deadline exceeded")
        headers = {"apikey": key} if is_pruna_host(url) else {}
        with requests.get(url, headers=headers, allow_redirects=False,
                          timeout=min(10, remaining), stream=True) as r:
            if r.is_redirect or r.is_permanent_redirect:
                url = urljoin(url, r.headers["Location"])
                continue
            return save_media(r, path, deadline, video=True, expected_duration=expected_duration)
    raise ValueError("too many redirects while downloading the render")


def gradium_tts(text: str, voice: str, key: str, path: str) -> str:
    with requests.post(f"{GRADIUM}/post/speech/tts", headers={"x-api-key": key},
                      json={"text": text, "voice_id": voice,
                            "output_format": "wav", "only_audio": True},
                      timeout=TIMEOUT, allow_redirects=False, stream=True) as r:
        size = save_media(r, path, time.monotonic() + 300)
    print(f"[1/4] synthesized {size} bytes -> {path}")
    return path


def pruna_upload(path: str, key: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{PRUNA}/files", headers={"apikey": key},
                          files={"content": (os.path.basename(path), f)},
                          timeout=TIMEOUT, allow_redirects=False)
    if r.status_code >= 300:
        sys.exit(f"Pruna upload failed: HTTP {r.status_code}")
    url = r.json()["urls"]["get"]
    print(f"[2/4] uploaded {os.path.basename(path)}")
    return url


def main() -> int:
    p = argparse.ArgumentParser(description="Gradium TTS -> Pruna talking video")
    p.add_argument("text", nargs="?", help="script to speak (omit when using --audio)")
    p.add_argument("--audio", help="existing audio file (wav/mp3/flac) instead of TTS")
    p.add_argument("--image", required=True, help="portrait (avatar) or scene image")
    p.add_argument("--gradium-voice", default="NbpkqMVS3CJeq2j8",
                   help="Gradium voice_id (flagship or clone)")
    p.add_argument("--mode", choices=["avatar", "scene"], default="avatar",
                   help="avatar=p-video-avatar (talking head), scene=p-video")
    p.add_argument("--prompt", default=None,
                   help="video_prompt (avatar) / prompt (scene, required there)")
    p.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", default="talking.mp4")
    args = p.parse_args()

    gkey, pkey = os.environ.get("GRADIUM_API_KEY"), os.environ.get("PRUNA_API_KEY")
    if not pkey or (not gkey and not args.audio):
        sys.exit("Set GRADIUM_API_KEY and PRUNA_API_KEY")
    if not args.text and not args.audio:
        sys.exit("Provide a script text or --audio")

    audio_path = args.audio or gradium_tts(args.text, args.gradium_voice, gkey,
                                           os.path.splitext(args.out)[0] + "_speech.wav")
    duration = media_duration(audio_path)
    image_url = pruna_upload(args.image, pkey)
    audio_url = pruna_upload(audio_path, pkey)

    if args.mode == "avatar":
        model = "p-video-avatar"
        inp = {"image": image_url, "audio": audio_url, "resolution": args.resolution,
               "video_prompt": args.prompt or "The person is talking naturally.",
               "disable_safety_filter": False, "disable_prompt_upsampling": True}
    else:
        model = "p-video"
        inp = {"image": image_url, "audio": audio_url, "resolution": args.resolution,
               "prompt": args.prompt or "the character speaks expressively",
               "save_audio": True}  # without this the scene render is silent
    if args.seed is not None:
        inp["seed"] = args.seed

    r = requests.post(f"{PRUNA}/predictions", json={"input": inp},
                      headers={"apikey": pkey, "Model": model,
                               "Content-Type": "application/json"},
                      timeout=TIMEOUT, allow_redirects=False)
    if r.status_code >= 300:
        sys.exit(f"Pruna prediction failed: HTTP {r.status_code}")
    pred = r.json()
    print(f"[3/4] prediction {pred['id']} ({model}) — polling")

    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        resp = requests.get(f"{PRUNA}/predictions/status/{pred['id']}",
                            headers={"apikey": pkey}, allow_redirects=False,
                            timeout=min(TIMEOUT, remaining))
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            continue
        if resp.status_code >= 300:
            sys.exit(f"poll failed: HTTP {resp.status_code}")
        s = resp.json()
        status = s.get("status")
        print(f"      {status}", end="\r")
        if status == "succeeded":
            print()
            size = download(s["generation_url"], pkey, args.out,
                            expected_duration=duration if args.mode == "avatar" else None)
            print(f"[4/4] wrote {args.out} ({size} bytes)")
            return 0
        if status == "failed":
            sys.exit("\nrender failed")
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    sys.exit("timed out after 20 minutes")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, requests.RequestException,
            subprocess.SubprocessError) as exc:
        sys.exit(f"video generation failed ({type(exc).__name__})")
