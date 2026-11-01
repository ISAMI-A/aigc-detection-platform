from PIL import Image
from PIL.ExifTags import TAGS


def analyze_exif(image_path: str) -> dict:
    result = {
        "has_exif": False,
        "camera_make": None,
        "camera_model": None,
        "software": None,
        "has_gps": False,
        "confidence": 0.3,
        "flags": ["无EXIF信息"]
    }

    try:
        img = Image.open(image_path)
        # TIFF/PNG 等格式没有 _getexif，使用 getexif() 公共 API
        try:
            exif = img.getexif()
        except AttributeError:
            exif = img._getexif() if hasattr(img, "_getexif") else None
    except Exception:
        return result

    if not exif:
        return result

    result["has_exif"] = True
    result["confidence"] = 0.5
    result["flags"] = []

    for tag_id, value in exif.items():
        tag = TAGS.get(tag_id, tag_id)
        if tag == "Make":
            result["camera_make"] = str(value).strip()
        elif tag == "Model":
            result["camera_model"] = str(value).strip()
        elif tag == "Software":
            result["software"] = str(value).strip()
        elif tag == "GPSInfo":
            result["has_gps"] = True

    if result["camera_make"] and result["camera_model"]:
        result["confidence"] = 0.9

    sw = (result["software"] or "").lower()
    ai_tools = ["photoshop", "gimp", "stable diffusion", "midjourney",
                "dall-e", "firefly", "comfyui", "invokeai", "adobe"]
    if any(k in sw for k in ai_tools):
        result["confidence"] = 0.1
        result["flags"].append(f"检测到编辑软件: {result['software']}")

    return result
