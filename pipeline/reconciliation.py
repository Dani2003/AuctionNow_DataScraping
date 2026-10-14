"""
AuctionNow Backend Catalog Reconciliation Engine.

Loads existing product catalog exports from AuctionNow's reverse marketplace backend
(auctionnow_backend_json/) and diffs them against newly scraped models and active listings.

Identifies:
1. Missing models not currently available to buyers on the AuctionNow app.
2. Missing variants, colors, RAM, and storage options for existing models.
3. Formats an ingestion-ready JSON artifact (`models_to_add_to_auctionnow.json`)
   suitable for review and direct onboarding into the AuctionNow catalog.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from pipeline.logger import get_logger
from pipeline.schema import Category, NewModelEntry, RawListing

logger = get_logger("pipeline.reconciliation")

# Brand alias map for standardizing scraped brand names to AuctionNow backend slugs
BRAND_ALIASES: dict[str, str] = {
    "apple": "apple",
    "iphone": "apple",
    "samsung": "samsung",
    "galaxy": "samsung",
    "xiaomi": "xiaomi",
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "infinix": "infinix",
    "techno": "tecno",
    "tecno": "tecno",
    "vivo": "vivo",
    "oppo": "oppo",
    "realme": "realme",
    "google": "google",
    "pixel": "google",
    "oneplus": "oneplus",
    "honor": "honor",
    "motorola": "motorola",
    "huawei": "huawei",
    "hp": "hp",
    "hewlett-packard": "hp",
    "dell": "dell",
    "lenovo": "lenovo",
    "asus": "asus",
    "acer": "acer",
    "msi": "msi",
    "microsoft": "microsoft",
    "razer": "razer",
    "benelli": "benelli",
    "yamaha": "yamaha",
    "honda": "honda",
    "suzuki": "suzuki",
    "kawasaki": "kawasaki",
    "toyota": "toyota",
    "kia": "kia",
    "hyundai": "hyundai",
    "changan": "changan",
    "mg": "mg",
    "haval": "haval",
}

KEY_DISCRIMINATOR_TOKENS = {
    "pro", "max", "ultra", "plus", "mini", "lite", "fe", "se",
    "ags", "vxl", "vxr", "glx", "gli", "altis",
    "m1", "m2", "m3", "m4", "m5",
    "i3", "i5", "i7", "i9",
}


def slugify(text: str) -> str:
    """Generate a clean, lowercase hyphenated slug from string."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return cleaned.strip("-")


def normalize_brand(brand: str) -> str:
    """Map brand string to standardized AuctionNow brand slug."""
    clean = slugify(brand)
    return BRAND_ALIASES.get(clean, clean)


class BackendCatalog:
    """In-memory index of AuctionNow's active backend catalog."""

    def __init__(self, backend_dir: str | Path):
        self.backend_dir = Path(backend_dir)
        # category -> brand_slug -> { model_slug: model_info }
        self.catalog: dict[str, dict[str, dict[str, Any]]] = {
            "mobile": {},
            "laptop": {},
            "bike": {},
            "car": {},
        }
        self.missing_flags: list[dict] = []
        self._loaded = False

    def load(self) -> None:
        """Load all available backend audit files from backend_dir."""
        if not self.backend_dir.exists():
            logger.warning("Backend catalog directory %s does not exist; proceeding with empty catalog.", self.backend_dir)
            return

        self._load_mobiles()
        self._load_laptops()
        self._load_bikes()
        self._load_cars()
        self._load_missing_flags()
        self._loaded = True
        logger.info(
            "Loaded backend catalog: %d mobile brands, %d laptop brands, %d bike brands, %d car brands.",
            len(self.catalog["mobile"]),
            len(self.catalog["laptop"]),
            len(self.catalog["bike"]),
            len(self.catalog["car"]),
        )

    def _load_mobiles(self) -> None:
        path = self.backend_dir / "mobile_models_audit.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for brand, models in data.items():
                    b_slug = normalize_brand(brand)
                    if b_slug not in self.catalog["mobile"]:
                        self.catalog["mobile"][b_slug] = {}
                    if isinstance(models, list):
                        for m in models:
                            m_slug = slugify(m.get("slug", ""))
                            self.catalog["mobile"][b_slug][m_slug] = {
                                "id": m.get("id"),
                                "slug": m.get("slug"),
                                "value": m.get("value"),
                                "metadata": m.get("metadata", {}),
                                "raw": m,
                            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load mobile backend audit JSON: %s", e)

    def _load_laptops(self) -> None:
        path = self.backend_dir / "laptop_full_specs_audit.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for brand, models in data.items():
                    b_slug = normalize_brand(brand)
                    if b_slug not in self.catalog["laptop"]:
                        self.catalog["laptop"][b_slug] = {}
                    if isinstance(models, dict):
                        for m_slug, specs in models.items():
                            clean_slug = slugify(m_slug)
                            # Create a display value from slug if value is not explicit
                            val = m_slug.replace("-", " ").title()
                            self.catalog["laptop"][b_slug][clean_slug] = {
                                "slug": m_slug,
                                "value": val,
                                "specs": specs if isinstance(specs, dict) else {},
                                "raw": specs,
                            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load laptop backend audit JSON: %s", e)

    def _load_bikes(self) -> None:
        path = self.backend_dir / "bike_models_audit.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Structure: { subcategory: { brands: { brand_slug: [ {id, slug, value} ] } } }
                for subcat_data in data.values():
                    if isinstance(subcat_data, dict) and "brands" in subcat_data:
                        brands_dict = subcat_data["brands"]
                        if isinstance(brands_dict, dict):
                            for brand, models in brands_dict.items():
                                b_slug = normalize_brand(brand)
                                if b_slug not in self.catalog["bike"]:
                                    self.catalog["bike"][b_slug] = {}
                                if isinstance(models, list):
                                    for m in models:
                                        m_slug = slugify(m.get("slug", ""))
                                        self.catalog["bike"][b_slug][m_slug] = {
                                            "id": m.get("id"),
                                            "slug": m.get("slug"),
                                            "value": m.get("value"),
                                            "metadata": m.get("metadata", {}),
                                            "raw": m,
                                        }
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load bike backend audit JSON: %s", e)

    def _load_cars(self) -> None:
        path = self.backend_dir / "car_models_audit.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for brand, models in data.items():
                    b_slug = normalize_brand(brand)
                    if b_slug not in self.catalog["car"]:
                        self.catalog["car"][b_slug] = {}
                    if isinstance(models, list):
                        for m in models:
                            m_slug = slugify(m.get("slug", ""))
                            self.catalog["car"][b_slug][m_slug] = {
                                "id": m.get("id"),
                                "slug": m.get("slug"),
                                "value": m.get("value"),
                                "metadata": m.get("metadata", {}),
                                "raw": m,
                            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load car backend audit JSON: %s", e)

    def _load_missing_flags(self) -> None:
        path = self.backend_dir / "laptop_specs_missing_flags.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.missing_flags = data
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load laptop missing flags JSON: %s", e)

    def find_match(self, category: str | Category, brand: str, model_name: str, variant: str | None = None) -> tuple[bool, str | None, dict | None]:
        """
        Check if a model exists in the backend catalog.
        Returns: (is_match, matched_slug, backend_model_entry)
        """
        cat_key = category.value if isinstance(category, Category) else str(category).lower()
        if cat_key not in self.catalog:
            return False, None, None

        b_slug = normalize_brand(brand)
        brand_models = self.catalog[cat_key].get(b_slug)
        if not brand_models:
            # Entire brand missing from this category in AuctionNow
            return False, None, None

        target_slug = slugify(model_name)
        target_slug_with_var = slugify(f"{model_name} {variant or ''}")

        # 1. Exact slug match
        if target_slug in brand_models:
            return True, target_slug, brand_models[target_slug]
        if target_slug_with_var in brand_models:
            return True, target_slug_with_var, brand_models[target_slug_with_var]

        # 2. Check value matches
        clean_name = model_name.strip().lower()
        for b_mslug, entry in brand_models.items():
            b_val = str(entry.get("value", "")).strip().lower()
            if b_val and b_val == clean_name:
                return True, b_mslug, entry

        # 3. Fuzzy match across brand models
        target_tokens = set(re.findall(r"\b[a-zA-Z0-9]+\b", model_name.lower()))
        best_score = 0
        best_match: tuple[str, dict] | None = None

        for b_mslug, entry in brand_models.items():
            candidate_str = entry.get("value") or b_mslug.replace("-", " ")
            score = fuzz.token_sort_ratio(model_name, candidate_str)

            if score > best_score:
                best_score = score
                best_match = (b_mslug, entry)

        if best_score >= 88 and best_match:
            # Check discriminator tokens to prevent false positives (e.g., M2 vs M3, Pro vs non-Pro)
            matched_slug, matched_entry = best_match
            matched_tokens = set(re.findall(r"\b[a-zA-Z0-9]+\b", (matched_entry.get("value") or matched_slug).lower()))
            target_diff = (target_tokens ^ matched_tokens) & KEY_DISCRIMINATOR_TOKENS
            if not target_diff:
                return True, matched_slug, matched_entry

        return False, None, None


def reconcile_with_backend(
    models: list[NewModelEntry | RawListing],
    backend_dir: str | Path,
    run_date: date | None = None,
) -> dict[str, Any]:
    """
    Compare scraped models against AuctionNow backend catalog exports.
    Generates a reconciliation report detailing missing models to add and missing options to enrich.
    """
    run_dt = run_date or date.today()
    catalog = BackendCatalog(backend_dir)
    catalog.load()

    missing_models: list[dict[str, Any]] = []
    attribute_updates: list[dict[str, Any]] = []

    seen_missing_keys: set[str] = set()

    for item in models:
        cat = item.category
        brand = item.brand
        model = item.model
        variant = item.variant
        price_pkr = item.price_pkr
        color_opts = getattr(item, "color_options", [])
        ram_opts = getattr(item, "ram_options", [])
        storage_opts = getattr(item, "storage_options", [])
        specs = getattr(item, "specs", {})
        images = getattr(item, "images", [])

        # Extract source url
        source_url = None
        if hasattr(item, "sources") and item.sources:
            source_url = item.sources[0].url
        elif hasattr(item, "source") and item.source:
            source_url = item.source.url

        is_found, matched_slug, backend_entry = catalog.find_match(cat, brand, model, variant)

        if not is_found:
            dedup_key = f"{cat.value if isinstance(cat, Category) else cat}:{normalize_brand(brand)}:{slugify(model)}"
            if dedup_key in seen_missing_keys:
                continue
            seen_missing_keys.add(dedup_key)

            suggested_slug = slugify(f"{brand}-{model}")
            suggested_value = f"{brand.title()} {model}".strip()

            missing_models.append({
                "category": cat.value if isinstance(cat, Category) else str(cat),
                "brand": brand,
                "model": model,
                "variant": variant,
                "suggested_slug": suggested_slug,
                "suggested_value": suggested_value,
                "price_pkr": price_pkr,
                "price_as_of": run_dt.isoformat(),
                "color_options": color_opts,
                "ram_options": ram_opts,
                "storage_options": storage_opts,
                "specs": specs,
                "images": images,
                "source_url": source_url,
                "auctionnow_catalog_payload": {
                    "slug": suggested_slug,
                    "value": suggested_value,
                    "display_order": 9999,
                    "picker_priority": 4,
                    "is_popular": False,
                    "metadata": {
                        "title": suggested_value,
                        "category": cat.value if isinstance(cat, Category) else str(cat),
                        "brand": normalize_brand(brand),
                        "initial_price_pkr": price_pkr,
                        "color_options": color_opts,
                        "ram_options": ram_opts,
                        "storage_options": storage_opts,
                        "specs": specs,
                        "source_url": source_url,
                    },
                },
            })
        else:
            # Model exists in backend — check for newly discovered options or empty backend specs
            missing_colors: list[str] = []
            missing_ram: list[str] = []
            missing_storage: list[str] = []

            backend_specs = backend_entry.get("specs", {}) if backend_entry else {}
            if isinstance(backend_specs, dict):
                backend_rams = [
                    opt.get("value") or opt.get("slug")
                    for opt in backend_specs.get("ram", [])
                    if isinstance(opt, dict)
                ]
                backend_storages = [
                    opt.get("value") or opt.get("slug")
                    for opt in backend_specs.get("storage", [])
                    if isinstance(opt, dict)
                ]

                # Find any RAM/Storage options not currently in backend
                for r in ram_opts:
                    if not any(r.lower() in str(br).lower() for br in backend_rams):
                        missing_ram.append(r)
                for s in storage_opts:
                    if not any(s.lower() in str(bs).lower() for bs in backend_storages):
                        missing_storage.append(s)

            if color_opts:
                missing_colors = color_opts

            if missing_colors or missing_ram or missing_storage:
                attribute_updates.append({
                    "category": cat.value if isinstance(cat, Category) else str(cat),
                    "brand": brand,
                    "model": model,
                    "backend_slug": matched_slug,
                    "missing_colors_to_add": missing_colors,
                    "missing_ram_to_add": missing_ram,
                    "missing_storage_to_add": missing_storage,
                    "scraped_specs": specs,
                })

    # Tally category counts for missing models
    missing_by_cat: dict[str, int] = {}
    for mm in missing_models:
        c = mm["category"]
        missing_by_cat[c] = missing_by_cat.get(c, 0) + 1

    report = {
        "run_date": run_dt.isoformat(),
        "catalog_sources_reconciled": [
            str(p.name) for p in Path(backend_dir).glob("*.json")
        ],
        "summary": {
            "total_models_evaluated": len(models),
            "total_missing_models": len(missing_models),
            "missing_by_category": missing_by_cat,
            "total_models_with_attribute_updates": len(attribute_updates),
        },
        "missing_models": missing_models,
        "attribute_updates": attribute_updates,
    }
    return report


def save_reconciliation_report(report_data: dict[str, Any], runs_dir: str | Path, run_date: date) -> Path:
    """Save reconciliation output to runs/<date>/models_to_add_to_auctionnow.json."""
    out_dir = Path(runs_dir) / run_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "models_to_add_to_auctionnow.json"
    out_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved AuctionNow catalog reconciliation report to %s", out_path)
    return out_path
