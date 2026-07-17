"""Country name -> flag emoji for the Telegram posts.

COUNTRY_FLAGS maps normalized country names to ISO 3166 alpha-2 codes; the
flag itself is computed from regional-indicator codepoints, so no emoji
literals clutter the source. Keys must already be in normalize_country() form.

Covers every Eurovision participant plus the OCR/display variants the stream
uses. Unknown / OCR-mangled / missing countries, and defunct states with no
emoji flag (Yugoslavia, Serbia & Montenegro), all fall back to the EU flag.
"""

import re


def _flag(iso2: str) -> str:
    """ISO alpha-2 code -> flag emoji via regional-indicator codepoints."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso2.upper())


FALLBACK_FLAG = _flag("EU")  # "EU" regional indicators render as the EU flag


def normalize_country(name: str) -> str:
    """Casefold, drop dots ("F.Y.R." -> "FYR"), unify "&" -> "and", collapse
    whitespace, strip a leading "the" -- so OCR/display variants of the same
    country hit one dict key."""
    s = name.casefold().replace("&", " and ").replace(".", "")
    s = re.sub(r"\s+", " ", s).strip()

    return s.removeprefix("the ")


COUNTRY_FLAGS = {
    "albania": "AL",
    "andorra": "AD",
    "armenia": "AM",
    "australia": "AU",
    "austria": "AT",
    "azerbaijan": "AZ",
    "belarus": "BY",
    "belgium": "BE",
    "bosnia and herzegovina": "BA",
    "bosnia & herzegovina": "BA",
    "bosnia herzegovina": "BA",
    "bulgaria": "BG",
    "croatia": "HR",
    "cyprus": "CY",
    "czech republic": "CZ",
    "czechia": "CZ",
    "denmark": "DK",
    "estonia": "EE",
    "finland": "FI",
    "france": "FR",
    "georgia": "GE",
    "germany": "DE",
    "great britain": "GB",
    "greece": "GR",
    "holland": "NL",
    "hungary": "HU",
    "iceland": "IS",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "latvia": "LV",
    "lithuania": "LT",
    "luxembourg": "LU",
    "macedonia": "MK",
    "fyr macedonia": "MK",
    "north macedonia": "MK",
    "malta": "MT",
    "moldova": "MD",
    "republic of moldova": "MD",
    "monaco": "MC",
    "montenegro": "ME",
    "morocco": "MA",
    "netherlands": "NL",
    "norway": "NO",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "russia": "RU",
    "russian federation": "RU",
    "san marino": "SM",
    "serbia": "RS",
    "slovakia": "SK",
    "slovenia": "SI",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "türkiye": "TR",
    "turkiye": "TR",  # OCR often loses the umlaut
    "turkey": "TR",
    "uk": "GB",
    "ukraine": "UA",
    "united kingdom": "GB",
    # default fallback for serbia & montenegro — serbian flag (sorry!)
    "serbia & montenegro": "RS",
    "serbia and montenegro": "RS",
    "serbia montenegro": "RS",
    # Defunct states with no emoji flag -> deliberate EU fallback.
    "yugoslavia": "EU",
}

# special handling of Serbia & Montenegro entries
S_AND_M_SLUGS = (
    "serbia & montenegro",
    "serbia and montenegro",
    "serbia montenegro",
)
S_AND_M_YEARS = (
    "2004",
    "2005",
)


def flag_for(country: str | None, year: str | None) -> str:
    """Flag emoji for a (possibly missing or OCR-mangled) country name."""
    if not country:
        return FALLBACK_FLAG

    normalized_country = normalize_country(country)

    # special handling of Serbia & Montenegro entries
    if normalized_country in S_AND_M_SLUGS and year in S_AND_M_YEARS:
        match year:
            case "2004":
                return _flag("RS")
            case "2005":
                return _flag("ME")

    iso2 = COUNTRY_FLAGS.get(normalized_country)

    return _flag(iso2) if iso2 else FALLBACK_FLAG
