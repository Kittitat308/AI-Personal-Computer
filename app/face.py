import threading
from dataclasses import dataclass

import cv2
import numpy as np

from app.database import Database, User


@dataclass(frozen=True)
class FaceResult:
    detected: bool
    embedding: np.ndarray | None = None


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

        analyzer = FaceAnalysis(
            name="buffalo_m",
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
