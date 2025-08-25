import re
from urllib.parse import urljoin

from markdownify import markdownify as md


class Article:
    url: str

    def __init__(self, title: str, html_content: str):
        self.title = title
        self.html_content = html_content
        self.markdown_content = None

    def set_markdown(self, markdown: str):
        self.markdown_content = markdown

    def to_markdown(self, including_title: bool = True) -> str:
        if self.markdown_content is not None:
            return self.markdown_content

        markdown = ""
        if including_title:
            markdown += f"# {self.title}\n\n"
        markdown += md(self.html_content)
        return markdown

    def to_message(self) -> list[dict]:
        image_pattern = r"!\[.*?\]\((.*?)\)"

        content: list[dict[str, str]] = []
        parts = re.split(image_pattern, self.to_markdown())

        for i, part in enumerate(parts):
            if i % 2 == 1:
                image_url = urljoin(self.url, part.strip())
                content.append({"type": "image_url", "image_url": {"url": image_url}})
            else:
                content.append({"type": "text", "text": part.strip()})

        return content
