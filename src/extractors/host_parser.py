import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class HostParser:
    """
    Extracts host details from a single review container where possible.

    Attempts to populate:
      - id
      - firstName
      - profilePath
      - pictureUrl
      - isSuperhost
    """

    def parse_host(self, container: Any) -> Dict[str, Any]:
        host: Dict[str, Any] = {
            "id": None,
            "firstName": None,
            "profilePath": None,
            "pictureUrl": None,
            "isSuperhost": False,
        }

        host_link = self._find_host_link(container)
        if host_link:
            href = host_link.get("href")
            host["profilePath"] = href
            host["id"] = self._extract_user_id_from_href(href)
            text = host_link.get_text(strip=True)
            if text:
                # Airbnb often shows "Response from <FirstName>"
                text = re.sub(r"^Response from\s+", "", text, flags=re.IGNORECASE)
                host["firstName"] = text

        picture = self._find_host_picture(container)
        if picture:
            host["pictureUrl"] = picture

        host["isSuperhost"] = self._detect_superhost_flag(container)
        return host

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _find_host_link(self, container: Any) -> Optional[Any]:
        """
        We try to discover the host link based on context:
        usually near a "Response from" phrase or inside a host response block.
        """
        # Search within a host-response section if present
        host_sections = [
            container.find("section", attrs={"data-testid": "host-response"}),
            container.find("div", attrs={"data-testid": "review-detail-host-response"}),
        ]
        for section in host_sections:
            if not section:
                continue
            for link in section.find_all("a", href=True):
                if "/users/show/" in link["href"]:
                    return link

        # Fallback: any link with /users/show/ and "Response from" nearby
        text = container.get_text(" ", strip=True)
        response_idx = text.lower().find("response from")
        for link in container.find_all("a", href=True):
            href = link["href"]
            if "/users/show/" not in href:
                continue
            if response_idx != -1:
                # Heuristic: this link is likely the host
                return link

        # If still nothing, we give up
        return None

    def _extract_user_id_from_href(self, href: str) -> Optional[str]:
        match = re.search(r"/users/show/(\d+)", href)
        if match:
            return match.group(1)
        return None

    def _find_host_picture(self, container: Any) -> Optional[str]:
        # Look for avatar-like images inside host-response sections
        host_sections = [
            container.find("section", attrs={"data-testid": "host-response"}),
            container.find("div", attrs={"data-testid": "review-detail-host-response"}),
        ]
        for section in host_sections:
            if not section:
                continue
            for img in section.find_all("img"):
                src = img.get("src")
                if src:
                    return src
        return None

    def _detect_superhost_flag(self, container: Any) -> bool:
        text = container.get_text(" ", strip=True).lower()
        # Look for "superhost" near a host indicator; for simplicity, just check text
        return "superhost" in text