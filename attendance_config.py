"""Prototype configuration for the attendance system."""

import os

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Silence OpenCV logging warnings globally
os.environ["OPENCV_VIDEOIO_LOGGING_LEVEL"] = "0"
os.environ["OPENCV_LOG_LEVEL"] = "OFF"


DB_CONFIG = {
    'host': os.getenv('ATTENDANCE_DB_HOST', 'localhost'),
    'database': os.getenv('ATTENDANCE_DB_NAME', 'attendance2'),
    'user': os.getenv('ATTENDANCE_DB_USER', 'postgres'),
    'password': os.getenv('ATTENDANCE_DB_PASSWORD', ''),
    'port': int(os.getenv('ATTENDANCE_DB_PORT', '5432')),
}

FACE_RECOGNITION_CONFIG = {
    'use_yolo': False,
    'yolo_model': 'yolov8n.pt',
    'yolo_confidence': 0.3,
    'insightface_model': 'buffalo_l',
    'det_thresh': 0.45,
    'det_size': (1280, 736),
    'recognition_tolerance': 0.95,
    'detection_scale': 1.0,
}

ATTENDANCE_COOLDOWN = 300

CAMERA_CONFIG = {
    'default_camera': 0,
    'frame_width': 1280,
    'frame_height': 720,
    'fps': 30
}

# UI Settings
UI_CONFIG = {
    'theme': 'default',  # ttk theme
    'primary_color': '#2196F3',
    'success_color': '#4CAF50',
    'error_color': '#F44336',
    'warning_color': '#FF9800'
}
