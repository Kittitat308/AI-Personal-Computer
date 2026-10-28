import os
import threading
from pathlib import Path
from dataclasses import dataclass

import cv2
import numpy as np

from app.database import Database, User


@dataclass(frozen=True)
class FaceResult:
    detected: bool
    embedding: np.ndarray | None = None
    reason: str = ""
    bbox: tuple[float, float, float, float] | None = None


FACE_GUIDE_WIDTH_RATIO = 0.38
FACE_GUIDE_HEIGHT_RATIO = 0.84


class FaceService:
    def __init__(self, database: Database, threshold: float = 0.45):
        self.database = database
        self.threshold = threshold
        self._analyzer = None
        self._capture = None
        self._lock = threading.RLock()
        self._model_lock = threading.RLock()

    def load(self) -> None:
        if self._analyzer is not None:
            return
        from insightface.app import FaceAnalysis

        model_root = Path(
            os.environ.get("AIPC_INSIGHTFACE_HOME", "~/.insightface")
        ).expanduser()
        analyzer = FaceAnalysis(
            name="buffalo_m",
            root=str(model_root),
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        analyzer.prepare(ctx_id=-1, det_size=(640, 640))
        self._analyzer = analyzer

    def open_camera(self) -> None:
        with self._lock:
            if self._capture is not None and self._capture.isOpened():
                return
            capture = cv2.VideoCapture(0)
            if not capture.isOpened():
                capture.release()
                raise RuntimeError("ไม่พบกล้องที่พร้อมใช้งาน")
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self._capture = capture

    def close_camera(self) -> None:
        with self._lock:
            if self._capture is not None:
                self._capture.release()
            self._capture = None

    def read_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._capture is None or not self._capture.isOpened():
                return None
            ok, frame = self._capture.read()
        return frame if ok else None

    def extract_largest(self, frame: np.ndarray | None) -> FaceResult:
        if frame is None:
            return FaceResult(False)
        self.load()
        with self._model_lock:
            faces = self._analyzer.get(frame)
        if not faces:
            return FaceResult(False)
        face = max(
            faces,
            key=lambda item: max(0.0, item.bbox[2] - item.bbox[0])
            * max(0.0, item.bbox[3] - item.bbox[1]),
        )
        embedding = np.asarray(face.normed_embedding, dtype=np.float32)
        return FaceResult(True, embedding)

    @staticmethod
    def _enrollment_quality_reason(
        frame_shape: tuple[int, ...],
        bbox: np.ndarray,
        kps: np.ndarray | None,
        det_score: float,
    ) -> str:
        """Return an instruction when a detected face is unsuitable for enrollment."""
        frame_height, frame_width = frame_shape[:2]
        x1, y1, x2, y2 = (float(value) for value in bbox)
        face_width = max(0.0, x2 - x1)
        face_height = max(0.0, y2 - y1)
        center_x = (x1 + x2) / (2.0 * frame_width)
        center_y = (y1 + y2) / (2.0 * frame_height)
        width_ratio = face_width / frame_width
        height_ratio = face_height / frame_height

        if det_score < 0.65:
            return "จัดแสงให้เห็นใบหน้าชัดเจน"
        if abs(center_x - 0.5) > 0.11 or abs(center_y - 0.5) > 0.13:
            return "วางใบหน้าให้อยู่ตรงกลางกรอบ"
        if width_ratio < 0.19 or height_ratio < 0.30:
            return "ขยับเข้าใกล้กล้องอีกเล็กน้อย"
        if width_ratio > 0.43 or height_ratio > 0.82:
            return "ขยับออกจากกล้องอีกเล็กน้อย"
        if kps is None or np.asarray(kps).shape != (5, 2):
            return "มองกล้องให้เห็นใบหน้าตรง ๆ"

        points = np.asarray(kps, dtype=np.float32)
        left_eye, right_eye, nose, left_mouth, right_mouth = points
        eye_vector = right_eye - left_eye
        eye_distance = float(np.linalg.norm(eye_vector))
        if eye_distance < 1.0:
            return "มองกล้องให้เห็นใบหน้าตรง ๆ"

        raw_roll = float(np.degrees(np.arctan2(eye_vector[1], eye_vector[0])))
        roll = abs((raw_roll + 90.0) % 180.0 - 90.0)
        eye_midpoint = (left_eye + right_eye) / 2.0
        mouth_midpoint = (left_mouth + right_mouth) / 2.0
        mouth_distance = float(mouth_midpoint[1] - eye_midpoint[1])
        nose_horizontal_offset = abs(float(nose[0] - eye_midpoint[0])) / eye_distance
        mouth_horizontal_offset = abs(float(mouth_midpoint[0] - eye_midpoint[0])) / eye_distance
        nose_vertical_ratio = (
            float(nose[1] - eye_midpoint[1]) / mouth_distance
            if mouth_distance > 1.0
            else 0.0
        )
        if (
            roll > 12.0
            or nose_horizontal_offset > 0.28
            or mouth_horizontal_offset > 0.35
            or not 0.32 <= nose_vertical_ratio <= 0.78
        ):
            return "ตั้งศีรษะให้ตรงและมองกล้อง"
        return ""

    def extract_for_enrollment(self, frame: np.ndarray | None) -> FaceResult:
        """Detect and validate position/pose before running recognition."""
        if frame is None:
            return FaceResult(False, reason="มองกล้องเพื่อสแกนใบหน้า")
        self.load()
        from insightface.app.common import Face

        with self._model_lock:
            bboxes, kpss = self._analyzer.det_model.detect(
                frame,
                max_num=0,
                metric="default",
            )
            if bboxes.shape[0] == 0:
                return FaceResult(False, reason="มองกล้องเพื่อสแกนใบหน้า")
            areas = (bboxes[:, 2] - bboxes[:, 0]) * (bboxes[:, 3] - bboxes[:, 1])
            index = int(np.argmax(areas))
            bbox = np.asarray(bboxes[index, :4], dtype=np.float32)
            det_score = float(bboxes[index, 4])
            kps = None if kpss is None else np.asarray(kpss[index], dtype=np.float32)
            reason = self._enrollment_quality_reason(
                frame.shape,
                bbox,
                kps,
                det_score,
            )
            bbox_tuple = tuple(float(value) for value in bbox)
            if reason:
                return FaceResult(True, reason=reason, bbox=bbox_tuple)

            face = Face(bbox=bbox, kps=kps, det_score=det_score)
            recognition = self._analyzer.models.get("recognition")
            if recognition is None:
                raise RuntimeError("ไม่พบโมเดลจดจำใบหน้า")
            recognition.get(frame, face)
            embedding = np.asarray(face.normed_embedding, dtype=np.float32)
            return FaceResult(True, embedding, bbox=bbox_tuple)

    def has_face(self, frame: np.ndarray | None) -> bool:
        """Run only the detector; do not create a recognition embedding."""
        if frame is None:
            return False
        self.load()
        with self._model_lock:
            bboxes, _ = self._analyzer.det_model.detect(
                frame,
                max_num=0,
                metric="default",
            )
        return bool(bboxes.shape[0])

    def recognize(self, embedding: np.ndarray) -> User | None:
        best_user = None
        best_score = -1.0
        for user, stored in self.database.list_face_profiles():
            if stored.shape != embedding.shape:
                continue
            score = float(np.dot(embedding, stored))
            if score > best_score:
                best_score = score
                best_user = user
        return best_user if best_score >= self.threshold else None

    @staticmethod
    def frame_to_rgb(frame: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self.close_camera()
        self._analyzer = None
