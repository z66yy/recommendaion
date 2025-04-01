from django import template
import json

register = template.Library()

@register.filter
def split(value, arg):
    """
    将一个字符串分割成列表，或者返回已经是列表的值
    用法: {{ value|split:"," }}
    """
    if value:
        if isinstance(value, str):
            return value.split(arg)
        elif isinstance(value, list):
            return value  # 如果已经是列表，直接返回
    return []

@register.filter
def to_json(value):
    """
    将Python对象转换为JSON字符串
    用法: {{ value|to_json }}
    """
    try:
        return json.dumps(value)
    except Exception:
        return '{}' 