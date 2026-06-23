# scripts/test_email.py
"""
Verify SMTP email settings by sending a test alert.
Usage: python scripts/test_email.py <recipient_email>
"""

import sys
import os

# Add parent directory to path to find email_sender
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from email_sender import send_low_attendance_warning, SMTP_HOST, SMTP_USER

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_email.py <recipient_email>")
        print("Falling back to dry-run verification mode.")
        recipient = "test-student@example.com"
    else:
        recipient = sys.argv[1]

    print("--- [SMTP Diagnostic Check] ---")
    print(f"SMTP Host: {SMTP_HOST or 'Not Configured (Will mock send)'}")
    print(f"SMTP User: {SMTP_USER or 'Not Configured'}")
    
    print("\nAttempting to send warning email alert...")
    success = send_low_attendance_warning(
        student_email=recipient,
        student_name="Test Student",
        subject_name="Engineering Mathematics-II",
        percentage=64.5
    )

    if success:
        print("\n[OK] Verification complete! Check the output or your email inbox.")
    else:
        print("\n[ERROR] Verification failed.")

if __name__ == "__main__":
    main()
