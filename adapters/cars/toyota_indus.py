"""
Adapter for Indus Motor Company (Toyota Pakistan) official vehicle pages.

Scrapes official manufacturer models and specifications for Toyota vehicles in Pakistan.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from adapters.base import BaseAdapter
from pipeline.schema import Category, RawListing, SourceRef

PKR_RE = re.compile(r"(?:PKR|Rs\.?)\s*([\d,]{6,})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(202\d)\b")

KNOWN_MODELS = {
    "yaris": "Yaris",
    "corolla": "Corolla",
    "corolla-cross": "Corolla Cross",
    "fortuner": "Fortuner",
    "fortuner-grs": "Fortuner GR-S",
    "camry-hybrid": "Camry Hybrid",
    "hilux-e": "Hilux E",
    "revo": "Hilux Revo",
    "revo-grs": "Hilux Revo GR-S",
    "land-cruiser-300": "Land Cruiser 300",
    "prado-250": "Prado 250",
    "prius": "Prius",
}


class ToyotaIndusAdapter(BaseAdapter):
    source_id = "indus_motor_toyota"
    category = "car"

    def list_candidates(self) -> list[dict]:
        """Fetch Toyota Indus homepage/catalog and discover vehicle models."""
        html = self.client.get(self.base_url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_candidates_from_html(html)

    def parse_candidates_from_html(self, html: str) -> list[dict]:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[dict] = []
        seen_urls: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].split("?")[0].rstrip("/") + "/"
            for slug, display_name in KNOWN_MODELS.items():
                if f"/{slug}/" in href:
                    full_url = urljoin(self.base_url, href)
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        candidates.append({
                            "brand": "Toyota",
                            "model": display_name,
                            "variant": None,
                            "url": full_url,
                        })
                    break

        return candidates

    def fetch_detail(self, candidate: dict) -> RawListing:
        """Fetch vehicle detail page and extract official manufacturer specs."""
        url = candidate["url"]
        html = self.client.get(url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_detail_from_html(candidate, html)

    def parse_detail_from_html(self, candidate: dict, html: str) -> RawListing:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # 1. Specs extraction from tables
        specs: dict[str, str] = {}
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
                if len(cells) >= 2:
                    k = cells[0].strip()
                    v = " | ".join(c.strip() for c in cells[1:] if c.strip())
                    if k and v and len(k) < 40 and not any(ign in k.lower() for ign in ["variant", "ex-factory", "*"]):
                        specs[k] = v

        # 2. Price in PKR
        price_pkr = None
        m_price = PKR_RE.search(html)
        if m_price:
            price_pkr = float(m_price.group(1).replace(",", ""))

        # 3. Colors
        color_options: list[str] = []
        for c_el in soup.select("div.color-name, p.color-title, ul.colors-list li"):
            name = c_el.get_text(strip=True)
            if name and name not in color_options:
                color_options.append(name)

        # 4. Images
        images: list[str] = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if "wp-content/uploads" in src and any(m.lower() in src.lower() for m in candidate["model"].split()):
                full_img = urljoin(self.base_url, src)
                if full_img not in images:
                    images.append(full_img)

        # 5. Model Year
        model_year = None
        if soup.title and soup.title.string:
            ym = YEAR_RE.search(soup.title.string)
            if ym:
                model_year = int(ym.group(1))

        flags = []
        if price_pkr is None:
            flags.append("price_not_found")
        if not color_options:
            flags.append("color_not_found")
        if not specs:
            flags.append("specs_empty")

        return RawListing(
            category=Category.car,
            brand=candidate["brand"],
            model=candidate["model"],
            variant=candidate.get("variant"),
            model_year=model_year,
            price_pkr=price_pkr,
            price_as_of=date.today() if price_pkr is not None else None,
            specs=specs,
            ram_options=[],
            storage_options=[],
            color_options=color_options,
            images=images,
            source=SourceRef(
                site="toyota-indus.com",
                url=candidate["url"],
                fetched_at=datetime.now(UTC),
            ),
            confidence="medium" if flags else "high",
            flags=flags,
        )
