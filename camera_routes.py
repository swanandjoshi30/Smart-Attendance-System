"""
camera_routes.py – Dual-camera attendance API routes.

Endpoints
─────────
GET/POST  /api/classes/{class_id}/cameras          – read / save camera URLs per class
POST      /api/attendance/{class_id}/entry          – in-cam detects student (records entry)
POST      /api/attendance/{class_id}/exit           – out-cam detects student (records exit)
GET       /api/attendance/{class_id}/summary/{date} – per-day attendance summary
POST      /api/sessions/process-ip-camera-frame     – backend grabs frame from IP/MJPEG camera
                                                      and runs face recognition (bypasses CORS)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional, List
import threading
import cv2
import numpy as np

router = APIRouter()


# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────

def grab_frame_from_url(url: str, timeout_sec: float = 5.0):
    """
    Grab a single frame from an MJPEG / HTTP camera stream or RTSP/webcam source.
    If HTTP/HTTPS, attempts to fetch as a single snapshot via standard HTTP GET,
    bypassing cv2.VideoCapture limitations/hangs.
    """
    import urllib.request
    import urllib.parse
    import base64

    # 1. Try direct HTTP fetch for HTTP/HTTPS URLs
    url_str = str(url).strip()
    if url_str.startswith("http://") or url_str.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(url_str)
            snapshot_url = url_str

            # Map stream endpoints to snapshot endpoints to avoid downloading infinite MJPEG streams
            if "/video" in parsed.path:
                snapshot_url = url_str.replace("/video", "/shot.jpg")
            elif "/stream" in parsed.path:
                snapshot_url = url_str.replace("/stream", "/snapshot.jpg")
            elif parsed.path == "" or parsed.path == "/":
                # Appending snapshot endpoint for root URLs (e.g. IP Webcam default)
                new_path = "/shot.jpg"
                snapshot_url = urllib.parse.urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    new_path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))

            # Handle Basic Authentication in URL (e.g., http://user:pass@ip:port/path)
            parsed_snap = urllib.parse.urlparse(snapshot_url)
            headers = {'User-Agent': 'Mozilla/5.0'}
            request_url = snapshot_url

            if parsed_snap.username or parsed_snap.password:
                username = parsed_snap.username or ""
                password = parsed_snap.password or ""
                # Strip credentials from request URL to conform to standard urllib expectations
                netloc = parsed_snap.hostname
                if parsed_snap.port:
                    netloc += f":{parsed_snap.port}"
                request_url = urllib.parse.urlunparse((
                    parsed_snap.scheme,
                    netloc,
                    parsed_snap.path,
                    parsed_snap.params,
                    parsed_snap.query,
                    parsed_snap.fragment
                ))
                auth_str = f"{username}:{password}"
                auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
                headers['Authorization'] = f"Basic {auth_b64}"

            print(f"[DEBUG IP CAM] Fetching snapshot from URL: {request_url}")
            req = urllib.request.Request(request_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                img_bytes = response.read()
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is not None:
                    print(f"[DEBUG IP CAM] Successfully fetched and decoded snapshot via HTTP")
                    return frame, None
        except Exception as e:
            print(f"[DEBUG IP CAM] HTTP snapshot fetch failed: {e}")
            # If snapshot mapping failed or threw an error, try original URL direct fetch if different
            if 'request_url' in locals() and request_url != url_str:
                try:
                    # Clean credentials from original URL if present
                    parsed_orig = urllib.parse.urlparse(url_str)
                    headers_orig = {'User-Agent': 'Mozilla/5.0'}
                    req_url_orig = url_str
                    if parsed_orig.username or parsed_orig.password:
                        netloc = parsed_orig.hostname
                        if parsed_orig.port:
                            netloc += f":{parsed_orig.port}"
                        req_url_orig = urllib.parse.urlunparse((
                            parsed_orig.scheme,
                            netloc,
                            parsed_orig.path,
                            parsed_orig.params,
                            parsed_orig.query,
                            parsed_orig.fragment
                        ))
                        auth_str = f"{parsed_orig.username or ''}:{parsed_orig.password or ''}"
                        auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
                        headers_orig['Authorization'] = f"Basic {auth_b64}"

                    req = urllib.request.Request(req_url_orig, headers=headers_orig)
                    with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                        img_bytes = response.read()
                        nparr = np.frombuffer(img_bytes, np.uint8)
                        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            return frame, None
                except Exception as e2:
                    print(f"[DEBUG IP CAM] Original URL HTTP fetch also failed: {e2}")

    # 2. Fallback to OpenCV VideoCapture (RTSP, local webcams, or HTTP streams that don't support snapshot)
    frame_holder = [None]
    error_holder = [None]

    def _read():
        try:
            # Check if index is a local webcam digit
            src = int(url_str) if url_str.isdigit() else url_str
            cap = cv2.VideoCapture(src)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # don't buffer old frames
            if cap.isOpened():
                # Discard a few buffered frames to get the most current one
                for _ in range(3):
                    cap.grab()
                ret, frame = cap.read()
                if ret and frame is not None:
                    frame_holder[0] = frame
                else:
                    error_holder[0] = "cap.read() returned no frame"
            else:
                error_holder[0] = f"Could not open video source: {url_str}"
            cap.release()
        except Exception as e:
            error_holder[0] = str(e)

    print(f"[DEBUG IP CAM] Falling back to OpenCV VideoCapture for source: {url_str}")
    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        return None, f"Timeout ({timeout_sec}s) connecting to video source"

    return frame_holder[0], error_holder[0]




# ─────────────────────────────────────────────────────────
#  Camera URL config per classroom
# ─────────────────────────────────────────────────────────

class CameraConfig(BaseModel):
    in_camera_url:  Optional[str] = ""
    out_camera_url: Optional[str] = ""


@router.post("/classes/{class_id}/cameras")
async def set_camera_urls(class_id: int, config: CameraConfig):
    """Save in/out camera URLs for a classroom with auto-normalization."""
    try:
        from run_api import db
        in_url = (config.in_camera_url or "").strip()
        out_url = (config.out_camera_url or "").strip()

        def normalize(u: str) -> str:
            if not u:
                return ""
            if u.isdigit() or u.lower() in ("local", "webcam"):
                return u
            if not (u.startswith("http://") or u.startswith("https://") or u.startswith("rtsp://")):
                if "." in u or ":" in u:
                    return "http://" + u
            return u

        normalized_in = normalize(in_url)
        normalized_out = normalize(out_url)
        print(f"[DEBUG CAMERA CONFIG] Saving normalized URLs - In: {normalized_in}, Out: {normalized_out}")

        db.set_camera_urls(class_id, normalized_in, normalized_out)
        return {"success": True, "detail": "Camera URLs updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/classes/{class_id}/cameras")
async def get_camera_urls(class_id: int):
    """Read saved camera URLs for a classroom."""
    try:
        from run_api import db
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT in_camera_url, out_camera_url FROM Classes WHERE class_id = %s",
                    (class_id,)
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Class not found")
                return {
                    "in_camera_url":  row[0] or "",
                    "out_camera_url": row[1] or ""
                }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────
#  IP / MJPEG camera — backend-side frame grab + recognition
#  This completely bypasses the browser CORS restriction that
#  taints canvas when drawing a cross-origin <img> stream.
# ─────────────────────────────────────────────────────────

class IPCameraFramePayload(BaseModel):
    session_id:  int
    camera_url:  str
    class_id:    int


@router.post("/sessions/process-ip-camera-frame")
async def process_ip_camera_frame(payload: IPCameraFramePayload):
    """
    Grab one frame from the given IP/MJPEG camera URL on the server side,
    run face recognition, log session detections, and return results.

    Called by the frontend instead of canvas capture whenever an IP camera
    (HTTP stream) is configured — avoids the CORS tainted-canvas issue.
    """
    try:
        from run_api import face_engine, db
        print(f"[DEBUG IP CAM] Processing frame for session {payload.session_id}, class {payload.class_id}, URL: {payload.camera_url}")

        # ── 1. Grab frame from camera ──
        frame, error = grab_frame_from_url(payload.camera_url, timeout_sec=5.0)
        if frame is None:
            print(f"[DEBUG IP CAM] Frame grab failed: {error}")
            return {
                "success": False,
                "detail":  error or "Could not grab frame from camera",
                "results": []
            }

        h, w = frame.shape[:2]
        print(f"[DEBUG IP CAM] Grabbed frame of size {w}x{h}")

        # ── 2. Enhance + detect faces ──
        frame_enhanced = face_engine.enhance_image_quality(frame)
        face_locations, face_encodings = face_engine.detect_and_encode_face(frame_enhanced)

        results        = []
        recognized_prns = []

        print(f"[DEBUG IP CAM] Detected {len(face_encodings)} faces in frame")

        if face_encodings:
            recognitions = face_engine.recognize_faces(face_encodings)

            for i, (prn, confidence) in enumerate(recognitions):
                loc = face_locations[i]  # (top, right, bottom, left)

                if prn:
                    # Only accept students enrolled in this session's class
                    student_class_id = db.get_student_class_id(prn)
                    print(f"[DEBUG IP CAM] Recognized PRN: {prn} (confidence: {confidence}%), student class: {student_class_id}, session class: {payload.class_id}")
                    if student_class_id != payload.class_id:
                        results.append({
                            "box":        {"top": loc[0], "right": loc[1],
                                           "bottom": loc[2], "left": loc[3]},
                            "name":       "Unknown (Other Class)",
                            "prn":        None,
                            "status":     "unknown",
                            "confidence": round(confidence, 1)
                        })
                        continue

                    student_name = db.get_student_name(prn)
                    results.append({
                        "box":        {"top": loc[0], "right": loc[1],
                                       "bottom": loc[2], "left": loc[3]},
                        "name":       student_name or prn,
                        "prn":        prn,
                        "status":     "success",
                        "confidence": round(confidence, 1)
                    })
                    recognized_prns.append(prn)
                else:
                    print(f"[DEBUG IP CAM] Face detected but unrecognized")
                    results.append({
                        "box":        {"top": loc[0], "right": loc[1],
                                       "bottom": loc[2], "left": loc[3]},
                        "name":       "Unknown",
                        "prn":        None,
                        "status":     "unknown",
                        "confidence": round(confidence, 1)
                    })

        # ── 3. Log session detections ──
        if recognized_prns:
            db.log_session_detections(payload.session_id, recognized_prns)
            print(f"[DEBUG IP CAM] Logged {len(recognized_prns)} recognized PRNs to DB")

        return {"success": True, "results": results}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



# ─────────────────────────────────────────────────────────
#  Entry / Exit recording
# ─────────────────────────────────────────────────────────

class EntryPayload(BaseModel):
    student_id:   str
    entry_time:   datetime
    session_date: date


@router.post("/attendance/{class_id}/entry")
async def record_entry(class_id: int, payload: EntryPayload):
    """
    Record a student entry detected by the in-camera.
    The DB method guards against duplicate open entries — safe to call repeatedly.
    """
    try:
        from run_api import db
        record_id = db.record_entry(
            class_id,
            payload.student_id,
            payload.entry_time,
            payload.session_date
        )
        return {"success": True, "detail": "Entry recorded", "record_id": record_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ExitPayload(BaseModel):
    student_id: str
    exit_time:  datetime


@router.post("/attendance/{class_id}/exit")
async def record_exit(class_id: int, payload: ExitPayload):
    """
    Record a student exit detected by the out-camera.
    Automatically finds the latest open entry record for this student —
    frontend does not need to track record_ids.
    Returns success=False (not an error) when no open entry exists.
    """
    try:
        from run_api import db
        record_id = db.get_latest_open_entry(class_id, payload.student_id)
        if not record_id:
            return {
                "success": False,
                "detail":  "No open entry found — student not currently inside"
            }
        db.record_exit(record_id, payload.exit_time)
        return {"success": True, "detail": "Exit recorded", "record_id": record_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────
#  Per-day attendance summary
# ─────────────────────────────────────────────────────────

@router.get("/attendance/{class_id}/summary/{session_date}")
async def get_attendance_summary(class_id: int, session_date: date):
    """
    Returns attendance summary for a class on a given date.
    Requires at least one completed session for that class/date.
    """
    try:
        from run_api import db

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT prn_no, name, roll_no, email FROM Students WHERE class_id = %s ORDER BY roll_no",
                    (class_id,)
                )
                students = cur.fetchall()

                cur.execute(
                    """
                    SELECT start_time, end_time FROM Sessions
                    WHERE class_id = %s AND DATE(start_time) = %s AND status = 'completed'
                    ORDER BY end_time DESC LIMIT 1
                    """,
                    (class_id, session_date)
                )
                session = cur.fetchone()

        if not session:
            return {"success": False, "detail": "No completed session found for this class and date"}

        session_start, session_end = session
        results = []
        for prn, name, roll_no, email in students:
            pct, status = db.calculate_presence(
                class_id, prn, session_date, session_start, session_end, threshold=75.0
            )
            results.append({
                "prn":                prn,
                "name":               name,
                "roll_no":            roll_no,
                "email":              email,
                "presence_percentage": pct,
                "status":             status
            })

        return {"success": True, "summary": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
