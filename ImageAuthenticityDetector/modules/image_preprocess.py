import os
from PIL import Image, UnidentifiedImageError


class ImagePreprocessError(Exception):
    pass


def preprocess(image_path: str, max_size: int = 2048, temp_dir: str = "./temp") -> str:
    """
    预处理图片：损坏检测、模式转换、尺寸限制。
    返回处理后的临时文件路径。
    """
    os.makedirs(temp_dir, exist_ok=True)

    # 1. 尝试打开（捕获损坏图片）
    try:
        img = Image.open(image_path)
        img.load()  # 强制解码，捕获 truncated 图片
    except UnidentifiedImageError:
        raise ImagePreprocessError("无法识别图片格式，文件可能损坏")
    except OSError as e:
        raise ImagePreprocessError(f"图片文件损坏或无法读取: {e}")

    # 2. 模式转换
    if img.mode == "CMYK":
        img = img.convert("RGB")
    elif img.mode == "RGBA":
        # 透明通道填充白色背景
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # 3. 尺寸限制（保持比例）
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        new_size = (int(w * ratio), int(h * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    # 4. 保存临时文件
    basename = os.path.splitext(os.path.basename(image_path))[0]
    temp_path = os.path.join(temp_dir, f"{basename}_preproc.jpg")
    img.save(temp_path, "JPEG", quality=95)

    return temp_path
