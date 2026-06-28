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
import threading

class DatabaseManager:
    def __init__(self, config):
        self.config = config
        self.schema_path = Path(__file__).with_name('tables')
        self._cache_lock = threading.Lock()
        self._student_name_cache = {}
        self._student_class_cache = {}
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
                    self._clear_student_cache(prn)
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
                    self._clear_student_cache(prn)
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
                    self._clear_student_cache(prn)
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

    def _clear_student_cache(self, prn):
        """Invalidate cache entries for a student"""
        with self._cache_lock:
            self._student_name_cache.pop(prn, None)
            self._student_class_cache.pop(prn, None)

    def get_student_name(self, prn_no):
        """Get student name by PRN"""
        with self._cache_lock:
            if prn_no in self._student_name_cache:
                return self._student_name_cache[prn_no]
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM Students WHERE prn_no = %s", (prn_no,))
                result = cur.fetchone()
                name = result[0] if result else None
                if name is not None:
                    with self._cache_lock:
                        self._student_name_cache[prn_no] = name
                return name

    def get_student_class_id(self, prn_no):
        """Get student class ID by PRN"""
        with self._cache_lock:
            if prn_no in self._student_class_cache:
                return self._student_class_cache[prn_no]
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT class_id FROM Students WHERE prn_no = %s", (prn_no,))
                result = cur.fetchone()
                class_id = result[0] if result else None
                if class_id is not None:
                    with self._cache_lock:
                        self._student_class_cache[prn_no] = class_id
                return class_id

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

    def get_cumulative_attendance_for_class_subject(self, class_id, subject_id):
        """Get cumulative attendance for all students in a class for a specific subject"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Count total sessions for this class and subject in Sessions table (completed status)
                cur.execute("""
                    SELECT COUNT(*) FROM Sessions 
                    WHERE class_id = %s AND subject_id = %s AND status = 'completed'
                """, (class_id, subject_id))
                total_sessions = cur.fetchone()[0]

                # Fetch all students in the class
                cur.execute("""
                    SELECT prn_no, roll_no, name, email 
                    FROM Students 
                    WHERE class_id = %s 
                    ORDER BY roll_no
                """, (class_id,))
                students = cur.fetchall()

                # For each student, get their logs for this subject
                results = []
                for prn, roll_no, name, email in students:
                    cur.execute("""
                        SELECT presence_percentage, status 
                        FROM AttendanceLog 
                        WHERE prn_no = %s AND subject_id = %s
                    """, (prn, subject_id))
                    logs = cur.fetchall()
                    
                    sessions_attended = sum(1 for log in logs if log[1] == 'present')
                    
                    if total_sessions > 0:
                        # average presence is the sum of presence_percentages divided by total_sessions
                        avg_presence = sum(log[0] for log in logs) / total_sessions
                    else:
                        avg_presence = 0.0

                    results.append({
                        "prn": prn,
                        "roll_no": roll_no,
                        "name": name,
                        "email": email,
                        "total_sessions": total_sessions,
                        "sessions_attended": sessions_attended,
                        "average_presence": avg_presence
                    })
                return results

    def get_analytics_stats(self, class_id, subject_id):
        """Get database stats for attendance analytics dashboard"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Subject averages for the selected class
                cur.execute("""
                    SELECT s.subject_id, s.subject_name, COALESCE(AVG(al.presence_percentage), 0.0) as avg_presence
                    FROM Subjects s
                    CROSS JOIN (SELECT class_id FROM Classes WHERE class_id = %s) c
                    LEFT JOIN Students st ON st.class_id = c.class_id
                    LEFT JOIN AttendanceLog al ON al.prn_no = st.prn_no AND al.subject_id = s.subject_id
                    GROUP BY s.subject_id, s.subject_name
                    ORDER BY s.subject_name
                """, (class_id,))
                
                subject_rows = cur.fetchall()
                subject_averages = [
                    {"subject_id": r[0], "subject_name": r[1], "avg_attendance": float(r[2])}
                    for r in subject_rows
                ]

                # 2. Session-by-session trends for this class and subject (last 10 completed sessions)
                cur.execute("""
                    SELECT s.session_id, s.start_time, COALESCE(AVG(al.presence_percentage), 0.0) as avg_presence
                    FROM Sessions s
                    LEFT JOIN AttendanceLog al ON al.session_id = s.session_id
                    WHERE s.class_id = %s AND s.subject_id = %s AND s.status = 'completed'
                    GROUP BY s.session_id, s.start_time
                    ORDER BY s.start_time ASC
                    LIMIT 10
                """, (class_id, subject_id))
                session_rows = cur.fetchall()
                session_trends = [
                    {"session_id": r[0], "start_time": str(r[1]), "avg_attendance": float(r[2])}
                    for r in session_rows
                ]

                return {
                    "subject_averages": subject_averages,
                    "session_trends": session_trends
                }

    def get_or_create_class_by_name(self, class_name):
        """Fetch class_id for a class_name, creating it if it doesn't exist"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT class_id FROM Classes WHERE class_name = %s", (class_name,))
                row = cur.fetchone()
                if row:
                    return row[0]
                
                cur.execute("INSERT INTO Classes (class_name) VALUES (%s) RETURNING class_id", (class_name,))
                class_id = cur.fetchone()[0]
                conn.commit()
                return class_id

    def register_student_no_encoding(self, prn, class_id, roll_no, name, email):
        """Register a student without face encoding (useful for bulk import)"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO Students (prn_no, class_id, roll_no, name, email) 
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (prn_no) DO UPDATE 
                        SET class_id = EXCLUDED.class_id, roll_no = EXCLUDED.roll_no, name = EXCLUDED.name, email = EXCLUDED.email
                        """,
                        (prn, class_id, int(roll_no), name, email)
                    )
                    conn.commit()
                    self._clear_student_cache(prn)
                    return True, "Student registered successfully"
                except psycopg2.IntegrityError as e:
                    conn.rollback()
                    if "students_email_key" in str(e):
                        return False, f"Email '{email}' already exists"
                    elif "unique_roll_in_class" in str(e):
                        return False, f"Roll number '{roll_no}' already exists in this class"
                    else:
                        return False, str(e)
                except Exception as e:
                    conn.rollback()
                    return False, str(e)

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
        """Ends the session, computes attendance percentages using interval merging, logs final records, and returns results"""
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

                # Fetch all students in this class
                cur.execute(
                    "SELECT prn_no, name, roll_no, email FROM Students WHERE class_id = %s ORDER BY roll_no",
                    (class_id,)
                )
                students = cur.fetchall()

                results = []
                session_date = start_time.date()

                for prn, name, roll_no, email in students:
                    # Use same connection to avoid pool exhaustion
                    presence_percentage, status = self._calculate_presence_with_conn(
                        conn, class_id, prn, session_date, start_time, end_time, threshold=75.0
                    )

                    # Log the final attendance status to AttendanceLog
                    cur.execute(
                        "INSERT INTO AttendanceLog (prn_no, subject_id, session_id, timestamp, presence_percentage, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        (prn, subject_id, session_id, end_time, presence_percentage, status)
                    )

                    results.append({
                        "prn": prn,
                        "name": name,
                        "roll_no": roll_no,
                        "email": email,
                        "presence_percentage": presence_percentage,
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

    def execute_read_query(self, query, params=None):
        """Execute a read-only SELECT query and return list of dicts (rows)"""
        cleaned_query = query.strip().upper()
        if not cleaned_query.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed for safety reasons.")
        
        # Basic SQL injection / destructive command safety check
        destructive_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"]
        for kw in destructive_keywords:
            if f" {kw} " in f" {cleaned_query} " or cleaned_query.endswith(kw) or cleaned_query.startswith(kw):
                raise ValueError(f"Unauthorized destructive keyword '{kw}' detected in query.")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or ())
                if cur.description:
                    colnames = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    return [dict(zip(colnames, row)) for row in rows]
                return []

    def set_camera_urls(self, class_id, in_url, out_url):
        """Set the in and out camera URLs for a classroom."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE Classes SET in_camera_url = %s, out_camera_url = %s WHERE class_id = %s",
                    (in_url, out_url, class_id)
                )
                conn.commit()

    def record_entry(self, class_id, student_id, entry_time, session_date):
        """Record entry time for a student (in-camera). Skips if an open entry already exists."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Guard: only insert if no open entry exists for this student today
                cur.execute(
                    "SELECT record_id FROM AttendanceInOut WHERE class_id = %s AND student_id = %s AND session_date = %s AND exit_time IS NULL LIMIT 1",
                    (class_id, student_id, session_date)
                )
                existing = cur.fetchone()
                if existing:
                    # Already has an open entry — student is currently inside, do nothing
                    return existing[0]  # return existing record_id

                cur.execute(
                    "INSERT INTO AttendanceInOut (class_id, student_id, entry_time, session_date) VALUES (%s, %s, %s, %s) RETURNING record_id",
                    (class_id, student_id, entry_time, session_date)
                )
                record_id = cur.fetchone()[0]
                conn.commit()
                return record_id


    def record_exit(self, record_id, exit_time):
        """Record exit time for a student (out-camera)."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE AttendanceInOut SET exit_time = %s WHERE record_id = %s",
                    (exit_time, record_id)
                )
                conn.commit()

    def merge_intervals(self, intervals, max_gap_seconds=300):
        """Merge overlapping intervals or intervals separated by less than max_gap_seconds."""
        if not intervals:
            return []

        # Sort intervals by start time
        intervals.sort(key=lambda x: x[0])

        merged = [intervals[0]]
        for current in intervals[1:]:
            last = merged[-1]
            last_start, last_end = last
            current_start, current_end = current

            # If gap between end of last and start of current is within tolerance, merge
            gap = (current_start - last_end).total_seconds()
            if gap <= max_gap_seconds:
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                merged.append(current)

        return merged

    def _calculate_presence_with_conn(self, conn, class_id, student_id, session_date, session_start, session_end, threshold=75.0):
        """Calculate presence using an already-open DB connection (used inside transactions)."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT entry_time, exit_time FROM AttendanceInOut WHERE class_id = %s AND student_id = %s AND session_date = %s",
                (class_id, student_id, session_date)
            )
            records = cur.fetchall()

        if not records:
            return 0.0, "absent"

        intervals = []
        for entry, exit_t in records:
            if not exit_t:
                exit_t = session_end
            intervals.append((entry, exit_t))

        merged_intervals = self.merge_intervals(intervals)

        total_present_seconds = 0
        for start, end in merged_intervals:
            actual_start = max(start, session_start)
            actual_end = min(end, session_end)
            if actual_end > actual_start:
                total_present_seconds += (actual_end - actual_start).total_seconds()

        session_duration = (session_end - session_start).total_seconds()
        if session_duration <= 0:
            return 0.0, "absent"

        presence_percentage = min(100.0, (total_present_seconds / session_duration) * 100.0)
        status = "present" if presence_percentage >= threshold else "absent"
        return round(presence_percentage, 1), status

    def calculate_presence(self, class_id, student_id, session_date, session_start, session_end, threshold=75.0):
        """Calculate presence percentage based on in/out timestamps and short-break merging."""
        with self.get_connection() as conn:
            return self._calculate_presence_with_conn(conn, class_id, student_id, session_date, session_start, session_end, threshold)

    def get_latest_open_entry(self, class_id, student_id):
        """Return the record_id of the most recent AttendanceInOut entry for the student where exit_time is NULL."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT record_id FROM AttendanceInOut WHERE class_id = %s AND student_id = %s AND exit_time IS NULL ORDER BY entry_time DESC LIMIT 1",
                    (class_id, student_id)
                )
                row = cur.fetchone()
                return row[0] if row else None

    def close(self):
        """Close all connections in the pool"""
        self.connection_pool.closeall()



