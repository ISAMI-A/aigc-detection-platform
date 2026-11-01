"""文件名解析：从"整改图/暗访图"命名中提取 UUID、地点、编号等信息。

文件名格式：
    2020_2_{UUID}_{地点}_{序号}_{整改图|暗访图}_{编号}.png
    2020_3_{UUID}_{地点}_{序号}_{整改图|暗访图}_{编号}.png
"""

import re
from pathlib import Path
from typing import Optional


def parse_filename(path: str) -> Optional[dict]:
    """
    解析文件名，返回结构化信息。

    文件名格式：
      2020_2_{UUID}_{地点}_{序号}_{整改图|暗访图}_{编号}.png
      2020_3_{UUID}_{地点}_{序号}_{整改图|暗访图}_{编号}.png
    """
    name = Path(path).stem

    # 提取 UUID
    uuid_pat = r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    uuid_match = re.search(uuid_pat, name)
    if not uuid_match:
        return None
    uuid = uuid_match.group(1)

    # 提取图片类型
    type_match = re.search(r'(整改图|暗访图)', name)
    if not type_match:
        return None
    photo_type = type_match.group(1)

    # 提取编号（整改图_0 中的 0）
    num_match = re.search(rf'{re.escape(photo_type)}_(\d+)', name)
    photo_num = num_match.group(1) if num_match else "0"

    # 提取地点名称：UUID 之后、序号之前的文本
    after_uuid = name[uuid_match.end():]
    location_match = re.match(r'_(.+?)_(\d+)_(?:整改图|暗访图)', after_uuid)
    location = location_match.group(1) if location_match else "未知地点"
    location_idx = location_match.group(2) if location_match else "0"

    return {
        'path': path,
        'uuid': uuid,
        'location': location,
        'idx': location_idx,
        'photo_type': photo_type,
        'photo_num': photo_num,
        'filename': Path(path).name,
    }
