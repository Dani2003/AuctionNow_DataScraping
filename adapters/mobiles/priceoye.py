"""
Adapter for PriceOye.pk mobile listings and spec details.

Extracts candidate mobile models, pricing in PKR, color variants, RAM/storage
options, and technical specifications using clean DOM selection and Schema.org
Product JSON-LD extraction.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from adapters.base import BaseAdapter
from pipeline.schema import Category, RawListing, SourceRef

RAM_RE = re.compile(r"\b(\d+\s*GB)\s*RAM\b", re.IGNORECASE)
STORAGE_RE = re.compile(r"\b(\d+\s*(?:GB|TB))\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(202\d)\b")
SCREEN_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:inches|inch|\"))", re.IGNORECASE)
BATTERY_RE = re.compile(r"(\d+\s*mAh)", re.IGNORECASE)
CAMERA_RE = re.compile(r"(\d+\s*MP\s*(?:[a-zA-Z\s]+)?camera)", re.IGNORECASE)


class PriceOyeAdapter(BaseAdapter):
    source_id = "priceoye"
    category = "mobile"

    def list_candidates(self) -> list[dict]:
        """Fetch /mobiles index page and extract all current product cards."""
        index_url = urljoin(self.base_url, "/mobiles")
        html = self.client.get(index_url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_candidates_from_html(html)

    def parse_candidates_from_html(self, html: str) -> list[dict]:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[dict] = []
        seen_urls: set[str] = set()

        for box in soup.select("div.productBox"):
            a = box.select_one("a[href]")
            title_tag = box.select_one(".p-title") or a
            if not a or not title_tag:
                continue

            href = a["href"]
            full_url = urljoin(self.base_url, href)
            if full_url in seen_urls:
                continue

            title = title_tag.get_text(strip=True)
            if not title:
                continue

            parts = title.split()
            brand = parts[0] if parts else "Unknown"
            model = " ".join(parts[1:]) if len(parts) > 1 else brand

            variant = None
            v_match = STORAGE_RE.search(model)
            if v_match:
                variant = v_match.group(1).upper().replace(" ", "")

            seen_urls.add(full_url)
            candidates.append({
                "brand": brand,
                "model": model,
                "variant": variant,
                "url": full_url,
            })

        return candidates

    def fetch_detail(self, candidate: dict) -> RawListing:
        """Fetch detail page for one model and extract specifications and pricing."""
        url = candidate["url"]
        html = self.client.get(url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_detail_from_html(candidate, html)

    def parse_detail_from_html(self, candidate: dict, html: str) -> RawListing:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # 1. Parse JSON-LD Product schema if present
        product_ld: dict = {}
        for s in soup.find_all("script", type="application/ld+json"):
            if not s.string:
                continue
            try:
                data = json.loads(s.string)
                if isinstance(data, dict) and data.get("@type") == "Product":
                    product_ld = data
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        # 2. Extract Price in PKR
        price_pkr = None
        if "offers" in product_ld and isinstance(product_ld["offers"], dict):
            raw_p = product_ld["offers"].get("price")
            if raw_p:
                try:
                    price_pkr = float(str(raw_p).replace(",", ""))
                except ValueError:
                    pass

        if price_pkr is None:
            price_box = soup.select_one(".price-box, .price")
            if price_box:
                m = re.search(r"Rs\.?\s*([\d,]+)", price_box.get_text())
                if m:
                    price_pkr = float(m.group(1).replace(",", ""))

        # 3. Colors
        color_options: list[str] = []
        for ul in soup.select("ul.colors"):
            for li in ul.find_all("li"):
                c_name = li.get_text(strip=True)
                if c_name and c_name not in color_options and not any(k in c_name.lower() for k in ["gb", "ram"]):
                    color_options.append(c_name)

        # 4. Storage & RAM Options
        storage_options: list[str] = []
        ram_options: list[str] = []
        for ul in soup.select("ul.sizes, ul.colors"):
            for li in ul.find_all("li"):
                text = li.get_text(strip=True)
                for s in STORAGE_RE.findall(text):
                    s_clean = s.upper().replace(" ", "")
                    if s_clean not in storage_options and not s_clean.endswith("RAM"):
                        storage_options.append(s_clean)
                for r in RAM_RE.findall(text):
                    r_clean = r.upper().replace(" ", "")
                    if r_clean not in ram_options:
                        ram_options.append(r_clean)

        # 5. Technical specs from description or metadata
        specs: dict[str, str] = {}
        desc = product_ld.get("description", "")
        if desc:
            specs["summary"] = desc
            m_screen = SCREEN_RE.search(desc)
            if m_screen:
                specs["display_size"] = m_screen.group(1)
            m_bat = BATTERY_RE.search(desc)
            if m_bat:
                specs["battery_capacity"] = m_bat.group(1)
            m_cam = CAMERA_RE.search(desc)
            if m_cam:
                specs["camera"] = m_cam.group(1)

        # 6. Images
        images: list[str] = []
        ld_img = product_ld.get("image")
        if isinstance(ld_img, str) and ld_img:
            images.append(ld_img)
        elif isinstance(ld_img, list):
            images.extend([img for img in ld_img if isinstance(img, str)])

        for img in soup.select("div.slider-item img, div.product-image img"):
            src = img.get("src") or img.get("data-src")
            if src and src.startswith("http") and src not in images:
                images.append(src)

        # 7. Model Year
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
                site="priceoye.pk",
                url=candidate["url"],
                fetched_at=datetime.now(UTC),
            ),
            confidence="medium" if flags else "high",
            flags=flags,
        )
