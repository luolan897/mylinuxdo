"""
cron: 0 */7 * * *
new Env("Linux.Do 签到")
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

try:
    from sendNotify import send
except:
    def send(*args):
        print("未找到通知文件sendNotify.py不启用通知！")

List = []

display = Display(size=(1920, 1080))
display.start()

def create_extension(plugin_path=None):
    # 创建Chrome插件的manifest.json文件内容
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

    # 创建Chrome插件的script.js文件内容
    script_js = """
function getRandomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

// old method wouldn't work on 4k screens

let screenX = getRandomInt(800, 1200);
let screenY = getRandomInt(400, 600);

Object.defineProperty(MouseEvent.prototype, 'screenX', { value: screenX });

Object.defineProperty(MouseEvent.prototype, 'screenY', { value: screenY });
    """

    # 创建插件目录并写入manifest.json和script.js文件
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
                    if attempt == retries - 1:  # 最后一次尝试
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
        # co = ChromiumOptions().set_browser_path(r"/usr/bin/google-chrome-stable")
        co = ChromiumOptions()
        co.auto_port()
        co.set_timeouts(base=2)
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
                logger.warning(f"处理 Turnstile 时出错: {str(e)}")
            time.sleep(1)
        self.page.refresh()
        # raise Exception("failed to solve turnstile")

    def login(self):
        logger.info("开始登录")
        self.page.get(LOGIN_URL)
        time.sleep(2)
        turnstile_token = self.getTurnstileToken()
        logger.info(f"turnstile_token: {turnstile_token}")
        if turnstile_token:
            self.page.get_screenshot("screenshot.png")
            self.page.ele("@id=login-account-name").input(USERNAME)
            self.page.ele("@id=login-account-password").input(PASSWORD)
            self.page.ele("@id=login-button").click()
            time.sleep(10)
            user_ele = self.page.ele("@id=current-user")
            if not user_ele:
                logger.error("登录失败")
                List.append("❌每日登录失败")
                return False
            else:
                logger.info("登录成功")
                List.append("✅每日登录成功")
                return True
        else:
            self.page.get("https://ping0.cc/geo")
            ip_addr = self.page.ele('tag:body').text
            logger.info(f"当前ip无法访问：\n {ip_addr}")
            List.append(f"当前ip无法访问：\n {ip_addr}")
            return False

    def click_topic(self):
        topic_list = self.page.ele("@id=list-area").eles(".:title")
        logger.info(f"发现 {len(topic_list)} 个主题帖，随机选择30个")
        for topic in random.sample(topic_list, 30):
            self.click_one_topic(topic.attr("href"))

    @retry_decorator()
    def click_one_topic(self, topic_url):
        new_page = self.browser.new_tab()
        new_page.get(topic_url)
        
        # --- 修改处：删除了点赞逻辑 ---
        # 原有的随机点赞代码已被移除
        
        self.browse_post(new_page)
        new_page.close()

    def browse_post(self, page):
        prev_url = None
        # 开始自动滚动，最多滚动10次
        for _ in range(10):
            # 随机滚动一段距离
            scroll_distance = random.randint(550, 650)  # 随机滚动 550-650 像素
            logger.info(f"向下滚动 {scroll_distance} 像素...")
            page.run_js(f"window.scrollBy(0, {scroll_distance})")
            logger.info(f"已加载页面: {page.url}")

            if random.random() < 0.03:  # 33 * 4 = 132
                logger.success("随机退出浏览")
                break

            # 检查是否到达页面底部
            at_bottom = page.run_js(
                "window.scrollY + window.innerHeight >= document.body.scrollHeight"
            )
            current_url = page.url
            if current_url != prev_url:
                prev_url = current_url
            elif at_bottom and prev_url == current_url:
                logger.success("已到达页面底部，退出浏览")
                break

            # 动态随机等待
            wait_time = random.uniform(2, 4)  # 随机等待 2-4 秒
            logger.info(f"等待 {wait_time:.2f} 秒...")
            time.sleep(wait_time)

    def run(self):
        if not self.login():  # 登录
            logger.error("登录失败，程序终止")
            self.send_notifications()  # 发送通知
            sys.exit(1)  # 使用非零退出码终止整个程序

        if BROWSE_ENABLED:
            self.click_topic()  # 点击主题
            logger.info("完成浏览任务")
            List.append("完成浏览任务")

        self.print_connect_info()  # 打印连接信息
        self.send_notifications()  # 发送通知
        self.page.close()
        self.browser.quit()

    # --- 修改处：删除了 click_like 函数 ---

    def print_connect_info(self):
        logger.info("获取连接信息")
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
            logger.info("连接错误，请检查！（账户等级过低，无法查看任务信息）")
            List.append("连接错误，请检查！（账户等级过低，无法查看任务信息）")
        page.close()

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
