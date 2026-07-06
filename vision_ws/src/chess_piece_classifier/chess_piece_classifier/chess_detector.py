"""YOLO-based chess piece detector using a pretrained Ultralytics model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PieceDetection:
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    score: float
    class_id: int
    class_name: str
    polygon: tuple[tuple[float, float], ...] | None = None


def _bbox_iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def merge_detections(
    detections: list[PieceDetection],
    iou_threshold: float = 0.45,
) -> list[PieceDetection]:
    """Merge overlapping boxes, keeping the highest-confidence detection."""
    if not detections:
        return []

    ordered = sorted(detections, key=lambda det: det.score, reverse=True)
    kept: list[PieceDetection] = []
    for candidate in ordered:
        if any(_bbox_iou(candidate.bbox, kept_det.bbox) >= iou_threshold for kept_det in kept):
            continue
        kept.append(candidate)
    return kept


class ChessPieceDetector:
    def __init__(
        self,
        model_path: str,
        conf: float = 0.45,
        iou: float = 0.5,
        imgsz: int = 416,
        device: str = '',
    ) -> None:
        from ultralytics import YOLO

        from chess_piece_classifier.model_resolver import resolve_model_path

        self.model = YOLO(resolve_model_path(model_path))
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.device = device or None
        self.preprocess = True
        self.multi_pass = True

    def set_preprocess(self, enabled: bool) -> None:
        self.preprocess = enabled

    def set_multi_pass(self, enabled: bool) -> None:
        self.multi_pass = enabled

    def _clahe(self, bgr_image: np.ndarray, clip_limit: float, tile: int) -> np.ndarray:
        import cv2

        lab = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile, tile))
        l_channel = clahe.apply(l_channel)
        enhanced = cv2.merge((l_channel, a_channel, b_channel))
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    def _preprocess(self, bgr_image: np.ndarray) -> np.ndarray:
        if not self.preprocess:
            return bgr_image
        return self._clahe(bgr_image, clip_limit=2.5, tile=8)

    def _preprocess_white_boost(self, bgr_image: np.ndarray) -> np.ndarray:
        """Boost edges/contrast to help white pieces on light squares."""
        import cv2

        enhanced = self._clahe(bgr_image, clip_limit=4.0, tile=4)
        gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        blended = cv2.addWeighted(enhanced, 0.82, edges_bgr, 0.18, 0.0)
        return cv2.convertScaleAbs(blended, alpha=1.25, beta=-12)

    def _preprocess_inverted(self, bgr_image: np.ndarray) -> np.ndarray:
        """Invert luminance to improve white-piece contrast on light squares."""
        import cv2

        gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        inv = cv2.bitwise_not(gray)
        inv_bgr = cv2.cvtColor(inv, cv2.COLOR_GRAY2BGR)
        return cv2.convertScaleAbs(inv_bgr, alpha=1.2, beta=0)

    def _image_variants(self, bgr_image: np.ndarray) -> list[np.ndarray]:
        import cv2

        variants = [bgr_image]
        if self.preprocess:
            variants.append(self._preprocess(bgr_image))
        variants.append(cv2.convertScaleAbs(bgr_image, alpha=1.35, beta=8))
        variants.append(self._preprocess_white_boost(bgr_image))
        variants.append(self._preprocess_inverted(bgr_image))
        return variants

    def _predict_once(self, bgr_image: np.ndarray) -> list[PieceDetection]:
        if bgr_image is None or bgr_image.size == 0:
            return []

        results = self.model.predict(
            bgr_image,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            device=self.device,
            verbose=False,
        )
        if not results:
            return []

        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            return []

        detections: list[PieceDetection] = []
        names = result.names
        for box, score, cls_id in zip(
            result.boxes.xyxy.tolist(),
            result.boxes.conf.tolist(),
            result.boxes.cls.tolist(),
        ):
            x1, y1, x2, y2 = box
            detections.append(
                PieceDetection(
                    bbox=(x1, y1, x2, y2),
                    center=((x1 + x2) / 2.0, (y1 + y2) / 2.0),
                    score=float(score),
                    class_id=int(cls_id),
                    class_name=str(names[int(cls_id)]),
                )
            )
        return detections

    def detect(self, bgr_image: np.ndarray) -> list[PieceDetection]:
        if bgr_image is None or bgr_image.size == 0:
            return []

        if not self.multi_pass:
            image = self._preprocess(bgr_image) if self.preprocess else bgr_image
            return self._predict_once(image)

        merged: list[PieceDetection] = []
        for variant in self._image_variants(bgr_image):
            merged.extend(self._predict_once(variant))
        return merge_detections(merged, iou_threshold=self.iou)

    def annotate(self, bgr_image: np.ndarray, detections: list[PieceDetection]) -> np.ndarray:
        import cv2

        annotated = bgr_image.copy()
        for det in detections:
            label = f'{det.class_name} {det.score:.2f}'
            if det.polygon and len(det.polygon) >= 3:
                pts = np.array(det.polygon, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(annotated, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                x1, y1 = pts[0][0]
            else:
                x1, y1, x2, y2 = map(int, det.bbox)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                annotated,
                label,
                (int(x1), max(0, int(y1) - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
        return annotated
