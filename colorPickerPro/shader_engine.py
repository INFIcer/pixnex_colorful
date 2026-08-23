"""
shader_engine.py — 基于 QOpenGLContext + GLSL 着色器的 GPU 滤镜引擎
=================================================================
- 通过 QOpenGLContext + QOffscreenSurface 提供离屏 OpenGL 上下文，无需可见窗口
- 将 numpy 图像（BGR 或灰度）上传为 RGBA 纹理
- 经片段着色器逐像素处理，从 FBO 读回为 numpy 数组
- GLSL_COMMON 提供公共着色器函数（灰度 / HSV / HLS / CIELAB 等）
- 引擎不可用时 available() 返回 False，上层可安全回退到 CPU
"""

import numpy as np

from PySide6.QtGui import QImage, QOpenGLContext, QOffscreenSurface, QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram,
    QOpenGLTexture, QOpenGLVertexArrayObject,
)
from PySide6.QtWidgets import QApplication


_VERTEX_SRC = """\
#version 330 core
layout(location = 0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = a_pos * 0.5 + 0.5;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

# PySide6 的 QOpenGLFunctions 不暴露 GL_* 常量，这里使用标准 OpenGL 常量值
_GL_TEXTURE_2D = 0x0DE1
_GL_TEXTURE0 = 0x84C0
_GL_UNPACK_ALIGNMENT = 0x0CF5
_GL_RGBA = 0x1908
_GL_RGBA8 = 0x8058
_GL_UNSIGNED_BYTE = 0x1401
_GL_FLOAT = 0x1406
_GL_TRIANGLES = 0x0004
_GL_COLOR_BUFFER_BIT = 0x4000

GLSL_COMMON = """\
#version 330 core
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_tex;
uniform vec2 u_resolution;

float gray_of(vec2 uv) {
    vec3 c = texture(u_tex, uv).rgb;
    return dot(c, vec3(0.299, 0.587, 0.114)) * 255.0;
}

vec3 srgb_to_linear(vec3 c) {
    return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c));
}

vec3 rgb_to_xyz(vec3 c) {
    vec3 lin = srgb_to_linear(c);
    return vec3(
        0.4124564 * lin.r + 0.3575761 * lin.g + 0.1804375 * lin.b,
        0.2126729 * lin.r + 0.7151522 * lin.g + 0.0721750 * lin.b,
        0.0193339 * lin.r + 0.1191920 * lin.g + 0.9503041 * lin.b
    );
}

vec3 xyz_to_lab(vec3 xyz) {
    vec3 t = xyz / vec3(0.95047, 1.0, 1.08883);
    vec3 cbrt_t = pow(t, vec3(1.0 / 3.0));
    vec3 ft = mix(t / 0.1284185493 + 0.1379310345, cbrt_t, step(vec3(0.0088564516), t));
    return vec3(116.0 * ft.y - 16.0, 500.0 * (ft.x - ft.y), 200.0 * (ft.y - ft.z));
}

vec3 rgb_to_lab(vec3 c) {
    return xyz_to_lab(rgb_to_xyz(c));
}

float rgb_to_hsv_s(vec3 c) {
    float mx = max(c.r, max(c.g, c.b));
    float mn = min(c.r, min(c.g, c.b));
    float df = mx - mn;
    return mx > 0.0 ? df / mx : 0.0;
}

float rgb_to_hls_l(vec3 c) {
    float mx = max(c.r, max(c.g, c.b));
    float mn = min(c.r, min(c.g, c.b));
    return (mx + mn) * 0.5;
}
"""


class ShaderEngine:
    """离屏 GLSL 滤镜引擎（单例）。"""

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._context = None
        self._surface = None
        self._ready = False
        self._error = None
        self._programs = {}
        self._texture = None
        self._vao = None
        self._vbo = None
        self._fbo = None
        self._fbo_size = (0, 0)
        if QApplication.instance() is None:
            self._error = "ShaderEngine 需要 QApplication 实例"
            return
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(0)
        self._context = QOpenGLContext()
        self._context.setFormat(fmt)
        self._surface = QOffscreenSurface()
        self._surface.setFormat(fmt)

    def available(self):
        if self._ready:
            return True
        if self._error:
            return False
        try:
            self._ensure_gl()
        except Exception:
            return False
        return self._ready

    def error(self):
        return self._error

    def _make_current(self):
        if not self._context.create():
            raise RuntimeError("QOpenGLContext 创建失败")
        self._surface.create()
        if not self._surface.isValid():
            raise RuntimeError("QOffscreenSurface 创建失败")
        if not self._context.makeCurrent(self._surface):
            raise RuntimeError("makeCurrent 失败")

    def _context_funcs(self):
        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            raise RuntimeError("无当前 OpenGL 上下文")
        return ctx.functions()

    def _ensure_gl(self):
        if self._ready:
            return
        try:
            self._make_current()
            funcs = self._context_funcs()

            self._vao = QOpenGLVertexArrayObject()
            if not self._vao.create():
                raise RuntimeError("VAO 创建失败")
            self._vao.bind()
            self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            if not self._vbo.create():
                raise RuntimeError("VBO 创建失败")
            self._vbo.bind()
            verts = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype=np.float32)
            self._vbo.allocate(verts.tobytes(), verts.nbytes)
            self._vbo.release()
            self._vao.release()

            self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
            if not self._texture.create():
                raise RuntimeError("纹理创建失败")
            self._texture.setMinificationFilter(QOpenGLTexture.Nearest)
            self._texture.setMagnificationFilter(QOpenGLTexture.Nearest)
            self._texture.setWrapMode(QOpenGLTexture.ClampToEdge)

            self._ready = True
        except Exception as ex:
            self._error = f"GPU 引擎初始化失败: {ex}"
            self._ready = False
            raise RuntimeError(self._error)

    def _ensure_fbo(self, w, h):
        if self._fbo is not None and self._fbo_size == (w, h):
            return
        self._fbo = QOpenGLFramebufferObject(w, h)
        self._fbo_size = (w, h)

    def _program(self, fragment_src):
        prog = self._programs.get(fragment_src)
        if prog is not None:
            return prog
        prog = QOpenGLShaderProgram()
        if not prog.addShaderFromSourceCode(QOpenGLShader.Vertex, _VERTEX_SRC):
            raise RuntimeError(f"顶点着色器编译失败: {prog.log()}")
        if not prog.addShaderFromSourceCode(QOpenGLShader.Fragment, fragment_src):
            raise RuntimeError(f"片段着色器编译失败: {prog.log()}")
        if not prog.link():
            raise RuntimeError(f"着色器链接失败: {prog.log()}")
        self._programs[fragment_src] = prog
        return prog

    @staticmethod
    def _set_uniforms(funcs, program, uniforms):
        for name, value in (uniforms or {}).items():
            loc = program.uniformLocation(name)
            if loc < 0:
                continue
            if isinstance(value, bool):
                funcs.glUniform1i(loc, int(value))
            elif isinstance(value, (int, float)):
                funcs.glUniform1f(loc, float(value))
            elif isinstance(value, (tuple, list)):
                vals = [float(v) for v in value]
                if len(vals) == 2:
                    funcs.glUniform2f(loc, vals[0], vals[1])
                elif len(vals) == 3:
                    funcs.glUniform3f(loc, vals[0], vals[1], vals[2])
                elif len(vals) == 4:
                    funcs.glUniform4f(loc, vals[0], vals[1], vals[2], vals[3])

    def apply(self, fragment_src, img, uniforms=None, gray=False):
        """运行片段着色器处理图像。

        img 支持 (H,W) 灰度或 (H,W,3) BGR uint8。
        gray=True 时返回 (H,W) uint8（取红通道），否则返回 (H,W,3) BGR uint8。
        """
        self._ensure_gl()
        img = np.ascontiguousarray(img)
        if img.ndim == 2:
            h, w = img.shape
            data = np.empty((h, w, 4), dtype=np.uint8)
            data[..., 0] = img
            data[..., 1] = img
            data[..., 2] = img
            data[..., 3] = 255
        elif img.ndim == 3 and img.shape[2] >= 3:
            h, w = img.shape[:2]
            data = np.empty((h, w, 4), dtype=np.uint8)
            data[..., 0] = img[..., 2]
            data[..., 1] = img[..., 1]
            data[..., 2] = img[..., 0]
            data[..., 3] = 255
        else:
            raise ValueError(f"不支持的图像形状: {img.shape}")
        data = np.ascontiguousarray(data)

        qi = None
        try:
            if not self._context.makeCurrent(self._surface):
                raise RuntimeError("makeCurrent 失败")
            funcs = self._context_funcs()
            program = self._program(fragment_src)
            self._ensure_fbo(w, h)

            self._texture.bind(0)
            funcs.glActiveTexture(_GL_TEXTURE0)
            funcs.glPixelStorei(_GL_UNPACK_ALIGNMENT, 1)
            funcs.glTexImage2D(_GL_TEXTURE_2D, 0, _GL_RGBA8, w, h, 0,
                               _GL_RGBA, _GL_UNSIGNED_BYTE, data.tobytes())
            self._texture.release()

            self._fbo.bind()
            funcs.glViewport(0, 0, w, h)
            funcs.glClearColor(0.0, 0.0, 0.0, 1.0)
            funcs.glClear(_GL_COLOR_BUFFER_BIT)
            program.bind()
            program.setUniformValue(program.uniformLocation("u_tex"), 0)
            program.setUniformValue(program.uniformLocation("u_resolution"), float(w), float(h))
            self._set_uniforms(funcs, program, uniforms)
            self._texture.bind(0)
            self._vao.bind()
            self._vbo.bind()
            program.enableAttributeArray(0)
            program.setAttributeBuffer(0, _GL_FLOAT, 0, 2)
            funcs.glDrawArrays(_GL_TRIANGLES, 0, 3)
            self._vbo.release()
            self._vao.release()
            self._texture.release()
            program.release()
            qi = self._fbo.toImage()
            self._fbo.release()
        finally:
            self._context.doneCurrent()

        if qi is None or qi.isNull():
            raise RuntimeError("FBO 读取失败")
        qi = qi.convertToFormat(QImage.Format_RGBA8888)
        ptr = qi.constBits()
        if hasattr(ptr, "setsize"):
            ptr.setsize(qi.sizeInBytes())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 4)
        if gray:
            return arr[::-1, :, 0].copy()
        return arr[::-1, :, [2, 1, 0]].copy()
