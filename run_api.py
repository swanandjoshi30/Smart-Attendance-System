import os
from typing import List, Optional
import numpy as np
import base64
import cv2
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Depends, Header, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from attendance_config import DB_CONFIG, FACE_RECOGNITION_CONFIG
from database_manager import DatabaseManager
from face_recognition_engine import FaceRecognitionEngine
from email_sender import send_low_attendance_warning, send_session_attendance_notification

import camera_routes

app = FastAPI(
    title="Attendance System API V2",
    description="Backend API for Web-based Face Recognition Attendance System",
    version="2.0.0"
)

app.include_router(camera_routes.router, prefix="/api")

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

class ChatPayload(BaseModel):
    message: str

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
async def end_session(session_id: int, background_tasks: BackgroundTasks):
    try:
        # Get class_id and subject_id for this session before ending it to compute cumulative attendance
        class_id = None
        subject_id = None
        subject_name = "Subject"
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT class_id, subject_id FROM Sessions WHERE session_id = %s", (session_id,))
                    sess_row = cur.fetchone()
                    if sess_row:
                        class_id, subject_id = sess_row[0], sess_row[1]
                        
                        cur.execute("SELECT subject_name FROM Subjects WHERE subject_id = %s", (subject_id,))
                        sub_row = cur.fetchone()
                        if sub_row:
                            subject_name = sub_row[0]
        except Exception as err:
            print(f"[WARNING] Failed to fetch session details for email checks: {err}")

        success, message, results = db.end_session(session_id)
        if not success:
            raise HTTPException(status_code=400, detail=message)
            
        # Trigger email alerts for all students regarding this session's attendance
        if results:
            try:
                for student_res in results:
                    if student_res.get("email"):
                        background_tasks.add_task(
                            send_session_attendance_notification,
                            student_res["email"],
                            student_res["name"],
                            subject_name,
                            student_res["status"],
                            student_res["presence_percentage"]
                        )
            except Exception as email_err:
                print(f"[WARNING] Failed to queue session attendance emails: {email_err}")

        # Trigger low-attendance email warnings if session ended successfully
        if class_id is not None and subject_id is not None:
            try:
                cumulative_stats = db.get_cumulative_attendance_for_class_subject(class_id, subject_id)
                for stat in cumulative_stats:
                    if stat["average_presence"] < 70.0 and stat["email"]:
                        background_tasks.add_task(
                            send_low_attendance_warning,
                            stat["email"],
                            stat["name"],
                            subject_name,
                            stat["average_presence"]
                        )
            except Exception as email_err:
                print(f"[WARNING] Failed to queue attendance warning emails: {email_err}")

        return {
            "success": True,
            "detail": message,
            "session_id": session_id,
            "results": results
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/class-subject-stats")
async def get_analytics_stats(class_id: int, subject_id: int):
    try:
        stats = db.get_analytics_stats(class_id, subject_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/students/bulk-import")
async def bulk_import_students(file: UploadFile = File(...)):
    import csv
    import io
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")
        
    try:
        contents = await file.read()
        csv_text = contents.decode('utf-8')
        csv_file = io.StringIO(csv_text)
        
        reader = csv.DictReader(csv_file)
        
        required_headers = {'prn', 'name', 'roll_no', 'email', 'class_name'}
        headers = set([h.lower().strip() for h in reader.fieldnames]) if reader.fieldnames else set()
        
        header_mapping = {}
        for h in reader.fieldnames or []:
            header_mapping[h.lower().strip()] = h
            
        if not required_headers.issubset(headers):
            missing = required_headers - headers
            raise HTTPException(
                status_code=400, 
                detail=f"CSV is missing required headers: {', '.join(missing)}. Found headers: {', '.join(reader.fieldnames or [])}"
            )
            
        success_count = 0
        errors = []
        idx = 0
        
        for idx, row in enumerate(reader):
            try:
                prn = row[header_mapping['prn']].strip()
                name = row[header_mapping['name']].strip()
                roll_no = row[header_mapping['roll_no']].strip()
                email = row[header_mapping['email']].strip()
                class_name = row[header_mapping['class_name']].strip()
                
                if not prn or not name or not roll_no or not class_name:
                    errors.append(f"Row {idx+2}: Missing required values (prn, name, roll_no, or class_name).")
                    continue
                
                class_id = db.get_or_create_class_by_name(class_name)
                success, msg = db.register_student_no_encoding(prn, class_id, int(roll_no), name, email)
                if success:
                    success_count += 1
                else:
                    errors.append(f"Row {idx+2} (PRN: {prn}): {msg}")
            except Exception as e:
                errors.append(f"Row {idx+2}: {str(e)}")
                
        return {
            "success": True,
            "imported_count": success_count,
            "total_rows": idx + 1 if 'idx' in locals() else 0,
            "errors": errors
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process CSV file: {str(e)}")

# ----------------- AI CHAT INTERFACE -----------------

DB_SCHEMA_PROMPT = """You are an expert PostgreSQL database assistant.
Your task is to translate a user's natural language request into a single, valid, read-only SELECT SQL query.

Here is the database schema:
-- Classes table
Classes (
  class_id SERIAL PRIMARY KEY,
  class_name VARCHAR(100) UNIQUE NOT NULL
)

-- Subjects table
Subjects (
  subject_id SERIAL PRIMARY KEY,
  subject_name VARCHAR(200) UNIQUE NOT NULL,
  subject_code VARCHAR(100) UNIQUE,
  semester INTEGER NOT NULL
)

-- Students table
Students (
  prn_no VARCHAR(20) PRIMARY KEY,
  class_id INTEGER REFERENCES Classes(class_id),
  roll_no INTEGER NOT NULL,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(100) UNIQUE
)

-- Sessions table
Sessions (
  session_id SERIAL PRIMARY KEY,
  class_id INTEGER REFERENCES Classes(class_id),
  subject_id INTEGER REFERENCES Subjects(subject_id),
  start_time TIMESTAMP,
  end_time TIMESTAMP,
  status VARCHAR(20) -- 'active', 'completed'
)

-- AttendanceLog table (presence_percentage is float 0.0-100.0, status is 'present' or 'absent')
AttendanceLog (
  log_id SERIAL PRIMARY KEY,
  prn_no VARCHAR(20) REFERENCES Students(prn_no) ON DELETE CASCADE,
  subject_id INTEGER REFERENCES Subjects(subject_id) ON DELETE CASCADE,
  session_id INTEGER REFERENCES Sessions(session_id) ON DELETE CASCADE,
  timestamp TIMESTAMP,
  presence_percentage FLOAT DEFAULT 0.0,
  status VARCHAR(20) DEFAULT 'absent'
)

Important rules:
1. Return ONLY the raw SQL query. Do not wrap it in markdown code blocks or ```sql blocks. Do not write explanations.
2. The query MUST be a SELECT query. Do not include INSERT, UPDATE, DELETE, or other write operations.
3. Be careful to match text values case-insensitively using ILIKE where appropriate (e.g. for student name, class name, subject name).
4. Use CURRENT_DATE or appropriate date/time arithmetic if the user asks for 'today' or 'yesterday'.
5. Always join tables properly. For example, to find attendance of a student by name, join Students and AttendanceLog.
6. If the user request is just general greeting/conversation (like 'hello', 'who are you') or cannot be translated to a database query, return an empty string.
7. ALWAYS use DISTINCT when querying students based on attendance logs to avoid repeating names. For example, SELECT DISTINCT s.name, s.prn_no...
8. Always select comprehensive details like roll_no, name, prn_no, and email when showing students.

User Request: {user_query}
SQL Query:"""

RESPONSE_FORMAT_PROMPT = """You are the EduVision Smart Attendance AI Assistant, a highly professional, polite, and helpful assistant.
The user asked: "{user_query}"

To answer this, we executed the following SQL query:
{sql_query}

The query returned these results:
{query_results_json}

Please write a highly professional, structured, and clear response in natural language answering the user's question based on these results.
- Always use standard Markdown tables if there are lists of students or tables of data to neatly show proper details.
- Keep the response accurate and matching the database results precisely.
- Do not mention the internal SQL query or technical database terms unless the user explicitly asked for them.
- Be extremely polite and professional (e.g., "Here are the details you requested...", "I found the following information...").
"""

def make_llm_request(prompt: str) -> str:
    """Send a request to Gemini, OpenAI, or Groq, depending on which key is configured."""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    
    if gemini_key == "your_gemini_api_key" or not gemini_key:
        gemini_key = ""
    if openai_key == "your_openai_api_key" or not openai_key:
        openai_key = ""
    if groq_key == "your_groq_api_key" or not groq_key:
        groq_key = ""

    import urllib.request
    import json

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    if gemini_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": user_agent
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip()

    elif openai_key:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_key}",
            "User-Agent": user_agent
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["choices"][0]["message"]["content"]
            return text.strip()

    elif groq_key:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {groq_key}",
            "User-Agent": user_agent
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["choices"][0]["message"]["content"]
            return text.strip()
            
    else:
        raise ValueError("No API key configured for Gemini, OpenAI, or Groq.")

@app.post("/api/chat")
async def chat_query(payload: ChatPayload):
    user_msg = payload.message
    
    # Try using the LLM. If it fails (e.g. no API key), use fallback logic.
    try:
        # Step 1: SQL generation
        prompt_sql = DB_SCHEMA_PROMPT.format(user_query=user_msg)
        generated_sql = make_llm_request(prompt_sql)
        
        # Clean any markdown wrapping (e.g. ```sql ... ```) if the LLM output was noisy
        if generated_sql.startswith("```"):
            lines = generated_sql.splitlines()
            if len(lines) > 2:
                # Remove starting and ending markdown ticks
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                generated_sql = "\n".join(lines).strip()
        
        # Step 2: Execute query if not empty
        sql_to_run = generated_sql.strip()
        results = []
        
        if sql_to_run:
            try:
                results = db.execute_read_query(sql_to_run)
            except Exception as db_err:
                print(f"[WARNING] SQL generated failed to execute: {db_err}")
                return {
                    "success": False,
                    "response": f"I generated this SQL query but it failed to run against the database: `{sql_to_run}`. Error: {str(db_err)}",
                    "sql": sql_to_run,
                    "results": []
                }
                
        # Step 3: Format response
        import json
        prompt_resp = RESPONSE_FORMAT_PROMPT.format(
            user_query=user_msg,
            sql_query=sql_to_run or "(No database query needed)",
            query_results_json=json.dumps(results, indent=2)
        )
        ai_response = make_llm_request(prompt_resp)
        
        return {
            "success": True,
            "response": ai_response,
            "sql": sql_to_run,
            "results": results
        }
        
    except Exception as e:
        # Fallback Mode Logic
        print(f"[INFO] Chat fallback activated: {e}")
        
        msg_lower = user_msg.lower()
        fallback_sql = ""
        context_msg = ""
        
        if "absent" in msg_lower:
            fallback_sql = "SELECT DISTINCT s.roll_no, s.name, s.prn_no, s.email FROM Students s JOIN AttendanceLog al ON s.prn_no = al.prn_no WHERE DATE(al.timestamp) = CURRENT_DATE AND al.status = 'absent' ORDER BY s.roll_no;"
            context_msg = "students marked absent today"
        elif "present" in msg_lower:
            fallback_sql = "SELECT DISTINCT s.roll_no, s.name, s.prn_no, s.email FROM Students s JOIN AttendanceLog al ON s.prn_no = al.prn_no WHERE DATE(al.timestamp) = CURRENT_DATE AND al.status = 'present' ORDER BY s.roll_no;"
            context_msg = "students marked present today"
        elif "all students" in msg_lower or "list students" in msg_lower or "registered" in msg_lower:
            fallback_sql = "SELECT roll_no, name, prn_no, email FROM Students ORDER BY roll_no;"
            context_msg = "all registered students"
        elif "below 70" in msg_lower or "low attendance" in msg_lower:
            fallback_sql = "SELECT s.roll_no, s.name, s.prn_no, ROUND(CAST(AVG(al.presence_percentage) AS numeric), 2) as average_attendance FROM Students s JOIN AttendanceLog al ON s.prn_no = al.prn_no GROUP BY s.roll_no, s.name, s.prn_no HAVING AVG(al.presence_percentage) < 70.0 ORDER BY s.roll_no;"
            context_msg = "students with attendance below 70%"
        else:
            fallback_sql = ""
            
        fallback_results = []
        fallback_response = ""
        
        if fallback_sql:
            try:
                fallback_results = db.execute_read_query(fallback_sql)
            except Exception as db_err:
                print(f"[WARNING] Fallback SQL failed to execute: {db_err}")
                
            if fallback_results:
                keys = fallback_results[0].keys()
                header = "| " + " | ".join([k.replace("_", " ").title() for k in keys]) + " |"
                separator = "| " + " | ".join(["---" for _ in keys]) + " |"
                rows = []
                for row in fallback_results:
                    rows.append("| " + " | ".join([str(val) for val in row.values()]) + " |")
                table_str = "\\n".join([header, separator] + rows)
                fallback_response = f"I am operating in local mode. Here are the details for {context_msg}:\\n\\n{table_str}"
            else:
                fallback_response = f"I am operating in local mode. I couldn't find any records for {context_msg}."
        else:
            fallback_sql = "(None)"
            fallback_response = f"*(Fallback Mode)*: I received your query: '{user_msg}'. To connect this to live database data dynamically, please configure an API key in your `.env` file. Currently, I can answer standard queries like 'show all students', 'who is absent', 'who is present', or 'low attendance'."
            
        return {
            "success": True,
            "response": fallback_response,
            "sql": fallback_sql,
            "results": fallback_results
        }

# Mount Web Dashboard files
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("run_api:app", host="0.0.0.0", port=8000, reload=True)