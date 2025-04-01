import json
import ast
import logging

logger = logging.getLogger(__name__)

def parse_image_data(image_str):
    """
    解析电影图片数据，支持多种格式
    """
    if not image_str or image_str == '{}':
        return None
        
    try:
        # 尝试解析JSON
        data = json.loads(image_str)
        return data
    except json.JSONDecodeError:
        try:
            # 尝试解析Python字典字符串
            data = ast.literal_eval(image_str)
            return data
        except (ValueError, SyntaxError):
            # 如果无法解析，尝试从字符串中提取URL
            import re
            urls = re.findall(r'https?://[^\s,\'"]+', image_str)
            if urls:
                return {
                    'large': urls[0],
                    'medium': urls[0],
                    'small': urls[0]
                }
    return None 