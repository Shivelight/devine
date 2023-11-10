from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Optional, Union

import requests

if TYPE_CHECKING:
    from requests.sessions import _Data


class ServiceSession(metaclass=ABCMeta):
    """The Service Session Base Class."""

    @property
    @abstractmethod
    def cookies(self) -> Any:
        ...

    @property
    @abstractmethod
    def headers(self) -> Any:
        ...

    @property
    @abstractmethod
    def proxies(self) -> Any:
        ...

    @abstractmethod
    def get(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def options(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def head(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def post(self, url: Union[str, bytes], data: Optional["_Data"] = None, json: Any = None, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def put(self, url: Union[str, bytes], data: Optional["_Data"] = None, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def patch(self, url: Union[str, bytes], data: Optional["_Data"] = None, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def delete(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        ...


class RequestsSession(ServiceSession):
    """Service Session for requests and requests-like libraries."""

    def __init__(self, session: Union[requests.Session, Any] = None):
        self.session = session or requests.Session()

    @property
    def cookies(self) -> Any:
        return self.session.cookies

    @property
    def headers(self) -> Any:
        return self.session.headers

    @property
    def proxies(self) -> Any:
        return self.session.proxies

    def get(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        return self.session.get(url, **kwargs)

    def options(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        return self.session.options(url, **kwargs)

    def head(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        return self.session.head(url, **kwargs)

    def post(self, url: Union[str, bytes], data: Optional["_Data"] = None, json: Any = None, **kwargs: Any) -> Any:
        return self.session.post(url, data=data, json=json, **kwargs)

    def put(self, url: Union[str, bytes], data: Optional["_Data"] = None, **kwargs: Any) -> Any:
        return self.session.put(url, data=data, **kwargs)

    def patch(self, url: Union[str, bytes], data: Optional["_Data"] = None, **kwargs: Any) -> Any:
        return self.session.patch(url, data=data, **kwargs)

    def delete(self, url: Union[str, bytes], **kwargs: Any) -> Any:
        return self.session.delete(url, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)


__ALL__ = (ServiceSession, RequestsSession)
