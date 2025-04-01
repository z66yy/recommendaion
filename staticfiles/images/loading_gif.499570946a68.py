import os
import base64
from PIL import Image, ImageDraw
import io

def create_loading_gif():
    """创建一个简单的加载动画GIF"""
    frames = []
    size = (50, 50)
    center = (25, 25)
    radius = 20
    dot_radius = 4
    
    # 创建8帧的加载动画
    for i in range(8):
        frame = Image.new('RGBA', size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(frame)
        
        # 计算点的位置
        angle = i * 45
        x = center[0] + int(radius * 0.7 * (angle % 90) / 90) * (1 if angle < 180 else -1)
        y = center[1] + int(radius * 0.7 * (angle % 90) / 90) * (1 if angle < 90 or angle >= 270 else -1)
        
        # 绘制点
        alpha = int(255 * (i + 1) / 8)
        draw.ellipse((x-dot_radius, y-dot_radius, x+dot_radius, y+dot_radius), fill=(0, 0, 0, alpha))
        
        frames.append(frame)
    
    # 保存为GIF
    output_path = os.path.join(os.path.dirname(__file__), 'loading.gif')
    frames[0].save(
        output_path,
        format='GIF',
        append_images=frames[1:],
        save_all=True,
        duration=100,
        loop=0,
        transparency=0,
        disposal=2
    )
    
    print(f"加载动画GIF已保存到 {output_path}")
    
    # 创建一个1x1像素的透明GIF (用于默认图片)
    transparent_gif = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    transparent_path = os.path.join(os.path.dirname(__file__), 'transparent.gif')
    transparent_gif.save(transparent_path, format='GIF')
    
    print(f"透明GIF已保存到 {transparent_path}")
    
    # 创建默认海报图片
    default_poster = Image.new('RGB', (300, 450), (240, 240, 240))
    draw = ImageDraw.Draw(default_poster)
    
    # 绘制文字
    text = "无图片"
    draw.text((150, 225), text, fill=(100, 100, 100))
    
    # 绘制边框
    draw.rectangle([(0, 0), (299, 449)], outline=(200, 200, 200), width=1)
    
    # 保存
    default_path = os.path.join(os.path.dirname(__file__), 'default-poster.jpg')
    default_poster.save(default_path, format='JPEG', quality=80)
    
    print(f"默认海报图片已保存到 {default_path}")

if __name__ == "__main__":
    create_loading_gif() 