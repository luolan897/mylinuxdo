"""
cron: 0 */7 * * *
new Env("Linux.Do 签到+刷帖+点赞")
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

# --- 配置区域 ---
TARGET_TOPIC_COUNT = 100  # 每天刷帖的目标数量
MAX_DAILY_LIKES = 20      # 每天最大点赞数量（防止风控）
LIKE_PROBABILITY = 0.2    # 单个帖子点赞的概率 (0.2 = 20%)
# ----------------

try:
    from sendNotify import send
except:
    def send(*args):
        print("未找到通知文件sendNotify.py不启用通知！")

List = []
current_like_count = 0  # 当前运行的点赞计数

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
            "js": [
                "./script.js"
            ],
            "matches": [
                "<all_urls>"
            ],
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
                        logger.error(f"函数 {func.__name__} 最终执行失败: {str(e)}")
                    logger.warning(
                        f"函数 {func.__name__} 第 {attempt + 1}/{retries} 次尝试失败: {str(e)}"
                    )
                    time.sleep(1)
            return None
        return wrapper
    return decorator


USERNAME = os.environ.get("LINUXDO_USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD")
BROWSE_ENABLED = os.environ.get("BROWSE_ENABLED", "true").strip().lower() not in [
    "false",
    "0",
    "off",
]
if not USERNAME:
    USERNAME = os.environ.get("USERNAME")
if not PASSWORD:
    PASSWORD = os.environ.get("PASSWORD")

HOME_URL = "https://linux.do/"
LOGIN_URL = "https://linux.do/login"


class LinuxDoBrowser:
    def __init__(self) -> None:
        co = ChromiumOptions()
        co.auto_port()
        co.set_timeouts(base=5) # 稍微增加基础超时时间
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
        turnstileResponse = None
        for i in range(0, 10):
            try:
                turnstileResponse = self.page.run_js("try { return turnstile.getResponse() } catch(e) { return null }")
                if turnstileResponse:
                    return turnstileResponse
                challengeSolution = self.page.ele("@name=cf-turnstile-response")
                challengeWrapper = challengeSolution.parent()
                challengeIframe = challengeWrapper.shadow_root.ele("tag:iframe")
                challengeIframeBody = challengeIframe.ele("tag:body").shadow_root
                challengeButton = challengeIframeBody.ele("tag:input")
                challengeButton.click()
            except Exception as e:
                # logger.warning(f"处理 Turnstile 中... {str(e)}")
                pass
            time.sleep(1)
        self.page.refresh()

    def login(self):
        logger.info("开始登录")
        self.page.get(LOGIN_URL)
        time.sleep(2)
        turnstile_token = self.getTurnstileToken()
        logger.info(f"检查 Turnstile 状态...")
        
        # 尝试登录逻辑
        try:
            self.page.ele("@id=login-account-name").input(USERNAME)
            self.page.ele("@id=login-account-password").input(PASSWORD)
            self.page.ele("@id=login-button").click()
            time.sleep(5)
            
            # 检查是否登录成功
            user_ele = self.page.ele("@id=current-user")
            if not user_ele:
                # 如果没找到用户信息，可能需要更长时间等待或者有验证码
                time.sleep(5)
                user_ele = self.page.ele("@id=current-user")
            
            if not user_ele:
                logger.error("登录失败")
                List.append("❌每日登录失败")
                return False
            else:
                logger.info("登录成功")
                List.append("✅每日登录成功")
                return True
        except Exception as e:
            logger.error(f"登录过程异常: {e}")
            return False

    def click_topic(self):
        """
        获取帖子链接并进行访问。
        为了达到100贴，需要先在主页滚动加载更多帖子。
        """
        logger.info(f"开始准备帖子列表，目标: {TARGET_TOPIC_COUNT} 篇...")
        
        collected_urls = set()
        scroll_attempts = 0
        
        # 循环滚动以获取足够的帖子链接
        while len(collected_urls) < TARGET_TOPIC_COUNT and scroll_attempts < 20:
            # 获取当前页面的所有主题链接
            topic_elements = self.page.ele("@id=list-area").eles(".:title")
            for topic in topic_elements:
                url = topic.attr("href")
                if url and "linux.do" in url:
                    collected_urls.add(url)
            
            logger.info(f"当前已收集不重复帖子: {len(collected_urls)} 篇")
            
            if len(collected_urls) >= TARGET_TOPIC_COUNT:
                break
                
            # 向下滚动加载更多
            self.page.scroll.down(1000)
            time.sleep(1.5)
            scroll_attempts += 1
            
        # 转换为列表并截取目标数量
        final_list = list(collected_urls)[:TARGET_TOPIC_COUNT]
        logger.info(f"收集完成，准备访问 {len(final_list)} 篇帖子")

        for idx, topic_url in enumerate(final_list):
            logger.info(f"[{idx+1}/{len(final_list)}] 正在访问: {topic_url}")
            self.click_one_topic(topic_url)
            # 批次之间稍微休息一下，避免并发过高
            if idx > 0 and idx % 10 == 0:
                time.sleep(2)

    @retry_decorator()
    def click_one_topic(self, topic_url):
        new_page = self.browser.new_tab()
        try:
            new_page.get(topic_url)
            
            # 浏览帖子
            self.browse_post(new_page)
            
            # 尝试点赞
            self.click_like(new_page)
            
        except Exception as e:
            logger.warning(f"访问帖子出错: {e}")
        finally:
            new_page.close()

    def click_like(self, page):
        """
        点赞逻辑：
        1. 检查是否达到每日上限
        2. 随机概率决定是否点赞
        3. 查找点赞按钮并点击
        """
        global current_like_count
        
        if current_like_count >= MAX_DAILY_LIKES:
            return

        # 随机概率判断 (比如 20% 的概率点赞)
        if random.random() > LIKE_PROBABILITY:
            return

        try:
            # 查找底部的点赞按钮 (Discourse 论坛结构)
            #通常是 .toggle-like 或者 title="点赞此帖子"
            # 排除已经点赞的 (通常已有 .d-liked 类或类似标识)
            
            # 先滚动到底部附近确保按钮加载
            page.scroll.to_bottom()
            time.sleep(0.5)
            page.scroll.up(300) #稍微往回一点
            
            # 寻找未点赞的按钮
            # css:button.toggle-like 且没有 .d-liked 类
            like_btn = page.ele("css:button.toggle-like:not(.d-liked)")
            
            if like_btn:
                # 再次确认 title 属性，避免取消点赞
                title = like_btn.attr("title")
                if title and "取消" in title:
                    logger.info("该帖已点赞，跳过")
                    return

                like_btn.click()
                current_like_count += 1
                logger.success(f"❤️ 点赞成功! (今日已赞: {current_like_count})")
                time.sleep(1) # 点赞后稍作停留
        except Exception as e:
            # logger.debug(f"点赞尝试失败(可能没找到按钮): {e}")
            pass

    def browse_post(self, page):
        prev_url = None
        # 因为要刷100贴，减少单贴停留时间，只滚动几次
        max_scrolls = random.randint(3, 6) 
        
        for _ in range(max_scrolls):
            scroll_distance = random.randint(400, 600)
            # logger.info(f"向下滚动 {scroll_distance} 像素...")
            page.run_js(f"window.scrollBy(0, {scroll_distance})")
            
            # 检查是否到底
            at_bottom = page.run_js(
                "window.scrollY + window.innerHeight >= document.body.scrollHeight"
            )
            if at_bottom:
                break
            
            time.sleep(random.uniform(1, 2)) # 减少等待时间，加快速度

    def run(self):
        if not self.login():
            logger.error("登录失败，程序终止")
            self.send_notifications()
            sys.exit(1)

        if BROWSE_ENABLED:
            self.click_topic()
            logger.info("完成浏览任务")
            List.append(f"✅完成浏览任务 (目标: {TARGET_TOPIC_COUNT})")
            List.append(f"❤️本次运行点赞数: {current_like_count}")

        self.print_connect_info()
        self.send_notifications()
        self.page.close()
        self.browser.quit()

    def print_connect_info(self):
        logger.info("获取连接信息")
        try:
            page = self.browser.new_tab()
            page.get("https://connect.linux.do/")
            rows = page.ele("tag:table").eles("tag:tr")
            if rows:
                info = []
                for row in rows:
                    cells = row.eles("tag:td")
                    if len(cells) >= 3:
                        project = cells[0].text.strip()
                        current = cells[1].text.strip()
                        requirement = cells[2].text.strip()
                        info.append([project, current, requirement])
                msg = tabulate(info, headers=["项目", "当前", "要求"], tablefmt="pretty")
                print("--------------Connect Info-----------------")
                print(msg)
                List.append(msg)
            else:
                logger.info("无法获取Connect信息")
            page.close()
        except Exception as e:
            logger.error(f"获取连接信息失败: {e}")

    def send_notifications(self):
        msg = '\n'.join(List)
        send("LINUX DO", msg)

if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        print("Please set USERNAME and PASSWORD")
        send("LINUX DO", "Please set USERNAME and PASSWORD")
        exit(1)
    l = LinuxDoBrowser()
    l.run()
