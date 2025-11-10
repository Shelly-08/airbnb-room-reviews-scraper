import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from xml.etree.ElementTree import Element, SubElement, ElementTree

logger = logging.getLogger(__name__)

def export_reviews(
    reviews: List[Dict[str, Any]],
    output_path: Path,
    output_format: str,
) -> None:
    """
    Export the collected reviews into one of the supported formats:
    json, jsonl, csv, excel, xml, html.
    """
    output_format = output_format.lower()
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "json":
        _export_json(reviews, output_path)
    elif output_format == "jsonl":
        _export_jsonl(reviews, output_path)
    elif output_format == "csv":
        _export_tabular(reviews, output_path, kind="csv")
    elif output_format == "excel":
        _export_tabular(reviews, output_path, kind="excel")
    elif output_format == "html":
        _export_tabular(reviews, output_path, kind="html")
    elif output_format == "xml":
        _export_xml(reviews, output_path)
    else:
        raise ValueError(f"Unsupported output format: {output_format}")

def _export_json(reviews: List[Dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %d review(s) to JSON: %s", len(reviews), output_path)

def _export_jsonl(reviews: List[Dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        for row in reviews:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info("Wrote %d review(s) to JSONL: %s", len(reviews), output_path)

def _export_tabular(
    reviews: List[Dict[str, Any]],
    output_path: Path,
    kind: str,
) -> None:
    # Flatten nested dictionaries using pandas.json_normalize
    df = pd.json_normalize(reviews)

    if kind == "csv":
        df.to_csv(output_path, index=False)
        logger.info("Wrote %d review(s) to CSV: %s", len(df), output_path)
    elif kind == "excel":
        df.to_excel(output_path, index=False)
        logger.info("Wrote %d review(s) to Excel: %s", len(df), output_path)
    elif kind == "html":
        html = df.to_html(index=False, border=0)
        with output_path.open("w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Wrote %d review(s) to HTML: %s", len(df), output_path)
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported tabular kind: {kind}")

def _export_xml(reviews: List[Dict[str, Any]], output_path: Path) -> None:
    root = Element("reviews")

    for review in reviews:
        review_elem = SubElement(root, "review")
        _populate_xml(review_elem, review)

    tree = ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    logger.info("Wrote %d review(s) to XML: %s", len(reviews), output_path)

def _populate_xml(parent: Element, data: Any, prefix: str = "") -> None:
    """
    Recursively populate XML elements from nested dict/list structures.
    Keys with dots are converted to underscores for valid tag names.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            tag = (prefix + key).replace(".", "_")
            child = SubElement(parent, tag)
            _populate_xml(child, value)
    elif isinstance(data, list):
        for item in data:
            child = SubElement(parent, "item")
            _populate_xml(child, item)
    else:
        parent.text = "" if data is None else str(data)