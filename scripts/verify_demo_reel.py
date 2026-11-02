# Container facts for the broadcast reel, read from ffmpeg's own output rather
# than assumed: size against the 15 MB limit, duration against the 48 to 52 second
# window, codecs and frame size, and a comma audit of both caption files.
import os
import re
import subprocess
import sys

try:
    import imageio_ffmpeg
except ImportError:
    sys.exit("imageio-ffmpeg is required: pip install imageio-ffmpeg")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(ROOT, "docs", "demo-video-subtitled.mp4")
BUILD = os.path.join(ROOT, "scripts", "video-build")
os.makedirs(BUILD, exist_ok=True)
LOG = os.path.join(BUILD, "ffprobe.log")

size = os.path.getsize(VIDEO)
exe = imageio_ffmpeg.get_ffmpeg_exe()
with open(LOG, "wb") as log:
    subprocess.run([exe, "-hide_banner", "-loglevel", "info", "-i", VIDEO, "-f", "null", "-"],
                   stdout=subprocess.DEVNULL, stderr=log, check=False)
info = open(LOG, encoding="utf-8", errors="replace").read()

duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", info)
secs = 0.0
if duration:
    h, m, s = duration.groups()
    secs = int(h) * 3600 + int(m) * 60 + float(s)
video_stream = re.search(r"Video:\s*(\S+).*?(\d{3,4})x(\d{3,4})", info)
audio_stream = re.search(r"Audio:\s*(\S+)", info)

checks = []
checks.append(("file size under 15 MB", size < 15 * 1_048_576, f"{size} B ({size / 1_048_576:.2f} MB)"))
checks.append(("duration inside 48 to 52 s", 48.0 <= secs <= 52.0, f"{secs:.2f} s"))
checks.append(("video codec is libx264 output h264", bool(video_stream) and video_stream.group(1) == "h264",
               video_stream.group(1) if video_stream else "n/a"))
checks.append(("frame size 1280x720", bool(video_stream) and f"{video_stream.group(2)}x{video_stream.group(3)}" == "1280x720",
               f"{video_stream.group(2)}x{video_stream.group(3)}" if video_stream else "n/a"))
checks.append(("audio codec is aac", bool(audio_stream) and audio_stream.group(1) == "aac",
               audio_stream.group(1) if audio_stream else "n/a"))

for name in ("docs/demo-video-subtitles.srt", os.path.join("scripts", "video-build", "captions.ass")):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        checks.append((f"captions present {name}", False, "MISSING"))
        continue
    text = open(p, encoding="utf-8").read()
    if name.endswith(".ass"):
        dialogue = [l.split(",", 9)[-1] for l in text.splitlines() if l.startswith("Dialogue:")]
    else:
        dialogue = [l for l in text.splitlines()
                    if l.strip() and not l.strip().isdigit() and "-->" not in l]
    commas = sum(1 for d in dialogue if "," in d)
    checks.append((f"zero commas in caption text {name}", commas == 0, f"{len(dialogue)} lines, {commas} with comma"))

failed = 0
for label, ok, detail in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {detail}")
    failed += 0 if ok else 1
print(f"reel checks: {len(checks) - failed}/{len(checks)} pass")
sys.exit(1 if failed else 0)
