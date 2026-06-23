# classroom_attendance.py
"""
Classroom Session-Based Attendance Kiosk
Tracks student presence over a lecture duration and marks attendance based on an 80% threshold.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import cv2
import threading
import time
from datetime import datetime
import numpy as np

from email_sender import send_session_attendance_notification

class ClassroomAttendanceApp:
    def __init__(self, root, db_manager, face_engine, camera_manager):
        self.root = root
        self.db = db_manager
        self.face_engine = face_engine
        self.camera_manager = camera_manager
        
        self.root.title("Classroom Session Attendance - Face Recognition")
        self.root.geometry("1400x850")
        self.root.configure(bg='#f5f7fb')
        
        # Session State Variables
        self.session_id = None
        self.is_session_running = False
        self.session_start_time = None
        self.video_thread = None
        self.is_camera_running = False
        
        # Detection Buffering (resilient to quick look-aways)
        self.detected_buffer = set()
        self.buffer_lock = threading.Lock()
        self.logging_thread = None
        
        # UI Selection Variables
        self.classes = {}
        self.subjects = {}
        self.selected_class = tk.StringVar()
        self.selected_subject = tk.StringVar()
        self.selected_camera = tk.StringVar()
        
        # Statistics
        self.stats_total_students = tk.StringVar(value="0")
        self.stats_active_detected = tk.StringVar(value="0")
        self.stats_elapsed_time = tk.StringVar(value="00:00:00")
        
        self.setup_ui()
        self.load_data()
        
    def setup_ui(self):
        """Create the professional session attendance user interface"""
        # Top Header Card
        header_frame = tk.Frame(self.root, bg='#1e3a8a', height=80)
        header_frame.pack(fill='x', side='top')
        header_frame.pack_propagate(False)
        
        title_label = tk.Label(
            header_frame, 
            text="🎓 Classroom Attendance Session Manager", 
            font=("Arial", 22, "bold"),
            bg='#1e3a8a', 
            fg='white'
        )
        title_label.pack(side='left', padx=30, pady=20)
        
        self.datetime_label = tk.Label(
            header_frame,
            text="",
            font=("Arial", 12, "bold"),
            bg='#1e3a8a',
            fg='#93c5fd'
        )
        self.datetime_label.pack(side='right', padx=30)
        self.update_datetime()
        
        # Main Work Area
        main_container = tk.Frame(self.root, bg='#f5f7fb')
        main_container.pack(fill='both', expand=True, padx=25, pady=25)
        
        # Left Panel (Controls & Camera Feed)
        left_panel = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        left_panel.pack(side='left', fill='both', expand=True, padx=(0, 15))
        
        # Control Header
        control_header = tk.Frame(left_panel, bg='#f8fafc', height=50)
        control_header.pack(fill='x')
        tk.Label(
            control_header, 
            text="🎥 Class Session Controls & Camera Feed", 
            font=("Arial", 13, "bold"),
            bg='#f8fafc', 
            fg='#1e293b'
        ).pack(side='left', padx=15, pady=12)
        
        # Configuration Fields
        config_frame = tk.Frame(left_panel, bg='white', padx=20, pady=15)
        config_frame.pack(fill='x')
        
        # Row 1: Class & Subject
        tk.Label(config_frame, text="Class:", font=("Arial", 10, "bold"), bg='white').grid(row=0, column=0, sticky='w', pady=5)
        self.class_dropdown = ttk.Combobox(config_frame, textvariable=self.selected_class, state='readonly', font=("Arial", 10), width=25)
        self.class_dropdown.grid(row=0, column=1, padx=(5, 20), pady=5, sticky='w')
        
        tk.Label(config_frame, text="Subject:", font=("Arial", 10, "bold"), bg='white').grid(row=0, column=2, sticky='w', pady=5)
        self.subject_dropdown = ttk.Combobox(config_frame, textvariable=self.selected_subject, state='readonly', font=("Arial", 10), width=25)
        self.subject_dropdown.grid(row=0, column=3, padx=5, pady=5, sticky='w')
        
        # Row 2: Camera selection & Status
        tk.Label(config_frame, text="Camera:", font=("Arial", 10, "bold"), bg='white').grid(row=1, column=0, sticky='w', pady=5)
        self.camera_dropdown = ttk.Combobox(config_frame, textvariable=self.selected_camera, state='readonly', font=("Arial", 10), width=25)
        self.camera_dropdown.grid(row=1, column=1, padx=(5, 20), pady=5, sticky='w')
        
        # Bottom Buttons inside Left Panel
        btn_frame = tk.Frame(left_panel, bg='white', pady=15)
        btn_frame.pack(side='bottom', fill='x', padx=20)
        
        # Live Video Box
        self.video_label = tk.Label(left_panel, bg='#0f172a')
        self.video_label.pack(fill='both', expand=True, padx=20, pady=10)
        
        self.session_btn = tk.Button(
            btn_frame,
            text="▶ Start Class Session",
            command=self.toggle_session,
            bg='#10b981',
            fg='white',
            font=("Arial", 13, "bold"),
            relief='flat',
            pady=12,
            width=25,
            cursor='hand2'
        )
        self.session_btn.pack(side='left', padx=(0, 10))
        
        self.status_pill = tk.Label(
            btn_frame,
            text="STATUS: INACTIVE",
            font=("Arial", 10, "bold"),
            bg='#e2e8f0',
            fg='#475569',
            padx=15,
            pady=12
        )
        self.status_pill.pack(side='left')
        
        # Right Panel (Live Statistics & Detected Roster)
        right_panel = tk.Frame(main_container, bg='white', relief='solid', bd=1, width=420)
        right_panel.pack(side='right', fill='y')
        right_panel.pack_propagate(False)
        
        # Stats Header
        stats_header = tk.Frame(right_panel, bg='#f8fafc', height=50)
        stats_header.pack(fill='x')
        tk.Label(
            stats_header, 
            text="📊 Session Statistics", 
            font=("Arial", 13, "bold"),
            bg='#f8fafc', 
            fg='#1e293b'
        ).pack(side='left', padx=15, pady=12)
        
        # Stats Cards
        stats_cards_frame = tk.Frame(right_panel, bg='white', padx=15, pady=15)
        stats_cards_frame.pack(fill='x')
        
        # Helper function to create cards
        def create_stat_card(parent, title, textvar, color):
            card = tk.Frame(parent, bg='#f8fafc', relief='solid', bd=1, padx=10, pady=10)
            tk.Label(card, text=title, font=("Arial", 9, "bold"), bg='#f8fafc', fg='#64748b').pack(anchor='w')
            tk.Label(card, textvariable=textvar, font=("Arial", 18, "bold"), bg='#f8fafc', fg=color).pack(anchor='w', pady=(5, 0))
            return card
            
        card_total = create_stat_card(stats_cards_frame, "Registered Students", self.stats_total_students, '#1e3a8a')
        card_total.pack(fill='x', pady=5)
        
        card_active = create_stat_card(stats_cards_frame, "Students Seen This Session", self.stats_active_detected, '#10b981')
        card_active.pack(fill='x', pady=5)
        
        card_time = create_stat_card(stats_cards_frame, "Session Elapsed Time", self.stats_elapsed_time, '#f59e0b')
        card_time.pack(fill='x', pady=5)
        
        # List of detected students
        roster_header = tk.Frame(right_panel, bg='#f8fafc', height=40)
        roster_header.pack(fill='x', pady=(10, 0))
        tk.Label(
            roster_header, 
            text="👥 Live Detection Log (Buffer Ticks)", 
            font=("Arial", 11, "bold"),
            bg='#f8fafc', 
            fg='#1e293b'
        ).pack(side='left', padx=15, pady=8)
        
        # Log frame
        self.roster_canvas = tk.Canvas(right_panel, bg='white', highlightthickness=0)
        self.roster_scrollbar = ttk.Scrollbar(right_panel, orient='vertical', command=self.roster_canvas.yview)
        self.roster_list_frame = tk.Frame(self.roster_canvas, bg='white')
        
        self.roster_canvas.create_window((0, 0), window=self.roster_list_frame, anchor='nw')
        self.roster_canvas.configure(yscrollcommand=self.roster_scrollbar.set)
        
        self.roster_canvas.pack(side='left', fill='both', expand=True, padx=(15, 0), pady=10)
        self.roster_scrollbar.pack(side='right', fill='y', pady=10)
        
        self.roster_list_frame.bind('<Configure>', lambda e: self.roster_canvas.configure(scrollregion=self.roster_canvas.bbox('all')))
        
        self.recent_detected_ui = {} # prn -> label widget
        
    def update_datetime(self):
        """Update live clock"""
        now = datetime.now().strftime("%A, %B %d, %Y | %I:%M:%S %p")
        self.datetime_label.config(text=now)
        self.root.after(1000, self.update_datetime)
        
    def load_data(self):
        """Fetch classes and subjects from database"""
        try:
            self.classes = self.db.get_all_classes()
            if self.classes:
                self.class_dropdown['values'] = list(self.classes.keys())
                self.class_dropdown.current(0)
                self.update_registered_students_count()
            else:
                messagebox.showwarning("Warning", "No classes found in database")
                
            self.subjects = self.db.get_all_subjects()
            if self.subjects:
                self.subject_dropdown['values'] = list(self.subjects.keys())
                self.subject_dropdown.current(0)
            else:
                messagebox.showwarning("Warning", "No subjects found in database")
                
            cameras = self.camera_manager.get_camera_list()
            if cameras:
                self.camera_dropdown['values'] = cameras
                self.camera_dropdown.current(0)
            else:
                messagebox.showerror("Error", "No cameras detected")
                
            self.class_dropdown.bind("<<ComboboxSelected>>", lambda e: self.update_registered_students_count())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load configuration: {e}")
            
    def update_registered_students_count(self):
        class_name = self.selected_class.get()
        if not class_name:
            return
        class_id = self.classes[class_name]
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM Students WHERE class_id = %s", (class_id,))
                count = cur.fetchone()[0]
                self.stats_total_students.set(str(count))
                
    def toggle_session(self):
        """Starts or stops the session"""
        if not self.is_session_running:
            self.start_classroom_session()
        else:
            self.end_classroom_session()
            
    def start_classroom_session(self):
        """Initializes and runs the session"""
        if not self.selected_class.get() or not self.selected_subject.get():
            messagebox.showerror("Error", "Please select a Class and Subject first.")
            return
            
        camera_index = self.camera_dropdown.current()
        if camera_index < 0:
            messagebox.showerror("Error", "Please select a Camera source.")
            return
            
        class_name = self.selected_class.get()
        subject_name = self.selected_subject.get()
        class_id = self.classes[class_name]
        subject_id = self.subjects[subject_name]
        
        # Load face embeddings to face engine
        try:
            encodings, prns = self.db.get_all_face_encodings()
            if not encodings:
                messagebox.showwarning("Warning", "No registered student face encodings found in database.")
                return
            self.face_engine.load_known_faces(encodings, prns)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load student face encodings: {e}")
            return
            
        # Create session in Database
        try:
            self.session_id = self.db.start_session(class_id, subject_id)
            self.session_start_time = datetime.now()
            self.is_session_running = True
            self.is_camera_running = True
            
            # Update UI
            self.session_btn.config(text="⏹ End Class Session", bg='#ef4444')
            self.status_pill.config(text=f"SESSION ACTIVE (ID: {self.session_id})", bg='#fee2e2', fg='#ef4444')
            self.stats_active_detected.set("0")
            
            # Clear UI list
            for widget in self.roster_list_frame.winfo_children():
                widget.destroy()
            self.recent_detected_ui.clear()
            
            # Disable selection changes during active session
            self.class_dropdown.config(state='disabled')
            self.subject_dropdown.config(state='disabled')
            self.camera_dropdown.config(state='disabled')
            
            # Start camera loop
            self.video_thread = threading.Thread(target=self.video_loop, args=(camera_index,), daemon=True)
            self.video_thread.start()
            
            # Start database detection logger thread (ticks every 10 seconds)
            self.logging_thread = threading.Thread(target=self.db_logging_loop, daemon=True)
            self.logging_thread.start()
            
            # Start session timer
            self.update_session_timer()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start session: {e}")
            
    def end_classroom_session(self):
        """Ends the active session and computes 70% duration attendance"""
        if not self.is_session_running:
            return
            
        if not messagebox.askyesno("Confirm End Session", "Are you sure you want to end this attendance session?"):
            return
            
        self.is_session_running = False
        self.is_camera_running = False
        
        # Wait for threads to terminate
        if self.video_thread:
            self.video_thread.join(timeout=1.5)
        if self.logging_thread:
            self.logging_thread.join(timeout=1.5)
            
        # Flush any remaining detections in buffer to DB
        with self.buffer_lock:
            if self.detected_buffer:
                prns_to_log = list(self.detected_buffer)
                self.detected_buffer.clear()
                try:
                    self.db.log_session_detections(self.session_id, prns_to_log)
                except Exception as e:
                    print(f"Error logging final batch detections: {e}")
            
        # Call DB to compile results
        try:
            success, msg, results = self.db.end_session(self.session_id)
            
            # Restore UI controls
            self.session_btn.config(text="▶ Start Class Session", bg='#10b981')
            self.status_pill.config(text="STATUS: INACTIVE", bg='#e2e8f0', fg='#475569')
            self.class_dropdown.config(state='readonly')
            self.subject_dropdown.config(state='readonly')
            self.camera_dropdown.config(state='readonly')
            self.video_label.configure(image="")
            
            if success:
                # Trigger email notifications in a background thread
                subject_name = self.selected_subject.get()
                threading.Thread(
                    target=self.send_session_emails,
                    args=(results, subject_name),
                    daemon=True
                ).start()
                
                self.show_attendance_results_window(results)
            else:
                messagebox.showerror("Error", f"Failed to compile attendance: {msg}")
                
        except Exception as e:
            messagebox.showerror("Error", f"Error ending session: {e}")
            
    def send_session_emails(self, results, subject_name):
        """Send email notifications in a background thread to avoid freezing the UI"""
        for item in results:
            email = item.get("email")
            if email:
                try:
                    send_session_attendance_notification(
                        student_email=email,
                        student_name=item["name"],
                        subject_name=subject_name,
                        status=item["status"],
                        percentage=item["presence_percentage"]
                    )
                except Exception as e:
                    print(f"[WARNING] Failed to send email to {email}: {e}")

    def update_session_timer(self):
        """Update elapsed session time in UI"""
        if not self.is_session_running:
            return
            
        elapsed = datetime.now() - self.session_start_time
        hours, remainder = divmod(elapsed.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.stats_elapsed_time.set(f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        
        self.root.after(1000, self.update_session_timer)
        
    def video_loop(self, camera_index):
        """Reads frames and runs detection/recognition continuously for visualization and buffering"""
        cap = self.camera_manager.open_camera(camera_index)
        if not cap:
            messagebox.showerror("Error", "Failed to open selected camera source")
            self.is_session_running = False
            self.is_camera_running = False
            return
            
        import time as pytime
        frame_count = 0
        process_every_n_frames = 4  # Run detection on every 4th frame to reduce CPU load
        last_results = []
        
        while self.is_camera_running:
            ret, frame = cap.read()
            if not ret:
                pytime.sleep(0.01)
                continue
                
            frame_count += 1
            if frame_count % process_every_n_frames == 0:
                frame_enhanced = self.face_engine.enhance_image_quality(frame)
                face_locations, face_encodings = self.face_engine.detect_and_encode_face(frame_enhanced)
                
                results = []
                if face_encodings:
                    recognitions = self.face_engine.recognize_faces(face_encodings)
                    for i, (prn, confidence) in enumerate(recognitions):
                        loc = face_locations[i]
                        if prn:
                            student_name = self.db.get_student_name(prn)
                            name_display = student_name or prn
                            results.append((loc, name_display, 'success', confidence))
                            
                            # Add to thread-safe buffer
                            with self.buffer_lock:
                                self.detected_buffer.add(prn)
                                
                            # Dynamically update UI roster
                            self.add_student_to_live_roster_ui(prn, name_display, is_present=True)
                        else:
                            results.append((loc, "Unknown", 'unknown', confidence))
                last_results = results
            
            # Always display the current frame with the last known bounding boxes for 30 FPS fluidity
            self.display_annotated_frame(frame, last_results)
                
        cap.release()
        
    def db_logging_loop(self):
        """Writes buffered detections to database every 10 seconds"""
        while self.is_session_running:
            time.sleep(10.0)
            if not self.is_session_running:
                break
                
            with self.buffer_lock:
                if not self.detected_buffer:
                    continue
                prns_to_log = list(self.detected_buffer)
                # We do not clear the buffer entirely if we want to keep track of active distinct
                # counts, but we clear it to log new ticks in DB for the next 10-second block
                self.detected_buffer.clear()
                
            try:
                self.db.log_session_detections(self.session_id, prns_to_log)
            except Exception as e:
                print(f"Error logging batch detections to DB: {e}")
                
    def add_student_to_live_roster_ui(self, prn, name, is_present=True):
        """Creates or updates student item in the live detection list"""
        if prn in self.recent_detected_ui:
            entry, time_label = self.recent_detected_ui[prn]
            time_label.config(text=f"Seen: {datetime.now().strftime('%I:%M:%S %p')}")
            return
            
        bg_color = '#f0fdf4'
        fg_color = '#15803d'
        status_text = f"Seen: {datetime.now().strftime('%I:%M:%S %p')}"
        
        entry = tk.Frame(self.roster_list_frame, bg=bg_color, relief='solid', bd=1, padx=10, pady=8)
        entry.pack(fill='x', pady=4, padx=5)
        
        # Layout details
        info_frame = tk.Frame(entry, bg=bg_color)
        info_frame.pack(side='left', fill='both', expand=True)
        
        name_lbl = tk.Label(info_frame, text=name, font=("Arial", 10, "bold"), bg=bg_color, fg=fg_color)
        name_lbl.pack(anchor='w')
        
        prn_lbl = tk.Label(info_frame, text=f"PRN: {prn}", font=("Arial", 8), bg=bg_color, fg=fg_color)
        prn_lbl.pack(anchor='w')
        
        time_label = tk.Label(entry, text=status_text, font=("Arial", 8), bg=bg_color, fg=fg_color)
        time_label.pack(side='right')
        
        self.recent_detected_ui[prn] = (entry, time_label)
        
        # Update UI stats count
        self.stats_active_detected.set(str(len(self.recent_detected_ui)))
        
    def display_annotated_frame(self, frame, results):
        """Displays OpenCV camera frame with bounding boxes"""
        display_frame = frame.copy()
        
        for result in results:
            face_location, name, status, confidence = result
            top, right, bottom, left = face_location
            
            color = (16, 185, 129) if status == 'success' else (239, 68, 68) # Green vs Red (BGR format)
            
            # Draw box & text
            cv2.rectangle(display_frame, (left, top), (right, bottom), color, 2)
            cv2.rectangle(display_frame, (left, bottom - 25), (right, bottom), color, cv2.FILLED)
            cv2.putText(display_frame, f"{name} ({confidence:.0f}%)", (left + 5, bottom - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                        
        # Resize to fit screen
        frame_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        frame_resized = cv2.resize(frame_rgb, (800, 500))
        img = Image.fromarray(frame_resized)
        imgtk = ImageTk.PhotoImage(image=img)
        
        self.video_label.imgtk = imgtk
        self.video_label.configure(image=imgtk)
        
    def show_attendance_results_window(self, results):
        """Open a secondary window showing final 70% present attendance report with CSV download option"""
        results_win = tk.Toplevel(self.root)
        results_win.title("Class Session Attendance Report Summary")
        results_win.geometry("900x600")
        results_win.configure(bg='#f8fafc')
        results_win.grab_set()
        
        # Header
        header = tk.Frame(results_win, bg='#1e3a8a', height=60)
        header.pack(fill='x', side='top')
        tk.Label(
            header, 
            text="📝 Session Attendance Summary Report (70% presence rule)", 
            font=("Arial", 14, "bold"),
            bg='#1e3a8a', 
            fg='white'
        ).pack(pady=15)
        
        # Content frame
        content_frame = tk.Frame(results_win, bg='#f8fafc', padx=15, pady=15)
        content_frame.pack(fill='both', expand=True)
        
        style = ttk.Style()
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))
        style.configure("Treeview", font=("Arial", 10), rowheight=28)
        
        # --- PANEL: PRESENT STUDENTS ---
        present_frame = tk.LabelFrame(
            content_frame, 
            text="🟢 Present Students (>= 70% duration)", 
            font=("Arial", 11, "bold"), 
            fg='#15803d', 
            bg='white', 
            padx=10, 
            pady=10
        )
        present_frame.pack(fill='both', expand=True)
        
        scrollbar_pres = ttk.Scrollbar(present_frame)
        scrollbar_pres.pack(side='right', fill='y')
        
        tree_pres = ttk.Treeview(
            present_frame, 
            columns=('roll', 'name', 'prn', 'percentage'), 
            show='headings', 
            yscrollcommand=scrollbar_pres.set
        )
        tree_pres.heading('roll', text='Roll No')
        tree_pres.heading('name', text='Name')
        tree_pres.heading('prn', text='PRN')
        tree_pres.heading('percentage', text='Presence %')
        
        tree_pres.column('roll', width=100, anchor='center')
        tree_pres.column('name', width=300, anchor='w')
        tree_pres.column('prn', width=180, anchor='center')
        tree_pres.column('percentage', width=150, anchor='center')
        tree_pres.pack(fill='both', expand=True)
        scrollbar_pres.config(command=tree_pres.yview)
        
        # Sort results
        sorted_results = sorted(results, key=lambda x: int(x['roll_no']) if str(x['roll_no']).isdigit() else 9999)
        
        present_count = 0
        
        # Insert rows into table
        for item in sorted_results:
            if item['status'] == 'present':
                row_values = (
                    item['roll_no'],
                    item['name'],
                    item['prn'],
                    f"{item['presence_percentage']}%"
                )
                tree_pres.insert('', 'end', values=row_values)
                present_count += 1
                
        def export_to_csv():
            import csv
            from tkinter import filedialog
            
            subject_clean = self.selected_subject.get().replace(" ", "_")
            date_clean = datetime.now().strftime("%Y-%m-%d")
            file_path = filedialog.asksaveasfilename(
                parent=results_win,
                title="Save Present Students List",
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv")],
                initialfile=f"present_students_{subject_clean}_{date_clean}.csv"
            )
            if not file_path:
                return
                
            try:
                with open(file_path, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Roll No", "Name", "PRN", "Presence Percentage"])
                    for item in sorted_results:
                        if item['status'] == 'present':
                            writer.writerow([
                                item['roll_no'],
                                item['name'],
                                item['prn'],
                                f"{item['presence_percentage']}%"
                            ])
                messagebox.showinfo("Success", f"CSV file exported successfully to:\n{file_path}", parent=results_win)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export CSV: {e}", parent=results_win)
                
        # Footer Frame at the bottom
        footer_frame = tk.Frame(results_win, bg='#f8fafc', pady=15)
        footer_frame.pack(side='bottom', fill='x', padx=20)
        
        # Stats summary on the left
        stats_summary = tk.Label(
            footer_frame,
            text=f"Total Registered: {len(results)}   |   🟢 Present (>=70%): {present_count}",
            font=("Arial", 11, "bold"),
            bg='#f8fafc',
            fg='#334155'
        )
        stats_summary.pack(side='left', padx=10)
        
        # CSV Export Button on the right
        btn_export = tk.Button(
            footer_frame,
            text="📥 Export Present List to CSV",
            font=("Arial", 10, "bold"),
            bg='#10b981',
            fg='white',
            relief='flat',
            padx=15,
            pady=8,
            command=export_to_csv
        )
        btn_export.pack(side='right', padx=10)

    def on_close(self):
        """Triggered when window is closed"""
        self.is_session_running = False
        self.is_camera_running = False
        if self.video_thread:
            self.video_thread.join(timeout=0.5)
        self.root.destroy()
