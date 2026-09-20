"""主题引擎：深/浅双主题 token + QSS 生成（2026-09-20 视觉翻新）。

设计决策（impeccable 拍板：双主题 + 蓝紫渐变 + 克制微动）：
- 中性色冷调 tint（chroma ~0.006 的 teal 偏移），拒绝死灰
- 强调色 teal→sky 渐变（#14B8A6 → #0EA5E9），仅用于主按钮/选中态/滑杆
- 深色为主（长时间挂屏工具），浅色完整可达（WCAG AA 正文 4.5:1）
- 组件层次：背景 < 卡片 < 悬浮（elevation 三级），卡片用 1px 边框 + 微投影替代生硬分块
- QSS 不支持 oklch/color-mix，色值为 OKLCH 设计后折算的 hex
"""

from __future__ import annotations

import os
import tempfile


def eye_icons(t: dict) -> dict:
    """极简几何眼睛图标（睁/闭两态 PNG）。

    抽象设计：睁眼 = 杏仁形轮廓（两段弧）+ 中心瞳孔圆点；
    闭眼 = 一条向下弧线。无睫毛无眼白血丝，纯几何不吓人。
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

    scale = 2
    w, h = 18, 12
    color = QColor(t["fg_dim"])

    def _paint(kind: str) -> QPixmap:
        pm = QPixmap(w * scale, h * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if kind == "open":
            # 杏仁形：上下两段弧
            path = QPainterPath()
            top = QPainterPath()
            top.moveTo(2.5, 6)
            top.quadTo(9, 0.5, 15.5, 6)
            bottom = QPainterPath()
            bottom.moveTo(2.5, 6)
            bottom.quadTo(9, 11.5, 15.5, 6)
            path = top
            p.drawPath(path)
            p.drawPath(bottom)
            # 瞳孔
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(9, 6), 2.2, 2.2)
        else:  # closed：一条下弧
            path = QPainterPath()
            path.moveTo(3, 4.5)
            path.quadTo(9, 10, 15, 4.5)
            p.drawPath(path)
        p.end()
        path_str = os.path.join(
            tempfile.gettempdir(),
            f"qlt_eye_{kind}_{t['name']}_{t['fg_dim'].lstrip('#')}.png",
        )
        pm.save(path_str, "PNG")
        return path_str.replace("\\", "/")

    return {"open": _paint("open"), "closed": _paint("closed")}


def sun_moon_icons(t: dict) -> dict:
    """太阳/月亮主题切换图标（QPainter 画 PNG，主题色）。

    Windows 14px emoji 渲染不可靠（☀ 塌成 3px 彩点，与下拉箭头同病根）。
    第二版教训：细线条几何（1.6px 描边）在 16px 下太抽象看不懂；
    本版改**实心填充**经典造型——太阳=实心盘+8 粗光线、月亮=实心月牙，
    小尺寸辨识度优先。
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

    scale = 2
    size = 18
    color = QColor(t["fg_dim"])

    def _sun() -> QPixmap:
        pm = QPixmap(size * scale, size * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        c = size / 2
        r = 4.0  # 日心半径
        # 实心日盘
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(c, c), r, r)
        # 8 条粗光线（实心短线，RoundCap 端点圆润）
        import math
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        for i in range(8):
            ang = math.radians(i * 45)
            r1 = r + 2.0
            r2 = r + 3.8 if i % 2 == 0 else r + 3.2
            p.drawLine(
                QPointF(c + r1 * math.cos(ang), c + r1 * math.sin(ang)),
                QPointF(c + r2 * math.cos(ang), c + r2 * math.sin(ang)),
            )
        p.end()
        return pm

    def _moon() -> QPixmap:
        pm = QPixmap(size * scale, size * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        # 实心月牙：大圆（月轮）挖去偏移小圆（阴影）——路径填充差集。
        # 经典粗月牙：月轮 r8 撑满画布，挖洞 r6.1 右上偏移，最宽 ~7px（≈40%）
        outer = QPainterPath()
        outer.addEllipse(QRectF(1.5, 1.5, 16.0, 16.0))   # 月轮 r8
        inner = QPainterPath()
        inner.addEllipse(QRectF(7.6, 0.6, 12.2, 12.2))   # 挖洞 r6.1 右上偏移
        crescent = outer.subtracted(inner)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(crescent)
        p.end()
        return pm

    out = {}
    for kind, fn in (("sun", _sun), ("moon", _moon)):
        pm = fn()
        path_str = os.path.join(
            tempfile.gettempdir(),
            f"qlt_themeicon_{kind}_{t['name']}_{t['fg_dim'].lstrip('#')}.png",
        )
        pm.save(path_str, "PNG")
        out[kind] = path_str.replace("\\", "/")
    return out


def _arrow_png(t: dict) -> str:
    """运行时用 QPainter 画下拉箭头三角（主题色，2x 抗锯齿），存临时 PNG。

    Qt QSS 的 border 三角法在 Windows 风格下渲染成实心矩形（实测），
    只能用真图片。路径含主题色哈希，切主题自动换文件。
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF

    scale = 2  # 2x 采样，高分屏清晰
    w, h = 12, 8
    pm = QPixmap(w * scale, h * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(t["fg_dim"]))
    p.setPen(Qt.NoPen)
    p.drawPolygon(QPolygonF([
        QPointF(1.5, 2.5), QPointF(10.5, 2.5), QPointF(6.0, 6.5),
    ]))
    p.end()
    path = os.path.join(
        tempfile.gettempdir(),
        f"qlt_arrow_{t['name']}_{t['fg_dim'].lstrip('#')}.png",
    )
    pm.save(path, "PNG")
    return path.replace("\\", "/")

# ---------- Token ----------
DARK = {
    "name": "dark",
    # 冷调中性阶（teal 微 tint）
    "bg": "#101517",          # 窗口背景（最深，teal tint）
    "surface": "#161C1E",     # 卡片
    "surface2": "#1D2427",    # 悬浮/输入框/下拉
    "hover": "#242D30",       # 交互悬停
    "border": "#28333A",      # 卡片描边（可见对比）
    "border_strong": "#35434C",
    "fg": "#E6EEF0",          # 主文字
    "fg_dim": "#96A8AE",      # 次级文字
    "fg_faint": "#5E7479",    # 占位/禁用
    # 强调（渐变两端 + 纯色态）
    "accent": "#14B8A6",      # teal 500
    "accent2": "#0EA5E9",     # sky 500
    "accent_hover": "#2DD4BF",
    "accent_soft": "rgba(20,184,166,0.16)",   # 选中底/焦点环
    "on_accent": "#FFFFFF",
    # 语义
    "ok": "#34D399",
    "bad": "#F87171",
    # 阴影（卡片）
    "card_shadow": "rgba(0,0,0,0.45)",
}

LIGHT = {
    "name": "light",
    "bg": "#F2F5F6",          # 窗口背景（冷白，teal tint）
    "surface": "#FFFFFF",     # 卡片
    "surface2": "#F5F6FA",    # 输入框/下拉
    "hover": "#ECEDF4",
    "border": "#E3E5EE",
    "border_strong": "#D3D6E2",
    "fg": "#1A1D28",
    "fg_dim": "#5D6474",
    "fg_faint": "#9BA1B1",
    "accent": "#0D9488",
    "accent2": "#0284C7",
    "accent_hover": "#14B8A6",
    "accent_soft": "rgba(13,148,136,0.10)",
    "on_accent": "#FFFFFF",
    "ok": "#0E9F6E",
    "bad": "#DC2626",
    "card_shadow": "rgba(26,29,40,0.10)",
}

FONT = "'Microsoft YaHei UI', 'Segoe UI', sans-serif"

# ---------- 圆角体系（全局统一，px）----------
# 设计规则：以 2px 为步进的单一梯度；控件越小圆角越小，层级越高圆角越大。
R_MICRO = 3    # 微件：滑杆轨道、滚动条滑块（细长条，微圆即可）
R_SMALL = 6    # 小件：复选框、表格单元格选中态
R_INPUT = 8    # 气泡提示、图标按钮
R_CTRL = 10    # 标准控件：按钮、输入框、下拉（含弹层）
R_PRIMARY = 11  # 主按钮（略大于标准控件，强调层级）
R_CARD = 14    # 容器：卡片、表格、字幕窗小按钮同档
R_WINDOW = 16  # 窗口级：悬浮字幕条主体
R_PILL = 11    # 胶囊标签（小高度标签的全圆端，=标签高度一半）


def get(theme: str) -> dict:
    return LIGHT if theme == "light" else DARK


# ---------- QSS 生成器 ----------
def console_qss(t: dict) -> str:
    """控制台完整样式表（4px 基数网格：4/8/12/16/20）。"""
    return f"""
    QWidget {{
        background: {t['bg']}; color: {t['fg']};
        font-family: {FONT}; font-size: 13px;
    }}
    /* QLabel 不吃背景填充：全局 QWidget 背景会让卡片上的 QLabel 渲染成
       窗口底色直角色块（数值/key提示行实锤），统一透明回归文字本色 */
    QLabel {{ background: transparent; }}
    QLabel#dim {{ color: {t['fg_dim']}; font-size: 11px; }}
    /* 字段标签：用只读按钮实现（QLabel 的 QSS background 不裁圆角，Qt 已知行为）。
       选择器同时匹配 #fieldLabel 与 #dim（labeled_slider 里 setObjectName("dim")
       会覆盖 fieldLabel，两处命名都收口到同一胶囊样式） */
    QPushButton#fieldLabel, QPushButton#dim {{
        background: {t['surface2']}; color: {t['fg_dim']};
        font-size: 12px; font-weight: 400;
        border: none;
        border-radius: {R_PILL}px;
        padding: 4px 2px;
    }}
    QPushButton#fieldLabel:hover, QPushButton#dim:hover {{ background: {t['surface2']}; }}
    QPushButton#fieldLabel:pressed, QPushButton#dim:pressed {{ background: {t['surface2']}; }}
    QPushButton#fieldLabel:focus, QPushButton#dim:focus {{ border: none; }}
    /* 切换胶囊（原复选框）：圆角胶囊底，选中 accent_soft + 左侧圆点状态 */
    QPushButton#togglePill {{
        background: {t['surface2']}; color: {t['fg_dim']};
        font-size: 12px; font-weight: 400;
        border: none;
        border-radius: {R_PILL}px;
        padding: 4px 10px;
        text-align: left;
    }}
    QPushButton#togglePill:hover {{ background: {t['hover']}; }}
    QPushButton#togglePill:checked {{
        background: {t['accent_soft']}; color: {t['accent']};
        font-weight: 600;
    }}
    QPushButton#togglePill:focus {{ border: none; }}
    /* 数值标签（滑杆右侧 1.0x/90%/820px）：胶囊化——QLabel 背景不裁圆角
       （全局 QWidget 背景曾把它渲染成直角色块），改用按钮实现与字段标签成对 */
    QPushButton#val {{
        background: {t['surface2']}; color: {t['fg_dim']};
        font-size: 12px; font-weight: 400;
        border: none;
        border-radius: {R_PILL}px;
        padding: 4px 6px;
        text-align: center;
    }}
    QPushButton#val:hover, QPushButton#val:pressed {{ background: {t['surface2']}; }}
    QPushButton#val:focus {{ border: none; }}
    QLabel#title {{ font-size: 17px; font-weight: 700; letter-spacing: 0.5px; }}
    QLabel#keyHint {{ color: {t['fg_faint']}; font-size: 10.5px; }}

    QFrame#card {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: {R_CARD}px;
    }}

    /* ---- 按钮（统一 8px 圆角 / 500 字重 / 文字居中）---- */
    QPushButton {{
        background: {t['surface2']}; color: {t['fg']};
        border: 2px solid {t['border']};
        border-radius: {R_CTRL}px; padding: 6px 11px;
        font-weight: 500;
        text-align: center;
    }}
    QPushButton:hover {{ background: {t['hover']}; border-color: {t['border_strong']}; }}
    QPushButton:pressed {{ background: {t['border']}; }}
    QPushButton:focus {{ border: 2px solid {t['accent']}; }}
    QPushButton:checked {{
        background: {t['accent_soft']}; color: {t['accent']};
        border: 2px solid {t['accent']};
        font-weight: 600;
    }}
    QPushButton#primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t['accent']}, stop:1 {t['accent2']});
        color: {t['on_accent']};
        border: 2px solid transparent; border-radius: {R_PRIMARY}px;
        font-size: 14px; font-weight: 700;
        padding: 10px; letter-spacing: 2px;
    }}
    QPushButton#primary:focus {{ border: 2px solid {t['on_accent']}; }}
    QPushButton#primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t['accent_hover']}, stop:1 #38BDF8);
    }}
    QPushButton#primary:pressed {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #109A8C, stop:1 #0379C4);
    }}
    QPushButton#primary:disabled {{
        background: {t['surface2']}; color: {t['fg_faint']}; border: none;
    }}
    /* 图标按钮（主题切换/眼睛）：32x32 方形热区 */
    QPushButton#icon {{
        background: transparent; border: none;
        border-radius: {R_INPUT}px; padding: 2px; margin: 0;
        color: {t['fg_dim']}; font-size: 14px;
    }}
    /* 主题切换按钮要求全态无边框：默认/hover/pressed/focus/checked 均不画边框
       （focus 仅保留悬停底色作为反馈，无描边） */
    QPushButton#icon:hover {{ background: {t['hover']}; color: {t['fg']}; }}
    QPushButton#icon:pressed {{ background: transparent; }}
    QPushButton#icon:focus {{ border: none; outline: none; }}
    QPushButton#icon:checked {{ color: {t['accent']}; }}
    QPushButton#icon:checked:hover {{ background: {t['hover']}; }}

    /* ---- 下拉 ---- */
    QComboBox {{
        background: {t['surface2']}; color: {t['fg']};
        border: 2px solid {t['border']};
        border-radius: {R_CTRL}px; padding: 5px 9px;
    }}
    QComboBox:hover {{ border-color: {t['border_strong']}; }}
    QComboBox:focus {{ border-color: {t['accent']}; }}
    QComboBox::drop-down {{
        border: none; width: 24px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{
        image: url({_arrow_png(t)});
        width: 12px; height: 8px;
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {t['surface']}; color: {t['fg']};
        border: 1px solid {t['border_strong']};
        border-radius: {R_CTRL}px; padding: 4px;
        selection-background-color: {t['accent_soft']};
        selection-color: {t['accent']};
        outline: none;
    }}

    /* ---- 输入框 ---- */
    QLineEdit {{
        background: {t['surface2']}; color: {t['fg']};
        border: 2px solid {t['border']};
        border-radius: {R_CTRL}px; padding: 5px 9px;
        selection-background-color: {t['accent']};
        selection-color: {t['on_accent']};
    }}
    QLineEdit:focus {{ border: 2px solid {t['accent']}; background: {t['surface']}; }}

    /* ---- 滑杆 ---- */
    /* 控件本体胶囊化：全局 QWidget 背景会把 QSlider 填成窗口底色直角大色块
       （真机实锤），透明化后自绘胶囊底（surface2 + R_PILL） */
    QSlider {{
        background: {t['surface2']};
        border: none;
        border-radius: {R_PILL}px;
        min-height: 22px;
    }}
    QSlider::groove:horizontal {{
        background: transparent; height: 4px; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t['accent']}, stop:1 {t['accent2']});
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {t['surface']}; border: 2px solid {t['accent']};
        width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ border-color: {t['accent2']}; }}
    QSlider::focus {{ border: none; }}

    /* ---- 复选框 ---- */
    QCheckBox {{ spacing: 8px; color: {t['fg']}; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px; border-radius: 5px;
        border: 2px solid {t['border_strong']};
        background: {t['surface2']};
    }}
    QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
    QCheckBox::indicator:checked {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t['accent']}, stop:1 {t['accent2']});
        border: 2px solid {t['accent']};
    }}

    /* ---- 气泡提示（Qt 默认直角+系统色，全局圆角化）---- */
    QToolTip {{
        background: {t['surface2']}; color: {t['fg']};
        border: 1px solid {t['border_strong']};
        border-radius: {R_INPUT}px; padding: 6px 10px;
    }}
    """


def history_qss(t: dict) -> str:
    """历史窗完整样式表（与控制台同语言）。"""
    return f"""
    QWidget {{
        background: {t['bg']}; color: {t['fg']};
        font-family: {FONT}; font-size: 13px;
    }}
    QLabel#dim {{ color: {t['fg_dim']}; font-size: 11px; }}
    QFrame#card, QTableWidget {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: {R_CARD}px;
    }}
    QPushButton {{
        background: {t['surface2']}; color: {t['fg']};
        border: 2px solid {t['border']};
        border-radius: {R_CTRL}px; padding: 6px 11px; font-weight: 500;
    }}
    QPushButton:hover {{ background: {t['hover']}; border-color: {t['border_strong']}; }}
    QPushButton:focus {{ border: 2px solid {t['accent']}; }}
    QPushButton#accent {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t['accent']}, stop:1 {t['accent2']});
        color: {t['on_accent']}; border: none; font-weight: 600;
    }}
    QPushButton#accent:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t['accent_hover']}, stop:1 #38BDF8);
    }}
    QTableWidget {{
        alternate-background-color: {t['surface2']};
        gridline-color: transparent;
        selection-background-color: {t['accent_soft']};
        selection-color: {t['fg']};
        outline: none;
    }}
    QTableWidget::item {{
        padding: 6px 8px; border-bottom: 1px solid {t['border']};
        border-radius: {R_SMALL}px;
    }}
    QTableWidget::item:selected {{ background: {t['accent_soft']}; border-radius: {R_SMALL}px; }}
    QHeaderView::section {{
        background: {t['surface2']}; color: {t['fg_dim']};
        border: none; border-bottom: 1px solid {t['border_strong']};
        padding: 8px 6px; font-size: 12px; font-weight: 600;
    }}
    QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t['border_strong']}; border-radius: {R_MICRO}px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t['fg_faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['border_strong']}; border-radius: {R_MICRO}px; min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {t['fg_faint']}; }}

    /* ---- 消息弹窗（QMessageBox 默认直角系统样式）---- */
    QMessageBox {{
        background: {t['surface']};
    }}
    QMessageBox QLabel {{ background: transparent; color: {t['fg']}; }}
    QMessageBox QPushButton {{
        background: {t['surface2']}; color: {t['fg']};
        border: 2px solid {t['border']};
        border-radius: {R_CTRL}px; padding: 6px 16px;
        min-width: 64px; font-weight: 500;
    }}
    QMessageBox QPushButton:hover {{
        background: {t['hover']}; border-color: {t['border_strong']};
    }}
    """
