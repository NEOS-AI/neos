from abc import ABC

from neos.utils.trafilatura_utils import extract_url_content

from .article import Article
from .jina_client import JinaClient
from .readability_extractor import ReadabilityExtractor


class BaseCrawler(ABC):
    def crawl(self, url: str) -> Article:
        raise NotImplementedError


class Crawler(BaseCrawler):
    def crawl(self, url: str) -> Article:
        # To help LLMs better understand content, we extract clean
        # articles from HTML, convert them to markdown, and split
        # them into text and image blocks for one single and unified
        # LLM message.
        #
        # Jina is not the best crawler on readability, however it's
        # much easier and free to use.
        #
        # Instead of using Jina's own markdown converter, we'll use
        # our own solution to get better readability results.
        jina_client = JinaClient()
        html = jina_client.crawl(url, return_format="html")
        extractor = ReadabilityExtractor()
        article = extractor.extract_article(html)
        article.url = url
        return article


class TrafilaturaCrawler(BaseCrawler):
    def crawl(self, url: str) -> Article:
        result = extract_url_content(
            url, output_format="markdown", include_tables=True, deduplicate=True
        )
        content = result["content"]
        title = result["title"]

        article = Article(title=title, html_content=content)
        article.set_markdown(content)

        return article
