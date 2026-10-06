"""Record a match as a vertical 1080x1920 MP4, ready to post.

    uv run --group tools python tools/record.py <match id>                 # a recorded match (server must be running)
    uv run --group tools python tools/record.py --demo                     # the browser simulation
    uv run --group tools python tools/record.py <id> --url http://localhost:8795 --out luna.mp4
    uv run --group tools python tools/record.py <id> --stills 1 12 32     # PNGs at those seconds, for checking a layout

Headless Chrome opens the viewer with ?record, which shows only the frame at 1:1
and lets this script step time itself: each video frame is exactly 1/fps after
the last, so nothing stutters or drops however long a screenshot takes. Frames
go straight into ffmpeg (the copy bundled with imageio-ffmpeg) as H.264, which
LinkedIn, X and phones all play. It uses your installed Google Chrome, or
Playwright's Chromium (`uv run --group tools playwright install chromium`).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

W, H = 1080, 1920


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("match", nargs="?", help="match id from logs/ or /api/matches")
    ap.add_argument("--demo", action="store_true", help="record the browser simulation instead")
    ap.add_argument("--url", default="http://localhost:8000", help="where the arena is running")
    ap.add_argument("--out", help="output file (default: <match id>.mp4 or demo.mp4)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--hold", type=float, default=5.0, help="seconds to stay on the result card")
    ap.add_argument("--max", type=float, default=120.0, help="stop after this many seconds of video regardless")
    ap.add_argument("--stills", type=float, nargs="+", help="save PNGs at these seconds of video instead of an MP4")
    a = ap.parse_args()
    if not a.match and not a.demo:
        ap.error("give a match id, or --demo")
    page_url = f"{a.url.rstrip('/')}/?{'demo' if a.demo else 'replay=' + a.match}&record"
    out = a.out or f"{'demo' if a.demo else a.match}.mp4"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if a.stills:
        stills(page_url, sorted(a.stills), a.fps, Path(out).with_suffix(""))
        return

    ffmpeg = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
         "-f", "image2pipe", "-framerate", str(a.fps), "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", out],
        stdin=subprocess.PIPE)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(page_url)
        page.wait_for_function("window.arenaRecord && window.arenaRecord.ready", timeout=30_000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(500)  # sprites finish decoding
        dt, n, t0 = 1 / a.fps, 0, time.time()
        while True:
            state = page.evaluate(f"window.arenaRecord.step({dt})")
            ffmpeg.stdin.write(page.screenshot(type="png"))
            n += 1
            if n % a.fps == 0:
                print(f"\r{n / a.fps:5.1f}s of video", end="", flush=True)
            if (state["ended"] and state["afterEnd"] >= a.hold) or n / a.fps >= a.max:
                break
        browser.close()

    ffmpeg.stdin.close()
    if ffmpeg.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"\nwrote {out}: {n / a.fps:.1f}s at {a.fps} fps, {W}x{H}, in {time.time() - t0:.0f}s")


def stills(page_url: str, times: list, fps: int, stem: Path) -> None:
    """Step to each time (in seconds of video) and save a full-size PNG there; no video is encoded."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(page_url)
        page.wait_for_function("window.arenaRecord && window.arenaRecord.ready", timeout=30_000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(500)
        n = 0
        for t in times:
            while n < round(t * fps):
                page.evaluate(f"window.arenaRecord.step({1 / fps})")
                n += 1
            path = f"{stem}-{t:g}s.png"
            page.screenshot(path=path)
            print("wrote", path)
        browser.close()


if __name__ == "__main__":
    main()
