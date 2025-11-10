import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from langdetect import LangDetectException, detect

from .reviewer_parser import ReviewerParser
from .host_parser import HostParser

logger = logging.getLogger(__name__)

class ReviewParser:
    """
    Responsible for turning a single Airbnb room's HTML review page
    into a list of normalized review dictionaries.

    The parser uses a "best-effort" approach: if specific elements
    cannot be found, fields are left as None or sensible defaults.
    """

    def __init__(self) -> None:
        self.reviewer_parser = ReviewerParser()
        self.host_parser = HostParser()

    def parse_reviews(
        self,
        html: str,
        room_url: str,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        containers = self._find_review_containers(soup)

        reviews: List[Dict[str, Any]] = []
        for container in containers:
            if max_items is not None and len(reviews) >= max_items:
                break

            try:
                review = self._parse_single_review(container, room_url)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Failed to parse review: %s", exc)
                continue

            if review:
                reviews.append(review)

        return reviews

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _find_review_containers(self, soup: BeautifulSoup) -> List[Any]:
        """
        Try several CSS selectors that commonly appear on Airbnb review pages.
        If none match, fall back to generic <article> tags.
        """
        selectors = [
            "[data-review-id]",
            'div[data-testid="review"]',
            'div[itemprop="review"]',
            "div.review",
            "article",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                logger.debug(
                    "Found %d review containers using selector %r",
                    len(elements),
                    selector,
                )
                return elements

        logger.warning("No obvious review containers found, returning empty list.")
        return []

    def _parse_single_review(self, container: Any, room_url: str) -> Dict[str, Any]:
        review_id = (
            container.get("data-review-id")
            or container.get("id")
            or self._extract_review_id_from_attributes(container)
        )

        comment = self._extract_comment(container)
        rating = self._extract_rating(container)
        created_at, localized_date = self._extract_dates(container)
        response = self._extract_host_response(container)
        review_photos = self._extract_review_photos(container)

        reviewer = self.reviewer_parser.parse_reviewer(container)
        host = self.host_parser.parse_host(container)

        language: Optional[str] = None
        if comment:
            try:
                language = detect(comment)
            except LangDetectException:
                language = None

        review: Dict[str, Any] = {
            "roomUrl": room_url,
            "reviewId": review_id,
            "rating": rating,
            "comment": comment,
            "language": language,
            "createdAt": created_at,
            "localizedDate": localized_date,
            "reviewer": reviewer,
            "host": host,
            "response": response,
            "reviewPhotos": review_photos,
        }
        return review

    def _extract_review_id_from_attributes(self, container: Any) -> Optional[str]:
        # Last-resort: search for "review-" pattern in id or data- attributes
        for attr, value in container.attrs.items():
            if not isinstance(value, str):
                continue
            match = re.search(r"review[-_]?(\d+)", value)
            if match:
                return match.group(1)
        return None

    def _extract_comment(self, container: Any) -> Optional[str]:
        # Airbnb often uses data-testid attributes for key content
        candidates = [
            'div[data-testid="review-comments"]',
            "q",
            "blockquote",
            "p",
        ]

        for selector in candidates:
            element = container.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                if text:
                    return text

        # Fallback: look for any <span> with long text
        longest_text = ""
        for span in container.find_all("span"):
            text = span.get_text(strip=True)
            if len(text) > len(longest_text):
                longest_text = text

        return longest_text or None

    def _extract_rating(self, container: Any) -> Optional[float]:
        # Look for explicit ratingValue
        rating_element = container.find(attrs={"itemprop": "ratingValue"})
        if rating_element and rating_element.get("content"):
            try:
                return float(rating_element["content"])
            except (TypeError, ValueError):
                pass

        # Look for aria-label patterns like "5 out of 5"
        for elem in container.find_all(attrs={"aria-label": True}):
            label = elem["aria-label"]
            match = re.search(r"(\d+(?:\.\d+)?)\s+out\s+of\s+5", label)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue

        # As a last resort, look for "★" patterns
        text = container.get_text(" ", strip=True)
        match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*5", text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        return None

    def _extract_dates(
        self,
        container: Any,
    ) -> (Optional[str], Optional[str]):
        # Look for <time> element first
        time_element = container.find("time")
        date_text = None

        if time_element:
            date_text = time_element.get("datetime") or time_element.get_text(strip=True)

        if not date_text:
            # Fallback: look for any span with 'date' in class or data-testid
            for span in container.find_all("span"):
                attrs = " ".join(
                    str(v) for v in span.attrs.values() if isinstance(v, str)
                )
                if "date" in attrs.lower():
                    date_text = span.get_text(strip=True)
                    break

        if not date_text:
            return None, None

        try:
            dt = dateparser.parse(date_text)
        except (ValueError, TypeError, OverflowError):
            return None, date_text  # Keep the original as "localizedDate" fallback

        created_at = dt.replace(tzinfo=None).isoformat() + "Z"
        localized_date = dt.strftime("%B %Y")
        return created_at, localized_date

    def _extract_host_response(self, container: Any) -> Optional[str]:
        candidates = [
            'div[data-testid="review-detail-host-response"]',
            'section[data-testid="host-response"]',
        ]

        for selector in candidates:
            elem = container.select_one(selector)
            if elem:
                text = elem.get_text(" ", strip=True)
                if text:
                    return text

        # Fallback: look for a "Response from" pattern
        text = container.get_text("\n", strip=True)
        pattern = r"Response from.*?:\s*(.+)"
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            response_text = match.group(1).strip()
            # Limit very long captures
            if len(response_text) > 2000:
                response_text = response_text[:2000].rsplit(" ", 1)[0] + "…"
            return response_text

        return None

    def _extract_review_photos(self, container: Any) -> List[str]:
        """
        Try to collect URLs for images that are likely part of the review
        content, not profile pictures.
        """
        photos: List[str] = []

        # Common attributes for review photos
        selectors = [
            'img[data-testid="review-photo"]',
            'img[data-original-uri]',
        ]
        for selector in selectors:
            for img in container.select(selector):
                url = img.get("data-original-uri") or img.get("src")
                if url and url not in photos:
                    photos.append(url)

        # Fallback: any <img> inside a dedicated photo container
        if not photos:
            for div in container.find_all("div"):
                classes = " ".join(div.get("class", []))
                if any(keyword in classes.lower() for keyword in ["photo", "image"]):
                    for img in div.find_all("img"):
                        url = img.get("src")
                        if url and url not in photos:
                            photos.append(url)

        return photos