"""
track_analysis.py
Funktionen für:
  - Minimap-Ausschnitt aus einem Video-Frame extrahieren
  - 8-Punkte Homographie-Vergleich (Minimap ↔ Referenz-Track)
  - Bewegenden Punkt per Farbbereich (HSV) erkennen
  - Overlay-Visualisierung
"""

from __future__ import annotations
import cv2
import numpy as np
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def extract_minimap_crop(
    frame: np.ndarray,
    track_roi: dict,
    vid_w: int,
    vid_h: int,
) -> np.ndarray:
    """
    Schneidet den track_minimap-Ausschnitt aus einem Video-Frame.

    Parameters
    ----------
    frame     : RGB-Frame (H×W×3)
    track_roi : {'x', 'y', 'w', 'h'} in Original-Pixeln
    vid_w, vid_h : Originale Video-Auflösung

    Returns
    -------
    crop : RGB-Bild des Minimap-Ausschnitts
    """
    dh, dw = frame.shape[:2]
    sx = dw / vid_w if vid_w else 1.0
    sy = dh / vid_h if vid_h else 1.0

    x = max(0, int(track_roi["x"] * sx))
    y = max(0, int(track_roi["y"] * sy))
    w = max(1, int(track_roi["w"] * sx))
    h = max(1, int(track_roi["h"] * sy))

    x2 = min(x + w, dw)
    y2 = min(y + h, dh)
    crop = frame[y:y2, x:x2].copy()
    return crop


def load_reference_track(path: str | Path) -> np.ndarray | None:
    """Lädt ein Referenz-Track-Bild (RGB)."""
    img = cv2.imread(str(path))
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


# ─────────────────────────────────────────────────────────────────────────────
# 8-Punkte-Vergleich via Homographie
# ─────────────────────────────────────────────────────────────────────────────

def compare_minimap_to_reference(
    minimap_crop: np.ndarray,
    ref_img: np.ndarray,
    minimap_pts: list[list[float]],   # 8 × [x, y] in Minimap-Koordinaten
    ref_pts:     list[list[float]],   # 8 × [x, y] in Referenz-Koordinaten
) -> dict:
    """
    Vergleicht 8 Punkte auf der Minimap mit 8 Punkten auf der Referenzkarte.

    Berechnet:
      - Homographie-Matrix H: Minimap → Referenz
      - Rückprojektionsfehler für alle 8 Punktpaare
      - Mean / Max Abstand (Pixel)
      - Transformiertes Minimap-Bild (für Overlay)

    Returns
    -------
    dict mit:
      'H'              : 3×3 Homographie-Matrix (oder None)
      'mean_dist_px'   : float
      'max_dist_px'    : float
      'homography_err' : float (mittlerer Rückprojektionsfehler)
      'reprojected'    : np.ndarray  (8 × 2 projizierte Punkte auf Referenz)
      'warped_minimap' : np.ndarray  (Minimap auf Referenz-Bildgröße transformiert)
    """
    result = dict(H=None, mean_dist_px=0.0, max_dist_px=0.0,
                  homography_err=0.0, reprojected=None,
                  warped_minimap=None, error=None)

    # Punkte validieren
    try:
        src = np.array(minimap_pts, dtype=np.float32)   # Minimap
        dst = np.array(ref_pts,     dtype=np.float32)   # Referenz

        if src.shape != (8, 2) or dst.shape != (8, 2):
            result["error"] = "Genau 8 Punktpaare benötigt."
            return result

        # Homographie berechnen (RANSAC für Robustheit)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if H is None:
            result["error"] = "Homographie konnte nicht berechnet werden."
            return result

        result["H"] = H.tolist()

        # Rückprojektionsfehler
        src_h = np.concatenate([src, np.ones((8,1), dtype=np.float32)], axis=1)  # 8×3
        dst_proj = (H @ src_h.T).T                    # 8×3
        dst_proj = dst_proj[:, :2] / dst_proj[:, 2:3] # homogen → Euklidisch

        dists = np.linalg.norm(dst_proj - dst, axis=1)
        result["mean_dist_px"]   = float(np.mean(dists))
        result["max_dist_px"]    = float(np.max(dists))
        result["homography_err"] = float(np.mean(dists))
        result["reprojected"]    = dst_proj.tolist()

        # Minimap auf Referenz-Größe transformieren
        rh, rw = ref_img.shape[:2]
        mm_bgr = cv2.cvtColor(minimap_crop, cv2.COLOR_RGB2BGR)
        warped = cv2.warpPerspective(mm_bgr, H, (rw, rh))
        result["warped_minimap"] = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)

    except Exception as e:
        result["error"] = str(e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Bewegenden Punkt erkennen (Farberkennung im HSV-Raum)
# ─────────────────────────────────────────────────────────────────────────────

def detect_moving_point(
    minimap_crop: np.ndarray,
    color_range: dict,
) -> dict | None:
    """
    Findet den größten zusammenhängenden Blob der Zielfarbe im Minimap-Crop.

    Parameters
    ----------
    minimap_crop  : RGB-Bild
    color_range   : {'h_lo','h_hi','s_lo','s_hi','v_lo','v_hi'}

    Returns
    -------
    {'x', 'y', 'area', 'confidence'} oder None
    """
    try:
        hsv = cv2.cvtColor(minimap_crop, cv2.COLOR_RGB2HSV)

        lo = np.array([color_range["h_lo"], color_range["s_lo"], color_range["v_lo"]],
                      dtype=np.uint8)
        hi = np.array([color_range["h_hi"], color_range["s_hi"], color_range["v_hi"]],
                      dtype=np.uint8)

        mask = cv2.inRange(hsv, lo, hi)

        # Hue-Wrap (z.B. Rot: 160–10 → zwei Bereiche)
        if color_range["h_lo"] > color_range["h_hi"]:
            lo2 = np.array([0,              color_range["s_lo"], color_range["v_lo"]], dtype=np.uint8)
            hi2 = np.array([color_range["h_hi"], color_range["s_hi"], color_range["v_hi"]], dtype=np.uint8)
            lo1 = np.array([color_range["h_lo"], color_range["s_lo"], color_range["v_lo"]], dtype=np.uint8)
            hi1 = np.array([179,            color_range["s_hi"], color_range["v_hi"]], dtype=np.uint8)
            mask = cv2.bitwise_or(cv2.inRange(hsv, lo1, hi1),
                                  cv2.inRange(hsv, lo2, hi2))

        # Morphologisches Glätten
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
        mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        # Konturen finden
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # Größten Blob nehmen
        best = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(best)
        if area < 4:   # zu klein → ignorieren
            return None

        M = cv2.moments(best)
        if M["m00"] == 0:
            return None

        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]

        total_px  = minimap_crop.shape[0] * minimap_crop.shape[1]
        confidence = min(1.0, area / max(total_px * 0.005, 1.0))  # normiert auf ~0.5% Bild

        return {"x": float(cx), "y": float(cy),
                "area": float(area), "confidence": float(confidence)}

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Overlay-Visualisierung
# ─────────────────────────────────────────────────────────────────────────────

def draw_comparison_overlay(
    minimap_crop: np.ndarray,
    ref_img: np.ndarray,
    minimap_pts: list[list[float]],
    ref_pts:     list[list[float]],
    cmp_result:  dict,
    color_range: dict,
) -> np.ndarray:
    """
    Erstellt ein Overlay-Bild:
      - Referenz-Track als Basis (abgedunkelt)
      - Minimap transformiert und eingeblendet (blau getönt, halbtransparent)
      - Referenzpunkte grün, Minimap-reprojiziert rot, Verbindungslinien
      - Erkannter bewegender Punkt gelb markiert

    Returns
    -------
    RGB-Bild gleicher Größe wie ref_img
    """
    rh, rw = ref_img.shape[:2]
    overlay = ref_img.copy().astype(np.float32)

    try:
        # Minimap transformiert einblenden
        warped = cmp_result.get("warped_minimap")
        if warped is not None and warped.shape[:2] == (rh, rw):
            wf = warped.astype(np.float32)
            # Blau-Tint für Minimap
            tint = np.zeros_like(wf)
            tint[:,:,2] = 80   # Blau-Kanal
            wf = np.clip(wf * 0.6 + tint, 0, 255)
            # nur nicht-schwarze Pixel einblenden
            gray_w = cv2.cvtColor(warped, cv2.COLOR_RGB2GRAY)
            alpha_mask = (gray_w > 15).astype(np.float32)[:,:,np.newaxis]
            overlay = overlay * (1 - alpha_mask * 0.45) + wf * (alpha_mask * 0.45)

        overlay = np.clip(overlay, 0, 255).astype(np.uint8)

        # Referenzpunkte (grün)
        clrs = [(255,80,80),(255,160,0),(255,255,0),(80,255,80),
                (0,200,255),(100,100,255),(200,80,255),(255,80,200)]
        for pi, pt in enumerate(ref_pts or []):
            if pt and len(pt) == 2:
                cv2.circle(overlay, (int(pt[0]),int(pt[1])), 8, clrs[pi%8], -1)
                cv2.putText(overlay, f"R{pi+1}", (int(pt[0])+10, int(pt[1])),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, clrs[pi%8], 1)

        # Minimap reprojizierte Punkte (weiß/gestrichelt) + Abstandslinien
        reproj = cmp_result.get("reprojected")
        if reproj and ref_pts:
            for pi, (rpt, mpt) in enumerate(zip(ref_pts, reproj)):
                if rpt and mpt and len(rpt)==2 and len(mpt)==2:
                    rx, ry = int(rpt[0]), int(rpt[1])
                    mx, my = int(mpt[0]), int(mpt[1])
                    # Verbindungslinie (Abstandsfehler)
                    cv2.line(overlay, (rx,ry), (mx,my), (255,255,255), 1, cv2.LINE_AA)
                    cv2.circle(overlay, (mx,my), 5, (255,255,255), 1)

        # Bewegenden Punkt auf Referenzkarte (falls homographie vorhanden)
        H_list = cmp_result.get("H")
        if H_list:
            H_arr = np.array(H_list, dtype=np.float64)
            # Für aktuellen Frame nochmal detect aufrufen (Crop schon bekannt)
            # Da wir das Crop hier nicht haben, zeigen wir nur den letzten bekannten Punkt
            # → wird in app.py mit History befüllt

    except Exception:
        pass

    return overlay
