from typing import List, Optional
import numpy as np
import base64
import cv2
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from attendance_config import DB_CONFIG, FACE_RECOGNITION_CONFIG
from database_manager import DatabaseManager
from face_recognition_engine import FaceRecognitionEngine

app = FastAPI(
    title="Attendance System API V2",
    description="Backend API for Web-based Face Recognition Attendance System",
    version="2.0.0"
)

# Enable CORS for frontend flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = DatabaseManager(DB_CONFIG)
face_engine = FaceRecognitionEngine(FACE_RECOGNITION_CONFIG)

def verify_and_seed_users():
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Create table if not exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS Users (
                        user_id SERIAL PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL,
                        role VARCHAR(20) NOT NULL DEFAULT 'teacher',
                        name VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # 2. Insert/Update default users to ensure password hashes match expected values
                import hashlib
                admin_hash = hashlib.sha256(b'admin123').hexdigest()
                teacher_hash = hashlib.sha256(b'teacher123').hexdigest()
                
                cur.execute("""
                    INSERT INTO Users (username, password_hash, role, name) VALUES
                    ('admin', %s, 'admin', 'System Administrator'),
                    ('teacher', %s, 'teacher', 'Classroom Teacher')
                    ON CONFLICT (username) DO UPDATE 
                    SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role, name = EXCLUDED.name
                """, (admin_hash, teacher_hash))
                conn.commit()
                print("✓ Verified and synchronized default user accounts in database")
    except Exception as e:
        print(f"✗ Failed to verify/seed Users table: {e}")

def load_system_known_faces():
    try:
        encodings, prns = db.get_all_face_encodings()
        if encodings:
            face_engine.load_known_faces(encodings, prns)
            print(f"✓ Loaded {len(prns)} face encodings into recognition engine")
        else:
            print("⚠ No face encodings found in database")
    except Exception as e:
        print(f"✗ Failed to load known faces: {e}")

@app.on_event("startup")
async def startup_event():
    verify_and_seed_users()
    load_system_known_faces()

@app.get("/health")
async def health():
    return {"status": "ok"}

# ----------------- PYDANTIC PAYLOADS -----------------

class LoginPayload(BaseModel):
    username: str
    password: str

class StartSessionPayload(BaseModel):
    class_id: int
    subject_id: int

class ProcessFramePayload(BaseModel):
    session_id: int
    image_base64: str  # data:image/jpeg;base64,...

# ----------------- AUTHENTICATION -----------------

@app.post("/api/login")
async def login(payload: LoginPayload):
    user = db.validate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Generate simple session token (SHA256 of username + timestamp)
    token_seed = f"{user['username']}_{datetime.now().isoformat()}"
    token = hashlib.sha256(token_seed.encode('utf-8')).hexdigest()
    
    return {
        "success": True,
        "token": token,
        "role": user["role"],
        "name": user["name"],
        "username": user["username"]
    }

# ----------------- GENERAL DATA LISTS -----------------

@app.get("/api/classes")
async def list_classes():
    classes = db.get_all_classes()
    return [
        {"id": class_id, "name": class_name}
        for class_name, class_id in classes.items()
    ]

@app.get("/api/subjects")
async def list_subjects():
    return db.get_all_subjects_detailed()

@app.get("/api/students")
async def get_students():
    return db.get_all_students()

@app.get("/api/attendance")
async def get_attendance():
    return db.get_attendance_logs()

@app.delete("/api/students/{prn}")
async def delete_student(prn: str):
    success, message = db.delete_student(prn)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    load_system_known_faces()
    return {"success": True, "detail": message}

@app.post("/api/students/{prn}/edit")
async def edit_student(
    prn: str,
    class_id: int = Form(...),
    roll_no: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    image_base64: Optional[str] = Form(None)
):
    try:
        encoding_array = None
        if image_base64 and len(image_base64.strip()) > 0 and image_base64 != "undefined":
            header, encoded = image_base64.split(",", 1) if "," in image_base64 else ("", image_base64)
            image_data = base64.b64decode(encoded)
            np_arr = np.frombuffer(image_data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            if frame is None:
                raise HTTPException(status_code=400, detail="Invalid image file or format")
                
            frame_enhanced = face_engine.enhance_image_quality(frame)
            face_locations, face_encodings = face_engine.detect_and_encode_face(frame_enhanced, for_registration=True)
            
            if not face_encodings:
                raise HTTPException(status_code=400, detail="No face detected in the image. Please try another photo.")
            if len(face_encodings) > 1:
                raise HTTPException(status_code=400, detail="Multiple faces detected. Please upload a photo with exactly one face.")
                
            quality_ok, quality_report = face_engine.check_face_quality(frame_enhanced, face_locations[0])
            if not quality_ok:
                raise HTTPException(status_code=400, detail=f"Low face quality: {quality_report}")
                
            encoding_array = np.array(face_encodings[0], dtype=np.float32)

        success, message = db.update_student(
            prn,
            class_id,
            roll_no,
            name,
            email,
            encoding_array
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
            
        load_system_known_faces()
        return {"success": True, "detail": "Student updated successfully", "prn": prn}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- ENROLLMENT (ADMIN ONLY) -----------------

@app.post("/api/students/enroll")
async def enroll_student(
    prn: str = Form(...),
    class_id: int = Form(...),
    roll_no: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    image_base64: str = Form(...)
):
    try:
        # Decode base64 image
        header, encoded = image_base64.split(",", 1) if "," in image_base64 else ("", image_base64)
        image_data = base64.b64decode(encoded)
        np_arr = np.frombuffer(image_data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid image file or format")
            
        # Enhance & get face encoding
        frame_enhanced = face_engine.enhance_image_quality(frame)
        face_locations, face_encodings = face_engine.detect_and_encode_face(frame_enhanced, for_registration=True)
        
        if not face_encodings:
            raise HTTPException(status_code=400, detail="No face detected in the image. Please try another photo.")
        if len(face_encodings) > 1:
            raise HTTPException(status_code=400, detail="Multiple faces detected. Please upload a photo with exactly one face.")
            
        # Check quality
        quality_ok, quality_report = face_engine.check_face_quality(frame_enhanced, face_locations[0])
        if not quality_ok:
            raise HTTPException(status_code=400, detail=f"Low face quality: {quality_report}")
            
        # Register student
        encoding_array = np.array(face_encodings[0], dtype=np.float32)
        success, message = db.register_student(
            prn,
            class_id,
            roll_no,
            name,
            email,
            encoding_array
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
            
        # Reload known faces in face engine
        load_system_known_faces()
        
        return {"success": True, "detail": "Student enrolled successfully", "prn": prn}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/students/{prn}")
async def delete_student(prn: str):
    try:
        success, message = db.delete_student(prn)
        if not success:
            raise HTTPException(status_code=400, detail=message)
        # Reload known faces in face engine
        load_system_known_faces()
        return {"success": True, "detail": "Student deleted successfully"}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- SESSION TRACKING & PROCESSING -----------------

@app.post("/api/sessions/start")
async def start_session(payload: StartSessionPayload):
    try:
        session_id = db.start_session(payload.class_id, payload.subject_id)
        return {
            "success": True,
            "session_id": session_id,
            "class_id": payload.class_id,
            "subject_id": payload.subject_id,
            "start_time": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/active")
async def get_active_session():
    try:
        session = db.get_active_session()
        return session or {"session_id": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sessions/process-frame")
async def process_frame(payload: ProcessFramePayload):
    try:
        # Decode base64 image
        header, encoded = payload.image_base64.split(",", 1) if "," in payload.image_base64 else ("", payload.image_base64)
        image_data = base64.b64decode(encoded)
        np_arr = np.frombuffer(image_data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid image frame data")
            
        # Run face detection and recognition
        frame_enhanced = face_engine.enhance_image_quality(frame)
        face_locations, face_encodings = face_engine.detect_and_encode_face(frame_enhanced)
        
        results = []
        recognized_prns = []
        
        session_class_id = None
        if payload.session_id and payload.session_id > 0:
            session_class_id = db.get_session_class_id(payload.session_id)
        
        if face_encodings:
            recognitions = face_engine.recognize_faces(face_encodings)
            for i, (prn, confidence) in enumerate(recognitions):
                loc = face_locations[i]  # (top, right, bottom, left)
                if prn:
                    # Check class enrollment restriction
                    if session_class_id is not None:
                        student_class_id = db.get_student_class_id(prn)
                        if student_class_id != session_class_id:
                            results.append({
                                "box": {"top": loc[0], "right": loc[1], "bottom": loc[2], "left": loc[3]},
                                "name": "Unknown (Other Class)",
                                "prn": None,
                                "status": "unknown",
                                "confidence": round(confidence, 1)
                            })
                            continue
                    
                    student_name = db.get_student_name(prn)
                    name_display = student_name or prn
                    results.append({
                        "box": {"top": loc[0], "right": loc[1], "bottom": loc[2], "left": loc[3]},
                        "name": name_display,
                        "prn": prn,
                        "status": "success",
                        "confidence": round(confidence, 1)
                    })
                    recognized_prns.append(prn)
                else:
                    results.append({
                        "box": {"top": loc[0], "right": loc[1], "bottom": loc[2], "left": loc[3]},
                        "name": "Unknown",
                        "prn": None,
                        "status": "unknown",
                        "confidence": round(confidence, 1)
                    })
                    
        # Log detections to database if a session is active
        if recognized_prns and payload.session_id:
            db.log_session_detections(payload.session_id, recognized_prns)
            
        return {
            "success": True,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sessions/{session_id}/end")
async def end_session(session_id: int):
    try:
        success, message, results = db.end_session(session_id)
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        # After successfully ending session, trigger email warning notifications
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT class_id, subject_id FROM Sessions WHERE session_id = %s", (session_id,))
                    row = cur.fetchone()
            
            if row:
                class_id, subject_id = row
                # Get subject name
                with db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT subject_name FROM Subjects WHERE subject_id = %s", (subject_id,))
                        sub_row = cur.fetchone()
                        subject_name = sub_row[0] if sub_row else f"Subject #{subject_id}"
                
                # Fetch cumulative attendance for all students in class
                cumulative_list = db.get_class_cumulative_attendance(class_id, subject_id)
                
                # Send email warning to students with < 70% cumulative attendance
                from email_service import send_attendance_warning
                for item in cumulative_list:
                    pct = item["attendance_percentage"]
                    if pct < 70.0:
                        email = item["email"]
                        name = item["name"]
                        if email:
                            try:
                                send_attendance_warning(email, name, subject_name, pct)
                            except Exception as em:
                                print(f"✗ Failed triggering warning for {email}: {em}")
        except Exception as notify_err:
            print(f"✗ Failed warning emails processor: {notify_err}")

        return {
            "success": True,
            "detail": message,
            "session_id": session_id,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- ANALYTICS & CSV BULK IMPORT -----------------

import csv
import io

@app.get("/api/analytics/class-stats")
async def get_class_analytics():
    try:
        return db.get_class_attendance_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/trends")
async def get_attendance_trends():
    try:
        return db.get_attendance_trends()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/import/students")
async def import_students(file: UploadFile = File(...)):
    try:
        content = await file.read()
        decoded = content.decode('utf-8')
        csv_reader = csv.reader(io.StringIO(decoded))
        
        # Read header and validate
        header = next(csv_reader, None)
        if not header:
            raise HTTPException(status_code=400, detail="Empty CSV file")
        
        # Check standard headers (case-insensitive strip matching)
        header_normalized = [h.strip().lower() for h in header]
        expected_headers = ["prn", "class_id", "roll_no", "name", "email"]
        for eh in expected_headers:
            if eh not in header_normalized:
                raise HTTPException(status_code=400, detail=f"Missing required column in CSV: {eh}")
                
        prn_idx = header_normalized.index("prn")
        class_idx = header_normalized.index("class_id")
        roll_idx = header_normalized.index("roll_no")
        name_idx = header_normalized.index("name")
        email_idx = header_normalized.index("email")
        
        imported_count = 0
        errors = []
        
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                for line_no, row in enumerate(csv_reader, start=2):
                    if not row or len(row) < len(expected_headers):
                        continue
                    
                    try:
                        prn = row[prn_idx].strip()
                        class_id = int(row[class_idx].strip())
                        roll_no = int(row[roll_idx].strip())
                        name = row[name_idx].strip()
                        email = row[email_idx].strip()
                        
                        if not prn or not name:
                            raise ValueError("PRN and Name cannot be empty")
                            
                        # Insert student (without face embedding initially)
                        cur.execute("""
                            INSERT INTO Students (prn_no, class_id, roll_no, name, email)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (prn_no) DO UPDATE 
                            SET class_id = EXCLUDED.class_id, roll_no = EXCLUDED.roll_no, 
                                name = EXCLUDED.name, email = EXCLUDED.email
                        """, (prn, class_id, roll_no, name, email))
                        imported_count += 1
                    except Exception as e:
                        errors.append(f"Row {line_no}: {str(e)}")
                        
                conn.commit()
                
        detail_msg = f"Successfully registered/updated {imported_count} students."
        if errors:
            detail_msg += f" Had issues with {len(errors)} rows: " + "; ".join(errors[:3])
            if len(errors) > 3:
                detail_msg += f" and {len(errors)-3} more errors."
        
        return {"success": True, "detail": detail_msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/import/subjects")
async def import_subjects(file: UploadFile = File(...)):
    try:
        content = await file.read()
        decoded = content.decode('utf-8')
        csv_reader = csv.reader(io.StringIO(decoded))
        
        # Read header and validate
        header = next(csv_reader, None)
        if not header:
            raise HTTPException(status_code=400, detail="Empty CSV file")
            
        header_normalized = [h.strip().lower() for h in header]
        expected_headers = ["subject_code", "subject_name", "class_id", "semester"]
        for eh in expected_headers:
            if eh not in header_normalized:
                raise HTTPException(status_code=400, detail=f"Missing required column in CSV: {eh}")
                
        code_idx = header_normalized.index("subject_code")
        name_idx = header_normalized.index("subject_name")
        sem_idx = header_normalized.index("semester")
        
        imported_count = 0
        errors = []
        
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                for line_no, row in enumerate(csv_reader, start=2):
                    if not row or len(row) < 4:
                        continue
                        
                    try:
                        code = row[code_idx].strip()
                        name = row[name_idx].strip()
                        semester = int(row[sem_idx].strip())
                        
                        if not code or not name:
                            raise ValueError("Subject Code and Subject Name cannot be empty")
                            
                        cur.execute("""
                            INSERT INTO Subjects (subject_code, subject_name, semester)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (subject_code) DO UPDATE 
                            SET subject_name = EXCLUDED.subject_name, semester = EXCLUDED.semester
                        """, (code, name, semester))
                        imported_count += 1
                    except Exception as e:
                        errors.append(f"Row {line_no}: {str(e)}")
                        
                conn.commit()
                
        detail_msg = f"Successfully registered/updated {imported_count} subjects."
        if errors:
            detail_msg += f" Had issues with {len(errors)} rows: " + "; ".join(errors[:3])
            if len(errors) > 3:
                detail_msg += f" and {len(errors)-3} more errors."
                
        return {"success": True, "detail": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- OVERRIDE & CAMERA CRUD ENDPOINTS -----------------

class OverridePayload(BaseModel):
    session_id: int
    prn: str
    status: str

class CameraPayload(BaseModel):
    camera_name: str
    rtsp_url: Optional[str] = None
    direction: str

@app.post("/api/attendance/override")
async def override_attendance(payload: OverridePayload):
    if payload.status not in ('present', 'absent'):
        raise HTTPException(status_code=400, detail="Invalid status value. Must be 'present' or 'absent'")
        
    success, message = db.override_attendance(payload.session_id, payload.prn, payload.status)
    if not success:
        raise HTTPException(status_code=400, detail=message)
        
    # Check if student drops below 70% and trigger warning
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT class_id, subject_id FROM Sessions WHERE session_id = %s", (payload.session_id,))
                row = cur.fetchone()
        
        if row:
            class_id, subject_id = row
            # Get subject name
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT subject_name FROM Subjects WHERE subject_id = %s", (subject_id,))
                    sub_row = cur.fetchone()
                    subject_name = sub_row[0] if sub_row else f"Subject #{subject_id}"
            
            # Fetch cumulative attendance for this class
            cumulative_list = db.get_class_cumulative_attendance(class_id, subject_id)
            
            # Look up this student specifically
            student_data = next((item for item in cumulative_list if item["prn"] == payload.prn), None)
            if student_data:
                pct = student_data["attendance_percentage"]
                if pct < 70.0:
                    email = student_data["email"]
                    name = student_data["name"]
                    if email:
                        from email_service import send_attendance_warning
                        send_attendance_warning(email, name, subject_name, pct)
    except Exception as notify_err:
        print(f"✗ Failed override warning emails checker: {notify_err}")
        
    return {"success": True, "detail": message}

@app.get("/api/cameras")
async def get_cameras():
    try:
        return db.get_all_cameras()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cameras")
async def add_camera(payload: CameraPayload):
    if payload.direction not in ('IN', 'OUT', 'BOTH'):
        raise HTTPException(status_code=400, detail="Invalid camera direction. Must be 'IN', 'OUT', or 'BOTH'")
    if not payload.camera_name.strip():
        raise HTTPException(status_code=400, detail="Camera name cannot be empty")
        
    success, message, camera_id = db.add_camera(payload.camera_name.strip(), payload.rtsp_url, payload.direction)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "detail": message, "camera_id": camera_id}

@app.post("/api/cameras/{camera_id}/edit")
async def edit_camera(camera_id: int, payload: CameraPayload):
    if payload.direction not in ('IN', 'OUT', 'BOTH'):
        raise HTTPException(status_code=400, detail="Invalid camera direction. Must be 'IN', 'OUT', or 'BOTH'")
    if not payload.camera_name.strip():
        raise HTTPException(status_code=400, detail="Camera name cannot be empty")
        
    success, message = db.update_camera(camera_id, payload.camera_name.strip(), payload.rtsp_url, payload.direction)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "detail": message}

@app.delete("/api/cameras/{camera_id}")
async def delete_camera(camera_id: int):
    success, message = db.delete_camera(camera_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "detail": message}

# ----------------- CONVERSATIONAL AI CHAT ENDPOINT -----------------

class ChatPayload(BaseModel):
    message: str
    session_id: Optional[str] = None

@app.post("/api/chat")
async def chat_ai(payload: ChatPayload):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    session_id = payload.session_id or "default_session"
    
    try:
        from ai_agent import query_attendance_ai
        response = query_attendance_ai(payload.message.strip(), session_id)
        return {"success": True, "response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/clear")
async def chat_clear(payload: ChatPayload):
    session_id = payload.session_id or "default_session"
    try:
        from ai_agent import memory_manager
        memory_manager.clear_history(session_id)
        return {"success": True, "detail": "Conversation history cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount Web Dashboard files
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("run_api:app", host="127.0.0.1", port=8000, reload=True)
