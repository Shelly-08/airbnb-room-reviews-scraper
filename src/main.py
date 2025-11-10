import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Ensure local src folder is on sys.path so we can import project modules
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from extractors.review_parser import ReviewParser  # noqa: E402
from utils.data_formatter import export_reviews  # noqa: E402

logger = logging.getLogger("airbnb_reviews")

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def load_settings(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        logger.warning("Settings file %s not found, using defaults.", path)
        return {
            "user_agent": "Mozilla/5.0 (compatible; AirbnbRoomReviewsScraper/1.0)",
            "timeout": 20,
            "verify_ssl": True,
            "proxies": None,
            "output_format": "json",
            "max_reviews_per_room": 200,
            "concurrent_requests": 2,
        }

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Fill sensible defaults if missing
    data.setdefault(
        "user_agent", "Mozilla/5.0 (compatible; AirbnbRoomReviewsScraper/1.0)"
    )
    data.setdefault("timeout", 20)
    data.setdefault("verify_ssl", True)
    data.setdefault("proxies", None)
    data.setdefault("output_format", "json")
    data.setdefault("max_reviews_per_room", 200)
    data.setdefault("concurrent_requests", 2)
    return data

def load_input(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Input file {path} not found. "
            "Create it or use --input-file to point to an existing JSON file."
        )

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "roomUrls" not in data or not isinstance(data["roomUrls"], list):
        raise ValueError(
            "Input JSON must contain a 'roomUrls' array with one or more Airbnb room review URLs."
        )

    return data

def create_session(settings: Dict[str, Any]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {"User-Agent": settings.get("user_agent")}
    )

    proxies = settings.get("proxies")
    if proxies:
        session.proxies.update(proxies)

    session.verify = settings.get("verify_ssl", True)
    return session

def scrape_room(
    room_url: str,
    session: requests.Session,
    parser: ReviewParser,
    settings: Dict[str, Any],
    max_items: Optional[int],
) -> List[Dict[str, Any]]:
    timeout = settings.get("timeout", 20)
    effective_max = max_items or settings.get("max_reviews_per_room")

    logger.info("Scraping reviews from %s (limit=%s)", room_url, effective_max)
    try:
        response = session.get(room_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch %s: %s", room_url, exc)
        return []

    html = response.text
    reviews = parser.parse_reviews(
        html=html,
        room_url=room_url,
        max_items=effective_max,
    )
    logger.info(
        "Parsed %d reviews for %s",
        len(reviews),
        room_url,
    )
    return reviews

def determine_output(
    input_cfg: Dict[str, Any],
    settings: Dict[str, Any],
    cli_format: Optional[str],
    cli_path: Optional[str],
) -> (str, Path):
    # Priority: CLI > input.json > settings > default
    fmt = (
        cli_format
        or input_cfg.get("output", {}).get("format")
        or settings.get("output_format")
        or "json"
    )
    fmt = fmt.lower()

    # Default output path if not specified anywhere
    default_name = f"reviews.{fmt}"
    path_str = (
        cli_path
        or input_cfg.get("output", {}).get("path")
        or str(Path("data") / default_name)
    )

    return fmt, Path(path_str)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Airbnb Room Reviews Scraper"
    )
    parser.add_argument(
        "--input-file",
        type=str,
        default=str(Path("data") / "sample_input.json"),
        help="Path to the JSON file containing roomUrls and optional options.",
    )
    parser.add_argument(
        "--settings-file",
        type=str,
        default=str(Path("src") / "config" / "settings.example.json"),
        help="Path to settings JSON file.",
    )
    parser.add_argument(
        "--output-format",
        type=str,
        choices=["json", "jsonl", "csv", "excel", "xml", "html"],
        help="Override output format (json, jsonl, csv, excel, xml, html).",
    )
    parser.add_argument(
        "--output-path",
        type=str,
        help="Override output file path.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()
    setup_logging(verbose=bool(args.verbose))

    settings_path = Path(args.settings_file)
    settings = load_settings(settings_path)

    input_path = Path(args.input_file)
    input_cfg = load_input(input_path)

    room_urls: List[str] = input_cfg["roomUrls"]
    max_items: Optional[int] = input_cfg.get("maxItems")

    output_format, output_path = determine_output(
        input_cfg, settings, args.output_format, args.output_path
    )

    if not room_urls:
        logger.warning("No room URLs provided in input. Nothing to do.")
        return

    session = create_session(settings)
    review_parser = ReviewParser()

    all_reviews: List[Dict[str, Any]] = []

    concurrent_requests = max(1, int(settings.get("concurrent_requests", 2)))
    logger.info(
        "Starting scrape for %d room(s) with concurrency=%d",
        len(room_urls),
        concurrent_requests,
    )

    with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
        future_to_room = {
            executor.submit(
                scrape_room,
                url,
                session,
                review_parser,
                settings,
                max_items,
            ): url
            for url in room_urls
        }

        for future in as_completed(future_to_room):
            url = future_to_room[future]
            try:
                reviews = future.result()
                all_reviews.extend(reviews)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Unexpected error while scraping %s: %s", url, exc)

    logger.info(
        "Scraping complete. Collected %d review(s) across %d room(s).",
        len(all_reviews),
        len(room_urls),
    )

    if not all_reviews:
        logger.warning("No reviews were collected; nothing will be exported.")
        return

    export_reviews(
        reviews=all_reviews,
        output_path=output_path,
        output_format=output_format,
    )
    logger.info("Exported reviews to %s (%s format).", output_path, output_format)

if __name__ == "__main__":
    main()