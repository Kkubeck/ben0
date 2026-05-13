"""
Synthetic dataset generator for Cascadia Demonstration Botanical Garden (CDBG).

Usage:
    python -m ben0.synthetic.generate_dataset
    # or via CLI: ben0 generate

Outputs to data/synthetic/ relative to project root.
"""

from __future__ import annotations

import csv
import os
import random
import textwrap
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

SEED = 42
random.seed(SEED)
fake = Faker()
fake.seed_instance(SEED)

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

FAMILIES = [
    "Rosaceae", "Fagaceae", "Betulaceae", "Pinaceae", "Cupressaceae",
    "Ericaceae", "Salicaceae", "Aceraceae", "Oleaceae", "Magnoliaceae",
    "Ranunculaceae", "Liliaceae", "Orchidaceae", "Asteraceae", "Apiaceae",
    "Lamiaceae", "Fabaceae", "Rhamnaceae", "Cornaceae", "Taxaceae",
]

GENERA = [
    ("Acer", "Aceraceae"), ("Quercus", "Fagaceae"), ("Betula", "Betulaceae"),
    ("Pinus", "Pinaceae"), ("Abies", "Pinaceae"), ("Picea", "Pinaceae"),
    ("Thuja", "Cupressaceae"), ("Chamaecyparis", "Cupressaceae"),
    ("Rhododendron", "Ericaceae"), ("Vaccinium", "Ericaceae"),
    ("Salix", "Salicaceae"), ("Populus", "Salicaceae"),
    ("Prunus", "Rosaceae"), ("Rosa", "Rosaceae"), ("Sorbus", "Rosaceae"),
    ("Magnolia", "Magnoliaceae"), ("Fraxinus", "Oleaceae"),
    ("Taxus", "Taxaceae"), ("Cornus", "Cornaceae"), ("Rhamnus", "Rhamnaceae"),
    ("Lilium", "Liliaceae"), ("Trillium", "Liliaceae"),
    ("Calypso", "Orchidaceae"), ("Erythronium", "Liliaceae"),
    ("Camassia", "Liliaceae"), ("Aquilegia", "Ranunculaceae"),
    ("Anemone", "Ranunculaceae"), ("Heuchera", "Saxifragaceae"),
    ("Lomatium", "Apiaceae"), ("Arnica", "Asteraceae"),
]

SPECIES_EPITHETS = [
    "sylvatica", "canadensis", "occidentalis", "platanoides", "rubra",
    "japonica", "sinensis", "chinensis", "europaea", "americana",
    "douglasii", "menziesii", "hookeriana", "nuttallii", "sitchensis",
    "heterophylla", "macrophylla", "grandiflora", "angustifolia", "latifolia",
    "montana", "alpina", "palustris", "riparia", "maritima",
    "spectabilis", "elegans", "glabra", "pubescens", "tomentosa",
    "pendula", "fastigiata", "columnaris", "compacta", "nana",
    "alba", "nigra", "viridis", "aurea", "purpurea",
]

IUCN_STATUSES = ["LC", "NT", "VU", "EN", "CR", "DD", "NE", "LC", "LC", "LC"]

TAXON_RANKS = ["species", "subspecies", "variety", "cultivar", "species"]

PROVENANCE_CODES = ["W", "Z", "G", "U", "", "", ""]  # weighted toward missing

LIFE_STATUSES = ["alive", "alive", "alive", "dead", "removed", "unknown"]

EVENT_TYPES = [
    "sowing", "pricking_out", "planting", "transfer", "death",
    "removal", "observation", "observation", "observation",
]

ESTABLISHMENT_MEANS = ["wild", "wildNative", "introduced", "cultivated", "unknown"]

SOURCE_TYPES = ["institution", "individual", "exchange", "unknown"]

INSTITUTION_NAMES = [
    "Royal Botanic Gardens Kew", "Missouri Botanical Garden",
    "Arnold Arboretum of Harvard University", "New York Botanical Garden",
    "Chicago Botanic Garden", "Denver Botanic Gardens",
    "UBC Botanical Garden", "VanDusen Botanical Garden",
    "Butchart Gardens", "Bloedel Reserve",
    "Royal Botanic Garden Edinburgh", "Gothenburg Botanical Garden",
    "Meise Botanic Garden", "Komarov Botanical Institute",
    "Beijing Botanical Garden", "Xishuangbanna Tropical Botanical Garden",
    "Fairchild Tropical Botanic Garden", "Longwood Gardens",
    "San Francisco Botanical Society", "Portland Japanese Garden",
    "Seed Savers Exchange", "North American Rock Garden Society",
    "Canadian Botanical Conservation Network", "Plant Delights Nursery",
    "Far Reaches Farm", "Cistus Nursery", "Dancing Oaks Nursery",
    "Colvos Creek Nursery", "Siskiyou Rare Plant Nursery",
    "Pacific Rim Native Plants", "Darts Hill Garden Park",
    "Sooke Region Wilderness Society", "Friends of Garry Oak Ecosystems",
    "Garry Oak Meadow Preservation Society", "BC Ministry of Environment",
    "Environment Canada – SARA", "Wild Cascades Recovery Fund",
    "Individual collector: J. Mathews", "Individual collector: P. Weston",
    "Individual collector: R. Baxter", "Individual collector: M. Chen",
    "Unknown source", "Legacy donation – estate of L. Firth",
    "Garden exchange programme", "BGCI PlantSearch network",
    "Index Seminum – CDBG", "Index Seminum – RBG Kew",
    "Habitat restoration programme – Cowichan Valley",
    "Saanich Natives Propagation Project",
    "Cascadia Native Plant Society seed bank",
    "Quadra Island Conservancy",
    "Southern Gulf Islands Heritage Seed Library",
    "Coastal Douglas-fir Conservation Partnership",
    "Pacific Spirit Regional Park restoration",
    "E&N Railway corridor revegetation",
    "Sooke Hills Wilderness Regional Park",
    "Capital Regional District – parks division",
    "Metro Vancouver – green infrastructure",
    "Sea to Sky Invasive Species Council",
    "Thompson Rivers University herbarium",
    "University of Victoria – biology department",
    "Simon Fraser University – biology department",
    "Oregon State University – herbarium",
    "University of Washington – Burke Museum",
    "University of British Columbia – herbarium",
    "Royal BC Museum – botany collection",
    "Haida Gwaii plant rescue project",
    "COSEWIC technical committee",
    "NatureServe Canada",
    "Western Society of Weed Science",
    "Intermountain Flora project",
    "Flora of North America editorial committee",
    "Canadian Museum of Nature",
    "Agriculture and Agri-Food Canada – plant gene resources",
    "Beaty Biodiversity Museum",
    "Whistler Naturalists Society",
    "Sunshine Coast Botanical Society",
    "Galiano Island Conservancy Association",
    "Salt Spring Island Conservancy",
    "Gulf Islands National Park Reserve",
    "Pacific Rim National Park Reserve",
    "Carmanah Walbran Provincial Park",
    "Cathedral Grove Nature Reserve",
    "Manning Provincial Park",
    "Cypress Provincial Park – restoration",
    "Garibaldi Provincial Park",
    "Valhalla Wilderness Society",
    "Mount Revelstoke National Park",
    "Glacier National Park – plant monitoring",
    "Nature Conservancy of Canada – BC region",
    "Ducks Unlimited – wetland restoration",
    "Land Conservancy of BC",
    "Langley Environmental Partners Society",
    "Squamish-Lillooet Regional District",
    "Okanagan Similkameen Conservation Alliance",
    "Desert Research Institute – Okanagan",
    "Royal Roads University – sustainability",
    "Kwantlen Polytechnic University – horticulture",
]

BED_CODES = [
    ("A1", "Alpine Garden Section 1"),
    ("A2", "Alpine Garden Section 2"),
    ("A3", "Asian Slope 3"),  # renamed
    ("BC1", "BC Native Plants – Section 1"),
    ("BC2", "BC Native Plants – Section 2"),
    ("BC3", "BC Native Plants – Section 3"),
    ("CF1", "Conifer Forest 1"),
    ("CF2", "Conifer Forest 2"),
    ("E1", "East Meadow"),
    ("E2", "East Border"),
    ("GH1", "Glasshouse Bay 1"),
    ("GH2", "Glasshouse Bay 2"),
    ("GH3", "Glasshouse Bay 3"),
    ("H1", "Heritage Garden"),
    ("INT", "Interpretive Garden"),
    ("LAKE", "Lakeside Planting"),
    ("N1", "North Slope"),
    ("N2", "North Woodland"),
    ("NUR", "Nursery"),          # nursery
    ("8", "Nursery – Zone 8"),   # old bed code, also nursery
    ("OAK", "Oak Meadow Restoration"),
    ("Q1", "Quarry Garden"),
    ("R1", "Rock Garden"),
    ("R2", "Raised Beds – East"),
    ("RHOD", "Rhododendron Walk"),
    ("S1", "South Slope"),
    ("S2", "South Border"),
    ("W1", "West Pond"),
    ("W2", "West Woodland"),
    ("TEMP", "Temporary Holding"),
]


def _rand_date(start_year: int, end_year: int) -> date:
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _fmt(d: date | None) -> str:
    return d.isoformat() if d else ""


# ---------------------------------------------------------------------------
# Generator functions
# ---------------------------------------------------------------------------

def generate_taxa(n: int = 150) -> list[dict]:
    rows = []
    used_names: set[str] = set()

    # Pre-bake ~10 synonym pairs — we'll mark some as synonyms after
    synonym_pairs: list[tuple[int, int]] = []

    for i in range(n):
        genus, family = random.choice(GENERA)
        epithet = random.choice(SPECIES_EPITHETS)
        sci_name = f"{genus} {epithet}"
        # ensure uniqueness by appending var. or subsp.
        if sci_name in used_names:
            infraranks = ["var.", "subsp.", "f."]
            sci_name = f"{sci_name} {random.choice(infraranks)} {fake.word()}"
        used_names.add(sci_name)

        rows.append({
            "scientific_name": sci_name,
            "genus": genus,
            "species": epithet,
            "family": family,
            "taxon_rank": random.choice(TAXON_RANKS),
            "iucn_status": random.choice(IUCN_STATUSES),
            "is_synonym": False,
            "accepted_name": "",
        })

    # Create ~10 synonym pairs: pick an existing name, duplicate it under alt genus
    synonym_indices = random.sample(range(n), 10)
    for idx in synonym_indices:
        original = rows[idx]
        alt_genus, alt_family = random.choice(GENERA)
        syn_name = f"{alt_genus} {original['species']}"
        if syn_name in used_names:
            continue
        used_names.add(syn_name)
        rows.append({
            "scientific_name": syn_name,
            "genus": alt_genus,
            "species": original["species"],
            "family": alt_family,
            "taxon_rank": original["taxon_rank"],
            "iucn_status": original["iucn_status"],
            "is_synonym": True,
            "accepted_name": original["scientific_name"],
        })

    return rows


def generate_locations() -> list[dict]:
    rows = []
    for code, name in BED_CODES:
        lat = round(49.25 + random.uniform(-0.05, 0.05), 6)
        lon = round(-123.20 + random.uniform(-0.05, 0.05), 6)
        rows.append({
            "name": name,
            "code": code,
            "bed_code": code,
            "description": f"Garden section: {name}",
            "latitude": lat,
            "longitude": lon,
        })
    return rows


def generate_sources(n: int = 100) -> list[dict]:
    rows = []
    names = INSTITUTION_NAMES[:n]
    for name in names:
        stype = "institution"
        if name.startswith("Individual"):
            stype = "individual"
        elif "exchange" in name.lower() or "index seminum" in name.lower():
            stype = "exchange"
        elif "unknown" in name.lower() or "legacy" in name.lower():
            stype = "unknown"
        rows.append({
            "source_type": stype,
            "institution_name": name,
            "contact": fake.email() if stype != "unknown" else "",
            "description": fake.sentence(nb_words=8),
        })
    return rows


def generate_accessions(
    taxa: list[dict],
    sources: list[dict],
    n: int = 300,
) -> list[dict]:
    rows = []
    source_names = [s["institution_name"] for s in sources]
    taxa_names = [t["scientific_name"] for t in taxa]

    # Accession number formats
    def _acc_num(i: int, year: int) -> str:
        fmt = random.choice(["YYYY-NNNN", "YYYY.NNN", "CDBG", "YY-NNN", "TEMP", "UNKNOWN"])
        seq = i + 1
        if fmt == "YYYY-NNNN":
            return f"{year}-{seq:04d}"
        elif fmt == "YYYY.NNN":
            return f"{year}.{seq:03d}"
        elif fmt == "CDBG":
            return f"CDBG-{year}-{seq:03d}"
        elif fmt == "YY-NNN":
            return f"{str(year)[2:]}-{seq:03d}"
        elif fmt == "TEMP":
            return f"TEMP-{seq:04d}"
        else:
            return f"UNKNOWN-{seq:02d}"

    used_nums: set[str] = set()
    for i in range(n):
        year = random.randint(1985, 2023)
        acc_num = _acc_num(i, year)

        # Deliberate duplicates: ~5-10 of them
        if i < 295 and acc_num not in used_nums:
            used_nums.add(acc_num)
        elif i >= 295:
            # Force duplicates: pick from existing pool
            acc_num = random.choice(list(used_nums)) if used_nums else acc_num

        taxon_name = random.choice(taxa_names)
        acc_date = _rand_date(year, min(year + 1, 2024))

        # ~20% missing provenance, more in pre-2000
        if year < 2000:
            prov = random.choice(["W", "Z", "G", "U", "", "", "", "", ""])
        else:
            prov = random.choice(PROVENANCE_CODES)

        rows.append({
            "accession_number": acc_num,
            "taxon_scientific_name": taxon_name,
            "provenance_code": prov,
            "source_description": random.choice(source_names),
            "accession_date": _fmt(acc_date),
            "institution_code": "CDBG",
            "notes": fake.sentence(nb_words=10) if random.random() < 0.4 else "",
        })

    return rows


def generate_items(accessions: list[dict], locations: list[dict], n: int = 500) -> list[dict]:
    rows = []
    loc_codes = [l["code"] for l in locations]
    bed_codes_no_temp = [c for c in loc_codes if c not in ("TEMP",)]

    for i in range(n):
        acc = random.choice(accessions)
        acc_num = acc["accession_number"]
        suffix = f"{random.randint(1, 5):02d}"
        status = random.choice(LIFE_STATUSES)

        acc_date_str = acc["accession_date"]
        try:
            acc_date = date.fromisoformat(acc_date_str) if acc_date_str else date(2000, 1, 1)
        except ValueError:
            acc_date = date(2000, 1, 1)

        planting_date = acc_date + timedelta(days=random.randint(30, 730))
        if planting_date > date.today():
            planting_date = date.today() - timedelta(days=random.randint(1, 365))

        removal_date = ""
        if status in ("dead", "removed"):
            rd = planting_date + timedelta(days=random.randint(180, 3650))
            if rd > date.today():
                rd = date.today()
            removal_date = _fmt(rd)

        # ~30 items alive with no current location
        if status == "alive" and i < 30:
            loc_code = ""
        # ~15 items dead but location still set
        elif status == "dead" and i < 15:
            loc_code = random.choice(bed_codes_no_temp)
        elif status in ("dead", "removed"):
            loc_code = ""
        else:
            loc_code = random.choice(loc_codes)

        rows.append({
            "accession_number": acc_num,
            "item_suffix": suffix,
            "current_location_code": loc_code,
            "life_status": status,
            "planting_date": _fmt(planting_date),
            "removal_date": removal_date,
            "establishment_means": random.choice(ESTABLISHMENT_MEANS),
            "notes": fake.sentence(nb_words=6) if random.random() < 0.3 else "",
        })

    return rows


def generate_events(
    accessions: list[dict],
    items: list[dict],
    locations: list[dict],
    n: int = 1500,
) -> list[dict]:
    rows = []
    loc_codes = [l["code"] for l in locations]
    item_lookup = {(it["accession_number"], it["item_suffix"]): it for it in items}

    for i in range(n):
        acc = random.choice(accessions)
        acc_num = acc["accession_number"]
        suffix = f"{random.randint(1, 5):02d}"

        acc_date_str = acc["accession_date"]
        try:
            acc_date = date.fromisoformat(acc_date_str) if acc_date_str else date(2000, 1, 1)
        except ValueError:
            acc_date = date(2000, 1, 1)

        # ~20 events with dates before accession date (data problem)
        if i < 20:
            event_date = acc_date - timedelta(days=random.randint(1, 365))
        else:
            event_date = acc_date + timedelta(days=random.randint(0, 3650))
            if event_date > date.today():
                event_date = date.today()

        # Ambiguous "REM" status used in notes (data problem)
        event_type = random.choice(EVENT_TYPES)
        notes = fake.sentence(nb_words=8) if random.random() < 0.5 else ""
        if event_type in ("removal", "death") and random.random() < 0.3:
            notes = f"REM – {notes}"

        rows.append({
            "accession_number": acc_num,
            "item_suffix": suffix,
            "event_type": event_type,
            "event_date": _fmt(event_date),
            "location_code": random.choice(loc_codes) if random.random() < 0.7 else "",
            "notes": notes,
        })

    return rows


def generate_conservation_status(taxa: list[dict]) -> list[dict]:
    rows = []
    authorities = ["IUCN", "COSEWIC", "NatureServe", "BC Conservation Data Centre"]

    for taxon in taxa:
        if taxon["iucn_status"] in ("VU", "EN", "CR", "NT"):
            for auth in random.sample(authorities, k=random.randint(1, 3)):
                assess_year = random.randint(2005, 2023)
                rows.append({
                    "taxon_name": taxon["scientific_name"],
                    "status_source": auth,
                    "conservation_status": taxon["iucn_status"],
                    "assessment_date": f"{assess_year}-01-01",
                })

    return rows


# ---------------------------------------------------------------------------
# Document generators
# ---------------------------------------------------------------------------

OCR_ARTIFACTS = [
    ("o", "0"), ("l", "1"), ("I", "l"), ("rn", "m"), ("cl", "d"),
]


def _add_ocr_noise(text: str) -> str:
    """Add mild OCR artifacts to simulate scanned handwriting."""
    chars = list(text)
    for i in range(len(chars)):
        if random.random() < 0.008:
            # Random character substitution
            old, new = random.choice(OCR_ARTIFACTS)
            chars[i] = chars[i].replace(old, new) if chars[i] == old else chars[i]
    return "".join(chars)


def generate_accession_card(acc_num: str, taxon_name: str, prov_code: str,
                             source: str, acc_date: str, notes: str) -> str:
    collector = fake.name()
    locality = fake.city() + ", " + fake.country()
    nursery_history = random.choice([
        f"Received as seed. Sown {fake.date_between(start_date='-5y', end_date='-1y')}. "
        f"Pricked out x{random.randint(3, 24)} seedlings.",
        f"Received as bare-root plant from nursery propagation.",
        f"Cutting taken {fake.date_between(start_date='-3y', end_date='-1y')}. Rooted under mist.",
        f"Division from existing CDBG stock. Parent plant Acc. {fake.bothify('####-####')}.",
    ])
    bed = random.choice(BED_CODES)[0]
    planted = fake.date_between(start_date="-4y", end_date="-6m")

    text = textwrap.dedent(f"""\
        CASCADIA DEMONSTRATION BOTANICAL GARDEN
        ACCESSION RECORD CARD

        Acc. {acc_num}
        Taxon: {taxon_name}
        Family: {random.choice(FAMILIES)}

        Date received: {acc_date}
        Source: {source}
        Provenance: {prov_code or 'not recorded'}
        Collector / Donor: {collector}
        Locality of origin: {locality}

        Nursery history:
        {nursery_history}

        Location: {bed}
        Date planted: {planted}

        Notes:
        {notes or fake.sentence(nb_words=15)}

        Conservation status: {random.choice(IUCN_STATUSES)}
        Sensitive taxa restrictions: {'YES – location withheld' if random.random() < 0.1 else 'None'}

        [Handwritten addition]
        {fake.sentence(nb_words=10)} — {fake.name()[:3].upper()}
        Checked: {fake.date_between(start_date='-2y', end_date='today')}
    """)

    return _add_ocr_noise(text)


POLICY_DOCS = {
    "data_sharing_policy.txt": textwrap.dedent("""\
        CASCADIA DEMONSTRATION BOTANICAL GARDEN
        DATA SHARING POLICY — Version 2.3 (revised 2022)

        1. SCOPE
        This policy governs the sharing of collection data maintained by the
        Cascadia Demonstration Botanical Garden (CDBG), including accession records,
        taxon data, provenance information, and associated documents.

        2. PUBLIC DATA
        The following data classes may be shared publicly via GBIF, iNaturalist, and
        the CDBG website, subject to individual record review:
          - Taxon name, family, and rank
          - Accession year and general provenance code (W/Z/G/U)
          - Conservation status (IUCN category only)
          - General garden location (section-level only, not bed-level)

        3. RESTRICTED DATA
        The following data must not be publicly released without curator approval:
          a) Precise GPS coordinates of wild-collected material
          b) Full locality information for COSEWIC EN/CR taxa
          c) Permit numbers, collector identities for sensitive collections
          d) Internal accession notes containing unpublished research data

        4. SENSITIVE TAXA
        All taxa listed on the CDBG Sensitive Species List (see sensitive_species_list.txt)
        require information to be withheld at the locality level before any public release.
        Location data for these taxa shall be generalised to the regional level only.

        5. DATA REQUESTS
        External data requests must be submitted in writing to the Curator of Living
        Collections. Requests will be assessed against this policy within 15 working days.

        6. GBIF PUBLICATION
        CDBG participates in GBIF data publication. Sensitive records are suppressed
        automatically by the ingestion pipeline prior to IPT upload. Any override requires
        written approval from two senior staff members.

        7. REVIEW
        This policy is reviewed annually. Contact collections@cdbg.example.org
    """),

    "sensitive_species_list.txt": textwrap.dedent("""\
        CASCADIA DEMONSTRATION BOTANICAL GARDEN
        SENSITIVE SPECIES LIST — updated 2023-03-15

        The following taxa require restricted data handling under the CDBG Data Sharing
        Policy. Locality information must be withheld or generalised before public release.

        Tier 1 — Full suppression (no public locality):
          Calypso bulbosa var. occidentalis (Western Fairy-slipper)
          Trillium ovatum (Western Wake Robin) — populations under collection pressure
          Erythronium revolutum (Pink Fawn Lily) — Cowichan Valley provenance only
          Camassia leichtlinii ssp. suksdorfii (Great Camas) — coastal ecotypes

        Tier 2 — Region-level only (county/district):
          Aquilegia formosa (Western Columbine) — Haida Gwaii accessions
          Lomatium dissectum (Fernleaf Biscuitroot) — all accessions
          Arnica amplexicaulis (Clasping Arnica) — alpine provenances

        Tier 3 — Internal note suppression:
          All wild-collected (W) accessions of EN or CR taxa
          Any accession flagged by COSEWIC technical committee

        NOTE: This list does not supersede permit conditions. Permit conditions take
        precedence in all cases. Contact the Research Coordinator for permit queries.

        Several legacy accessions in the pre-1995 records have not yet been assessed
        for sensitivity. These should be reviewed by the Curator before any export.
    """),

    "bed_codes_reference.txt": textwrap.dedent("""\
        CASCADIA DEMONSTRATION BOTANICAL GARDEN
        BED CODE REFERENCE — last updated 2021-07-08

        This document maps current bed codes to historical codes and descriptive names.
        Use the CURRENT CODE column when entering new records.

        CURRENT CODE | CURRENT NAME               | HISTORICAL CODES  | NOTES
        -------------|----------------------------|-------------------|--------------------------------------
        A1           | Alpine Garden Section 1    | ALP-1             |
        A2           | Alpine Garden Section 2    | ALP-2             |
        A3           | Asian Slope 3              | AS3, ASIAN3       | Renamed from 'A3' in 2018
        BC1          | BC Native Plants – Sec. 1  | NAT-1             |
        BC2          | BC Native Plants – Sec. 2  | NAT-2             |
        BC3          | BC Native Plants – Sec. 3  | NAT-3             | Added 2015
        CF1          | Conifer Forest 1           | CON-1             |
        CF2          | Conifer Forest 2           | CON-2             |
        E1           | East Meadow                | MED-E             |
        E2           | East Border                | BOR-E             |
        GH1          | Glasshouse Bay 1           | GL-1              |
        GH2          | Glasshouse Bay 2           | GL-2              |
        GH3          | Glasshouse Bay 3           | GL-3              | Added 2010
        H1           | Heritage Garden            | HER               |
        INT          | Interpretive Garden        | INTERP            |
        LAKE         | Lakeside Planting          | LAK               |
        N1           | North Slope                | NS-1              |
        N2           | North Woodland             | NW                |
        NUR          | Nursery                    | 8, NUR, NURS      | Code '8' retired 2005; NUR preferred
        OAK          | Oak Meadow Restoration     | —                 | New section, established 2019
        Q1           | Quarry Garden              | QUA               |
        R1           | Rock Garden                | ROC               |
        R2           | Raised Beds – East         | RBE               |
        RHOD         | Rhododendron Walk          | RHO, RW           |
        S1           | South Slope                | SS-1              |
        S2           | South Border               | BOR-S             |
        W1           | West Pond                  | WPD               |
        W2           | West Woodland              | WWD               |
        TEMP         | Temporary Holding          | TMP, HOLD         | Not a permanent location

        NOTES:
        - Code '8' was used prior to 2005 for nursery accessions. Records showing
          location '8' should be treated as equivalent to NUR.
        - 'REM' in status field is AMBIGUOUS: may indicate Removed, Dead, or Transferred.
          Do not use REM. Use life_status values: dead / removed / transferred.
        - TEMP is a staging area only. Plants should not remain in TEMP beyond 6 months.
    """),

    "accession_numbering_guide.txt": textwrap.dedent("""\
        CASCADIA DEMONSTRATION BOTANICAL GARDEN
        ACCESSION NUMBERING GUIDE — Version 1.4

        CDBG has used several accession numbering conventions over its history.
        This guide documents all formats encountered in the legacy database.

        CURRENT STANDARD FORMAT (post-2012):
          CDBG-YYYY-NNN
          Example: CDBG-2021-042
          The institution prefix CDBG is mandatory for all new records.
          Sequential number is zero-padded to 3 digits, resets annually.

        PRE-2012 FORMATS:
          YYYY-NNNN  Example: 2004-0118   (4-digit year, 4-digit seq)
          YYYY.NNN   Example: 2004.118    (dot separator)
          YY-NNN     Example: 87-113      (2-digit year — ambiguous for 1987 vs 2087)

        TEMPORARY NUMBERS:
          TEMP-NNNN  Example: TEMP-0041
          Used for unverified material or material awaiting identification.
          TEMP numbers must be resolved before any public data release.

        UNKNOWN PROVENANCE PLACEHOLDER:
          UNKNOWN-NN Example: UNKNOWN-17
          Used for legacy material with no documented accession number.
          These should be investigated and either confirmed or retired.

        DUPLICATE ACCESSION NUMBERS:
          Some legacy records share accession numbers due to poor data entry
          practices before 1995. These are known issues and are tracked in the
          validation_issue table. Do not assume accession numbers are unique
          across the full historical dataset.

        ITEM SUFFIXES:
          Individual plants within an accession are denoted by a numeric suffix:
          Accession 2004-0118, plant 1 = 2004-0118.01
          Accession 2004-0118, plant 2 = 2004-0118.02

        QUESTIONS: contact the Collections Registrar.
    """),

    "collection_scope.txt": textwrap.dedent("""\
        CASCADIA DEMONSTRATION BOTANICAL GARDEN
        COLLECTION SCOPE POLICY — Approved 2020-09-14

        1. MISSION
        The CDBG living collection documents, conserves, and interprets the native
        and cultivated flora of the Pacific Northwest bioregion, with emphasis on:
          (a) Species of conservation concern in British Columbia and Washington State
          (b) Culturally significant plants used by Coast Salish and other First Nations
          (c) Cultivated heritage plants documented in regional horticultural history
          (d) Research collections supporting academic and conservation partnerships

        2. GEOGRAPHIC FOCUS
        Primary: Coastal Douglas-fir and Western Hemlock biogeoclimatic zones
        Secondary: Interior Cedar-Hemlock, Engelmann Spruce-Subalpine Fir zones
        Tertiary: Pacific Northwest endemic genera regardless of zone

        3. ACQUISITION PRIORITIES
        High: Wild-collected (W) material from verified natural populations
              Material supporting ex situ conservation of EN/CR taxa
              Accessions with documented provenance and collection permits
        Medium: Garden-sourced (G) material from reputable botanic gardens
                Seed exchange material with known cultivar or provenance data
        Low:  Material of unknown provenance (U) — accepted only if taxonomically
              significant or if no other source is available
              TEMP accessions — must be resolved within 12 months

        4. DEACCESSION CRITERIA
        Items may be deaccessioned if:
          - Taxon is outside collection scope
          - Material is redundant (>10 individuals of common taxon in collection)
          - Plant is irreversibly declining and cannot be propagated
          - Space constraints require rationalisation
        Deaccession proposals require Curator sign-off and Board notification.

        5. RECORD KEEPING
        All acquisitions must have an accession record created in BEN-0 within
        30 days of receipt. Records must include: taxon name, source, provenance
        code, and accession date. Notes are strongly encouraged.

        Contact: Curator of Living Collections — curator@cdbg.example.org
    """),
}


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def generate_all(output_dir: Path, count: int = 300) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cards_dir = output_dir / "documents" / "cards"
    policies_dir = output_dir / "documents" / "policies"
    cards_dir.mkdir(parents=True, exist_ok=True)
    policies_dir.mkdir(parents=True, exist_ok=True)

    # Scale related entity counts proportionally to the accession count
    taxa_count = max(10, count // 2)
    sources_count = min(len(INSTITUTION_NAMES), max(10, count // 3))
    items_count = max(10, int(count * 1.67))
    events_count = max(10, count * 5)

    print("Generating taxa...")
    taxa = generate_taxa(taxa_count)
    _write_csv(output_dir / "taxa.csv", taxa)

    print("Generating locations...")
    locations = generate_locations()
    _write_csv(output_dir / "locations.csv", locations)

    print("Generating sources...")
    sources = generate_sources(sources_count)
    _write_csv(output_dir / "sources.csv", sources)

    print("Generating accessions...")
    accessions = generate_accessions(taxa, sources, count)
    _write_csv(output_dir / "accessions.csv", accessions)

    print("Generating items...")
    items = generate_items(accessions, locations, items_count)
    _write_csv(output_dir / "items.csv", items)

    print("Generating events...")
    events = generate_events(accessions, items, locations, events_count)
    _write_csv(output_dir / "events.csv", events)

    print("Generating conservation_status...")
    cs = generate_conservation_status(taxa)
    _write_csv(output_dir / "conservation_status.csv", cs)

    # OCR accession cards
    print("Generating 50 OCR accession cards...")
    sample_accs = random.sample(accessions, min(50, len(accessions)))
    taxa_by_name = {t["scientific_name"]: t for t in taxa}
    for acc in sample_accs:
        acc_num = acc["accession_number"]
        safe_num = acc_num.replace("/", "-").replace("\\", "-")
        card_path = cards_dir / f"card_{safe_num}.txt"
        text = generate_accession_card(
            acc_num=acc_num,
            taxon_name=acc["taxon_scientific_name"],
            prov_code=acc["provenance_code"],
            source=acc["source_description"],
            acc_date=acc["accession_date"],
            notes=acc["notes"],
        )
        card_path.write_text(text, encoding="utf-8")

    # Policy documents
    print("Generating policy documents...")
    for filename, content in POLICY_DOCS.items():
        (policies_dir / filename).write_text(content, encoding="utf-8")

    print(f"\nDone. Output written to: {output_dir}")
    print(f"  taxa:                {len(taxa)} rows")
    print(f"  locations:           {len(locations)} rows")
    print(f"  sources:             {len(sources)} rows")
    print(f"  accessions:          {len(accessions)} rows")
    print(f"  items:               {len(items)} rows")
    print(f"  events:              {len(events)} rows")
    print(f"  conservation_status: {len(cs)} rows")
    print(f"  OCR cards:           {len(sample_accs)} files")
    print(f"  Policy docs:         {len(POLICY_DOCS)} files")


if __name__ == "__main__":
    from ben0 import config
    generate_all(config.SYNTHETIC_DIR)
