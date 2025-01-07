import queue
import atexit
import threading

from typing import Any, Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor

from fruition.api.client.webservice.base import WebServiceAPIClientBase
from fruition.api.middleware.webservice.authentication.digest import DigestAuthenticationMiddleware
from fruition.util.strings import Serializer

class LogAggregateClient(
    WebServiceAPIClientBase,
    DigestAuthenticationMiddleware
):
    """
    Client for the Log Aggregate service
    """

    def __init__(self) -> None:
        super().__init__()
        self._logs = queue.Queue()
        self._stop = threading.Event()
        self._started = False

    def start(self) -> None:
        """
        Start the worker thread
        """
        self._started = True
        self._worker = threading.Thread(target=self.work, daemon=True)
        self._worker.start()
        atexit.register(self.stop)

    def check_start(self) -> None:
        """
        Start the worker thread if it hasn't been started
        """
        if not self._started:
            self.start()

    @property
    def max_workers(self) -> int:
        """
        :return: The maximum number of workers to use for flushing logs
        """
        return self.configuration.get("max_workers", 10)

    @property
    def interval(self) -> int:
        """
        :return: The interval in seconds to flush logs
        """
        return self.configuration.get("interval", 5)

    @property
    def stopped(self) -> bool:
        """
        :return: Whether the worker thread has been stopped
        """
        return self._stop.is_set()

    def stop(self) -> None:
        """
        Stop the worker thread
        """
        self._stop.set()
        self._worker.join()
        self.flush(True)

    def work(self) -> None:
        """
        Target method for worker thread
        """
        while not self.stopped:
            self.flush()
            self._stop.wait(self.interval)

    def flush(self, sync: bool=False) -> None:
        """
        Flush logs to the server
        Don't call this manually from outside the worker thread
        """
        if self._logs.empty():
            return

        log_lines: Dict[str, List[str]] = {}
        while not self._logs.empty():
            try:
                tag, line = self._logs.get_nowait()
                log_lines.setdefault(tag, []).append(line)
            except queue.Empty:
                break

        if sync:
            for tag, lines in log_lines.items():
                self.post(f"/{tag}", data="\n".join(lines))
            return
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for tag, lines in log_lines.items():
                executor.submit(self.post, f"/{tag}", data="\n".join(lines))

    def log(self, data: Any, tag: Optional[str]=None) -> None:
        """
        Log data to the server. This method is thread-safe.

        :param data: The data to log
        :param tag: The tag to log the data under. Defaults to "default"
        """
        self.check_start()
        if tag is None:
            tag = "default"
        self._logs.put_nowait((tag, Serializer.serialize(data)))

    def read(self, tag: Optional[str]=None, date: Optional[str]=None) -> str:
        """
        Read logs from the server

        :param tag: The tag to read logs from. Defaults to "default"
        :param date: The date to read logs from. Defaults to None
        :return: The logs
        """
        if tag is None:
            tag = "default"
        if date is not None:
            return self.get(f"/{tag}/{date}").text
        return self.get(f"/{tag}").text
