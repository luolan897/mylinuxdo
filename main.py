"""
cron: 0 */7 * * *
new Env("Linux.Do 自动刷帖(100帖)+仿真阅读+点赞")
"""

import os
import random
import time
import functools
import sys
from loguru import logger
from DrissionPage import ChromiumOptions, Chromium
from tabulate import tabulate
from pyvirtualdisplay import Display

# --- 核心配置区域 ---
TARGET_TOPIC_COUNT = 100   # 每天目标刷帖数量
MAX_DAILY_LIKES = 15       # 每天最多点赞数量 (建议不要超过20，避免封号)
LIKE_PROBABILITY = 0.15    # 单个帖子点赞概率 (0.15 = 15%)
READ_SPEED_FAST = True     # True=快速浏览(适合刷量), False=慢速阅读(更真实)
# --------------------

try:
    from sendNotify import send
except:
    def send(*args):
        print("未找到通知文件sendNotify.py不启用通知！")

List = []
current_like_count = 0  # 记录本次运行点赞数

# 启动虚拟显示器 (防止无头模式被检测)
display = Display(size=(1920, 1080))
display.start()

def create_extension(plugin_path=None):
    # 创建过检测插件
    manifest_json = """
{
    "manifest_version": 3,
    "name": "Turnstile Patcher",
    "version": "2.1",
    "content_scripts": [
        {
            "js": ["./script.js"],
            "matches": ["<all_urls>"],
            "run_at": "document_start",
            "all_frames": true,
            "world": "MAIN"
        }
    ]
}
    """
    script_js = """
function getRandomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}
let screenX = getRandomInt(800, 1200);
let screenY = getRandomInt(400, 600);
Object.defineProperty(MouseEvent.prototype, 'screenX', { value: screenX });
Object.defineProperty(MouseEvent.prototype, 'screenY', { value: screenY });
    """
    os.makedirs(plugin_path, exist_ok=True)
    with open(os.path.join(plugin_path, "manifest.json"), "w+") as f:
        f.write(manifest_json)
    with open(os.path.join(plugin_path, "script.js"), "w+") as f:
        f.write(script_js)
    return os.path.join(plugin_path)

def retry_decorator(retries=3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(f"函数 {func.__name__} 失败: {str(e)}")
                    time.sleep(1)
            return None
        return wrapper
    return decorator

# --- 环境变量读取 ---
USERNAME = os.environ.get("LINUXDO_USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD")
if not USERNAME: USERNAME = os.environ.get("USERNAME")
if not PASSWORD: PASSWORD = os.environ.get("PASSWORD")

LOGIN_URL = "https://linux.do/login"

class LinuxDoBrowser:
    def __init__(self) -> None:
        co = ChromiumOptions()
        co.auto_port()
        co.set_timeouts(base=4)
        
        # 加载过检测插件
        turnstilePatch = create_extension(plugin_path="turnstilePatch")
        co.add_extension(path=turnstilePatch)
        
        # 浏览器指纹伪装
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--disable-infobars')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-gpu')
        
        self.browser = Chromium(co)
        self.page = self.browser.new_tab()

    def getTurnstileToken(self):
        # 处理 Cloudflare 验证码
        self.page.r
