from copy import deepcopy
import trafilatura
from trafilatura.settings import DEFAULT_CONFIG
from trafilatura.spider import focused_crawler, is_still_navigation
from typing import Union
import orjson


def init_trafilatura_config():
    my_config = deepcopy(DEFAULT_CONFIG)

    #TODO see more options in <https://trafilatura.readthedocs.io/en/latest/settings.html>

    return my_config


def run_focused_crawler(
    url: str,
    max_seen_urls: int = 10,
    max_known_urls: int = 100000,
    todo: Union[list, None] = None,
    known_links: Union[list, None] = None,
    lang: Union[str, None] = None
) -> tuple[list[str], list[str], bool]:
    """

    Args:
        max_seen_urls: the maximum number of pages to visit (default: 10)
        max_known_urls: the maximum number of pages to “know” about (default: 100000)
        todo: provide a previously generated list of pages to visit (i.e. a crawl frontier)
        known_links: provide a list of previously known pages
        lang: try to target links according to language heuristics (two-letter code)

    Returns:
        tuple: Returns the snapshot of the current state of the crawler.
        - to_visit: the list of pages to visit (next visited)
        - known_links: the list of known (list of know links)
        - navigatable: whether the crawler is still navigatable
    """
    # `to_visit` variable keeps track of what is ahead
    # `known_links` variable ensures that the same pages are not visited twice
    to_visit, known_links = focused_crawler(
        url,
        max_seen_urls=max_seen_urls,
        max_known_urls=max_known_urls,
        todo=todo,
        known_links=known_links,
        lang=lang,
    )

    navigatable = is_still_navigation(to_visit)

    # cast to list
    to_visit = list(to_visit)
    known_links = list(known_links)

    return to_visit, known_links, navigatable


def extract_url_content(
    url,
    output_format: Union[str, None] = "markdown",
    include_tables: bool = True,
    deduplicate: bool = False
):
    if output_format not in {"json", "xml", "markdown"}:
        output_format = None

    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        raise ValueError(f"Failed to download {url}")

    # get metadata and description from the downloaded content
    metadata = trafilatura.extract_metadata(downloaded)
    if metadata is None:
        description = ""
        title = ""
        metadata_str = ""
    else:
        description = metadata.description
        title = metadata.title

        metadata_json = metadata.as_dict()
        metadata_str = orjson.dumps(metadata_json).decode("utf-8")

    if output_format is None:
        content =  trafilatura.extract(
            downloaded,
            include_tables=include_tables,
            deduplicate=deduplicate
        )
    else:
        content = trafilatura.extract(
            downloaded,
            deduplicate=deduplicate,
            output_format=output_format,
            include_tables=include_tables
        )

    if content is None:
        print(f"Failed to extract content from {url}")
        return None

    return {
        "url": url,
        "crawled_content": content,
        "description": description,
        "title": title,
        "metadata":metadata_str,
    }


class TrafilaturaCrawler:
    def __init__(self):
        self.config = init_trafilatura_config()

    def crawl(self, url: str, return_format: str = "markdown") -> str:
        """
        Crawl a URL and return the content in the specified format.

        Args:
            url (str): The URL to crawl.
            return_format (str): The format to return the content in. Options are 'html', 'json', 'xml', 'markdown'.

        Returns:
            str: The crawled content in the specified format.
        """
        result = extract_url_content(url, output_format=return_format)
        if result is None:
            raise ValueError(f"Failed to crawl {url}")
        return result
