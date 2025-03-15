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


# 状态
NOT_STARTED = "not_started"  # 未开始
IN_PROGRESS = "in_progress"  # 进行中
COMPLETED = "completed"  # 已完成


class LinovelibCrawler:

    def start_edge(self):
        printi("正在配置Edge浏览器...")
        options = Options()
        # options.add_argument("--headless")
        # options.add_argument("--disable-gpu")
        # 设置日志等级 INFO = 0 WARNING = 1 LOG_ERROR = 2 LOG_FATAL = 3 default is 0
        # options.add_argument("log-level=3")
        # options.add_experimental_option("excludeSwitches", ["enable-automation"])
        printi("Edge浏览器启动中...")
        self.driver = webdriver.Edge(options=options)
        printi("Edge浏览器已启动.")

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

        self.font_image_size = 1024
        self.decode_text_chunk_size = 32
        self.ocr = ddddocr.DdddOcr(beta=True, show_ad=False)

        self.metadata = {}

        self.start_edge()

    def driver_quit(self):
        try:
            printi("正在关闭浏览器...")
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
                printi("等待页面加载...")
                time.sleep(self.wait_time)  # 等待，以便页面加载完全

                page_source = self.driver.page_source
                while "<title>请稍候…</title>" in page_source:
                    time.sleep(3)
                if "（內容加載失敗！請刷新或更換瀏覽器）" in page_source:
                    with open(
                        f".page_source-{time.time()}.html", "w", encoding="utf-8"
                    ) as f:
                        f.write(page_source)
                    if self.wait_time < self.max_wait_time:
                        self.wait_time *= 2
                    raise Exception("页面加载失败，请刷新或更换浏览器")

                printi("页面加载完成.")
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

    # 获取卷列表
    def get_volume_list(self):
        printi("正在获取卷/章节列表...")
        catalog_url = f"{self.base_url}/novel/{self.novel_id}/catalog"
        tree = self.fetch_html(catalog_url)

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
                    "status": NOT_STARTED,
                }
                chapter_list.append(chapter)
            volume = {
                "name": volume_name,
                "chapters": chapter_list,
                "status": NOT_STARTED,
            }
            volume_list.append(volume)
        return volume_list

    # 解析图书信息
    def get_metadata(self):
        printi("正在获取图书元信息（书名、作者、章节目录）...")
        index_url = f"{self.base_url}/novel/{self.novel_id}.html"
        index_tree = self.fetch_html(index_url)
        
        book_name_tree = index_tree.xpath('//h1[@class="book-name"]/text()')  # 书名
        book_title = book_name_tree[0] if len(book_name_tree) >=1 else "书名获取失败"
        book_au_name_tree = index_tree.xpath('//div[@class="au-name"]/text()')  # 作者一
        book_author = book_au_name_tree[0] if len(book_au_name_tree)>=1 else "作者获取失败"
        book_img_tree = index_tree.xpath('//div[@class="book-img fl"]/img/@src')
        cover_url = book_img_tree[0] if len(book_img_tree) >=1 else ""

        volume_list = self.get_volume_list()
        self.metadata = {
            "metafile": f".{self.novel_id}.meta.json",
            "url": index_url,
            "title": book_title,
            "author": book_author,
            "cover": cover_url,
            "volumes": volume_list,
        }
        printi("解析图书元信息完成.")

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
        printi(f'正在解码文本: "{text}"...')
        font_path = "./read.woff2"
        if not os.path.exists(font_path):
            font_url = self.base_url + "/public/font/read.woff2"
            self.download_file(
                font_url,
                {
                    "accept": "*/*",
                    "origin": self.base_url,
                    "priority": "u=0",
                    "referer": "https://www.linovelib.com/",
                    "sec-fetch-dest": "font",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                },
            )

        # PIL.Image.DecompressionBombError: Image size (304012800 pixels) exceeds limit of 178956970 pixels, could be decompression bomb DOS attack.
        decoded_text = ""
        i = 0
        while i < len(text):
            chunk_size = (
                self.decode_text_chunk_size
                if len(text) - i > 1.5 * self.decode_text_chunk_size
                else len(text) - i
            )
            chunk = text[i : i + chunk_size]
            img = Image.new(
                "1", (self.font_image_size * len(chunk), self.font_image_size), 255
            )
            draw = ImageDraw.Draw(img)
            font = ImageFont.truetype(font_path, self.font_image_size)
            draw.text((0, -200), chunk, font=font)
            decoded_text += self.ocr.classification(img)
            i += chunk_size

        printi(f'文本解码完成: "{decoded_text}".')
        return decoded_text

    # 解析一页小说
    def parse_page(self, tree):
        printi("正在解析当前页面...")
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
                contents.append(f"![]({save_path})")

        printi("当前页面解析完成.")
        return "\n\n".join(contents)

    # 解析章节内容
    def parse_chapter(self, tree):
        printi("正在解析当前章节...")
        contents = []
        while True:
            contents.append(self.parse_page(tree))

            next_page = tree.xpath('//div[@class="mlfy_page"]/a[5]/@href')[0]
            # 如果下一页链接/后面不存在下划线则说明章节结束
            if next_page.split("/")[-1].find("_") == -1:
                break
            tree = self.fetch_html(next_page)

        printi("当前章节已解析完成.")
        return "\n".join(contents)

    def save_metadata(self):
        printi("正在保存章节信息...")
        try:
            with open(self.metadata["metafile"], "w", encoding="utf-8") as f:
                json.dump(self.metadata, f)
            printi("章节信息保存成功.")
        except Exception as e:
            printe(f"章节信息保存失败: {e}")

    def load_metadata(self):
        printi("正在读取章节信息...")
        metafile = f".{self.novel_id}.meta.json"
        if os.path.exists(metafile) and os.path.exists(self.sava_filename):
            try:
                with open(metafile, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                printi(f"章节信息已读取.")
                return
            except Exception as e:
                printe(f"章节信息读取失败: ")
                logging.exception(e)

        self.get_metadata()
        self.save_metadata()

        with open(self.sava_filename, "w", encoding="utf-8") as f:
            book_title = self.metadata["title"]
            f.write(f"{book_title}\n---\n")

    def delete_metadata(self):
        printi("正在删除章节信息...")
        try:
            os.remove(self.metadata["metafile"])
            printi("章节信息已删除.")
        except Exception as e:
            printe(f"章节信息删除失败: ")
            logging.exception(e)

    def delete_page_source_files(self):
        printi("正在删除章节文件缓存...")
        files = glob.glob(".page_source-*.html")
        for file in files:
            try:
                os.remove(file)
                printi(f"文件已删除: {file}")
            except Exception as e:
                printe(f"删除文件 {file} 时出错:")
                logging.exception(e)

    # 删除缓存
    def delete_cache(self):
        # 删除章节信息
        self.delete_metadata()
        # 删除错误的章节文件缓存
        self.delete_page_source_files()

    # 循环下载每一卷每一章
    def download_loop(self):
        printi("开启下载循环...")
        len_volumes = len(self.metadata["volumes"])
        for i, volume in enumerate(self.metadata["volumes"]):
            if volume["status"] == COMPLETED:
                continue

            volume_name = volume["name"]
            printi(f"({i+1}/{len_volumes}) 当前卷: {volume_name}")
            chapters = volume["chapters"]
            if volume["status"] == NOT_STARTED:
                with open(self.sava_filename, "a", encoding="utf-8") as f:
                    f.write(f"\n# {volume_name}\n\n")

                volume["status"] = IN_PROGRESS
                self.save_metadata()

            len_chapters = len(chapters)
            for j, chapter in enumerate(chapters):
                if chapter["status"] == COMPLETED:
                    continue

                chapter_title = chapter["name"]
                printi(f"({j+1}/{len_chapters}) 当前章节: {chapter_title}")
                if chapter["status"] == NOT_STARTED:
                    with open(self.sava_filename, "a", encoding="utf-8") as f:
                        f.write(f"## {chapter_title}\n\n")

                    chapter["status"] = IN_PROGRESS
                    self.save_metadata()

                chapter_link = chapter["link"]
                content_html = self.fetch_html(chapter_link)
                content = self.parse_chapter(content_html)
                with open(self.sava_filename, "a", encoding="utf-8") as f:
                    f.write(f"{content}\n\n")
                chapter["status"] = COMPLETED
                self.save_metadata()
            volume["status"] = COMPLETED
            self.save_metadata()
        printi("结束下载循环.")

    # 将 Markdown文件转换为 EPUB文件
    def to_epub(self):
        printi("正在生成 EPUB 文件...")
        printi("正在检查 pandoc 是否已安装...")
        pypandoc.ensure_pandoc_installed()
        printi("pandoc 已安装.")

        output_file = f"{self.metadata['title']}.epub"
        # 下载封面
        cover_url = self.metadata["cover"]
        cover_path = f"{self.novel_id}/cover.jpg"
        if cover_url:
            self.download_file(
                cover_url,
                {
                    "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "priority": "i",
                    "referer": self.metadata["url"],
                    "sec-fetch-dest": "image",
                    "sec-fetch-mode": "no-cors",
                    "sec-fetch-site": "same-origin",
                },
                cover_path,
            )
        extra_args=[
            "--metadata",
            f"title={self.metadata['title']}"
        ]
        if cover_url:
            extra_args.append("--epub-cover-image")
            extra_args.append(cover_path)
        pypandoc.convert_file(
            self.sava_filename,
            "epub",
            outputfile=output_file,
            extra_args=extra_args,
        )

        printi(f"EPUB 文件已生成 于: {output_file}")

    def download(self, novel_id):
        printi(f"开始下载 {novel_id}")

        self.novel_id = novel_id
        self.sava_filename = f"{novel_id}.md"

        self.load_metadata()
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
