import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class ReviewerParser:
    """
    Extracts reviewer details from a single review container.

    Attempts to populate:
      - id
      - firstName
      - profilePath
      - pictureUrl
      - isSuperhost
      - location
    """

    def parse_reviewer(self, container: Any) -> Dict[str, Any]:
        reviewer: Dict[str, Any] = {
            "id": None,
            "firstName": None,
            "profilePath": None,
            "pictureUrl": None,
            "isSuperhost": False,
            "location": None,
        }

        # Profile link (href usually contains /users/show/<id>)
        profile_link = self._find_profile_link(container)
        if profile_link:
            href = profile_link.get("href")
            reviewer["profilePath"] = href
            reviewer["id"] = self._extract_user_id_from_href(href)
            if profile_link.get_text(strip=True):
                reviewer["firstName"] = profile_link.get_text(strip=True)

        # Picture
        picture = self._find_profile_picture(container)
        if picture:
            reviewer["pictureUrl"] = picture

        # Location / Airbnb activity summary
        location = self._find_reviewer_location(container)
        if location:
            reviewer["location"] = location

        # Superhost? Usually marked by a badge or text near name
        reviewer["isSuperhost"] = self._detect_superhost_flag(container)

        return reviewer

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _find_profile_link(self, container: Any) -> Optional[Any]:
        for link in container.find_all("a", href=True):
            href = link["href"]
            if "/users/show/" in href:
                # Heuristic: first such link is usually the reviewer
                return link
        return None

    def _extract_user_id_from_href(self, href: str) -> Optional[str]:
        match = re.search(r"/users/show/(\d+)", href)
        if match:
            return match.group(1)
        return None

    def _find_profile_picture(self, container: Any) -> Optional[str]:
        # Look for <img> near the profile link
        for img in container.find_all("img"):
            alt = img.get("alt", "").lower()
            if "profile" in alt or "avatar" in alt:
                src = img.get("src")
                if src:
                    return src

        # Fallback: any small image likely to be avatar
        for img in container.find_all("img"):
            width = img.get("width")
            height = img.get("height")
            if width and height:
                try:
                    w = int(width)
                    h = int(height)
                except ValueError:
                    continue
                if max(w, h) <= 80:  # small avatar-size image
                    src = img.get("src")
                    if src:
                        return src
        return None

    def _find_reviewer_location(self, container: Any) -> Optional[str]:
        # Airbnb often shows "X years on Airbnb" or a location near the name
        text_candidates = []
        for elem in container.find_all(["span", "div"]):
            text = elem.get_text(" ", strip=True)
            if not text:
                continue
            lower = text.lower()
            if "years on airbnb" in lower or "year on airbnb" in lower:
                return text
            if "from " in lower and len(text) < 80:
                text_candidates.append(text)

        if text_candidates:
            # Take the shortest plausible location-like string
            return sorted(text_candidates, key=len)[0]
        return None

    def _detect_superhost_flag(self, container: Any) -> bool:
        text = container.get_text(" ", strip=True).lower()
        if "superhost" in text:
            # Could refer to host rather than reviewer, but usually okay as a heuristic
            return True
        return False