# -*- coding: utf-8 -*-
"""感知管道（通用版）：截屏 / 摄像头一帧 / 本地人脸闸门。

从知夏桌面端提炼。两处与私有版的差别：
- 人脸基准照**由调用方传入**（私有版绑定了主人的基准照目录）；
- cv2 为**可选依赖**（延迟导入）——没装 opencv 时只影响感知，不影响本包其他组件。

人脸闸门为什么存在：让 VLM"看图认人"是看图说话式的相似度——没有阈值、无法校准，
实测会把别人说成"看着像你"。本地人脸识别 = 检出 → SFace 特征 → 与基准照算余弦
→ 过阈值才认。**分数可标定**（"宁可漏认不可错认"就调高阈值）。

模型：opencv_zoo 的 YuNet（检测）+ SFace（特征），onnx 放 models_dir 即可，
纯本地、不联网。
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 0.363      # SFace 官方余弦阈值（越大越严）
DET_MAX_SIDE = 1024            # 超大原图会误检出假脸且慢，检测前缩到长边 ≤1024
DET_SCORE_THRESHOLD = 0.6


@dataclass
class FaceVerdict:
    n_faces: int
    best_score: float     # 所有脸里最高的余弦相似度（没脸 = -1）
    matched: bool
    threshold: float


def grab_screen(exclude_rect: tuple[int, int, int, int] | None = None,
                max_side: int = 1280, jpeg_quality: int = 72) -> bytes:
    """截全屏 → 把 exclude_rect 区域涂黑（伴侣窗口自己，避免它入镜）
    → 缩放 → JPEG 字节。需要 Pillow。"""
    from PIL import Image, ImageDraw, ImageGrab

    img = ImageGrab.grab()
    if exclude_rect:
        from PIL import ImageDraw as D
        x, y, w, h = exclude_rect
        D.Draw(img).rectangle([x, y, x + w, y + h], fill=(20, 20, 25))
    if img.width > max_side:
        ratio = max_side / img.width
        img = img.resize((max_side, int(img.height * ratio)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    return buf.getvalue()


def capture_camera(camera_index: int = 0) -> bytes | None:
    """抓摄像头一帧 → JPEG 字节。cv2 可选：没装返回 None（不影响其他功能）。"""
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(camera_index)
    try:
        ok, frame = cap.read()
        if not ok:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else None
    finally:
        cap.release()


class FaceGate:
    """本地人脸闸门。reference_images 为基准照 JPEG 字节列表（单人照片理应取最大脸）。

    cv2 缺失或模型文件缺失时，构造抛异常——调用方决定降级方式。
    """

    def __init__(self, reference_images: list[bytes], models_dir,
                 threshold: float = DEFAULT_THRESHOLD) -> None:
        import cv2
        import numpy as np
        self._cv2, self._np = cv2, np
        self.threshold = float(threshold)
        models_dir = Path(models_dir)
        det_p = models_dir / "face_detection_yunet_2023mar.onnx"
        rec_p = models_dir / "face_recognition_sface_2021dec.onnx"
        for p in (det_p, rec_p):
            if not p.is_file():
                raise FileNotFoundError(f"缺模型文件：{p}（opencv_zoo 的 YuNet / SFace）")
        self._detector = cv2.FaceDetectorYN.create(
            str(det_p), "", (320, 320), score_threshold=DET_SCORE_THRESHOLD,
            nms_threshold=0.3, top_k=5000)
        self._recognizer = cv2.FaceRecognizerSF.create(str(rec_p), "")
        self._refs = [self._embedding_of_image(img) for img in reference_images]
        self._refs = [e for e in self._refs if e is not None]

    def _decode(self, image_bytes: bytes):
        buf = self._np.frombuffer(image_bytes, dtype=self._np.uint8)
        img = self._cv2.imdecode(buf, self._cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("图片解码失败（不是有效图片字节）")
        return img

    def _detect(self, image):
        cv2, np = self._cv2, self._np
        h, w = image.shape[:2]
        scale = 1.0
        if max(h, w) > DET_MAX_SIDE:
            scale = DET_MAX_SIDE / float(max(h, w))
            image = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))))
        self._detector.setInputSize((image.shape[1], image.shape[0]))
        _ok, faces = self._detector.detect(image)
        if faces is None:
            return np.empty((0, 15), dtype=np.float32)
        if scale != 1.0:
            faces = faces.copy()
            faces[:, 0:14] /= scale        # 框和关键点都映射回原图
        return faces

    def _embedding_of_image(self, image_bytes: bytes):
        img = self._decode(image_bytes)
        faces = self._detect(img)
        if len(faces) == 0:
            return None
        biggest = max(faces, key=lambda f: float(f[2] * f[3]))   # 基准照取最大脸
        aligned = self._recognizer.alignCrop(img, biggest)
        return self._recognizer.feature(aligned)

    def verify(self, image_bytes: bytes) -> FaceVerdict:
        """判定一张图里有没有"基准照那个人"。无脸/无基准 → matched=False。"""
        img = self._decode(image_bytes)
        faces = self._detect(img)
        const = int(getattr(self._cv2, "FaceRecognizerSF_FR_COSINE",
                            getattr(self._cv2.FaceRecognizerSF, "FR_COSINE")))
        best, n = -1.0, int(len(faces))
        for face in faces:
            aligned = self._recognizer.alignCrop(img, face)
            feat = self._recognizer.feature(aligned)
            for ref in self._refs:
                s = float(self._recognizer.match(ref, feat, const))
                best = max(best, s)
        return FaceVerdict(n_faces=n, best_score=best,
                           matched=best >= self.threshold and n > 0,
                           threshold=self.threshold)
