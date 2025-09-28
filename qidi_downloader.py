import random
import re
import time
from urllib.parse import urlparse

import requests
import tqdm
from lxml import etree

book_page_url = "https://qidi.131437.xyz/read/santishijie/"
parsed_url = urlparse(book_page_url)
base_url = parsed_url.scheme + "://" + parsed_url.netloc

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
    "Referer": book_page_url,
}


def get_content(url, max_retry=3):
    if not url.startswith("http"):
        url = base_url + url
    for i in range(max_retry):
        try:
            time.sleep(random.random() * 3)
            response = requests.get(url, headers=headers)
            html = etree.fromstring(response.content, etree.HTMLParser())
            return html
        except Exception:
            print(f"Failed to get content from {url}, retrying... ({i+1}/{max_retry})")
            time.sleep(5)  # wait for 5 seconds before retrying
    raise Exception(f"Failed to get content from {url} after {max_retry} retries.")


# 1. 目录页处理
def get_chapter_urls():
    html = get_content(book_page_url)

    # 1.1 获取书名
    book_name = html.xpath(
        "//div[@class='m-book_info']/div[@class='m-infos']/h1/text()"
    )[0]
    book_name = book_name.strip()

    # 1.2 获取章节首页链接列表
    links = html.xpath('//*[@id="play_0"]/ul/li/a')
    return book_name, links


def content_process(content_origin):
    custom_replacements = {
        "我们马上记住本站网址,": "",
        ",若被浏/览/器/转/码,可退出转/码继续阅读,感谢支持.": "",
    }

    content = []
    for line in content_origin:
        for pattern, replacement in custom_replacements.items():
            line = line.replace(pattern, replacement)
        if not line:
            continue
        line = re.sub(r"([\\`*_\[\]()~#\+\-£\.!])", r"\\\1", line)
        content.append(line)

    return "\n".join(content)


# 2. 章节页处理
def get_chapter_content(chapter_url):
    chapter_content = []

    while chapter_url:
        content_html = get_content(chapter_url)
        # 2.1 获取章节内容
        content_origin = content_html.xpath('//*[@id="content"]/p/text()')
        content = content_process(content_origin)
        chapter_content.append(content)

        # 2.2 获取下一页链接
        next_page = content_html.xpath("//div[@class='m-page']/a[3]")[0]
        if next_page.text == "下一页":
            chapter_url = next_page.get("href")
        else:
            chapter_url = None

    return "\n\n".join(chapter_content)


if __name__ == "__main__":
    book_name, links = get_chapter_urls()
    print(f"Downloading {book_name}...")

    with open(book_name + ".md", "w", encoding="utf-8") as f:
        for link in tqdm.tqdm(links):
            title = link.text
            content_url = link.get("href")
            content = get_chapter_content(content_url)

            f.write("## " + title + "\n")
            f.write(content + "\n\n")

    print("Done!")
