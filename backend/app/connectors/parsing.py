"""Non-executing HTML and exact timestamp normalization."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from selectolax.parser import HTMLParser

from app.eligibility.models import PublicationEvidence, Salary

from .safe_http import SourceHTTPError, validate_url


def readable_html(value: str) -> str:
    tree = HTMLParser(html.unescape(value or ""))
    for element in tree.css("script,style,iframe,object,embed,svg,template,noscript"):
        element.decompose()
    text = tree.body.text(separator="\n") if tree.body else tree.text(separator="\n")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def safe_html(text: str) -> str:
    return "\n".join("<p>" + html.escape(line) + "</p>" for line in text.splitlines() if line.strip())


def sanitized_html(value: str) -> str:
    tree = HTMLParser(html.unescape(value or ""))
    allowed = {"p", "br", "ul", "ol", "li", "strong", "em", "b", "i", "h1", "h2", "h3", "h4", "a"}
    blocked = {"script", "style", "iframe", "object", "embed", "svg", "template", "noscript"}

    def render(node):
        if node.tag in blocked:
            return ""
        if node.tag == "-text":
            return html.escape(node.text())
        children, child = [], node.child
        while child is not None:
            children.append(render(child))
            child = child.next
        content = "".join(children)
        if node.tag not in allowed:
            return content
        attrs = ""
        if node.tag == "a":
            href = node.attributes.get("href", "")
            try:
                validate_url(href)
                attrs = ' href="' + html.escape(href, quote=True) + '" rel="noopener noreferrer"'
            except SourceHTTPError:
                return content
        return "<br>" if node.tag == "br" else "<" + node.tag + attrs + ">" + content + "</" + node.tag + ">"

    return render(tree.root) if tree.root else ""


def exact_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.tzinfo is not None else None
    except ValueError:
        return None


def publication(value: Any, field: str, kind: str = "ORIGINAL") -> PublicationEvidence:
    exact = exact_time(value)
    if exact:
        return PublicationEvidence(
            earliest=exact,
            latest=exact,
            precision="EXACT",
            kind=kind,
            source_field=field,
            source_timezone="explicit offset",
        )
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            base = datetime.fromisoformat(value).replace(tzinfo=UTC)
            # Date with unknown zone can span UTC+14 through UTC-12. No invented midnight precision.
            return PublicationEvidence(
                earliest=base - timedelta(hours=14),
                latest=base + timedelta(days=1, hours=12) - timedelta(microseconds=1),
                precision="DATE",
                kind=kind,
                source_field=field,
                source_timezone=None,
            )
        except ValueError:
            pass
    return PublicationEvidence(source_field=field, kind=kind)


def country(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value")
    if not isinstance(value, str):
        return None
    v = value.strip().upper()
    aliases = {
        "USA": "US",
        "UNITED STATES": "US",
        "UNITED STATES OF AMERICA": "US",
        "CANADA": "CA",
        "UNITED KINGDOM": "GB",
        "UK": "GB",
    }
    return aliases.get(v, v if re.fullmatch(r"[A-Z]{2}", v) else None)


def employment(value: Any) -> str | None:
    if isinstance(value, list):
        values = {employment(v) for v in value}
        return next(iter(values)) if len(values) == 1 else "CONFLICTING"
    if not isinstance(value, str):
        return None
    v = re.sub(r"[\s_-]", "", value).lower()
    return {
        "fulltime": "FULL_TIME",
        "parttime": "PART_TIME",
        "contract": "CONTRACT",
        "temporary": "TEMPORARY",
        "intern": "INTERNSHIP",
        "internship": "INTERNSHIP",
        "freelance": "FREELANCE",
        "seasonal": "SEASONAL",
    }.get(v, value)


def money(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def salary(minimum=None, maximum=None, currency=None, interval=None, source=None) -> Salary:
    minimum, maximum = money(minimum), money(maximum)
    if minimum is not None and maximum is not None and minimum > maximum:
        return Salary(source=source)
    interval = {
        "1 YEAR": "YEAR",
        "YEARLY": "YEAR",
        "ANNUAL": "YEAR",
        "YEAR": "YEAR",
        "1 HOUR": "HOUR",
        "HOURLY": "HOUR",
        "HOUR": "HOUR",
    }.get(str(interval).upper(), interval)
    return Salary(minimum=minimum, maximum=maximum, currency=currency, interval=interval, source=source)
