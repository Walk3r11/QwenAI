from io import BytesIO
from PIL import Image

def tiny_png_bytes(index: int=0) -> bytes:
    buf = BytesIO()
    r = 200 + index * 7 % 55 & 255
    g = 100 + index * 11 % 155 & 255
    b = 50 + index * 3 % 200 & 255
    Image.new('RGB', (8, 8), color=(r, g, b)).save(buf, format='PNG')
    return buf.getvalue()

def multipart_image_files(n: int, field_name: str='files') -> list[tuple]:
    return [(field_name, (f'scan{i:02d}.png', tiny_png_bytes(i), 'image/png')) for i in range(n)]