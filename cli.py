from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend import (
    build_result_payload,
    collect_r2_listing_debug,
    config_from_json_payload,
    config_from_mat_file,
    connect_r2_client,
    list_root_prefixes,
    load_r2_credentials,
    mat_bytes_from_result,
)
from storage import StorageManager


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str, str, str]:
    acc, key, sec, bkt = load_r2_credentials(secrets_path=args.secrets_file)
    return (
        args.account_id or acc,
        args.access_key  or key,
        args.secret_key  or sec,
        args.bucket      or bkt,
    )


def _connect_or_exit(args: argparse.Namespace):
    acc, key, sec, bkt = _resolve_credentials(args)
    ok, msg, client = connect_r2_client(acc, key, sec, bkt)
    if not ok or client is None:
        print(f"ERROR - {msg}")
        return None
    return client


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_connect(args: argparse.Namespace) -> int:
    acc, key, sec, bkt = _resolve_credentials(args)
    ok, msg, _ = connect_r2_client(acc, key, sec, bkt)
    print("OK" if ok else "ERROR", "-", msg if msg else f"Verbunden mit bucket '{bkt}'")
    return 0 if ok else 1


def cmd_list_prefixes(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    prefixes = list_root_prefixes(client)
    if args.json:
        print(json.dumps(prefixes, ensure_ascii=False, indent=2))
    else:
        for p in prefixes:
            print(p or "(root)")
    return 0


def cmd_list_files(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    ok, items = client.list_files(args.prefix)
    if not ok:
        print(f"ERROR - {items}")
        return 1
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for item in items:
            print(item)
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    local_path = Path(args.local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    ok, msg = client.download_file(args.key, str(local_path))
    if ok:
        print(f"OK - downloaded to {local_path}")
        return 0
    print(f"ERROR - {msg}")
    return 1


def cmd_upload(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    local_path = Path(args.local_path)
    if not local_path.exists():
        print(f"ERROR - local file not found: {local_path}")
        return 1
    ok, msg = client.upload_file(str(local_path), args.key)
    if ok:
        print(f"OK - uploaded {local_path} -> {args.key}")
        return 0
    print(f"ERROR - {msg}")
    return 1


def cmd_delete(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    ok, msg = client.delete_file(args.key)
    if ok:
        print(f"OK - deleted {args.key}")
        return 0
    print(f"ERROR - {msg}")
    return 1


def cmd_list_captures(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    sm = StorageManager(client, prefix=args.prefix)
    ok, items = sm.list_capture_folders()
    if not ok:
        print(f"ERROR - {items}")
        return 1
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for item in items:
            print(item)
    return 0


def cmd_list_results(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    sm = StorageManager(client, prefix=args.prefix)
    ok, items = sm.list_results()
    if not ok:
        print(f"ERROR - {items}")
        return 1
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for item in items:
            print(item)
    return 0


def cmd_debug_listing(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    report = collect_r2_listing_debug(client, prefix=args.prefix,
                                      capture_folder=args.capture_folder)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_json_to_mat(args: argparse.Namespace) -> int:
    in_path = Path(args.input_json)
    out_path = Path(args.output_mat)
    if not in_path.exists():
        print(f"ERROR - input not found: {in_path}")
        return 1
    try:
        data = json.loads(in_path.read_text(encoding="utf-8"))
        if "params" in data and "roi_table" in data and "video" in data:
            result = data
        else:
            cfg = config_from_json_payload(data, vid_duration=float(args.vid_duration))
            result = build_result_payload(
                t_start=cfg.get("t_start", 0.0),
                t_end=cfg.get("t_end", float(args.vid_duration)),
                rois=cfg.get("rois", []),
                video={
                    "width": int(args.video_width),
                    "height": int(args.video_height),
                    "fps": float(args.video_fps),
                    "duration": float(args.vid_duration),
                },
                track={
                    "ref_pts": cfg.get("ref_track_pts"),
                    "minimap_pts": cfg.get("minimap_pts"),
                    "moving_pt_color_range": cfg.get("moving_pt_color_range"),
                },
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(mat_bytes_from_result(result, video_name=args.video_name))
        print(f"OK - wrote {out_path}")
        return 0
    except Exception as e:
        print(f"ERROR - {e}")
        return 1


def cmd_mat_to_json(args: argparse.Namespace) -> int:
    in_path = Path(args.input_mat)
    out_path = Path(args.output_json)
    if not in_path.exists():
        print(f"ERROR - input not found: {in_path}")
        return 1
    try:
        cfg = config_from_mat_file(str(in_path), vid_duration=float(args.vid_duration))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK - wrote {out_path}")
        return 0
    except Exception as e:
        print(f"ERROR - {e}")
        return 1


# ── Parser ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCR Extractor CLI (R2 backend)")
    parser.add_argument("--secrets-file", default=".streamlit/secrets.toml")
    parser.add_argument("--account-id",  help="R2 Account ID")
    parser.add_argument("--access-key",  help="R2 Access Key ID")
    parser.add_argument("--secret-key",  help="R2 Secret Access Key")
    parser.add_argument("--bucket",      help="R2 Bucket Name")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("connect", help="Test R2 connection").set_defaults(func=cmd_connect)

    p_pfx = sub.add_parser("list-prefixes", help="List top-level prefixes in bucket")
    p_pfx.add_argument("--json", action="store_true")
    p_pfx.set_defaults(func=cmd_list_prefixes)

    p_ls = sub.add_parser("list-files", help="List objects under a prefix")
    p_ls.add_argument("--prefix", default="", help="Key prefix, e.g. 'captures/myfolder'")
    p_ls.add_argument("--json", action="store_true")
    p_ls.set_defaults(func=cmd_list_files)

    p_dl = sub.add_parser("download", help="Download object to local path")
    p_dl.add_argument("--key", required=True, help="R2 object key")
    p_dl.add_argument("--local-path", required=True)
    p_dl.set_defaults(func=cmd_download)

    p_ul = sub.add_parser("upload", help="Upload local file to R2")
    p_ul.add_argument("--local-path", required=True)
    p_ul.add_argument("--key", required=True, help="R2 object key")
    p_ul.set_defaults(func=cmd_upload)

    p_del = sub.add_parser("delete", help="Delete R2 object")
    p_del.add_argument("--key", required=True)
    p_del.set_defaults(func=cmd_delete)

    p_caps = sub.add_parser("list-captures", help="List capture folders")
    p_caps.add_argument("--prefix", default="", help="Project prefix")
    p_caps.add_argument("--json", action="store_true")
    p_caps.set_defaults(func=cmd_list_captures)

    p_res = sub.add_parser("list-results", help="List result files")
    p_res.add_argument("--prefix", default="", help="Project prefix")
    p_res.add_argument("--json", action="store_true")
    p_res.set_defaults(func=cmd_list_results)

    p_dbg = sub.add_parser("debug-listing", help="Debug bucket listing")
    p_dbg.add_argument("--prefix", default="")
    p_dbg.add_argument("--capture-folder", default="")
    p_dbg.set_defaults(func=cmd_debug_listing)

    p_j2m = sub.add_parser("json-to-mat", help="Convert result/config JSON to MAT")
    p_j2m.add_argument("--input-json", required=True)
    p_j2m.add_argument("--output-mat", required=True)
    p_j2m.add_argument("--video-name", default="")
    p_j2m.add_argument("--video-width", type=int, default=0)
    p_j2m.add_argument("--video-height", type=int, default=0)
    p_j2m.add_argument("--video-fps", type=float, default=0.0)
    p_j2m.add_argument("--vid-duration", type=float, default=0.0)
    p_j2m.set_defaults(func=cmd_json_to_mat)

    p_m2j = sub.add_parser("mat-to-json", help="Convert MAT to config JSON")
    p_m2j.add_argument("--input-mat", required=True)
    p_m2j.add_argument("--output-json", required=True)
    p_m2j.add_argument("--vid-duration", type=float, default=0.0)
    p_m2j.set_defaults(func=cmd_mat_to_json)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
