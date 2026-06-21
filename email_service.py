import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from attendance_config import SMTP_CONFIG

LOGS_DIR = "logs"
EMAIL_LOG_FILE = os.path.join(LOGS_DIR, "sent_emails.log")

def send_attendance_warning(student_email: str, student_name: str, subject_name: str, attendance_percentage: float):
    """Sends warning email to student if cumulative attendance drops below 70%.
    
    If SMTP settings are missing or if sending fails, it falls back to writing 
    the email contents to a local log file: logs/sent_emails.log
    """
    subject = f"Urgent: Attendance Warning for {subject_name}"
    
    body = f"""Dear {student_name},
    
This is an automated warning notification from the Smart Attendance System.

Your cumulative attendance for the subject '{subject_name}' has fallen to {attendance_percentage:.1f}%, which is below the mandatory requirement of 70.0%.

Please make sure to attend the upcoming lectures regularly to maintain the minimum attendance requirements.

Best regards,
Academic Administration
"""
    
    # Try sending via SMTP if host is configured
    host = SMTP_CONFIG.get('host')
    port = SMTP_CONFIG.get('port', 587)
    user = SMTP_CONFIG.get('user')
    password = SMTP_CONFIG.get('password')
    from_addr = SMTP_CONFIG.get('from_addr', 'no-reply@smartattendance.edu')
    
    success = False
    error_msg = None
    
    if host and user:
        try:
            msg = MIMEMultipart()
            msg['From'] = from_addr
            msg['To'] = student_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            # Connect and send
            server = smtplib.SMTP(host, port)
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, student_email, msg.as_string())
            server.quit()
            
            success = True
            print(f"✓ Warning email sent successfully to {student_email}")
        except Exception as e:
            error_msg = str(e)
            print(f"✗ Failed to send email via SMTP to {student_email}: {e}")
    else:
        error_msg = "SMTP server not configured"
        
    if not success:
        # Fallback: Write email details to logs/sent_emails.log
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] WARNING EMAIL (MOCK FALLBACK - Reason: {error_msg})\n"
            log_entry += f"To: {student_email} ({student_name})\n"
            log_entry += f"From: {from_addr}\n"
            log_entry += f"Subject: {subject}\n"
            log_entry += f"Body:\n{body}\n"
            log_entry += "-" * 60 + "\n\n"
            
            with open(EMAIL_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_entry)
            print(f"✓ Attendance warning logged to {EMAIL_LOG_FILE} for {student_email}")
        except Exception as le:
            print(f"✗ Failed to write email fallback log: {le}")
