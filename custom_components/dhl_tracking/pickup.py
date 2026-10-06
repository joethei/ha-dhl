"""Packstation and pickup point support.

A parcel that waits in a Packstation keeps ``statusCode: transit`` until it is
collected. What sets it apart is ``statusDetailed`` and a description that
embeds the pickup point as an HTML link::

    Die Sendung liegt in der <a href='https://www.dhl.de/...?address=27472:205
    &preferPackstation=true' ...><span class='arrow'></span>Packstation 205,
    Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven</a> zur Abholung bereit.

The helpers here turn that into structured data, and turn DHL's HTML texts
into plain text for sensor states and event payloads.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

from .const import READY_FOR_PICKUP_DETAIL_PREFIX, STATUS_CODE_TRANSIT


def is_ready_for_pickup(status: Any) -> bool:
    """Return whether a status block or event reports a parcel awaiting pickup.

    Works on both ``status`` and the entries of ``events[]``, which share the
    ``statusCode``/``statusDetailed`` fields.
    """
    if not isinstance(status, dict):
        return False
    detailed = status.get("statusDetailed")
    return (
        status.get("statusCode") == STATUS_CODE_TRANSIT
        and isinstance(detailed, str)
        and detailed.startswith(READY_FOR_PICKUP_DETAIL_PREFIX)
    )


class _TextAndLinks(HTMLParser):
    """Collect the visible text and the links of an HTML fragment."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, _collapse("".join(self._link_text))))
            self._href = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._href is not None:
            self._link_text.append(data)


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _parse(value: str) -> _TextAndLinks:
    parser = _TextAndLinks()
    parser.feed(value)
    parser.close()
    return parser


def plain_text(value: Any) -> Any:
    """Return DHL free text without HTML markup.

    Non-strings and texts without markup are returned unchanged, so this is
    safe to apply to any field.
    """
    if not isinstance(value, str) or "<" not in value:
        return value
    return _collapse("".join(_parse(value).text)) or None


def pickup_location(status: Any) -> dict[str, Any] | None:
    """Return the pickup point named in a status description, if any.

    The link text is DHL's own label (``Packstation 205, <street>, <postal
    code> <city>``). The ``address`` query parameter of the location finder
    link carries the postal code and the Packstation number in a language
    independent form, so those are taken from there.
    """
    if not isinstance(status, dict):
        return None
    for field in ("description", "remark"):
        value = status.get(field)
        if not isinstance(value, str) or "<a" not in value:
            continue
        for href, label in _parse(value).links:
            if not label:
                continue
            name, _, address = label.partition(",")
            location: dict[str, Any] = {
                "label": label,
                "name": name.strip(),
                "address": address.strip() or None,
                "url": href or None,
            }
            query = parse_qs(urlparse(href).query)
            postal_code, _, locker_id = (query.get("address") or [""])[0].partition(":")
            if postal_code:
                location["postal_code"] = postal_code
            if locker_id:
                location["locker_id"] = locker_id
            return {k: v for k, v in location.items() if v is not None}
    return None
