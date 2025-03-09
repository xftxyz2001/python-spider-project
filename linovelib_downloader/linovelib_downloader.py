import glob
import json
import logging
import os
import re
import time

import ddddocr
import pypandoc
import requests
from ebooklib import epub
from lxml import etree
from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.webdriver.edge.options import Options


# 绿色
def printi(text):
    print(f"\033[32m{text}\033[0m")


# 黄色
def printw(text):
    print(f"\033[33m{text}\033[0m")


# 红色
def printe(text):
    print(f"\033[31m{text}\033[0m")


class LinovelibCrawler:

    def start_edge(self):
        printi("正在启动Edge浏览器...")
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        # 设置日志等级 INFO = 0 WARNING = 1 LOG_ERROR = 2 LOG_FATAL = 3 default is 0
        # options.add_argument("log-level=3")
        # options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.driver = webdriver.Edge(options=options)
        time.sleep(2)

    # 初始化
    def __init__(self):
        printi("正在初始化...")

        self.base_url = "https://www.linovelib.com"
        self.session = requests.Session()
        self.headers = {
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
        }
        self.min_request_interval = 2  # 两次请求的最小间隔
        self.max_request_interval = 10
        self.request_interval = self.min_request_interval
        self.last_request_time = time.time() - self.min_request_interval
        self.max_retry = 5  # 最大重试次数

        self.min_wait_time = 2
        self.max_wait_time = 10
        self.wait_time = self.min_wait_time

        self.ocr = ddddocr.DdddOcr(beta=True, show_ad=False)

        self.matedata = {}

        self.start_edge()

    def driver_quit(self):
        try:
            self.driver.quit()
        except Exception as e:
            printe(f"关闭浏览器出错: ")
            logging.exception(e)

    # 退出
    def __del__(self):
        if hasattr(self, "driver") and self.driver:
            self.driver_quit()

    # 获取html
    def fetch_html(self, url):
        if not url.startswith("http"):
            url = self.base_url + url

        # 距离上次请求时间的时间
        time_since_last_request = time.time() - self.last_request_time
        if time_since_last_request < self.request_interval:
            time.sleep(time_since_last_request)
        self.last_request_time = time.time()

        for attempt in range(max(self.max_retry, 3)):
            try:
                printi(f"请求页面: {url}")

                if attempt == 1:  # 第二次重试，刷新
                    self.driver.refresh()
                else:
                    self.driver.get(url)
                time.sleep(self.wait_time)  # 等待，以便页面加载完全

                page_source = self.driver.page_source
                if "（內容加載失敗！請刷新或更換瀏覽器）" in page_source:
                    with open(
                        f".page_source-{time.time()}.html", "w", encoding="utf-8"
                    ) as f:
                        f.write(page_source)
                    if self.wait_time < self.max_wait_time:
                        self.wait_time *= 2
                    raise Exception("页面加载失败，请刷新或更换浏览器")

                self.wait_time = self.min_wait_time
                self.request_interval = self.min_request_interval
                return etree.HTML(page_source)
            except Exception as e:
                printe(f"请求页面失败: ")
                logging.exception(e)
                if self.request_interval < self.max_request_interval:
                    self.request_interval *= 2

                if attempt <= self.max_retry // 2:  # 前三次
                    printw(f"将在 {self.request_interval} 秒后重试...")
                    continue

                self.driver_quit()
                self.start_edge()

        printw("已达到最大重试次数，程序即将退出...")
        exit()

    # 解析图书信息
    def parse_matedata(self, tree):
        book_title = tree.xpath('//div[@class="book-meta"]/h1/text()')[0]
        book_author = tree.xpath('//div[@class="book-meta"]/p/span[1]/a/text()')[0]

        # 卷列表
        volume_list = []
        x_volumes = tree.xpath(
            '//div[@id="volume-list"]//div[@class="volume clearfix"]'
        )
        for x_volume in x_volumes:
            # 卷名
            volume_name = x_volume.xpath('./div[@class="volume-info"]/h2/text()')[0]

            # 章节列表
            chapter_list = []
            x_chapters = x_volume.xpath('./ul[@class="chapter-list clearfix"]/li/a')
            for x_chapter in x_chapters:
                # 章节名
                chapter_name = x_chapter.xpath("text()")[0]
                # 章节链接
                chapter_link = x_chapter.xpath("@href")[0]
                chapter = {
                    "name": chapter_name,
                    "link": chapter_link,
                    "status": "not_started",
                }
                chapter_list.append(chapter)
            volume = {
                "name": volume_name,
                "chapters": chapter_list,
                "status": "not_started",
            }
            volume_list.append(volume)
        self.metadata = {
            "title": book_title,
            "author": book_author,
            "volumes": volume_list,
        }

    # 下载文件
    def download_file(self, file_url, addtional_headers={}, save_path=None):
        printi(f"正在下载文件: {file_url}")
        response = self.session.get(
            file_url, headers={**self.headers, **addtional_headers}
        )
        if not response.ok:
            printe(f"下载文件失败: {response.status_code}")
            return

        save_path = save_path or file_url.split("/")[-1]
        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(response.content)
        printi(f"文件下载成功: {save_path}")

    # 解码文本
    def decode_text(self, text):
        font_path = "./read.woff2"
        if not os.path.exists(font_path):
            font_url = self.base_url + "/public/font/read.woff2"
            self.download_file(
                font_url,
                {
                    "accept": "*/*",
                    "origin": self.base_url,
                    "priority": "u=0",
                    "referer": "https://www.linovelib.com/novel/4515/261588_2.html",
                    "sec-fetch-dest": "font",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                },
            )

        img_size = 1024
        img = Image.new("1", (img_size * len(text), img_size), 255)
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(font_path, img_size)
        draw.text((0, -200), text, font=font)
        return self.ocr.classification(img)

    # 解析一页小说
    def parse_page(self, tree):
        # 检查是否有字体样式加密，并记录加密的p
        has_font_style = False
        if tree.xpath('//head/script[contains(text(),"adoptedStyleSheets")]'):
            has_font_style = True
            # 获取#TextContent p:nth-last-of-type(2)
            p_last2 = tree.xpath('//div[@id="TextContent"]/p')[-2]
            content_of_p_last2 = self.decode_text("".join(p_last2.xpath("text()")))

        contents = []
        # 处理TextContent中的p br img标签
        elements = tree.xpath('//div[@id="TextContent"]/*')
        for element in elements:
            if element.tag == "p":
                if has_font_style and element == p_last2:
                    contents.append(content_of_p_last2)
                    continue
                contents.append("".join(element.xpath("text()")))
            elif element.tag == "br":
                contents.append("\n")
            elif element.tag == "img":
                img_src = element.get("data-src") or element.get("src")
                img_name = img_src.split("/")[-1]
                save_path = f"{self.novel_id}/{img_name}"
                self.download_file(
                    img_src,
                    {
                        "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                        "priority": "i",
                        "referer": self.base_url,
                        "sec-fetch-dest": "image",
                        "sec-fetch-mode": "no-cors",
                        "sec-fetch-site": "cross-site",
                        "sec-fetch-storage-access": "active",
                    },
                    save_path,
                )
                contents.append(f"![{img_name}]({save_path})")

        return "\n\n".join(contents)

    # 解析章节内容
    def parse_chapter(self, tree):
        contents = []
        while True:
            contents.append(self.parse_page(tree))

            next_page = tree.xpath('//div[@class="mlfy_page"]/a[5]/@href')[0]
            # 如果下一页链接/后面不存在下划线则说明章节结束
            if next_page.split("/")[-1].find("_") == -1:
                break
            tree = self.fetch_html(next_page)

        return "\n".join(contents)

    def save_catalog(self):
        try:
            with open(f".{self.novel_id}.log.json", "w", encoding="utf-8") as f:
                json.dump(self.metadata, f)
            printi("章节信息保存成功.")
        except Exception as e:
            printe(f"章节信息保存失败: {e}")

    def load_catalog(self):
        if os.path.exists(f".{self.novel_id}.log.json") and os.path.exists(
            self.sava_filename
        ):
            try:
                with open(f".{self.novel_id}.log.json", "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                printi(f"章节信息已读取.")
                return
            except Exception as e:
                printe(f"章节信息读取失败: ")
                logging.exception(e)

        printi(f"获取章节目录...")
        catalog_url = f"{self.base_url}/novel/{self.novel_id}/catalog"

        catalog_html = self.fetch_html(catalog_url)
        self.parse_matedata(catalog_html)
        self.save_catalog()

        with open(self.sava_filename, "w", encoding="utf-8") as f:
            book_title = self.metadata["title"]
            f.write(f"{book_title}\n---\n")

    def delete_catalog(self):
        try:
            os.remove(f".{self.novel_id}.log.json")
        except Exception as e:
            printe(f"章节信息删除失败: {e}")

    def delete_page_source_files(self):
        files = glob.glob(".page_source-*.html")
        for file in files:
            try:
                os.remove(file)
                printi(f"文件已删除: {file}")
            except Exception as e:
                printe(f"删除文件 {file} 时出错:")
                logging.exception(e)

    def delete_cache(self):
        # 删除章节信息
        self.delete_catalog()
        # 删除错误的章节文件缓存
        self.delete_page_source_files()

    def download_loop(self):
        for volume in self.metadata["volumes"]:
            if volume["status"] == "completed":
                continue

            volume_name = volume["name"]
            printi(f"当前卷: {volume_name}")
            chapters = volume["chapters"]
            if volume["status"] == "not_started":
                with open(self.sava_filename, "a", encoding="utf-8") as f:
                    f.write(f"\n# {volume_name}\n\n")

                volume["status"] = "in_progress"
                self.save_catalog()

            for chapter in chapters:
                if chapter["status"] == "completed":
                    continue

                chapter_title = chapter["name"]
                printi(f"当前章节: {chapter_title}")
                if chapter["status"] == "not_started":
                    with open(self.sava_filename, "a", encoding="utf-8") as f:
                        f.write(f"## {chapter_title}\n\n")

                    chapter["status"] = "in_progress"
                    self.save_catalog()

                chapter_link = chapter["link"]
                content_html = self.fetch_html(chapter_link)
                content = self.parse_chapter(content_html)
                with open(self.sava_filename, "a", encoding="utf-8") as f:
                    f.write(f"{content}\n\n")
                chapter["status"] = "completed"
                self.save_catalog()
            volume["status"] = "completed"
            self.save_catalog()

    # 将 Markdown文件转换为 EPUB文件
    def to_epub(self):
        printi("正在生成 EPUB 文件...")
        outputfile = f"{self.sava_filename}.epub"
        pypandoc.ensure_pandoc_installed()
        pypandoc.convert_file(self.sava_filename, "epub", outputfile=outputfile)
        book = epub.read_epub(outputfile)
        book.set_title(self.metadata["title"])
        book.add_author(self.metadata["author"])
        book.set_language("zh")

        epub_name = f"{self.metadata['title']}.epub"
        epub.write_epub(epub_name, book)
        os.remove(outputfile)
        printi(f"EPUB 文件生成完成. {epub_name}")

    def download(self, novel_id):
        printi(f"开始下载 {novel_id}")

        self.novel_id = novel_id
        self.sava_filename = f"{novel_id}.md"

        self.load_catalog()
        self.download_loop()
        self.delete_cache()
        printi(f"{self.novel_id} 下载完成")

        self.to_epub()


if __name__ == "__main__":
    input_id = input(
        "请输入小说ID或粘贴网址\neg.(1)4521\n   (2)https://www.linovelib.com/novel/4521.html\n   (3)https://www.linovelib.com/novel/4521/catalog\n>>>"
    )
    novel_id = re.findall(r"\d+", input_id)[0]
    printi(f"小说ID已获取: {novel_id}")
    try:
        crawler = LinovelibCrawler()
        crawler.download(novel_id)
    except Exception as e:
        printe("出错了: ")
        logging.exception(e)
        input("按任意键退出...")
    printi("程序已退出.")
