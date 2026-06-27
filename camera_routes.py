"""
camera_routes.py – Dual-camera attendance API routes.

Endpoints
─────────
GET/POST  /api/classes/{class_id}/cameras      – read / save camera URLs per class
POST      /api/attendance/{class_id}/entry      – in-cam detects student (records entry)
POST      /api/attendance/{class_id}/exit       – out-cam detects student (records exit)
GET       /api/attendance/{class_id}/summary/{session_date}  – per-day summary
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional

router = APIRouter()

# ─────────────────────────────────────────────────────────
#  Camera URL config per classroom
# ─────────────────────────────────────────────────────────

class CameraConfig(BaseModel):
    in_camera_url:  Optional[str] = ""
    out_camera_url: Optional[str] = ""


@router.post("/classes/{class_id}/cameras")
async def set_camera_urls(class_id: int, config: CameraConfig):
    """Save in/out camera URLs for a classroom."""
    try:
        from run_api import db
        db.set_camera_urls(
            class_id,
            (config.in_camera_url  or "").strip(),
            (config.out_camera_url or "").strip()
        )
        return {"success": True, "detail": "Camera URLs updated"}
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
    The DB method guards against duplicate open entries,
    so calling this repeatedly for the same student is safe.
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
    Automatically finds the latest open entry record for
    this student so the frontend does not need to track record_ids.
    Returns 404 if no open entry exists (student is already outside).
    """
    try:
        from run_api import db
        record_id = db.get_latest_open_entry(class_id, payload.student_id)
        if not record_id:
            # No open entry — student is not currently marked as inside.
            # This is normal (e.g. out-cam fires before in-cam on first arrival).
            return {"success": False, "detail": "No open entry found — student not currently inside"}
        db.record_exit(record_id, payload.exit_time)
        return {"success": True, "detail": "Exit recorded", "record_id": record_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────
#  Per-day attendance summary (for a completed session)
# ─────────────────────────────────────────────────────────

@router.get("/attendance/{class_id}/summary/{session_date}")
async def get_attendance_summary(class_id: int, session_date: date):
    """
    Returns the attendance summary for a specific class on a given date.
    Requires a completed session to exist for that class/date combination.
    """
    try:
        from run_api import db

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch all students in class
                cur.execute(
                    "SELECT prn_no, name, roll_no, email FROM Students WHERE class_id = %s ORDER BY roll_no",
                    (class_id,)
                )
                students = cur.fetchall()

                # Find the most-recently completed session for this class on this date
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
            presence_pct, status = db.calculate_presence(
                class_id, prn, session_date, session_start, session_end, threshold=75.0
            )
            results.append({
                "prn":                prn,
                "name":               name,
                "roll_no":            roll_no,
                "email":              email,
                "presence_percentage": presence_pct,
                "status":             status
            })

        return {"success": True, "summary": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
