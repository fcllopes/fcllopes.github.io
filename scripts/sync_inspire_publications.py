#!/usr/bin/env python3
"""Sync Academic Pages publications from an INSPIRE-HEP author profile."""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

INSPIRE_AUTHOR_ID = "2939430"
INSPIRE_QUERY = f"authors.record.$ref:{INSPIRE_AUTHOR_ID}"
API_BASE = "https://inspirehep.net/api/literature"
ROOT = Path(__file__).resolve().parent.parent
PUBLICATIONS_DIR = ROOT / "_publications"
BIBTEX_DIR = ROOT / "files" / "bibtex"
GENERATED_MARKER = "inspire-sync"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_bibtex(control_number: str) -> str:
    url = f"https://inspirehep.net/api/literature/{control_number}?format=bibtex"
    request = urllib.request.Request(url, headers={"Accept": "application/x-bibtex"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8").strip()


def escape_yaml_single(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def strip_latex(title: str) -> str:
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r"\$([^$]+)\$", r"\1", title)
    title = re.sub(r"\\[a-zA-Z]+(\{([^}]*)\})?", r"\2", title)
    title = re.sub(r"[{}]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def clean_html_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title).strip()


def get_publication_date(metadata: dict) -> str:
    if metadata.get("preprint_date"):
        return metadata["preprint_date"][:10]

    publication_info = metadata.get("publication_info") or []
    dated = [info for info in publication_info if info.get("year")]
    if dated:
        year = str(dated[0]["year"])
        month = str(dated[0].get("month", "01")).zfill(2)
        day = str(dated[0].get("day", "01")).zfill(2)
        return f"{year}-{month}-{day}"

    if metadata.get("imprint", {}).get("date"):
        return metadata["imprint"]["date"][:10]

    return "1900-01-01"


def get_venue(metadata: dict) -> str:
    publication_info = metadata.get("publication_info") or []
    for info in publication_info:
        if info.get("journal_title"):
            volume = info.get("journal_volume")
            artid = info.get("artid") or info.get("page_start")
            year = info.get("year")
            parts = [info["journal_title"]]
            if volume:
                parts.append(str(volume))
            if artid:
                parts.append(str(artid))
            if year:
                parts.append(f"({year})")
            return " ".join(parts)
        if info.get("cnum"):
            return info["cnum"]
        if info.get("pubinfo_freetext"):
            return info["pubinfo_freetext"]

    arxiv = (metadata.get("arxiv_eprints") or [{}])[0].get("value")
    if arxiv:
        return f"arXiv:{arxiv}"

    return "Preprint"


def get_category(metadata: dict) -> str:
    publication_info = metadata.get("publication_info") or []
    for info in publication_info:
        if info.get("cnum"):
            return "conferences"

    authors = metadata.get("authors") or []
    if len(authors) > 5:
        return "lhcb"

    return "independent"


def get_paper_url(metadata: dict, control_number: str) -> str:
    for doi in metadata.get("dois") or []:
        value = doi.get("value")
        if value:
            return f"https://doi.org/{value}"

    for arxiv in metadata.get("arxiv_eprints") or []:
        value = arxiv.get("value")
        if value:
            return f"https://arxiv.org/abs/{value}"

    for document in metadata.get("documents") or []:
        url = document.get("url")
        if url:
            return url

    return f"https://inspirehep.net/literature/{control_number}"


def get_title(metadata: dict) -> str:
    titles = metadata.get("titles") or []
    if not titles:
        return "Untitled"

    for source in ("arXiv", "Springer", "INSPIRE"):
        match = next((item["title"] for item in titles if item.get("source") == source), None)
        if match:
            return clean_html_title(match)

    for item in titles:
        cleaned = clean_html_title(item["title"])
        if cleaned:
            return cleaned

    return strip_latex(titles[0]["title"])


def format_authors(metadata: dict) -> str:
    authors = metadata.get("authors") or []
    if not authors:
        return "Unknown authors"

    if len(authors) > 5:
        collaboration = metadata.get("collaborations") or []
        if collaboration:
            name = collaboration[0].get("value", "LHCb")
            if name == "LHCb":
                return "LHCb collaboration"
            return name
        return "LHCb collaboration"

    names = []
    for author in authors:
        name = author.get("full_name") or author.get("name", {}).get("value", "")
        if name:
            parts = [part.strip() for part in name.split(",")]
            if len(parts) == 2:
                names.append(f"{parts[1]} {parts[0]}")
            else:
                names.append(name)
    return " and ".join(names) if names else "Unknown authors"


def save_bibtex(control_number: str) -> str:
    BIBTEX_DIR.mkdir(parents=True, exist_ok=True)
    bibtex = fetch_bibtex(control_number)
    bib_path = BIBTEX_DIR / f"{control_number}.bib"
    bib_path.write_text(bibtex + "\n", encoding="utf-8")
    return f"/files/bibtex/{control_number}.bib"


def make_slug(control_number: str) -> str:
    return f"inspire-{control_number}"


def render_markdown(metadata: dict) -> tuple[str, str]:
    control_number = str(metadata["control_number"])
    title = get_title(metadata)
    pub_date = get_publication_date(metadata)
    venue = get_venue(metadata)
    category = get_category(metadata)
    paperurl = get_paper_url(metadata, control_number)
    authors = format_authors(metadata)
    bibtexurl = save_bibtex(control_number)
    slug = make_slug(control_number)
    filename = f"{pub_date}-{slug}.md"
    permalink = f"/publication/{pub_date}-{slug}"

    content = f"""---
title: {escape_yaml_single(title)}
collection: publications
category: {category}
permalink: {permalink}
date: {pub_date}
venue: {escape_yaml_single(venue)}
authors: {escape_yaml_single(authors)}
paperurl: {escape_yaml_single(paperurl)}
bibtexurl: {escape_yaml_single(bibtexurl)}
inspire_id: {control_number}
{GENERATED_MARKER}: true
---
"""
    return filename, content


def remove_generated_publications() -> None:
    if not PUBLICATIONS_DIR.exists():
        PUBLICATIONS_DIR.mkdir(parents=True)
        return

    for path in PUBLICATIONS_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if f"{GENERATED_MARKER}: true" in text:
            path.unlink()


def fetch_all_records() -> list[dict]:
    records: list[dict] = []
    page = 1
    size = 100

    while True:
        params = urllib.parse.urlencode(
            {
                "q": INSPIRE_QUERY,
                "size": size,
                "page": page,
                "sort": "mostrecent",
            }
        )
        payload = fetch_json(f"{API_BASE}?{params}")
        hits = payload["hits"]["hits"]
        records.extend(hit["metadata"] for hit in hits)

        total = payload["hits"]["total"]
        if page * size >= total:
            break
        page += 1

    return records


def main() -> int:
    print(f"Fetching publications for INSPIRE author {INSPIRE_AUTHOR_ID}...")
    records = fetch_all_records()
    print(f"Found {len(records)} records.")

    remove_generated_publications()

    written = 0
    for metadata in records:
        filename, content = render_markdown(metadata)
        output_path = PUBLICATIONS_DIR / filename
        output_path.write_text(content, encoding="utf-8")
        written += 1
        print(f"Wrote {filename}")

    print(f"Synced {written} publications to {PUBLICATIONS_DIR}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
