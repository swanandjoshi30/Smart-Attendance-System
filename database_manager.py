# database_manager.py
"""
Handles all database operations with connection pooling
"""

import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from pathlib import Path
import json
import numpy as np

class DatabaseManager:
    def __init__(self, config):
        self.config = config
        self.schema_path = Path(__file__).with_name('tables')
        try:
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 10,  # min and max connections
                host=config['host'],
                database=config['database'],
                user=config['user'],
                password=config['password'],
                port=config.get('port', 5432)
            )
            print("✓ Database connection pool created successfully")
            self.initialize_schema()
        except Exception as e:
            print(f"✗ Failed to create connection pool: {e}")
            raise

    def initialize_schema(self):
        """Create the prototype schema and seed data when needed."""
        if not self.schema_path.exists():
            print(f"⚠ Schema file not found: {self.schema_path}")
            return

        schema_sql = self.schema_path.read_text(encoding='utf-8')

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()

        print("✓ Prototype database schema verified")

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = self.connection_pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.connection_pool.putconn(conn)

    def get_all_classes(self):
        """Fetch all classes from database"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT class_id, class_name FROM Classes ORDER BY class_name")
                return {name: cid for cid, name in cur.fetchall()}

    def get_all_subjects(self):
        """Fetch all subjects from database"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT subject_id, subject_name FROM Subjects ORDER BY subject_name")
                return {name: sid for sid, name in cur.fetchall()}

    def get_all_subjects_detailed(self):
        """Fetch all subjects from database with all fields"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT subject_id, subject_name, subject_code, semester FROM Subjects ORDER BY subject_name")
                return [
                    {"id": row[0], "name": row[1], "code": row[2], "semester": row[3]}
                    for row in cur.fetchall()
                ]

    def register_student(self, prn, class_id, roll_no, name, email, face_encoding):
        """Register a new student with face encoding"""
        encoding_json = json.dumps(face_encoding.tolist())
        
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    # Insert student
                    cur.execute(
                        "INSERT INTO Students (prn_no, class_id, roll_no, name, email) VALUES (%s, %s, %s, %s, %s)",
                        (prn, class_id, int(roll_no), name, email)
                    )
                    # Insert face encoding
                    cur.execute(
                        "INSERT INTO FaceEncodings (prn_no, encoding_data) VALUES (%s, %s)",
                        (prn, encoding_json)
                    )
                    conn.commit()
                    return True, "Student registered successfully"
                except psycopg2.IntegrityError as e:
                    conn.rollback()
                    if "students_pkey" in str(e):
                        return False, f"PRN '{prn}' already exists"
                    elif "students_email_key" in str(e):
                        return False, f"Email '{email}' already exists"
                    elif "unique_roll_in_class" in str(e):
                        return False, f"Roll number '{roll_no}' already exists in this class"
                    else:
                        return False, str(e)

    def update_student(self, prn, class_id, roll_no, name, email, face_encoding=None):
        """Update student information in the database"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    # Update details
                    cur.execute("""
                        UPDATE Students 
                        SET class_id = %s, roll_no = %s, name = %s, email = %s
                        WHERE prn_no = %s
                    """, (class_id, int(roll_no), name, email, prn))
                    
                    # Update face encoding if provided
                    if face_encoding is not None:
                        encoding_json = json.dumps(face_encoding.tolist())
                        # Delete old encoding and insert new one
                        cur.execute("DELETE FROM FaceEncodings WHERE prn_no = %s", (prn,))
                        cur.execute("""
                            INSERT INTO FaceEncodings (prn_no, encoding_data)
                            VALUES (%s, %s)
                        """, (prn, encoding_json))
                    
                    conn.commit()
                    return True, "Student details updated successfully"
                except psycopg2.IntegrityError as e:
                    conn.rollback()
                    if "unique_roll_in_class" in str(e):
                        return False, f"Roll number '{roll_no}' already exists in this class"
                    elif "students_email_key" in str(e):
                        return False, f"Email '{email}' already exists"
                    else:
                        return False, str(e)
                except Exception as e:
                    conn.rollback()
                    return False, str(e)

    def delete_student(self, prn):
        """Delete a student and their face encoding from the database"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("DELETE FROM Students WHERE prn_no = %s", (prn,))
                    conn.commit()
                    return True, "Student deleted successfully"
                except Exception as e:
                    conn.rollback()
                    return False, str(e)

    def get_all_face_encodings(self):
        """Fetch all face encodings from database (JSONB format for compatibility)"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT prn_no, encoding_data FROM FaceEncodings ORDER BY prn_no")
                results = cur.fetchall()
                encodings = []
                prns = []
                for prn_no, encoding_data in results:
                    if encoding_data:
                        encodings.append(np.array(encoding_data, dtype=np.float32))
                        prns.append(prn_no)
                return encodings, prns

    def log_attendance(self, prn_no, subject_id):
        """Log attendance for a student"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "INSERT INTO AttendanceLog (prn_no, subject_id) VALUES (%s, %s)",
                        (prn_no, subject_id)
                    )
                    conn.commit()
                    return True
                except Exception as e:
                    conn.rollback()
                    print(f"Error logging attendance: {e}")
                    return False

    def get_student_name(self, prn_no):
        """Get student name by PRN"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM Students WHERE prn_no = %s", (prn_no,))
                result = cur.fetchone()
                return result[0] if result else None

    def get_student_class_id(self, prn_no):
        """Get student class ID by PRN"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT class_id FROM Students WHERE prn_no = %s", (prn_no,))
                result = cur.fetchone()
                return result[0] if result else None

    def get_session_class_id(self, session_id):
        """Get session class ID by session ID"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT class_id FROM Sessions WHERE session_id = %s", (session_id,))
                result = cur.fetchone()
                return result[0] if result else None
    def get_all_students(self):
        """Fetch all students"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT prn_no, class_id, roll_no, name, email
                    FROM Students
                    ORDER BY roll_no
                """)
                rows = cur.fetchall()

                students = []
                for row in rows:
                    students.append({
                        "prn": row[0],
                        "class_id": row[1],
                        "roll_no": row[2],
                        "name": row[3],
                        "email": row[4]
                    })

                return students

    def get_attendance_logs(self):
        """Fetch attendance logs"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT log_id, prn_no, subject_id, session_id, timestamp, presence_percentage, status
                    FROM AttendanceLog
                    ORDER BY timestamp DESC
                """)

                rows = cur.fetchall()

                logs = []
                for row in rows:
                    logs.append({
                        "log_id": row[0],
                        "prn": row[1],
                        "subject_id": row[2],
                        "session_id": row[3],
                        "timestamp": str(row[4]),
                        "presence_percentage": row[5] if row[5] is not None else 0.0,
                        "status": row[6]
                    })

                return logs

    def get_dashboard_stats(self):
        """Get simple dashboard stats"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM Students")
                total_students = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(DISTINCT prn_no)
                    FROM AttendanceLog
                    WHERE DATE(timestamp) = CURRENT_DATE
                """)
                present_today = cur.fetchone()[0]

            absent_today = total_students - present_today

            return {
                "total_students": total_students,
                "present_today": present_today,
                "absent_today": absent_today
            }
    
    def start_session(self, class_id, subject_id):
        """Start a new classroom session. Sets status='active'. Ends any existing active session."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Complete any existing active sessions
                cur.execute(
                    "UPDATE Sessions SET status = 'completed', end_time = CURRENT_TIMESTAMP WHERE status = 'active'"
                )
                # Create a new active session
                cur.execute(
                    "INSERT INTO Sessions (class_id, subject_id, status) VALUES (%s, %s, 'active') RETURNING session_id",
                    (class_id, subject_id)
                )
                session_id = cur.fetchone()[0]
                conn.commit()
                return session_id

    def get_active_session(self):
        """Retrieve the currently active session details if any"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT s.session_id, s.class_id, s.subject_id, s.start_time, c.class_name, sub.subject_name
                    FROM Sessions s
                    JOIN Classes c ON s.class_id = c.class_id
                    JOIN Subjects sub ON s.subject_id = sub.subject_id
                    WHERE s.status = 'active'
                    ORDER BY s.start_time DESC LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    return {
                        "session_id": row[0],
                        "class_id": row[1],
                        "subject_id": row[2],
                        "start_time": row[3],
                        "class_name": row[4],
                        "subject_name": row[5]
                    }
                return None

    def log_session_detections(self, session_id, prn_list):
        """Log detected students' PRNs for a specific session"""
        if not prn_list:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for prn in prn_list:
                    cur.execute(
                        "INSERT INTO SessionDetections (session_id, prn_no) VALUES (%s, %s)",
                        (session_id, prn)
                    )
                conn.commit()

    def end_session(self, session_id):
        """Ends the session, computes attendance percentages using time binning, logs final records, and returns results"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Update session end_time and status
                cur.execute(
                    "UPDATE Sessions SET status = 'completed', end_time = CURRENT_TIMESTAMP WHERE session_id = %s RETURNING class_id, subject_id, start_time, end_time",
                    (session_id,)
                )
                session_info = cur.fetchone()
                if not session_info:
                    return False, "Session not found", []
                
                class_id, subject_id, start_time, end_time = session_info
                
                import math
                # 2. Get session duration in seconds
                duration_seconds = (end_time - start_time).total_seconds()
                if duration_seconds <= 0:
                    duration_seconds = 1
                
                # Total 1-minute bins
                total_bins = float(max(1, math.ceil(duration_seconds / 60.0)))
                
                # 3. Fetch all students in this class
                cur.execute(
                    "SELECT prn_no, name, roll_no FROM Students WHERE class_id = %s ORDER BY roll_no",
                    (class_id,)
                )
                students = cur.fetchall()
                
                # 4. Fetch all detections for this session
                cur.execute(
                    "SELECT prn_no, timestamp FROM SessionDetections WHERE session_id = %s ORDER BY timestamp",
                    (session_id,)
                )
                detections = cur.fetchall()
                
                # Map student PRN to their list of detection timestamps
                student_detections = {student[0]: [] for student in students}
                for prn, timestamp in detections:
                    if prn in student_detections:
                        student_detections[prn].append(timestamp)
                
                results = []
                # 5. Calculate presence percentage for each student
                for prn, name, roll_no in students:
                    times = student_detections[prn]
                    if not times:
                        presence_percentage = 0.0
                    else:
                        # Find unique 1-minute bins in which the student was detected
                        bins_seen = set()
                        for t in times:
                            delta_seconds = (t - start_time).total_seconds()
                            bin_idx = int(delta_seconds // 60)
                            bins_seen.add(bin_idx)
                        
                        # Number of bins where student was present
                        seen_bins_count = len(bins_seen)
                        presence_percentage = float((seen_bins_count / total_bins) * 100.0)
                        presence_percentage = float(min(100.0, presence_percentage))
                    
                    status = "present" if presence_percentage >= 70.0 else "absent"
                    
                    # 6. Log the final attendance status to AttendanceLog
                    cur.execute(
                        "INSERT INTO AttendanceLog (prn_no, subject_id, session_id, timestamp, presence_percentage, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        (prn, subject_id, session_id, end_time, presence_percentage, status)
                    )
                    
                    results.append({
                        "prn": prn,
                        "name": name,
                        "roll_no": roll_no,
                        "presence_percentage": round(presence_percentage, 1),
                        "status": status
                    })
                
                conn.commit()
                return True, "Session ended and attendance processed successfully", results

    def validate_user(self, username, password):
        """Validate user credentials and return user details if successful"""
        import hashlib
        pass_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
        print(f"[DEBUG] validate_user input: username='{username}', password='{password}'")
        print(f"[DEBUG] generated pass_hash='{pass_hash}'")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username, password_hash FROM Users")
                all_users = cur.fetchall()
                print(f"[DEBUG] all users in DB: {all_users}")
                
                cur.execute(
                    "SELECT user_id, username, role, name FROM Users WHERE username = %s AND password_hash = %s",
                    (username, pass_hash)
                )
                user = cur.fetchone()
                print(f"[DEBUG] matched user row: {user}")
                if user:
                    return {
                        "user_id": user[0],
                        "username": user[1],
                        "role": user[2],
                        "name": user[3]
                    }
        return None

    def close(self):
        """Close all connections in the pool"""
        self.connection_pool.closeall()

