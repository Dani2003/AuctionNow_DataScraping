"""
Adapter for PakWheels' NEW CAR catalog pages (not used car classifieds).

Scrapes newly launched and featured new cars, extracting structured automotive
specifications, pricing in PKR, color options, high-resolution pictures, and
model year metadata.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from adapters.base import BaseAdapter
from pipeline.schema import Category, RawListing, SourceRef

PKR_EXACT_RE = re.compile(r"PKR\s*([\d,]{6,})", re.IGNORECASE)
PKR_LACS_RE = re.compile(r"PKR\s*([\d.]+)\s*(?:-\s*[\d.]+\s*)?lacs?", re.IGNORECASE)
PKR_CRORE_RE = re.compile(r"PKR\s*([\d.]+)\s*(?:-\s*[\d.]+\s*)?crore", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(202\d)\b")


def parse_car_price(text: str) -> float | None:
    """Parse PKR prices across exact, lacs, and crore representations."""
    # 1. Exact numeric PKR, e.g. "PKR 5,499,000"
    m_exact = PKR_EXACT_RE.search(text)
    if m_exact:
        return float(m_exact.group(1).replace(",", ""))

    # 2. Lacs representation, e.g. "PKR 54.99 lacs" or "PKR 54.99 - 58.99 lacs"
    m_lacs = PKR_LACS_RE.search(text)
    if m_lacs:
        return round(float(m_lacs.group(1)) * 100_000, 2)

    # 3. Crore representation, e.g. "PKR 1.22 crore"
    m_crore = PKR_CRORE_RE.search(text)
    if m_crore:
        return round(float(m_crore.group(1)) * 10_000_000, 2)

    return None


class PakWheelsNewCarsAdapter(BaseAdapter):
    source_id = "pakwheels_new_cars"
    category = "car"

    def list_candidates(self) -> list[dict]:
        """
        Fetch /new-cars/ index page and discover newly launched and featured cars.
        """
        index_url = urljoin(self.base_url, "/new-cars/")
        html = self.client.get(index_url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_candidates_from_html(html)

    def parse_candidates_from_html(self, html: str) -> list[dict]:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[dict] = []
        seen_urls: set[str] = set()

        def add_candidate(href: str, display_name: str | None = None):
            if not href.startswith("/new-cars/"):
                return
            clean_href = href.split("?")[0].rstrip("/") + "/"
            parts = [p for p in clean_href.strip("/").split("/") if p]
            # Must match pattern: new-cars/<brand>/<model>/
            if len(parts) != 3 or parts[0] != "new-cars":
                return
            if any(k in clean_href for k in ["newly-launched", "upcoming", "popular", "on-road-price"]):
                return

            full_url = urljoin(self.base_url, clean_href)
            if full_url in seen_urls:
                return

            brand_slug = parts[1]
            model_slug = parts[2]
            brand = brand_slug.replace("-", " ").title()
            model = model_slug.replace("-", " ").title()

            if display_name:
                cleaned_name = display_name.strip()
                # If display name contains brand, extract the clean model name
                if cleaned_name.lower().startswith(brand.lower()):
                    extracted_model = cleaned_name[len(brand):].strip()
                    if extracted_model:
                        model = extracted_model

            seen_urls.add(full_url)
            candidates.append({
                "brand": brand,
                "model": model,
                "variant": None,
                "url": full_url,
            })

        # 1. Newly launched cars section
        h_new = soup.find(lambda e: e.name in ["h2", "h3"] and "Newly Launched Cars" in e.get_text())
        if h_new:
            section = h_new.find_parent("section") or h_new.find_parent("div")
            if section:
                for a in section.find_all("a", href=True):
                    add_candidate(a["href"], a.get_text(strip=True))

        # 2. Browse cards on new cars landing: div.cards a
        for a in soup.select("div.cards a[href]"):
            title_tag = a.select_one("h3") or a
            add_candidate(a["href"], title_tag.get_text(strip=True))

        return candidates

    def fetch_detail(self, candidate: dict) -> RawListing:
        """
        Fetch full car details and specs from the model page.
        """
        url = candidate["url"]
        html = self.client.get(url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_detail_from_html(candidate, html)

    def parse_detail_from_html(self, candidate: dict, html: str) -> RawListing:
        """Pure parsing helper for testability against fixture HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # 1. Specifications extraction from table rows
        specs: dict[str, str] = {}
        detected_variant = candidate.get("variant")

        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                tds = tr.find_all(["td", "th"])
                if len(tds) == 2:
                    k = tds[0].get_text(strip=True)
                    v = tds[1].get_text(" ", strip=True)
                    # Filter out non-spec UI rows
                    if k and v and len(k) < 45 and not any(ign in k.lower() for ign in ["compare", "ex-factory", "pros", "cons"]):
                        specs[k] = v
                elif len(tds) >= 3 and not detected_variant:
                    # Table 0 variants list: capture primary variant name if available
                    v_name = tds[0].get_text(strip=True)
                    if v_name and v_name != "Variants" and candidate["model"].lower() in v_name.lower():
                        # Extract variant after model name
                        idx = v_name.lower().find(candidate["model"].lower())
                        after_model = v_name[idx + len(candidate["model"]):].strip()
                        # Clean out trailing spec notes like '998 cc...'
                        var_clean = re.split(r"\d+\s*cc|\bAutomatic\b|\bManual\b", after_model)[0].strip()
                        if var_clean:
                            detected_variant = var_clean

        # 2. Price in PKR
        price_pkr = None
        # Check variant tables first for exact PKR
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                txt = tr.get_text(" ", strip=True)
                p = parse_car_price(txt)
                if p:
                    price_pkr = p
                    break
            if price_pkr:
                break

        # Fallback to general price text on page
        if price_pkr is None:
            price_pkr = parse_car_price(html)

        # 3. Color options
        color_options = [
            p.get_text(strip=True)
            for p in soup.select("ul.color-list li p")
            if p.get_text(strip=True)
        ]
        if not color_options:
            color_p = soup.find(lambda t: t.name == "p" and "is available in" in t.get_text() and "colour" in t.get_text().lower())
            if color_p:
                m_colors = re.search(r"colours?\s*-\s*(.+)$", color_p.get_text(strip=True), re.IGNORECASE)
                if m_colors:
                    color_options = [
                        c.strip().replace("and ", "")
                        for c in re.split(r"[,;]", m_colors.group(1))
                        if c.strip()
                    ]

        # 4. Images
        images: list[str] = []
        for img in soup.find_all("img"):
            src = img.get("data-original") or img.get("src") or ""
            if "car_generation_pictures" in src:
                full_img_url = urljoin(self.base_url, src)
                if full_img_url not in images:
                    images.append(full_img_url)

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
            variant=detected_variant,
            model_year=model_year,
            price_pkr=price_pkr,
            price_as_of=date.today() if price_pkr is not None else None,
            specs=specs,
            ram_options=[],
            storage_options=[],
            color_options=color_options,
            images=images,
            source=SourceRef(
                site="pakwheels.com",
                url=candidate["url"],
                fetched_at=datetime.now(UTC),
            ),
            confidence="medium" if flags else "high",
            flags=flags,
        )
