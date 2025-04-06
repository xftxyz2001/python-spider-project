import os
import subprocess
import sys
import time

import requests
from bs4 import BeautifulSoup


def get_url_to_soup(url):
    """
    获取指定URL的BeautifulSoup对象
    """
    if not url.startswith("http"):
        url = "https://greasyfork.org" + url
    print(f"Fetching {url} ...")
    response = requests.get(url)
    time.sleep(2)
    response.raise_for_status()  # 检查请求是否成功
    return BeautifulSoup(response.text, "html.parser")


def get_all_version_info(url):
    """
    获取所有版本信息
    """
    versions = []

    url = f"{url}/versions?list_all=1"
    while url:
        soup = get_url_to_soup(url)

        version_list = soup.find("ul", class_="history_versions")
        if version_list is None:
            print(f"No version list found for {url}")
            break

        for version_item in version_list.find_all("li"):
            version = {}
            version["ver"] = version_item.find(
                "span", class_="version-number"
            ).get_text(strip=True)
            version["url"] = version_item.find("a")["href"]
            changelog = version_item.find("span", class_="version-changelog")
            if changelog:
                version["desc"] = changelog.get_text(strip=True)
            versions.append(version)

        # 获取下一页的链接
        pagination = soup.find("div", class_="pagination")
        if pagination:
            next_page = pagination.find("a", class_="next_page")
            if next_page:
                url = next_page["href"]
            else:
                break
        else:
            break

    return versions[::-1]


def download_one_version(version, config):
    """
    处理每个版本，下载并保存 version(ver, url, desc) config(base_file_name, use_git, git_path)
    """
    ver = version["ver"]
    url = version["url"]
    desc = version.get("desc", "")

    base_file_name = config["base_file_name"]
    use_git = config["use_git"]

    # 获取代码内容
    arg_index = url.find("?")
    if arg_index != -1:
        url = f"{url[:arg_index]}/code{url[arg_index:]}"

    soup = get_url_to_soup(url)
    code_container = soup.find("div", class_="code-container")
    if code_container is None:
        print(f"No code-container found for {ver}")
        return
    code_content = code_container.get_text()

    # 保存代码到文件
    if use_git:
        full_file_name = f"{base_file_name}.js"
        with open(full_file_name, "w", encoding="utf-8") as file:
            file.write(code_content)

        git_path = config["git_path"]
        if not os.path.exists(".git"):
            subprocess.run([git_path, "init"], check=True)
        subprocess.run([git_path, "add", full_file_name], check=True)
        comment = ver
        if desc:
            comment += f" {desc}"
        subprocess.run(
            [
                git_path,
                "commit",
                "-m",
                comment,
            ],
            check=True,
        )
    else:
        full_file_name = f"{base_file_name}_{ver}.js"
        with open(full_file_name, "w", encoding="utf-8") as file:
            file.write(code_content)


def py_greasyfork_download(url, config={}):
    # 获取所有版本信息
    print(f"Fetching all versions ...")
    versions = get_all_version_info(url)
    len_versions = len(versions)
    print(f"Total version: {len_versions}")

    for i, version in enumerate(versions):
        print(f"({i+1}/{len_versions}) Processing version {version['ver']} ...")
        download_one_version(
            version,
            {
                "base_file_name": "script",
                "use_git": False,
                "git_path": "git",
                **config,
            },
        )


if __name__ == "__main__":
    # 调用函数下载脚本，如果命令行数没有传递URL参数，则使用input函数获取
    # if len(sys.argv) > 1:
    #     url = sys.argv[1]
    # else:
    #     url = input("Please enter the URL: ")

    # url = input(
    #     "Please enter the URL(eg. https://greasyfork.org/zh-CN/scripts/123-abc): "
    # )
    # if len(url) == 0:
    #     print("URL is empty.")
    #     sys.exit(1)

    # # 请输入保存的文件名前缀，不包含.js
    # base_file_name = input(
    #     "Please enter the base file name(not include .js default script): "
    # )

    url = "https://greasyfork.org/zh-CN/scripts/436446-%E7%BD%91%E7%9B%98%E7%9B%B4%E9%93%BE%E4%B8%8B%E8%BD%BD%E5%8A%A9%E6%89%8B"
    py_greasyfork_download(
        url,
        {
            "base_file_name": "script",
            "use_git": True,
            "git_path": r"C:\Program Files\Git\mingw64\bin\git.exe",
        },
    )
    print("Done.")
