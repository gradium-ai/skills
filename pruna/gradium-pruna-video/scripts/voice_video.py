#!/usr/bin/env python3
"""Text -> Gradium TTS -> Pruna video. Tested against both live APIs.

Requires: pip install requests. Env: GRADIUM_API_KEY, PRUNA_API_KEY.

Usage:
  python voice_video.py "Welcome to the demo!" --image portrait.png --out talking.mp4
  python voice_video.py --audio narration.wav --image portrait.png --out talking.mp4
  python voice_video.py "text" --image scene.png --mode scene \
      --prompt "the character gestures while speaking" --out scene.mp4
"""
import argparse
import os
import sys
import time
from urllib.parse import urlparse

import requests

GRADIUM = "https://api.gradium.ai/api"
PRUNA = "https://api.pruna.ai/v1"
TIMEOUT = 120  # seconds per HTTP call; renders are polled, not awaited


def is_pruna_host(url: str) -> bool:
    u = urlparse(url)
    host = u.hostname or ""
    return u.scheme == "https" and (host == "api.pruna.ai" or host.endswith(".pruna.ai"))


def download(url: str, key: str, path: str) -> int:
    """Fetch a render. The API key is only sent to Pruna hosts, and redirects
    are followed manually so the key never travels to a third-party host."""
    for _ in range(5):
        if not urlparse(url).scheme == "https":
            sys.exit(f"refusing non-HTTPS download URL: {url}")
        headers = {"apikey": key} if is_pruna_host(url) else {}
        r = requests.get(url, headers=headers, allow_redirects=False,
                         timeout=TIMEOUT, stream=True)
        if r.is_redirect or r.is_permanent_redirect:
            url = r.headers.get("Location", "")
            r.close()
            continue
        if r.status_code != 200:
            sys.exit(f"download failed {r.status_code}: {r.text[:300]}")
        size = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                size += len(chunk)
        if size == 0:
            sys.exit("download returned an empty file")
        return size
    sys.exit("too many redirects while downloading the render")


def gradium_tts(text: str, voice: str, key: str, path: str) -> str:
    r = requests.post(f"{GRADIUM}/post/speech/tts", headers={"x-api-key": key},
                      json={"text": text, "voice_id": voice,
                            "output_format": "wav", "only_audio": True},
                      timeout=TIMEOUT)
    if r.status_code != 200:
        sys.exit(f"Gradium TTS failed {r.status_code}: {r.text[:300]}")
    with open(path, "wb") as f:
        f.write(r.content)
    print(f"[1/4] synthesized {len(r.content)} bytes -> {path}")
    return path


def pruna_upload(path: str, key: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{PRUNA}/files", headers={"apikey": key},
                          files={"content": (os.path.basename(path), f)},
                          timeout=TIMEOUT)
    if r.status_code >= 300:
        sys.exit(f"Pruna upload failed {r.status_code}: {r.text[:300]}")
    url = r.json()["urls"]["get"]
    print(f"[2/4] uploaded {os.path.basename(path)} -> {url}")
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
    image_url = pruna_upload(args.image, pkey)
    audio_url = pruna_upload(audio_path, pkey)

    if args.mode == "avatar":
        model = "p-video-avatar"
        inp = {"image": image_url, "audio": audio_url, "resolution": args.resolution,
               "video_prompt": args.prompt or "The person is talking naturally."}
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
                      timeout=TIMEOUT)
    if r.status_code >= 300:
        sys.exit(f"Pruna prediction failed {r.status_code}: {r.text[:300]}")
    pred = r.json()
    print(f"[3/4] prediction {pred['id']} ({model}) — polling")

    for _ in range(240):
        resp = requests.get(f"{PRUNA}/predictions/status/{pred['id']}",
                            headers={"apikey": pkey}, timeout=TIMEOUT)
        if resp.status_code >= 500:   # transient server error: keep polling
            time.sleep(5)
            continue
        if resp.status_code >= 300:
            sys.exit(f"poll failed {resp.status_code}: {resp.text[:300]}")
        s = resp.json()
        status = s.get("status")
        print(f"      {status}", end="\r")
        if status == "succeeded":
            print()
            size = download(s["generation_url"], pkey, args.out)
            print(f"[4/4] wrote {args.out} ({size} bytes)")
            return 0
        if status == "failed":
            sys.exit(f"\nrender failed: {s.get('error') or s}")
        time.sleep(5)
    sys.exit("timed out after 20 minutes")


if __name__ == "__main__":
    sys.exit(main())
