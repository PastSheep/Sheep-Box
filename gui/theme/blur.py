"""图像高斯模糊工具（纯 Qt 实现，无第三方依赖）。

用于给毛玻璃卡片生成"背景被磨砂"的底图：Qt 的 QSS 不支持 backdrop-filter，
因此采用「抓取卡片区域的背景像素 → 高斯模糊 → 卡片内绘制」的方案。
实现基于 ``QGraphicsBlurEffect`` 离屏渲染，质量档位取 ``QualityHint``。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
)

__all__ = ["blur_image"]


def blur_image(image: QImage, radius: float) -> QImage:
    """对图像做高斯模糊，保持原始设备像素比。

    Args:
        image: 源图（通常是从背景层裁出的切片）。
        radius: 模糊半径（逻辑像素）；``<=0`` 时原样返回。

    Returns:
        模糊后的图像；失败时返回原图。
    """
    if image.isNull() or radius <= 0:
        return image

    dpr = image.devicePixelRatio() or 1.0
    # 统一按物理像素做模糊：先把 dpr 归一化，模糊半径按物理像素放大
    raw = image
    if abs(dpr - 1.0) > 1e-6:
        raw = image.copy()
        raw.setDevicePixelRatio(1.0)

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(raw))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius * dpr)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    scene.setSceneRect(QRectF(0, 0, raw.width(), raw.height()))

    output = QImage(raw.size(), QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    target = QRectF(0, 0, raw.width(), raw.height())
    try:
        scene.render(painter, target, scene.sceneRect())
    finally:
        painter.end()
    scene.clear()
    # 恢复设备像素比，使逻辑尺寸与卡片一致
    output.setDevicePixelRatio(dpr)
    return output
