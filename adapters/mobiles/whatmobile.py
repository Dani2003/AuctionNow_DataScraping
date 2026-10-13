"""
Adapter for whatmobile.com.pk.

Scrapes new/latest mobile phone models and extracts structured specifications,
pricing in PKR, color options, memory options, and images from whatmobile's
spec tables.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from adapters.base import BaseAdapter
from pipeline.schema import Category, RawListing, SourceRef

LABEL_MAP = {
    "os": "os",
    "ui": "ui",
    "dimensions": "dimensions",
    "weight": "weight",
    "sim": "sim",
    "colors": "color_options",
    "cpu": "cpu",
    "chipset": "chipset",
    "gpu": "gpu",
    "size": "display_size",
    "technology": "display_tech",
    "resolution": "resolution",
    "built-in": "memory_builtin",
    "main": "camera_main",
    "front": "camera_front",
    "capacity": "battery_capacity",
    "battery capacity": "battery_capacity",
}

PRICE_RE = re.compile(r"(?:Price\s*in\s*Rs:?|Rs\.?)\s*([\d,]+)", re.IGNORECASE)
STORAGE_RE = re.compile(r"\b(\d+\s*(?:GB|TB))\s*Built-in\b", re.IGNORECASE)
RAM_RE = re.compile(r"\b(\d+\s*GB)\s*RAM\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(202\d)\b")


class WhatMobileAdapter(BaseAdapter):
    source_id = "whatmobile"
    category = "mobile"

    def list_candidates(self) -> list[dict]:
        """
        Fetch the main catalog page and extract candidate models from the
        'Latest Mobile Phones & Prices in Pakistan' section and product listings.
        """
        html = self.client.get(self.base_url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_candidates_from_html(html)

    def parse_candidates_from_html(self, html: str) -> list[dict]:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[dict] = []
        seen_urls: set[str] = set()

        # 1. Product cards on home / latest section: <li class="product">
        for li in soup.select("li.product"):
            a = li.select_one("h4.p4 a") or li.select_one("a[href]")
            if not a or not a.get("href"):
                continue

            href = a["href"]
            full_url = urljoin(self.base_url, href)
            if full_url in seen_urls or not href.startswith("/") or href.startswith("/m/"):
                continue

            lines = [s.strip() for s in a.stripped_strings if s.strip()]
            if len(lines) >= 2:
                brand = lines[0]
                model = " ".join(lines[1:])
            elif lines:
                parts = lines[0].split(maxsplit=1)
                brand = parts[0]
                model = parts[1] if len(parts) > 1 else lines[0]
            else:
                continue

            variant = None
            variant_match = re.search(r"\b(\d+\s*(?:GB|TB))\b", model, re.IGNORECASE)
            if variant_match:
                variant = variant_match.group(1).upper().replace(" ", "")

            seen_urls.add(full_url)
            candidates.append({
                "brand": brand,
                "model": model,
                "variant": variant,
                "url": full_url,
            })

        # 2. Schema item listing: <div class="item" itemprop="itemListElement">
        for item in soup.select("div.item[itemprop='itemListElement']"):
            a = item.select_one("a[href]")
            if not a or not a.get("href"):
                continue

            href = a["href"]
            full_url = urljoin(self.base_url, href)
            if full_url in seen_urls:
                continue

            title = a.get("title") or a.get_text(strip=True)
            if not title:
                continue

            parts = title.split()
            brand = parts[0] if parts else "Unknown"
            model = " ".join(parts[1:]) if len(parts) > 1 else brand

            variant = None
            variant_match = re.search(r"\b(\d+\s*(?:GB|TB))\b", model, re.IGNORECASE)
            if variant_match:
                variant = variant_match.group(1).upper().replace(" ", "")

            seen_urls.add(full_url)
            candidates.append({
                "brand": brand,
                "model": model,
                "variant": variant,
                "url": full_url,
            })

        return candidates

    def fetch_detail(self, candidate: dict) -> RawListing:
        """
        Fetch the detail page for one confirmed candidate and extract full specs.
        """
        url = candidate["url"]
        html = self.client.get(url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_detail_from_html(candidate, html)

    def parse_detail_from_html(self, candidate: dict, html: str) -> RawListing:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")

        row_values: dict[str, str] = {}
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) == 3:
                label = cells[1].get_text(strip=True).lower()
                val = cells[2].get_text(" ", strip=True)
                if label and val:
                    row_values[label] = val
            elif len(cells) == 2:
                label = cells[0].get_text(strip=True).lower()
                val = cells[1].get_text(" ", strip=True)
                if label and val:
                    row_values[label] = val

        # Colors
        color_options = []
        if "colors" in row_values:
            color_options = [c.strip() for c in row_values["colors"].split(",") if c.strip()]

        # Price in PKR
        price_pkr = None
        # Check explicit price row or fallback to regex across HTML
        price_cell = row_values.get("price in rs") or row_values.get("price in rupees")
        if price_cell:
            m = PRICE_RE.search(price_cell)
            if m:
                price_pkr = float(m.group(1).replace(",", ""))
        if price_pkr is None:
            m = PRICE_RE.search(html)
            if m:
                price_pkr = float(m.group(1).replace(",", ""))

        # RAM and Storage options
        memory_str = row_values.get("built-in") or row_values.get("memory") or ""
        ram_options = [r.strip().replace(" ", "") for r in RAM_RE.findall(memory_str)]
        storage_options = [s.strip().replace(" ", "") for s in STORAGE_RE.findall(memory_str)]

        # Model year
        model_year = None
        if soup.title and soup.title.string:
            ym = YEAR_RE.search(soup.title.string)
            if ym:
                model_year = int(ym.group(1))

        # Images
        images: list[str] = []
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "admin/images/" in src:
                full_img_url = urljoin(self.base_url, src)
                if full_img_url not in images:
                    images.append(full_img_url)

        specs = {
            schema_key: row_values[label]
            for label, schema_key in LABEL_MAP.items()
            if label in row_values and schema_key != "color_options"
        }

        flags = []
        if price_pkr is None:
            flags.append("price_not_found")
        if not color_options:
            flags.append("color_not_found")
        if not specs:
            flags.append("specs_empty")

        return RawListing(
            category=Category.mobile,
            brand=candidate["brand"],
            model=candidate["model"],
            variant=candidate.get("variant"),
            model_year=model_year,
            price_pkr=price_pkr,
            price_as_of=date.today() if price_pkr is not None else None,
            specs=specs,
            ram_options=ram_options,
            storage_options=storage_options,
            color_options=color_options,
            images=images,
            source=SourceRef(
                site="whatmobile.com.pk",
                url=candidate["url"],
                fetched_at=datetime.now(UTC),
            ),
            confidence="medium" if flags else "high",
            flags=flags,
        )
