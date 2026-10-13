import numpy as np

from colorPickerPro.filter_lib import (
    ImageConvert,
    TextWatermarkEmbedFilter,
    TextWatermarkVerifyFilter,
    _wm_str_to_bit,
)


def _test_image(size=256):
    """生成一张带有梯度纹理的测试图像（BGR uint8）。"""
    y, x = np.mgrid[0:size, 0:size]
    img = np.empty((size, size, 3), dtype=np.uint8)
    img[..., 0] = (x * 255 // size).astype(np.uint8)
    img[..., 1] = (y * 255 // size).astype(np.uint8)
    img[..., 2] = (((x + y) * 255 // (2 * size)) % 256).astype(np.uint8)
    return img


def test_wm_str_to_bit_consistent_with_extract():
    text = "pixnex 盲水印测试"
    bits = _wm_str_to_bit(text)
    assert bits.dtype == np.bool_
    assert bits.size > 0
    assert bits[0]  # bin() 去掉前导 0，首位必为 1


def test_embed_verify_roundtrip():
    img = _test_image()
    text = "hello 世界 watermark 2026"
    pwd_wm, pwd_img = 42, 777

    embed = TextWatermarkEmbedFilter()
    params = embed.exposed_parameters()
    params[0].value = text
    params[1].value = pwd_wm
    params[2].value = pwd_img
    embedded = embed.process_cpu(img)

    assert embedded.shape == img.shape
    assert embedded.dtype == np.uint8
    assert "嵌入成功" in params[3].value

    verify = TextWatermarkVerifyFilter()
    vparams = verify.exposed_parameters()
    vparams[0].value = int(_wm_str_to_bit(text).size)
    vparams[1].value = pwd_wm
    vparams[2].value = pwd_img
    out = verify.process_cpu(embedded)
    assert out.shape == img.shape
    assert text in vparams[3].value


def test_verify_wrong_password_fails():
    img = _test_image()
    text = "secret"
    pwd_wm, pwd_img = 42, 777

    embed = TextWatermarkEmbedFilter()
    params = embed.exposed_parameters()
    params[0].value = text
    params[1].value = pwd_wm
    params[2].value = pwd_img
    embedded = embed.process_cpu(img)

    verify = TextWatermarkVerifyFilter()
    vparams = verify.exposed_parameters()
    vparams[0].value = int(_wm_str_to_bit(text).size)
    vparams[1].value = 999  # 错误的水印密码
    vparams[2].value = pwd_img
    verify.process_cpu(embedded)
    result = vparams[3].value
    if "提取结果：" in result:
        assert text not in result
    else:
        assert "提取失败" in result


def test_embed_empty_text_returns_original():
    img = _test_image()
    embed = TextWatermarkEmbedFilter()
    params = embed.exposed_parameters()
    params[0].value = ""
    out = embed.process_cpu(img)
    assert np.array_equal(out, img)
    assert "请先输入水印文本" in params[3].value


def test_verify_size_exceeds_capacity_returns_original():
    img = _test_image()
    verify = TextWatermarkVerifyFilter()
    params = verify.exposed_parameters()
    params[0].value = 999999
    out = verify.process_cpu(img)
    assert np.array_equal(out, img)
    assert "容量" in params[3].value


def test_embed_preserves_alpha_channel():
    from PySide6.QtGui import QGuiApplication, QImage, QPixmap
    QGuiApplication.instance() or QGuiApplication([])

    h, w = 128, 256
    bgra = np.zeros((h, w, 4), dtype=np.uint8)
    bgra[..., 0] = 200
    bgra[..., 1] = 100
    bgra[..., 2] = 50
    bgra[..., 3] = 255
    bgra[:, w // 2:, 3] = 0  # 右半全透明
    pm = QPixmap.fromImage(QImage(bgra.data, w, h, w * 4, QImage.Format_ARGB32))
    assert pm.hasAlpha()

    bgr = ImageConvert.pixmap_to_numpy(pm)
    alpha = ImageConvert.alpha_from_pixmap(pm)
    assert int((alpha == 0).sum()) == w // 2 * h

    embed = TextWatermarkEmbedFilter()
    params = embed.exposed_parameters()
    params[0].value = "alpha test 2026"
    result = embed.process_cpu(bgr)
    result = ImageConvert.apply_alpha(result, alpha)
    out_pm = ImageConvert.numpy_to_pixmap(result)

    assert out_pm.hasAlpha()
    qi = out_pm.toImage().convertToFormat(QImage.Format_ARGB32)
    arr = np.frombuffer(qi.constBits(), dtype=np.uint8).reshape(h, w, 4)
    assert int((arr[..., 3] == 0).sum()) == int((alpha == 0).sum())
