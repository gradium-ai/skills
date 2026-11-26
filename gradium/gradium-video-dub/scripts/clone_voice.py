#!/usr/bin/env python3
"""Clone the speaker's voice with Gradium (only with the speaker's permission).

Usage: clone_voice.py <video> --lang fr --name "Name" --consent [--start 0 --dur 20]
Prints the new voice id. 10 s of clean speech is the documented minimum.
"""
import argparse, json, os, subprocess, tempfile

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("--lang", required=True); ap.add_argument("--name", required=True)
ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--dur", type=float, default=20.0)
ap.add_argument("--consent", action="store_true", help="confirm the speaker agreed to be cloned")
a = ap.parse_args()
if not a.consent:
    raise SystemExit("Refusing to clone without --consent: confirm the speaker gave permission.")

with tempfile.TemporaryDirectory() as d:
    wav = f"{d}/sample.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a.start), "-t", str(a.dur), "-i", a.video,
                    "-vn", "-ac", "1", "-ar", "48000", wav], check=True)
    out = subprocess.run(["curl", "-sS", "--fail-with-body", "-X", "POST", "https://api.gradium.ai/api/voices/",
                          "-H", f"x-api-key: {os.environ['GRADIUM_API_KEY']}", "-F", f"audio_file=@{wav}",
                          "--form-string", f"name={a.name}", "--form-string", f"language={a.lang}",
                          "--form-string", "description=Cloned with the speaker's permission",
                          "--form-string", "timeout_s=60"], capture_output=True, text=True, check=True).stdout
print(json.loads(out)["uid"])
