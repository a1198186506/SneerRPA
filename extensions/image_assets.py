"""Portable PNG templates, ready for later image matching nodes."""
import base64
import binascii
from datetime import datetime, timezone
import io
import uuid

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
PREFIX = 'data:image/png;base64,'


def encode_crop(screenshot, box, origin=(0, 0)):
    left, top, right, bottom = map(int, box)
    if not (0 <= left < right <= screenshot.width and 0 <= top < bottom <= screenshot.height):
        raise ValueError('截图区域超出屏幕范围')
    if right-left < 2 or bottom-top < 2:
        raise ValueError('请拖动框选至少 2 × 2 像素的区域')
    image = screenshot.crop((left, top, right, bottom)).convert('RGB')
    output = io.BytesIO()
    image.save(output, format='PNG')
    raw = output.getvalue()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('图片超过 8 MB，请缩小截图区域')
    return {'id': str(uuid.uuid4()), 'name': '新图片', 'format': 'png',
        'data_url': PREFIX + base64.b64encode(raw).decode('ascii'), 'width': image.width, 'height': image.height,
        'capture_rect': {'x': origin[0]+left, 'y': origin[1]+top, 'width': image.width, 'height': image.height},
        'captured_at': datetime.now(timezone.utc).isoformat()}


def validate_image(asset):
    from PIL import Image
    if not isinstance(asset, dict) or not isinstance(asset.get('id'), str) or not asset['id'] or not isinstance(asset.get('name'), str) or not asset['name'].strip():
        raise ValueError('图片 ID 或名称无效')
    if asset.get('format') != 'png':
        raise ValueError('图片素材必须使用 PNG 格式')
    for key in ('width','height'):
        if type(asset.get(key)) is not int or not 2 <= asset[key] <= 32768:
            raise ValueError('图片尺寸无效')
    if asset['width'] * asset['height'] > 64_000_000:
        raise ValueError('图片像素尺寸过大，请缩小区域')
    data_url = asset.get('data_url')
    if not isinstance(data_url, str) or not data_url.startswith(PREFIX) or len(data_url) > MAX_IMAGE_BYTES*4//3+128:
        raise ValueError('图片数据无效或超过 8 MB')
    try:
        raw = base64.b64decode(data_url[len(PREFIX):], validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('图片超过 8 MB')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'PNG' or image.size != (asset['width'],asset['height']):
                raise ValueError('图片实际尺寸或格式与记录不一致')
            image.verify()
    except (binascii.Error, OSError, SyntaxError) as exc:
        raise ValueError('PNG 图片内容无效') from exc
    rect = asset.get('capture_rect')
    if rect is not None and (not isinstance(rect, dict) or any(type(rect.get(key)) is not int for key in ('x','y','width','height'))
            or (rect['width'],rect['height']) != (asset['width'],asset['height'])):
        raise ValueError('图片捕获区域无效')
    return len(raw)
