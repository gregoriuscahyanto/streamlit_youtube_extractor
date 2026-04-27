from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from backend import _config_from_mat_file_v73


LOG_PATH = Path("logs/mat_fmt_categorical_test.log")


def _write_log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(message, encoding="utf-8")


def _pack_utf16_rows(rows: list[str]) -> np.ndarray:
    chars: list[int] = []
    for row in rows:
        chars.extend(ord(ch) for ch in row)

    packed: list[int] = []
    for start in range(0, len(chars), 4):
        word = 0
        for shift, value in enumerate(chars[start:start + 4]):
            word |= int(value) << (16 * shift)
        packed.append(word)

    header = [1, 2, len(rows), 0]
    lengths = [len(row) for row in rows]
    return np.array(header + lengths + packed, dtype=np.uint64)


def _char_cell(h5f: h5py.File, name: str, values: list[str]) -> h5py.Dataset:
    refs = []
    for idx, value in enumerate(values):
        ds = h5f.create_dataset(
            f"{name}_value_{idx}",
            data=np.array([ord(ch) for ch in value], dtype=np.uint16),
        )
        ds.attrs["MATLAB_class"] = np.bytes_("char")
        refs.append(ds.ref)

    cell = h5f.create_dataset(name, data=np.array(refs, dtype=h5py.ref_dtype))
    cell.attrs["MATLAB_class"] = np.bytes_("cell")
    return cell


def _descriptor(h5f: h5py.File, name: str, object_index: int) -> h5py.Dataset:
    return h5f.create_dataset(
        name,
        data=np.array([0, 0, 0, 0, object_index], dtype=np.uint64),
    )


def test_v73_roi_table_raw_fmt_categorical_2x1() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    mat_path = LOG_PATH.parent / "roi_fmt_categorical_v73.mat"
    if mat_path.exists():
        mat_path.unlink()
    base_idx = 5

    try:
        with h5py.File(mat_path, "w") as h5f:
            h5f.create_dataset(
                "recordResult/ocr/params/start_s",
                data=np.array([[10.0]], dtype=float),
            )
            h5f.create_dataset(
                "recordResult/ocr/params/end_s",
                data=np.array([[120.0]], dtype=float),
            )
            h5f.create_dataset(
                "recordResult/ocr/roi_table_raw",
                data=np.array([0, 0, 0, 0, base_idx], dtype=np.uint64),
            )

            name_categories = _char_cell(
                h5f,
                "name_categories",
                ["v_Fzg_kmph", "t_s"],
            )
            name_codes = h5f.create_dataset(
                "name_codes",
                data=np.array([[1], [2]], dtype=np.uint8),
            )
            roi_rows = h5f.create_dataset(
                "roi_rows",
                data=_pack_utf16_rows(["41 52 105 52", "321 28 306 70"]),
            )
            roi_rows.attrs["MATLAB_class"] = np.bytes_("uint64")
            fmt_categories = _char_cell(
                h5f,
                "fmt_categories",
                ["any", "time_m:ss", "time_hh:mm:ss"],
            )
            fmt_codes = h5f.create_dataset(
                "fmt_codes_actual",
                data=np.array([[2], [2]], dtype=np.uint8),
            )
            max_scale = h5f.create_dataset(
                "max_scale",
                data=np.array([[1.2], [1.2]], dtype=float),
            )

            desc_name_categories = _descriptor(h5f, "desc_name_categories", 20)
            desc_name_codes = _descriptor(h5f, "desc_name_codes", 21)
            desc_roi_rows = _descriptor(h5f, "desc_roi_rows", 22)
            desc_fmt_categories = _descriptor(h5f, "desc_fmt_categories", 23)

            data_cell = h5f.create_dataset(
                "data_cell",
                data=np.array(
                    [
                        desc_name_categories.ref,
                        desc_name_codes.ref,
                        desc_roi_rows.ref,
                        desc_fmt_categories.ref,
                        max_scale.ref,
                    ],
                    dtype=h5py.ref_dtype,
                ),
            )
            data_cell.attrs["MATLAB_class"] = np.bytes_("cell")

            dummy_primary = h5f.create_dataset(
                "wrong_primary_fmt_codes",
                data=np.array([[1], [1]], dtype=np.uint8),
            )

            mcos = h5f.create_dataset(
                "#subsystem#/MCOS",
                shape=(1, 32),
                dtype=h5py.ref_dtype,
            )
            mcos[0, base_idx + 2] = data_cell.ref
            mcos[0, base_idx + 3] = dummy_primary.ref
            mcos[0, 20] = name_categories.ref
            mcos[0, 21] = name_codes.ref
            mcos[0, 22] = roi_rows.ref
            mcos[0, 23] = fmt_categories.ref
            mcos[0, 24] = fmt_codes.ref

        cfg = _config_from_mat_file_v73(str(mat_path), vid_duration=200.0)
        assert cfg["t_start"] == 10.0
        assert cfg["t_end"] == 120.0
        assert len(cfg["rois"]) == 2
        assert cfg["rois"][0]["name"] == "v_Fzg_kmph"
        assert cfg["rois"][0]["fmt"] == "time_m:ss"
        assert cfg["rois"][1]["name"] == "t_s"
        assert cfg["rois"][1]["fmt"] == "time_m:ss"
        assert cfg["rois"][1]["x"] == 321.0
        _write_log("OK: v7.3 2x1 categorical fmt was decoded as time_m:ss.")
    except Exception as exc:
        _write_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        raise
    finally:
        if mat_path.exists():
            mat_path.unlink()
