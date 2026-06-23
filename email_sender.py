# email_sender.py
"""
Utility module for sending low-attendance warning emails to students.
Supports SMTP authentication. If credentials are not configured, it logs warnings locally.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load settings from environment (already processed by dotenv in run_api)
SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM = os.getenv('SMTP_FROM', 'no-reply@eduvision.edu')

def send_low_attendance_warning(student_email, student_name, subject_name, percentage):
    """
    Sends an email warning to a student whose cumulative attendance has dropped below 70%.
    """
    if not student_email:
        print(f"[EMAIL] Skipping warning for {student_name}: no email address provided.")
        return False

    # Email message contents
    subject = f"[WARNING] Attendance Warning: {subject_name}"
    body = (
        f"Dear {student_name},\n\n"
        f"This is an automated notification regarding your attendance in the subject: {subject_name}.\n\n"
        f"Your current cumulative attendance is {percentage:.1f}%, which is below the minimum required threshold of 70.0%.\n\n"
        f"Please attend future sessions regularly to bring your attendance back to compliance.\n\n"
        f"Best regards,\n"
        f"EduVision Academic Team"
    )

    # If SMTP is not fully configured, log the warning to standard output
    is_smtp_configured = SMTP_HOST and SMTP_USER and SMTP_PASSWORD
    if not is_smtp_configured or "your_email" in SMTP_USER:
        print(f"\n=================== [MOCK EMAIL SENT] ===================")
        print(f"To: {student_email} ({student_name})")
        print(f"Subject: {subject}")
        print(f"Content:\n{body}")
        print(f"=========================================================\n")
        return True

    # Send the actual email via SMTP
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM
        msg['To'] = student_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, student_email, msg.as_string())
        server.quit()
        print(f"[OK] [EMAIL] Successfully sent low-attendance alert to {student_email}")
        return True
    except Exception as e:
        print(f"[ERROR] [EMAIL] Failed to send email to {student_email} via SMTP: {e}")
        return False

def send_session_attendance_notification(student_email, student_name, subject_name, status, percentage):
    """
    Sends a session attendance email notification to a student (present or absent).
    """
    if not student_email:
        print(f"[EMAIL] Skipping notification for {student_name}: no email address provided.")
        return False

    if status == "present":
        subject = f"Attendance Marked: {subject_name}"
        body = (
            f"Dear {student_name},\n\n"
            f"This is to notify you that your attendance has been marked as PRESENT in the subject: {subject_name}.\n\n"
            f"Details:\n"
            f"- Status: PRESENT\n"
            f"- Session Attendance: {percentage:.1f}%\n\n"
            f"Thank you for attending!\n\n"
            f"Best regards,\n"
            f"EduVision Academic Team"
        )
    else:
        subject = f"Attendance Alert (ABSENT): {subject_name}"
        body = (
            f"Dear {student_name},\n\n"
            f"This is to notify you that you were marked as ABSENT in the subject: {subject_name}.\n\n"
            f"Details:\n"
            f"- Status: ABSENT\n"
            f"- Session Attendance: {percentage:.1f}%\n\n"
            f"If you believe this was an error, please contact your subject teacher.\n\n"
            f"Best regards,\n"
            f"EduVision Academic Team"
        )

    is_smtp_configured = SMTP_HOST and SMTP_USER and SMTP_PASSWORD
    if not is_smtp_configured or "your_email" in SMTP_USER:
        print(f"\n=================== [MOCK EMAIL SENT] ===================")
        print(f"To: {student_email} ({student_name})")
        print(f"Subject: {subject}")
        print(f"Content:\n{body}")
        print(f"=========================================================\n")
        return True

    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM
        msg['To'] = student_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, student_email, msg.as_string())
        server.quit()
        print(f"[OK] [EMAIL] Sent attendance notification to {student_email} (Status: {status.upper()})")
        return True
    except Exception as e:
        print(f"[ERROR] [EMAIL] Failed to send email to {student_email} via SMTP: {e}")
        return False
