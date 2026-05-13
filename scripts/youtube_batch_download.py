"""Batch download via scripts/record_youtube_cfr.py (pure Python, no MATLAB)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _parse_result(text: str) -> dict:
    out = {}
    for line in (text or "").splitlines():
        t = line.strip()
        if t.startswith("RESULT_") and ":" in t:
            k, v = t.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _download_one(url: str, out_base: Path, rec_script: Path, force: bool) -> tuple[bool, str]:
    folder = f"yt_{abs(hash(url)) % 10_000_000:07d}"
    cap = out_base / "captures" / folder
    cap.mkdir(parents=True, exist_ok=True)
    out_v = cap / "video.avi"
    out_a = cap / "audio.wav"
    if (not force) and out_v.exists() and out_a.exists() and out_v.stat().st_size > 0 and out_a.stat().st_size > 0:
        return True, f"skip existing: {folder}"

    cmd = [
        sys.executable,
        str(rec_script),
        "--url",
        url,
        "--duration",
        "86400",
        "--out",
        "capture",
        "--outdir",
        str(cap),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    txt = (p.stdout or "") + "\n" + (p.stderr or "")
    meta = _parse_result(txt)
    if p.returncode != 0:
        return False, txt.strip()[-500:]

    src_v = Path(str(meta.get("RESULT_VIDEO") or ""))
    src_a = Path(str(meta.get("RESULT_AUDIO") or ""))
    if src_v.exists():
        try:
            src_v.replace(out_v)
        except Exception:
            pass
    if src_a.exists():
        try:
            src_a.replace(out_a)
        except Exception:
            pass
    if not out_v.exists() or not out_a.exists():
        return False, "video/audio nicht vollständig erzeugt"
    return True, f"ok: {folder}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--links-file", required=True)
    ap.add_argument("--out-base", default=".")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    rec_script = Path("scripts") / "record_youtube_cfr.py"
    if not rec_script.exists():
        print(f"record script not found: {rec_script}")
        return 2

    links_path = Path(args.links_file)
    out_base = Path(args.out_base).resolve()
    if not links_path.exists():
        print(f"links file not found: {links_path}")
        return 2

    links = []
    for line in links_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        u = line.strip()
        if u and (u not in links):
            links.append(u)

    ok_n = 0
    err_n = 0
    for i, url in enumerate(links, 1):
        ok, msg = _download_one(url, out_base=out_base, rec_script=rec_script, force=args.force)
        print(f"[{i}/{len(links)}] {msg}")
        if ok:
            ok_n += 1
        else:
            err_n += 1
    print(f"done: ok={ok_n}, errors={err_n}")
    return 0 if err_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
