"""Encode the Houdini frame sequences and create the local evaluation player."""

import json
import shutil
import subprocess

from demo import HERE, OUTPUT


def main():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to encode the preview")
    for pattern, start, count, name in (
        ("frame_%04d.png", 1, 240, "forward.mp4"),
        ("back_%04d.png", 97, 96, "backward.mp4"),
    ):
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                "24",
                "-start_number",
                str(start),
                "-i",
                str(OUTPUT / pattern),
                "-frames:v",
                str(count),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(OUTPUT / name),
            ],
            check=True,
        )
    verification = json.loads((OUTPUT / "verification.json").read_text())
    assert verification["passed"]
    page = (HERE / "review.html").read_text(encoding="utf-8")
    page = page.replace("/*REVIEW_DATA*/", "window.REVIEW_DATA=" + json.dumps(verification) + ";")
    (OUTPUT / "index.html").write_text(page, encoding="utf-8")
    print(OUTPUT / "index.html")


if __name__ == "__main__":
    main()
