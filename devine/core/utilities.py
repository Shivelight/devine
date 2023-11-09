import ast
import contextlib
import importlib.util
import re
import shutil
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import AsyncIterator, Optional, Sequence, Union
from urllib.parse import urlparse

import chardet
import pproxy
from construct import ValidationError
from langcodes import Language, closest_match
from pymp4.parser import Box
from unidecode import unidecode

from devine.core.config import config
from devine.core.constants import LANGUAGE_MAX_DISTANCE
from devine.core.sessions import RequestsSession, ServiceSession


def rotate_log_file(log_path: Path, keep: int = 20) -> Path:
    """
    Update Log Filename and delete old log files.
    It keeps only the 20 newest logs by default.
    """
    if not log_path:
        raise ValueError("A log path must be provided")

    try:
        log_path.relative_to(Path(""))  # file name only
    except ValueError:
        pass
    else:
        log_path = config.directories.logs / log_path

    log_path = log_path.parent / log_path.name.format_map(defaultdict(
        str,
        name="root",
        time=datetime.now().strftime("%Y%m%d-%H%M%S")
    ))

    if log_path.parent.exists():
        log_files = [x for x in log_path.parent.iterdir() if x.suffix == log_path.suffix]
        for log_file in log_files[::-1][keep-1:]:
            # keep n newest files and delete the rest
            log_file.unlink()

    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


def import_module_by_path(path: Path) -> ModuleType:
    """Import a Python file by Path as a Module."""
    if not path:
        raise ValueError("Path must be provided")
    if not isinstance(path, Path):
        raise TypeError(f"Expected path to be a {Path}, not {path!r}")
    if not path.exists():
        raise ValueError("Path does not exist")

    # compute package hierarchy for relative import support
    if path.is_relative_to(config.directories.core_dir):
        name = []
        _path = path.parent
        while _path.stem != config.directories.core_dir.stem:
            name.append(_path.stem)
            _path = _path.parent
        name = ".".join([config.directories.core_dir.stem] + name[::-1])
    else:
        # is outside the src package
        if str(path.parent.parent) not in sys.path:
            sys.path.insert(1, str(path.parent.parent))
        name = path.parent.stem

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def get_binary_path(*names: str) -> Optional[Path]:
    """Find the path of the first found binary name."""
    for name in names:
        path = shutil.which(name)
        if path:
            return Path(path)
    return None


def sanitize_filename(filename: str, spacer: str = ".") -> str:
    """
    Sanitize a string to be filename safe.

    The spacer is safer to be a '.' for older DDL and p2p sharing spaces.
    This includes web-served content via direct links and such.
    """
    # replace all non-ASCII characters with ASCII equivalents
    filename = unidecode(filename)

    # remove or replace further characters as needed
    filename = "".join(c for c in filename if unicodedata.category(c) != "Mn")  # hidden characters
    filename = filename.\
        replace("/", " & ").\
        replace(";", " & ")  # e.g. multi-episode filenames
    filename = re.sub(r"[:; ]", spacer, filename)  # structural chars to (spacer)
    filename = re.sub(r"[\\*!?¿,'\"“”()<>|$#]", "", filename)  # not filename safe chars
    filename = re.sub(rf"[{spacer}]{{2,}}", spacer, filename)  # remove extra neighbouring (spacer)s

    return filename


def is_close_match(language: Union[str, Language], languages: Sequence[Union[str, Language, None]]) -> bool:
    """Check if a language is a close match to any of the provided languages."""
    languages = [x for x in languages if x]
    if not languages:
        return False
    return closest_match(language, list(map(str, languages)))[1] <= LANGUAGE_MAX_DISTANCE


def get_boxes(data: bytes, box_type: bytes, as_bytes: bool = False) -> Box:
    """Scan a byte array for a wanted box, then parse and yield each find."""
    # using slicing to get to the wanted box is done because parsing the entire box and recursively
    # scanning through each box and its children often wouldn't scan far enough to reach the wanted box.
    # since it doesn't care what child box the wanted box is from, this works fine.
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("data must be bytes")
    while True:
        try:
            index = data.index(box_type)
        except ValueError:
            break
        if index < 0:
            break
        if index > 4:
            index -= 4  # size is before box type and is 4 bytes long
        data = data[index:]
        try:
            box = Box.parse(data)
        except IOError:
            # since get_init_segment might cut off unexpectedly, pymp4 may be unable to read
            # the expected amounts of data and complain, so let's just end the function here
            break
        except ValidationError as e:
            if box_type == b"tenc":
                # ignore this error on tenc boxes as the tenc definition isn't consistent,
                # some services don't even put valid data and mix it up with avc1...
                continue
            raise e
        if as_bytes:
            box = Box.build(box)
        yield box


def ap_case(text: str, keep_spaces: bool = False, stop_words: tuple[str] = None) -> str:
    """
    Convert a string to title case using AP/APA style.
    Based on https://github.com/words/ap-style-title-case

    Parameters:
        text: The text string to title case with AP/APA style.
        keep_spaces: To keep the original whitespace, or to just use a normal space.
            This would only be needed if you have special whitespace between words.
        stop_words: Override the default stop words with your own ones.
    """
    if not text:
        return ""

    if not stop_words:
        stop_words = ("a", "an", "and", "at", "but", "by", "for", "in", "nor",
                      "of", "on", "or", "so", "the", "to", "up", "yet")

    splitter = re.compile(r"(\s+|[-‑–—])")
    words = splitter.split(text)

    return "".join([
        [" ", word][keep_spaces] if re.match(r"\s+", word) else
        word if splitter.match(word) else
        word.lower() if i != 0 and i != len(words) - 1 and word.lower() in stop_words else
        word.capitalize()
        for i, word in enumerate(words)
    ])


def get_ip_info(session: Optional[ServiceSession] = None) -> dict:
    """
    Use ipinfo.io to get IP location information.

    If you provide a Service Session with a Proxy, that proxies IP information
    is what will be returned.
    """
    return (session or RequestsSession()).get("https://ipinfo.io/json").json()


def time_elapsed_since(start: float) -> str:
    """
    Get time elapsed since a timestamp as a string.
    E.g., `1h56m2s`, `15m12s`, `0m55s`, e.t.c.
    """
    elapsed = int(time.time() - start)

    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)

    time_string = f"{minutes:d}m{seconds:d}s"
    if hours:
        time_string = f"{hours:d}h{time_string}"

    return time_string


def try_ensure_utf8(data: bytes) -> bytes:
    """
    Try to ensure that the given data is encoded in UTF-8.

    Parameters:
        data: Input data that may or may not yet be UTF-8 or another encoding.

    Returns the input data encoded in UTF-8 if successful. If unable to detect the
    encoding of the input data, then the original data is returned as-received.
    """
    try:
        data.decode("utf8")
        return data
    except UnicodeDecodeError:
        try:
            # CP-1252 is a superset of latin1
            return data.decode("cp1252").encode("utf8")
        except UnicodeDecodeError:
            try:
                # last ditch effort to detect encoding
                detection_result = chardet.detect(data)
                if not detection_result["encoding"]:
                    return data
                return data.decode(detection_result["encoding"]).encode("utf8")
            except UnicodeDecodeError:
                return data


@contextlib.asynccontextmanager
async def start_pproxy(proxy: str) -> AsyncIterator[str]:
    proxy = urlparse(proxy)

    scheme = {
        "https": "http+ssl",
        "socks5h": "socks"
    }.get(proxy.scheme, proxy.scheme)

    remote_server = f"{scheme}://{proxy.hostname}"
    if proxy.port:
        remote_server += f":{proxy.port}"
    if proxy.username or proxy.password:
        remote_server += "#"
    if proxy.username:
        remote_server += proxy.username
    if proxy.password:
        remote_server += f":{proxy.password}"

    server = pproxy.Server("http://localhost:0")  # random port
    remote = pproxy.Connection(remote_server)
    handler = await server.start_server({"rserver": [remote]})

    try:
        port = handler.sockets[0].getsockname()[1]
        yield f"http://localhost:{port}"
    finally:
        handler.close()
        await handler.wait_closed()


class FPS(ast.NodeVisitor):
    def visit_BinOp(self, node: ast.BinOp) -> float:
        if isinstance(node.op, ast.Div):
            return self.visit(node.left) / self.visit(node.right)
        raise ValueError(f"Invalid operation: {node.op}")

    def visit_Num(self, node: ast.Num) -> complex:
        return node.n

    def visit_Expr(self, node: ast.Expr) -> float:
        return self.visit(node.value)

    @classmethod
    def parse(cls, expr: str) -> float:
        return cls().visit(ast.parse(expr).body[0])
