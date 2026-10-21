"""Decode real image data, strip metadata, and bound what is stored/sent."""
import base64
import binascii
import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 20_000_000

def prepare(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('Фото має бути не більше 6 МБ.')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('Підтримуються JPEG, PNG та WebP.')
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError('Фото має бути не більше 20 мегапікселів.')
                if getattr(original, 'n_frames', 1) != 1:
                    raise ValueError('Виберіть одне нерухоме фото.')
                original.load()
                frame = ImageOps.exif_transpose(original).convert('RGB')
                frame.thumbnail((1600, 1600))
                # Copy pixel data only: no EXIF, GPS, comments or ICC payload.
                clean = Image.new('RGB', frame.size)
                clean.paste(frame)
                output = io.BytesIO()
                clean.save(output, format='JPEG', quality=88)
                return output.getvalue()
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Не вдалося прочитати фото. Оберіть справний JPEG, PNG або WebP.') from exc
