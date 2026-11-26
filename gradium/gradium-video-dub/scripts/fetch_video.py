#!/usr/bin/env python3
"""Get a video into OUTDIR/video.mp4 from a local file, a direct URL, or a page that embeds one.

Usage: fetch_video.py <url-or-path> <outdir>
Tries yt-dlp when installed; otherwise reads the page HTML (LinkedIn data-sources, og:video,
any .mp4 link) and downloads the highest-bitrate MP4 with curl.
"""
import html, json, os, re, shutil, subprocess, sys

src, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
dst = os.path.join(outdir, "video.mp4")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

def curl(url, path):
    subprocess.run(["curl", "-sSL", "--fail", "-A", UA, "-o", path, url], check=True)

page = None                                                          # set when the URL is a page to parse
if os.path.exists(src):
    shutil.copy(src, dst)
elif shutil.which("yt-dlp") and subprocess.run(
        ["yt-dlp", "-q", "-f", "mp4/bestvideo+bestaudio/best", "--merge-output-format", "mp4", "-o", dst, src]).returncode == 0:
    pass
else:
    page = os.path.join(outdir, "page.html")
    curl(src, page)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type",
                            "-of", "csv=p=0", page], capture_output=True, text=True).stdout
    if "video" in probe:                                             # a direct video URL, not a page
        os.replace(page, dst)
        page = None
if page:
    text = open(page, encoding="utf-8", errors="replace").read()
    cands = []  # (bitrate, url)
    for m in re.finditer(r'data-sources="([^"]+)"', text):           # LinkedIn
        for s in json.loads(html.unescape(m.group(1))):
            cands.append((s.get("data-bitrate", 0), s["src"]))
    for m in re.finditer(r'<meta[^>]+property="og:video(?::secure_url|:url)?"[^>]+content="([^"]+)"', text):
        cands.append((1, html.unescape(m.group(1))))
    for u in re.findall(r'https://[^"\'<>\s]+?\.mp4[^"\'<>\s]*', text):
        cands.append((0, html.unescape(u)))
    if not cands:
        sys.exit("No video found on the page. Download it manually and pass the file path.")
    curl(max(cands, key=lambda c: c[0])[1], dst)
    # LinkedIn also exposes its auto-captions (source language), handy as a timing hint
    m = re.search(r'https://dms\.licdn\.com/[^"]*video-auto-caption[^"]*', text)
    if m:
        subprocess.run(["curl", "-sSL", "-o", os.path.join(outdir, "platform_captions.srt"), html.unescape(m.group(0))])

info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                       "-of", "compact", dst], capture_output=True, text=True).stdout
print(dst); print(info.strip())
