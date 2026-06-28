# face_recognition_engine.py - YOLOv8 + InsightFace Version
import cv2
import numpy as np
from threading import Lock
from ultralytics import YOLO
from insightface import app
import time
from collections import defaultdict
import os
import onnxruntime as ort

# Monkeypatch ONNX Runtime InferenceSession to apply CPU optimizations before InsightFace loads models
_original_inference_session_init = ort.InferenceSession.__init__

def _optimized_inference_session_init(self, path_or_bytes, sess_options=None, *args, **kwargs):
    if sess_options is None:
        sess_options = ort.SessionOptions()
    
    # Enable all graph optimizations
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    
    # Configure CPU thread count
    cpu_cores = os.cpu_count() or 4
    # Default to physical cores (half of logical cores) or a max of 4 to prevent CPU exhaustion on host
    default_threads = max(1, min(4, cpu_cores // 2))
    intra_threads = int(os.getenv('ORT_INTRA_THREADS', str(default_threads)))
    
    sess_options.intra_op_num_threads = intra_threads
    sess_options.inter_op_num_threads = 1
    sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    
    _original_inference_session_init(self, path_or_bytes, sess_options, *args, **kwargs)

ort.InferenceSession.__init__ = _optimized_inference_session_init

class FaceRecognitionEngine:
    def __init__(self, config):
        self.config = config
        self.known_embeddings = []
        self.known_prns = []
        self.known_stack = None
        self.lock = Lock()
        self.face_analyzer = None
        self.yolo_detector = None
        self.last_detection = defaultdict(float)  # prn -> timestamp for deduplication
        self.camera_directions = {}  # camera_id -> direction (IN/OUT/BOTH)

        self._initialize_face_analyzer()
        self._initialize_yolo_detector()
        print("✓ Face recognition initialized")

    def _initialize_face_analyzer(self):
        model_name = self.config.get('insightface_model', 'buffalo_l')
        self.face_analyzer = app.FaceAnalysis(
            name=model_name,
            allowed_modules=['detection', 'recognition']
        )
        self.face_analyzer.prepare(
            ctx_id=0,
            det_thresh=self.config.get('det_thresh', 0.5),
            det_size=tuple(self.config.get('det_size', (640, 640)))
        )
        print(f"✓ InsightFace model loaded: {model_name}")

    def _initialize_yolo_detector(self):
        if not self.config.get('use_yolo', False):
            return

        model_path = self.config.get('yolo_model', 'yolov8n.pt')
        try:
            self.yolo_detector = YOLO(model_path)
            print(f"✓ YOLO detector loaded: {model_path}")
        except Exception as exc:
            print(f"⚠ Failed to load YOLO model '{model_path}': {exc}")
            self.yolo_detector = None

    def load_known_faces(self, encodings, prns):
        with self.lock:
            normalized_embeddings = []
            for encoding in encodings:
                embedding = np.asarray(encoding, dtype=np.float32).flatten()
                normalized_embeddings.append(self._normalize_embedding(embedding))
            self.known_embeddings = normalized_embeddings
            self.known_prns = list(prns)
            
            # Pre-compile the embeddings stack to avoid doing np.vstack on every request
            if normalized_embeddings:
                self.known_stack = np.vstack(normalized_embeddings)
            else:
                self.known_stack = None
        print(f"✓ Loaded {len(self.known_prns)} known face embeddings")

    def _normalize_embedding(self, embedding):
        norm = np.linalg.norm(embedding)
        if norm == 0:
            return embedding.astype(np.float32)
        return (embedding / norm).astype(np.float32)

    def detect_and_encode_face(self, frame, for_registration=False):
        scale = float(self.config.get('detection_scale', 1.0))
        detection_frame = frame
        if scale != 1.0:
            detection_frame = cv2.resize(frame, (0, 0), fx=scale, fy=scale)

        face_locations = []
        face_encodings = []

        if self.yolo_detector is not None:
            face_locations, face_encodings = self._detect_with_yolo(detection_frame)
            if face_encodings:
                if scale != 1.0:
                    face_locations = [
                        (int(top / scale), int(right / scale), int(bottom / scale), int(left / scale))
                        for top, right, bottom, left in face_locations
                    ]
                return face_locations, face_encodings

        faces = self.face_analyzer.get(detection_frame)
        for face in faces:
            bbox = getattr(face, 'bbox', None)
            embedding = getattr(face, 'embedding', None)
            if bbox is None or embedding is None:
                continue

            x1, y1, x2, y2 = [int(v) for v in bbox]
            top, right, bottom, left = y1, x2, y2, x1
            face_locations.append((top, right, bottom, left))
            face_encodings.append(self._normalize_embedding(np.asarray(embedding, dtype=np.float32)))

        if scale != 1.0:
            face_locations = [
                (int(top / scale), int(right / scale), int(bottom / scale), int(left / scale))
                for top, right, bottom, left in face_locations
            ]

        return face_locations, face_encodings

    def _detect_with_yolo(self, frame):
        face_locations = []
        face_encodings = []
        try:
            results = self.yolo_detector(frame)
        except Exception:
            return face_locations, face_encodings

        for result in results:
            boxes = getattr(result, 'boxes', None)
            if boxes is None or len(boxes) == 0:
                continue

            xyxy = boxes.xyxy.cpu().numpy()
            classes = boxes.cls.cpu().numpy()
            confidences = boxes.conf.cpu().numpy()

            for box, cls, conf in zip(xyxy, classes, confidences):
                if int(cls) != 0 or conf < float(self.config.get('yolo_confidence', 0.3)):
                    continue

                x1, y1, x2, y2 = map(int, box)
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(frame.shape[1], x2)
                y2 = min(frame.shape[0], y2)

                if x2 <= x1 or y2 <= y1:
                    continue

                crop = frame[y1:y2, x1:x2]
                if crop.size == 0:
                    continue

                crop_faces = self.face_analyzer.get(crop)
                for face in crop_faces:
                    bbox = getattr(face, 'bbox', None)
                    embedding = getattr(face, 'embedding', None)
                    if bbox is None or embedding is None:
                        continue

                    fx1, fy1, fx2, fy2 = [int(v) for v in bbox]
                    top = fy1 + y1
                    right = fx2 + x1
                    bottom = fy2 + y1
                    left = fx1 + x1

                    face_locations.append((top, right, bottom, left))
                    face_encodings.append(self._normalize_embedding(np.asarray(embedding, dtype=np.float32)))

        return face_locations, face_encodings

    def recognize_faces(self, face_encodings):
        results = []
        with self.lock:
            if getattr(self, 'known_stack', None) is None or len(self.known_stack) == 0:
                return [(None, 0.0) for _ in face_encodings]

            known_stack = self.known_stack
            threshold = float(self.config.get('recognition_tolerance', 0.8))

            for face_encoding in face_encodings:
                query = self._normalize_embedding(np.asarray(face_encoding, dtype=np.float32))
                distances = np.linalg.norm(known_stack - query, axis=1)
                best_idx = int(np.argmin(distances))
                best_dist = float(distances[best_idx])

                # Piecewise linear mapping to dynamically adjust confidence based on the threshold.
                # If distance is <= threshold, confidence is between 50% and 100%.
                # If distance is > threshold, confidence is between 0% and 50%.
                if best_dist <= threshold:
                    confidence = 50.0 + 50.0 * (1.0 - (best_dist / threshold if threshold > 0 else 0))
                    confidence = max(50.0, min(100.0, confidence))
                    prn = self.known_prns[best_idx]
                    results.append((prn, confidence))
                else:
                    denominator = max(0.01, 2.0 - threshold)
                    confidence = 50.0 * (1.0 - (best_dist - threshold) / denominator)
                    confidence = max(0.0, min(49.9, confidence))
                    results.append((None, confidence))

        return results

    def enhance_image_quality(self, frame):
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        enhanced = cv2.merge([l, a, b])
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    def check_face_quality(self, frame, face_location):
        """Check if a face meets quality thresholds for recognition.
        
        Returns: (is_quality_ok, quality_score_dict)
        """
        top, right, bottom, left = face_location
        face_crop = frame[top:bottom, left:right]
        
        if face_crop.size == 0:
            return False, {"error": "empty_crop"}

        # 1. Size check: minimum 80x80 pixels
        height, width = face_crop.shape[:2]
        min_size = int(self.config.get('min_face_size', 80))
        if width < min_size or height < min_size:
            return False, {"size": (width, height), "min_required": min_size}

        # 2. Blur check: Laplacian variance
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_threshold = float(self.config.get('blur_threshold', 100))
        if laplacian_var < blur_threshold:
            return False, {"blur_score": laplacian_var, "threshold": blur_threshold}

        # 3. Brightness check: mean pixel value
        brightness = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)[:, :, 0].mean()
        if brightness < 30 or brightness > 220:
            return False, {"brightness": brightness}

        return True, {
            "size": (width, height),
            "blur_score": laplacian_var,
            "brightness": brightness
        }

    def should_deduplicate(self, prn, camera_id=None):
        """Check if this face was detected too recently (deduplication).
        
        Returns: True if should skip (deduplicate), False if should process.
        """
        cooldown_seconds = int(self.config.get('detection_cooldown', 300))
        key = f"{prn}_{camera_id}" if camera_id else prn
        now = time.time()
        
        last_time = self.last_detection.get(key, 0.0)
        if now - last_time < cooldown_seconds:
            return True
        
        self.last_detection[key] = now
        return False

    def set_camera_direction(self, camera_id, direction):
        """Set or update camera direction (IN/OUT/BOTH).
        
        This allows distinguishing entry vs exit for attendance logic.
        """
        if direction not in ('IN', 'OUT', 'BOTH'):
            raise ValueError(f"Invalid direction: {direction}")
        self.camera_directions[camera_id] = direction

    def get_camera_direction(self, camera_id):
        """Get camera direction (IN/OUT/BOTH)."""
        return self.camera_directions.get(camera_id, 'BOTH')
