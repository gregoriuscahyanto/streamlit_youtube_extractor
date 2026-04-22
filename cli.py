from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend import (
    build_result_payload,
    config_from_json_payload,
    config_from_mat_file,
    connect_webdav_client,
    list_root_folders,
    load_webdav_credentials,
    mat_bytes_from_result,
    run_webdav_diagnostic,
)
from storage import StorageManager


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str, str]:
    sec_url, sec_user, sec_pass = load_webdav_credentials(secrets_path=args.secrets_file)
    url = args.url or sec_url
    user = args.user or sec_user
    password = args.password or sec_pass
    return url, user, password


def _print_diag(diag: list[tuple[str, str]]) -> None:
    for k, v in diag:
        print(f"{k}: {v}")


def cmd_diagnose(args: argparse.Namespace) -> int:
    url, user, password = _resolve_credentials(args)
    diag = run_webdav_diagnostic(url, user, password)
    _print_diag(diag)
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    url, user, password = _resolve_credentials(args)
    ok, msg, _client = connect_webdav_client(url, user, password)
    print("OK" if ok else "ERROR", "-", msg if msg else "Verbunden")
    return 0 if ok else 1


def cmd_list_roots(args: argparse.Namespace) -> int:
    url, user, password = _resolve_credentials(args)
    ok, msg, client = connect_webdav_client(url, user, password)
    if not ok or client is None:
        print(f"ERROR - {msg}")
        return 1
    roots = list_root_folders(client)
    if args.json:
        print(json.dumps(roots, ensure_ascii=False, indent=2))
    else:
        for root in roots:
            print(root)
    return 0


def _connect_or_exit(args: argparse.Namespace):
    url, user, password = _resolve_credentials(args)
    ok, msg, client = connect_webdav_client(url, user, password)
    if not ok or client is None:
        print(f"ERROR - {msg}")
        return None
    return client


def cmd_list_files(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    ok, items = client.list_files(args.remote_dir)
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
    ok, msg = client.download_file(args.remote_path, str(local_path))
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
    ok, msg = client.upload_file(str(local_path), args.remote_path)
    if ok:
        print(f"OK - uploaded {local_path} -> {args.remote_path}")
        return 0
    print(f"ERROR - {msg}")
    return 1


def cmd_delete(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    ok, msg = client.delete_file(args.remote_path)
    if ok:
        print(f"OK - deleted {args.remote_path}")
        return 0
    print(f"ERROR - {msg}")
    return 1


def cmd_list_captures(args: argparse.Namespace) -> int:
    client = _connect_or_exit(args)
    if client is None:
        return 1
    sm = StorageManager(client, root=args.root)
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
    sm = StorageManager(client, root=args.root)
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


def cmd_json_to_mat(args: argparse.Namespace) -> int:
    in_path = Path(args.input_json)
    out_path = Path(args.output_mat)
    if not in_path.exists():
        print(f"ERROR - input not found: {in_path}")
        return 1
    try:
        data = json.loads(in_path.read_text(encoding="utf-8"))
        # Accept either full result JSON or config-like payload.
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCR Extractor CLI (backend tools)")
    parser.add_argument("--secrets-file", default=".streamlit/secrets.toml", help="Path to local secrets.toml")
    parser.add_argument("--url", help="WebDAV URL (optional if in secrets)")
    parser.add_argument("--user", help="WebDAV username (optional if in secrets)")
    parser.add_argument("--password", help="WebDAV password (optional if in secrets)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="Run WebDAV connectivity diagnostic")
    p_diag.set_defaults(func=cmd_diagnose)

    p_conn = sub.add_parser("connect", help="Test WebDAV authentication")
    p_conn.set_defaults(func=cmd_connect)

    p_roots = sub.add_parser("list-roots", help="List root folders (2 levels)")
    p_roots.add_argument("--json", action="store_true", help="Output JSON")
    p_roots.set_defaults(func=cmd_list_roots)

    p_ls = sub.add_parser("list-files", help="List files/folders in a remote directory")
    p_ls.add_argument("--remote-dir", default="", help="Remote dir relative to base URL, e.g. captures/myfolder")
    p_ls.add_argument("--json", action="store_true", help="Output JSON")
    p_ls.set_defaults(func=cmd_list_files)

    p_dl = sub.add_parser("download", help="Download remote file to local path")
    p_dl.add_argument("--remote-path", required=True, help="Remote file path")
    p_dl.add_argument("--local-path", required=True, help="Local target path")
    p_dl.set_defaults(func=cmd_download)

    p_ul = sub.add_parser("upload", help="Upload local file to remote path")
    p_ul.add_argument("--local-path", required=True, help="Local source path")
    p_ul.add_argument("--remote-path", required=True, help="Remote target path")
    p_ul.set_defaults(func=cmd_upload)

    p_del = sub.add_parser("delete", help="Delete remote file")
    p_del.add_argument("--remote-path", required=True, help="Remote file path")
    p_del.set_defaults(func=cmd_delete)

    p_caps = sub.add_parser("list-captures", help="List capture folders under <root>/captures")
    p_caps.add_argument("--root", default="/", help="Project root, e.g. / or /my_project")
    p_caps.add_argument("--json", action="store_true", help="Output JSON")
    p_caps.set_defaults(func=cmd_list_captures)

    p_res = sub.add_parser("list-results", help="List result files under <root>/results")
    p_res.add_argument("--root", default="/", help="Project root, e.g. / or /my_project")
    p_res.add_argument("--json", action="store_true", help="Output JSON")
    p_res.set_defaults(func=cmd_list_results)

    p_j2m = sub.add_parser("json-to-mat", help="Convert result/config JSON to MAT")
    p_j2m.add_argument("--input-json", required=True, help="Input JSON path")
    p_j2m.add_argument("--output-mat", required=True, help="Output MAT path")
    p_j2m.add_argument("--video-name", default="", help="Optional video name for MAT metadata")
    p_j2m.add_argument("--video-width", type=int, default=0, help="Fallback width when input is config JSON")
    p_j2m.add_argument("--video-height", type=int, default=0, help="Fallback height when input is config JSON")
    p_j2m.add_argument("--video-fps", type=float, default=0.0, help="Fallback fps when input is config JSON")
    p_j2m.add_argument("--vid-duration", type=float, default=0.0, help="Fallback duration when input is config JSON")
    p_j2m.set_defaults(func=cmd_json_to_mat)

    p_m2j = sub.add_parser("mat-to-json", help="Convert MAT to normalized config JSON")
    p_m2j.add_argument("--input-mat", required=True, help="Input MAT path")
    p_m2j.add_argument("--output-json", required=True, help="Output JSON path")
    p_m2j.add_argument("--vid-duration", type=float, default=0.0, help="Fallback duration")
    p_m2j.set_defaults(func=cmd_mat_to_json)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
