"""
Detects country from phone number with special Canada / USA handling.
"""

import phonenumbers
from phonenumbers import geocoder

# ── Canadian area codes (complete list) ──────────────────────────────
CANADIAN_AREA_CODES: set[str] = {
    "204", "226", "236", "249", "250", "257", "289",
    "306", "343", "365", "368",
    "403", "416", "418", "428", "431", "437", "438", "450", "468", "474",
    "506", "514", "519", "548", "579", "581", "587",
    "604", "613", "639", "647", "672", "683",
    "705", "709", "742", "778", "780", "782",
    "807", "819", "825", "867", "873",
    "902", "905",
}

# Country code → readable name overrides (for common cases)
_COUNTRY_NAMES: dict[int, str] = {
    1:   "USA",        # default for +1; overridden to Canada when matched
    7:   "Russia",
    20:  "Egypt",
    27:  "South Africa",
    30:  "Greece",
    31:  "Netherlands",
    32:  "Belgium",
    33:  "France",
    34:  "Spain",
    36:  "Hungary",
    39:  "Italy",
    40:  "Romania",
    41:  "Switzerland",
    43:  "Austria",
    44:  "United Kingdom",
    45:  "Denmark",
    46:  "Sweden",
    47:  "Norway",
    48:  "Poland",
    49:  "Germany",
    51:  "Peru",
    52:  "Mexico",
    53:  "Cuba",
    54:  "Argentina",
    55:  "Brazil",
    56:  "Chile",
    57:  "Colombia",
    58:  "Venezuela",
    60:  "Malaysia",
    61:  "Australia",
    62:  "Indonesia",
    63:  "Philippines",
    64:  "New Zealand",
    65:  "Singapore",
    66:  "Thailand",
    81:  "Japan",
    82:  "South Korea",
    84:  "Vietnam",
    86:  "China",
    90:  "Turkey",
    91:  "India",
    92:  "Pakistan",
    93:  "Afghanistan",
    94:  "Sri Lanka",
    95:  "Myanmar",
    98:  "Iran",
    212: "Morocco",
    213: "Algeria",
    216: "Tunisia",
    218: "Libya",
    220: "Gambia",
    221: "Senegal",
    234: "Nigeria",
    249: "Sudan",
    254: "Kenya",
    255: "Tanzania",
    256: "Uganda",
    260: "Zambia",
    263: "Zimbabwe",
    351: "Portugal",
    353: "Ireland",
    354: "Iceland",
    358: "Finland",
    370: "Lithuania",
    371: "Latvia",
    372: "Estonia",
    380: "Ukraine",
    381: "Serbia",
    385: "Croatia",
    420: "Czech Republic",
    421: "Slovakia",
    502: "Guatemala",
    503: "El Salvador",
    504: "Honduras",
    505: "Nicaragua",
    506: "Costa Rica",
    507: "Panama",
    591: "Bolivia",
    593: "Ecuador",
    595: "Paraguay",
    598: "Uruguay",
    880: "Bangladesh",
    886: "Taiwan",
    960: "Maldives",
    961: "Lebanon",
    962: "Jordan",
    963: "Syria",
    964: "Iraq",
    965: "Kuwait",
    966: "Saudi Arabia",
    967: "Yemen",
    968: "Oman",
    971: "UAE",
    972: "Israel",
    973: "Bahrain",
    974: "Qatar",
    992: "Tajikistan",
    993: "Turkmenistan",
    994: "Azerbaijan",
    995: "Georgia",
    996: "Kyrgyzstan",
    998: "Uzbekistan",
}


def detect_country(phone: str) -> str:
    """
    Detect country from a phone number string.

    Special logic for +1:
      - Extract the 3-digit area code
      - If it matches a Canadian area code → 'Canada'
      - Otherwise → 'USA'

    For all other prefixes, use phonenumbers library + our name table.

    Returns a human-readable country name (e.g. 'Iran', 'USA', 'Canada').
    """
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    try:
        parsed = phonenumbers.parse(phone, None)
    except phonenumbers.NumberParseException:
        return "Unknown"

    country_code = parsed.country_code
    national = str(parsed.national_number)

    # ── Special handling for +1 (NANP) ──
    if country_code == 1 and len(national) >= 3:
        area_code = national[:3]
        if area_code in CANADIAN_AREA_CODES:
            return "Canada"
        return "USA"

    # ── Lookup from our table first, then phonenumbers ──
    if country_code in _COUNTRY_NAMES:
        return _COUNTRY_NAMES[country_code]

    # Fallback: use phonenumbers geocoder for region
    region = phonenumbers.region_code_for_number(parsed)
    if region and region != "ZZ":
        # Try to get a nice name
        description = geocoder.description_for_number(parsed, "en")
        if description:
            return description
        return region

    return "Unknown"


def format_phone_display(phone: str) -> str:
    """Format phone for display: +1234567890 → +1 234 567 890."""
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    try:
        parsed = phonenumbers.parse(phone, None)
        return phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
    except phonenumbers.NumberParseException:
        return phone
