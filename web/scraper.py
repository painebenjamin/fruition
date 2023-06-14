import os

from typing import List, Any

from pibble.util.log import logger
from pibble.util.strings import pretty_print
from pibble.util.helpers import find_executable

from urllib.parse import urlparse

try:
    from selenium.webdriver import Chrome
    from selenium.webdriver.chrome.options import Options
except ImportError:
    logger.warning(
        "Cannot import selenium. Make sure to install with the [browser] requirement selected."
    )
    raise


class WebScraper:
    """
    A simple class that wraps around Selenium webdrivers.

    Makes for easy initialization, as well as providing a few helper functions.

    :param width int: The width of the window. Default 1920.
    :param height int: The height of the window. Default 1080.
    """

    def __init__(self, width: int = 1920, height: int = 1080):
        self.arguments = ["--headless", "--window-size={0}x{1}".format(width, height)]
        if os.name != "nt" and os.geteuid() == 0:  # type: ignore
            logger.warning(
                "Running chromedriver with --no-sandbox as root. It is not recommended to do this."
            )
            self.arguments.append("--no-sandbox")

    def driver(self) -> Chrome:
        if not hasattr(self, "_driver"):
            chromedriver = find_executable("chromedriver")
            logger.debug(
                "Initializing web scraper with chrome driver {0}, arguments {1}".format(
                    chromedriver, pretty_print(*self.arguments)
                )
            )
            options = Options()
            for argument in self.arguments:
                options.add_argument(argument)  # type: ignore
            self._driver = Chrome(options=options)
        return self._driver

    def crawl(self, url: str) -> List[str]:
        """
        Starting from one URL, find all internal links on that URL. Then recursively
        find the URLs on those internal links, and return the set of all found URLs.

        :param url str: The starting URL.
        :returns list: All URLs found, sorted.
        """
        urls_crawled = set()
        crawled_domain = urlparse(url).netloc
        driver = self.driver()

        def crawl_url(url: str) -> None:
            urls_crawled.add(url)
            logger.debug("Crawling URL {0}".format(url))
            driver.get(url)
            for link in driver.find_elements_by_tag_name("a"):  # type: ignore
                href = link.get_attribute("href")
                if href:
                    parsed = urlparse(href)
                    if parsed.netloc == crawled_domain:
                        url_to_crawl = (
                            parsed._replace(fragment="")._replace(query="").geturl()
                        )
                        if url_to_crawl not in urls_crawled:
                            crawl_url(url_to_crawl)

        crawl_url(url)
        driver.close()
        crawled = list(urls_crawled)
        crawled.sort()
        return crawled

    def __enter__(self) -> Chrome:
        return self.driver()

    def __exit__(self, *args: Any) -> None:
        if hasattr(self, "_driver"):
            try:
                self._driver.close()
            except:
                pass
