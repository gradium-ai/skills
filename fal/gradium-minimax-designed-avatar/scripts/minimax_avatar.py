#!/usr/bin/env python3
"""Design a Gradium voice, speak a script with it, and lip-sync a portrait with
MiniMax H3 Max (``minimax/h3-max/lip-sync/image-to-video``) on fal.ai.

Requires: pip install requests 'urllib3>=2.2,<3', plus ffmpeg and ffprobe on PATH.
Env: GRADIUM_API_KEY (design, promote, discard, and render without --audio),
     FAL_KEY (render).

Usage:
  python minimax_avatar.py design "Calm, older, reassuring; measured pace." \
      --language en --out audition.wav             # prints a vox_emb_... candidate id
  python minimax_avatar.py promote vox_emb_... --name "Arthur"   # prints the permanent voice_id
  python minimax_avatar.py discard vox_emb_...                   # delete a rejected candidate
  python minimax_avatar.py render "Hi, I'm Arthur. Let's set up your policy." \
      --image portrait.png --voice <voice_id> --out talking.mp4
  python minimax_avatar.py render --audio speech.wav --image portrait.png --out talking.mp4

MiniMax needs at least 5 s of audio and lip-syncs at most 14.8 s in one
generation. Shorter audio is padded with silence; longer audio is refused
unless --allow-clip is given. The portrait's aspect ratio must be 0.4-2.5.
"""
import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urljoin, urlparse

import requests

GRADIUM = "https://api.gradium.ai/api"
FAL_QUEUE = "https://queue.fal.run"
FAL_APP = "minimax/h3-max"                      # queue status/result URLs use owner/alias only
FAL_ENDPOINT = FAL_APP + "/lip-sync/image-to-video"
TIMEOUT = 120                                    # seconds per HTTP call; renders are polled
MAX_BYTES = 512 * 1024 * 1024                    # render download cap
MAX_INPUT_BYTES = 8 * 1024 * 1024                # per inline (data URI) input
MIN_AUDIO_S, MAX_AUDIO_S, PAD_TO_S = 5.0, 14.8, 5.2
RATES = {"480P": 0.05, "768P": 0.08, "1080P": 0.16, "2K": 0.32}  # USD per output second
ID = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
AUDITION = {
    "en": "It is lovely to meet you. Let me walk you through it.",
    "fr": "Ravi de vous rencontrer. Laissez-moi vous guider.",
    "de": "Schön, Sie kennenzulernen. Ich führe Sie gern durch.",
    "es": "Encantado de conocerte. Déjame guiarte paso a paso.",
    "pt": "É um prazer conhecer você. Deixe-me guiá-lo.",
}


# ---------------------------------------------------------------- media helpers

def probe(path: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,format_name:stream=codec_type,width,height", "-of", "json", path],
        capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)


def media_duration(path: str, video: bool = False) -> float:
    info = probe(path)
    kinds = {s["codec_type"] for s in info["streams"]}
    duration = float(info["format"].get("duration", "nan"))
    if (not math.isfinite(duration) or duration <= 0 or "audio" not in kinds
            or (video and ("video" not in kinds
                           or "mp4" not in info["format"]["format_name"].split(",")))):
        raise ValueError("expected nonempty audio" + (" and MP4 video" if video else ""))
    return duration


def image_mime(path: str) -> str:
    """Sniff the container instead of trusting the extension or a Content-Type."""
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("portrait must be a PNG, JPEG, or WebP image")


def check_portrait(path: str) -> tuple[int, int]:
    mime = image_mime(path)
    streams = [s for s in probe(path)["streams"] if s.get("codec_type") == "video"]
    if not streams or not streams[0].get("width") or not streams[0].get("height"):
        raise ValueError("could not decode the portrait")
    w, h = int(streams[0]["width"]), int(streams[0]["height"])
    ratio = w / h
    if not 0.4 <= ratio <= 2.5:
        raise ValueError(f"portrait aspect ratio {ratio:.2f} is outside MiniMax's 0.4-2.5 range; "
                         "crop it before rendering")
    print(f"      portrait {w}x{h} ({mime})")
    return w, h


def prepare_audio(src: str, dst: str, allow_clip: bool) -> float:
    """Normalize to mono 24 kHz WAV, pad below 5 s, clip above 14.8 s only when allowed."""
    duration = media_duration(src)
    if duration > MAX_AUDIO_S and not allow_clip:
        raise ValueError(f"audio is {duration:.1f}s; MiniMax lip-syncs at most {MAX_AUDIO_S}s "
                         "in one generation. Shorten the script or pass --allow-clip")
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(dst))) as tmp:
        staged = os.path.join(tmp, "speech.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", src, "-vn",
                        "-t", str(MAX_AUDIO_S), "-af", f"apad=whole_dur={PAD_TO_S}",
                        "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", staged],
                       check=True, timeout=120)
        prepared = media_duration(staged)
        os.replace(staged, dst)
    if duration < MIN_AUDIO_S:
        print(f"      padded {duration:.1f}s of speech with silence to {prepared:.1f}s")
    elif duration > MAX_AUDIO_S:
        print(f"      clipped {duration:.1f}s of speech to {prepared:.1f}s")
    return prepared


def data_uri(path: str, mime: str) -> str:
    size = os.path.getsize(path)
    if size > MAX_INPUT_BYTES:
        raise ValueError(f"{os.path.basename(path)} is {size} bytes; inline inputs are capped at "
                         f"{MAX_INPUT_BYTES // (1024 * 1024)} MiB. Downscale it or host it and use --image-url")
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


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
                chunk = response.raw.read1(1 << 16, decode_content=True)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("media exceeds 512 MiB")
                f.write(chunk)
        duration = media_duration(staged, video)
        if expected_duration is not None and abs(duration - expected_duration) > max(1, expected_duration * .05):
            raise ValueError("video duration does not match the prepared audio")
        os.replace(staged, path)
    return size


def safe_https(url: str) -> None:
    u = urlparse(url)
    if (u.scheme != "https" or not u.hostname or u.username is not None
            or u.password is not None or u.port not in (None, 443)):
        raise ValueError("refusing unsafe download URL")


def download(url: str, path: str, expected_duration: float | None = None) -> int:
    """Fetch the finished render from fal's CDN. No credential is ever attached."""
    deadline = time.monotonic() + 300
    for _ in range(5):
        safe_https(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("download deadline exceeded")
        with requests.get(url, headers={}, allow_redirects=False,
                          timeout=min(10, remaining), stream=True) as r:
            if r.is_redirect or r.is_permanent_redirect:
                url = urljoin(url, r.headers["Location"])
                continue
            return save_media(r, path, deadline, video=True, expected_duration=expected_duration)
    raise ValueError("too many redirects while downloading the render")


# ---------------------------------------------------------------- Gradium

def gradium_headers(key: str) -> dict:
    return {"x-api-key": key}


def gradium_tts(text: str, voice: str, key: str, path: str, label: str = "[1/4]") -> str:
    with requests.post(f"{GRADIUM}/post/speech/tts", headers=gradium_headers(key),
                      json={"text": text, "voice_id": voice,
                            "output_format": "wav", "only_audio": True},
                      timeout=TIMEOUT, allow_redirects=False, stream=True) as r:
        size = save_media(r, path, time.monotonic() + 300)
    print(f"{label} synthesized {size} bytes -> {path}")
    return path


def discard_candidate(embedding_id: str, key: str) -> bool:
    if not ID.match(embedding_id):
        raise ValueError("malformed embedding id")
    r = requests.delete(f"{GRADIUM}/voice-generator/embeddings/{embedding_id}",
                        headers=gradium_headers(key), timeout=TIMEOUT, allow_redirects=False)
    return r.status_code < 300 or r.status_code == 404


def design(args, key: str) -> int:
    prompt = args.prompt.strip()
    if not 1 <= len(prompt) <= 500:
        sys.exit("the voice description must be 1-500 characters")
    audition = (args.audition or AUDITION[args.language]).strip()
    if not 1 <= len(audition) <= 100:
        sys.exit("audition text must be 1-100 characters")
    body = {"prompt": prompt, "language": args.language, "n_samples": 1,
            "json_config": {"cfg_scale": args.cfg}}
    if args.seed is not None:
        body["json_config"]["seed"] = args.seed
    r = requests.post(f"{GRADIUM}/voice-generator/generate", headers=gradium_headers(key),
                      json=body, timeout=TIMEOUT, allow_redirects=False)
    if r.status_code >= 300:
        sys.exit(f"voice generation failed: HTTP {r.status_code}")
    embeddings = r.json().get("embeddings") or []
    if not embeddings or not ID.match(str(embeddings[0].get("embedding_id", ""))):
        sys.exit("voice generation returned no candidate")
    emb = embeddings[0]["embedding_id"]
    print(f"[1/3] candidate {emb} requested")
    try:
        deadline = time.monotonic() + 300
        while True:
            r = requests.get(f"{GRADIUM}/voice-generator/embeddings",
                             params={"embedding_id": emb}, headers=gradium_headers(key),
                             timeout=min(TIMEOUT, max(1, deadline - time.monotonic())),
                             allow_redirects=False)
            if r.status_code >= 300:
                raise ValueError(f"candidate lookup failed: HTTP {r.status_code}")
            found = [e for e in r.json().get("embeddings", []) if e.get("embedding_id") == emb]
            if found and found[0].get("ready") is True:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("candidate was not ready after 5 minutes")
            time.sleep(min(3, max(0, deadline - time.monotonic())))
        print("[2/3] candidate ready; rendering the audition")
        gradium_tts(audition, emb, key, args.out, label="[3/3]")
    except BaseException:
        if discard_candidate(emb, key):
            print(f"      discarded candidate {emb}", file=sys.stderr)
        raise
    print(f"Listen to {args.out}. Keep it with:  promote {emb} --name \"<voice name>\"\n"
          f"Or drop it with:                    discard {emb}")
    return 0


def promote(args, key: str) -> int:
    if not ID.match(args.embedding_id):
        sys.exit("malformed embedding id")
    body = {"voxium_embedding_id": args.embedding_id, "name": args.name}
    if args.description:
        body["description"] = args.description
    r = requests.post(f"{GRADIUM}/voices/from-embedding", headers=gradium_headers(key),
                      json=body, timeout=TIMEOUT, allow_redirects=False)
    if r.status_code == 409:
        sys.exit("a permanent voice already exists for this candidate")
    if r.status_code >= 300:
        sys.exit(f"promotion failed: HTTP {r.status_code}")
    uid = str(r.json().get("uid", ""))
    if not ID.match(uid):
        sys.exit("promotion returned no voice id")
    print(f"permanent voice_id: {uid}\nStore it as GRADIUM_VOICE_ID; pass --voice {uid} to render.")
    return 0


def discard(args, key: str) -> int:
    if not discard_candidate(args.embedding_id, key):
        sys.exit("discard failed")
    print(f"discarded {args.embedding_id}")
    return 0


# ---------------------------------------------------------------- fal / MiniMax

def fal_headers(key: str) -> dict:
    return {"Authorization": f"Key {key}", "Content-Type": "application/json"}


def fal_error(r) -> str:
    """A short, sanitized reason from a fal error body (validation messages are useful)."""
    try:
        detail = r.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):
        detail = "; ".join(str(d.get("msg", "")) for d in detail if isinstance(d, dict))
    text = re.sub(r"[^\x20-\x7e]", " ", str(detail or ""))[:300]
    return f"HTTP {r.status_code}" + (f": {text}" if text else "")


def render(args) -> int:
    gkey, fkey = os.environ.get("GRADIUM_API_KEY"), os.environ.get("FAL_KEY")
    if not fkey or (not gkey and not args.audio):
        sys.exit("Set FAL_KEY and, unless --audio is given, GRADIUM_API_KEY")
    if not args.text and not args.audio:
        sys.exit("Provide a script text or --audio")
    if args.text and not args.voice:
        sys.exit("Pass --voice <permanent Gradium voice_id> with a script")

    stem = os.path.splitext(args.out)[0]
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(args.out))) as tmp:
        raw = args.audio or gradium_tts(args.text, args.voice, gkey, os.path.join(tmp, "tts.wav"))
        speech = stem + "_speech.wav"
        duration = prepare_audio(raw, speech, args.allow_clip)
    print(f"[2/4] prepared {duration:.1f}s of speech -> {speech}")
    check_portrait(args.image)

    inp = {"image_url": data_uri(args.image, image_mime(args.image)),
           "audio_url": data_uri(speech, "audio/wav"),
           "resolution": args.resolution, "enable_safety_checker": True}
    if args.transcribe:
        inp["enable_transcription"] = True
    if args.seed is not None:
        inp["seed"] = args.seed
    print(f"[3/4] submitting {duration:.1f}s at {args.resolution}: about "
          f"${duration * RATES[args.resolution]:.2f} of fal credits")

    r = requests.post(f"{FAL_QUEUE}/{FAL_ENDPOINT}", json=inp, headers=fal_headers(fkey),
                      timeout=TIMEOUT, allow_redirects=False)
    if r.status_code >= 300:
        sys.exit(f"fal submission failed: {fal_error(r)}")
    rid = str(r.json().get("request_id", ""))
    if not ID.match(rid):
        sys.exit("fal returned no request id")
    print(f"      request {rid} queued; polling")

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        resp = requests.get(f"{FAL_QUEUE}/{FAL_APP}/requests/{rid}/status",
                            headers={"Authorization": f"Key {fkey}"}, allow_redirects=False,
                            timeout=min(TIMEOUT, max(1, remaining)))
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            continue
        if resp.status_code >= 300:
            sys.exit(f"poll failed: {fal_error(resp)}")
        status = resp.json().get("status")
        print(f"      {status}", end="\r")
        if status == "COMPLETED":
            print()
            result = requests.get(f"{FAL_QUEUE}/{FAL_APP}/requests/{rid}",
                                  headers={"Authorization": f"Key {fkey}"}, allow_redirects=False,
                                  timeout=TIMEOUT)
            if result.status_code >= 300:
                sys.exit(f"render failed: {fal_error(result)}")
            body = result.json()
            video = body.get("video") if isinstance(body, dict) else None
            if not isinstance(video, dict) or not isinstance(video.get("url"), str):
                sys.exit("render result has no video URL")
            size = download(video["url"], args.out, expected_duration=duration)
            seed = body.get("seed")
            print(f"[4/4] wrote {args.out} ({size} bytes" + (f", seed {seed})" if seed is not None else ")"))
            return 0
        if status not in ("IN_QUEUE", "IN_PROGRESS"):
            sys.exit(f"\nunexpected status {status!r}")
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    sys.exit("timed out after 15 minutes; the request was not resubmitted")


# ---------------------------------------------------------------- CLI

def main() -> int:
    p = argparse.ArgumentParser(description="Gradium Voice Design + TTS -> MiniMax H3 Max lip-sync on fal")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("design", help="create one voice candidate and render an audition")
    d.add_argument("prompt", help="voice description, at most 500 characters")
    d.add_argument("--language", choices=sorted(AUDITION), default="en")
    d.add_argument("--audition", default=None, help="audition line, at most 100 characters")
    d.add_argument("--cfg", type=float, default=10.0, help="cfg_scale 1-20: how closely to follow the prompt")
    d.add_argument("--seed", type=int, default=None)
    d.add_argument("--out", default="audition.wav")

    pr = sub.add_parser("promote", help="keep an auditioned candidate as a permanent voice")
    pr.add_argument("embedding_id")
    pr.add_argument("--name", required=True)
    pr.add_argument("--description", default=None)

    di = sub.add_parser("discard", help="delete a rejected candidate")
    di.add_argument("embedding_id")

    r = sub.add_parser("render", help="speak the script and lip-sync the portrait")
    r.add_argument("text", nargs="?", help="script to speak (omit when using --audio)")
    r.add_argument("--audio", help="existing speech audio instead of Gradium TTS")
    r.add_argument("--voice", default=None, help="permanent Gradium voice_id for the script")
    r.add_argument("--image", required=True, help="portrait (PNG, JPEG, or WebP; aspect ratio 0.4-2.5)")
    r.add_argument("--resolution", default="768P", choices=sorted(RATES))
    r.add_argument("--seed", type=int, default=None)
    r.add_argument("--transcribe", action="store_true",
                   help="let MiniMax transcribe the audio to guide lip sync")
    r.add_argument("--allow-clip", action="store_true",
                   help="accept audio over 14.8 s and keep only its first 14.8 s")
    r.add_argument("--out", default="talking.mp4")
    args = p.parse_args()

    if args.command == "render":
        return render(args)
    key = os.environ.get("GRADIUM_API_KEY")
    if not key:
        sys.exit("Set GRADIUM_API_KEY")
    return {"design": design, "promote": promote, "discard": discard}[args.command](args, key)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TimeoutError, requests.RequestException,
            subprocess.SubprocessError) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}" if isinstance(exc, (ValueError, TimeoutError))
                 else f"failed ({type(exc).__name__})")
