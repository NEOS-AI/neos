import logging
from typing import Annotated
from langchain_core.tools import tool
import orjson

from src.config.crawler import USE_TRAFILATURA
from src.crawler import Crawler, TrafilaturaCrawler

from .decorators import log_io


logger = logging.getLogger(__name__)


@tool
@log_io
def crawl_tool(
    url: Annotated[str, "The url to crawl."],
) -> str:
    """Use this to crawl a url and get a readable content in markdown format."""
    try:
        if USE_TRAFILATURA:
            crawler = TrafilaturaCrawler()
            crawled_result = crawler.crawl(url, return_format="markdown")
            return orjson.dumps(crawled_result).decode("utf-8")
        else:
            crawler = Crawler()
            article = crawler.crawl(url)
            result = {"url": url, "crawled_content": article.to_markdown()[:1000]}
            return orjson.dumps(result).decode("utf-8")
    except BaseException as e:
        error_msg = f"Failed to crawl. Error: {repr(e)}"
        logger.error(error_msg)
        return error_msg
