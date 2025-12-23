"""
cron: 0 */7 * * *
new Env("Linux.Do 自动刷帖(修复版)")
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

# --- 核心配置 ---
TARGET_TOPIC_COUNT = 100   # 目标刷帖数量
MAX_DAILY_LIKES = 15       # 每天点赞上限
LIKE_PROBABILITY = 0.2     # 点赞概率 20%
# ----------------

try:
    from sendNotify import send
except:
    def send(*args):
        print("未找到通知文件sendNotify.py不启用通知！")

List = []
current_like_count = 0

# 启动虚拟显示器
display = Display(size=(1920, 1080))
display.start()

def create_extension(plugin_path=None):
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
                        logger.error(f"Error: {str(e)}")
                    time.sleep(1)
            return None
        return wrapper
    return decorator

USERNAME = os.environ.get("LINUXDO_USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD")
if not USERNAME: USERNAME = os.environ.get("USERNAME")
if not PASSWORD: PASSWORD = os.environ.get("PASSWORD")

LOGIN_URL = "https://linux.do/login"

class LinuxDoBrowser:
    def __init__(self) -> None:
        co = ChromiumOptions()
        co.auto_port()
        co.set_timeouts(base=5)
        
        turnstilePatch = create_extension(plugin_path="turnstilePatch")
        co.add_extension(path=turnstilePatch)
        
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--disable-infobars')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-gpu')
        
        self.browser = Chromium(co)
        self.page = self.browser.new_tab()

    def getTurnstileToken(self):
        self.page.run_js("try { turnstile.reset() } catch(e) { }")
        for i in range(10):
            try:
                if self.page.run_js("try { return turnstile.getResponse() } catch(e) { return null }"):
                    return True
                iframe = self.page.ele("tag:iframe")
                if iframe:
                    btn = iframe.ele("tag:body").shadow_root.ele("tag:input")
                    if btn: btn.click()
            except:
                pass
            time.sleep(1)

    def login(self):
        logger.info("开始登录...")
        self.page.get(LOGIN_URL)
        time.sleep(3)
        self.getTurnstileToken()
        
        try:
            self.page.ele("@id=login-account-name").input(USERNAME)
            self.page.ele("@id=login-account-password").input(PASSWORD)
            self.page.ele("@id=login-button").click()
            time.sleep(5)
            
            if self.page.ele("@id=current-user", timeout=5):
                logger.success("登录成功")
                List.append("✅ 登录成功")
                return True
            return False
        except Exception as e:
            logger.error(f"登录异常: {e}")
            return False

    def click_topic(self):
        # -----------------------------------------------------
        # 修复核心：不再直接 sample，而是先滚动收集链接
        # -----------------------------------------------------
        logger.info(f"正在收集帖子链接，目标: {TARGET_TOPIC_COUNT} 篇...")
        collected_urls = set()
        scroll_attempts = 0
        
        # 循环滚动，直到收集到足够的链接
        while len(collected_urls) < TARGET_TOPIC_COUNT and scroll_attempts < 50:
            # 提取当前页面的所有帖子链接
            links = self.page.ele("@id=list-area").eles("tag:a")
            for link in links:
                url = link.attr("href")
                # 确保是帖子链接
                if url and "/t/topic/" in url: 
                    collected_urls.add(url)
            
            logger.info(f"当前已收集: {len(collected_urls)} 篇")
            
            if len(collected_urls) >= TARGET_TOPIC_COUNT:
                break
                
            # 向下滚动加载更多
            self.page.scroll.down(2000)
            time.sleep(2) # 等待新内容加载
            scroll_attempts += 1

        # 截取目标数量
        target_list = list(collected_urls)[:TARGET_TOPIC_COUNT]
        logger.info(f"收集完毕，准备浏览 {len(target_list)} 篇帖子")

        # 开始浏览
        for i, url in enumerate(target_list):
            try:
                logger.info(f"[{i+1}/{len(target_list)}] 浏览: {url}")
                self.visit_and_scroll(url)
                
                # 防止请求过快，每10篇休息一下
                if (i + 1) % 10 == 0:
                    time.sleep(3)
            except Exception as e:
                logger.warning(f"浏览跳过: {e}")

    @retry_decorator()
    def visit_and_scroll(self, url):
        tab = self.browser.new_tab()
        try:
            tab.get(url)
            # 模拟阅读滚动
            self.simulate_reading(tab)
            # 尝试点赞
            self.try_like(tab)
        finally:
            tab.close()

    def simulate_reading(self, tab):
        """模拟人类阅读：慢慢往下滚"""
        current_scroll = 0
        while True:
            scroll_step = random.randint(500, 800)
            tab.run_js(f"window.scrollBy({{top: {scroll_step}, behavior: 'smooth'}})")
            current_scroll += scroll_step
            
            # 随机停留 0.5 - 1.5 秒
            time.sleep(random.uniform(0.5, 1.5))
            
            # 检查是否到底
            scrolled_height = tab.run_js("return window.scrollY + window.innerHeight")
            total_height = tab.run_js("return document.body.scrollHeight")
            
            if scrolled_height >= total_height - 100: # 接近底部
                break
            
            if current_scroll > 10000: # 防止无限长的帖子
                break
        
        time.sleep(1) # 到底后稍微停顿

    def try_like(self, tab):
        """随机点赞"""
        global current_like_count
        if current_like_count >= MAX_DAILY_LIKES: return
        if random.random() > LIKE_PROBABILITY: return

        try:
            tab.scroll.up(300) # 往回一点找按钮
            like_btn = tab.ele("css:button.toggle-like:not(.d-liked)")
            if like_btn:
                title = like_btn.attr("title")
                if not title or "取消" not in title:
                    like_btn.click()
                    current_like_count += 1
                    logger.success(f"❤️ 点赞成功 (今日: {current_like_count})")
                    time.sleep(1)
        except:
            pass

    def run(self):
        if not self.login():
            sys.exit(1)

        self.click_topic()
        
        List.append(f"✅ 任务完成: 刷帖 {TARGET_TOPIC_COUNT} 篇")
        List.append(f"❤️ 本次点赞: {current_like_count} 次")
        
        self.print_connect_info()
        self.send_notifications()
        self.page.close()
        self.browser.quit()

    def print_connect_info(self):
        try:
            tab = self.browser.new_tab()
            tab.get("https://connect.linux.do/")
            rows = tab.ele("tag:table").eles("tag:tr")
            if rows:
                info = []
                for row in rows:
                    cells = row.eles("tag:td")
                    if len(cells) >= 3:
                        info.append([c.text.strip() for c in cells[:3]])
                msg = tabulate(info, headers=["项目", "当前", "要求"], tablefmt="pretty")
                print(msg)
                List.append(msg)
            tab.close()
        except:
            pass

    def send_notifications(self):
        msg = '\n'.join(List)
        send("Linux.Do 助手", msg)

if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        print("请设置环境变量")
        sys.exit(1)
    LinuxDoBrowser().run()
