"""Central configuration: which series to pull and where files live."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = DATA_DIR / "job_market.db"
DOCS_DIR = ROOT / "docs"
REPORTS_DIR = ROOT / "reports"
README_PATH = ROOT / "README.md"

# Analysis window (JOLTS begins Dec 2000)
HISTORY_START = "2001-01-01"

# ---------------------------------------------------------------------------
# National series. Most are pulled from the official BLS API (see NATIONAL_BLS);
# USREC uses published NBER dates; weekly claims (ICSA/CCSA) need an optional
# free FRED_API_KEY. Series keep their FRED ids as the internal names.
# id -> (friendly name, frequency)
# ---------------------------------------------------------------------------
FRED_SERIES = {
    # JOLTS (Job Openings and Labor Turnover Survey), thousands / percent
    "JTSJOL": ("Job openings (thousands)", "M"),
    "JTSHIL": ("Hires (thousands)", "M"),
    "JTSQUL": ("Quits (thousands)", "M"),
    "JTSLDL": ("Layoffs & discharges (thousands)", "M"),
    "JTSJOR": ("Job openings rate (%)", "M"),
    "JTSHIR": ("Hires rate (%)", "M"),
    "JTSQUR": ("Quits rate (%)", "M"),
    "JTSLDR": ("Layoffs & discharges rate (%)", "M"),
    # Household & establishment surveys
    "UNRATE": ("Unemployment rate (%)", "M"),
    "U6RATE": ("U-6 underemployment rate (%)", "M"),
    "UNEMPLOY": ("Unemployed persons (thousands)", "M"),
    "PAYEMS": ("Nonfarm payrolls (thousands)", "M"),
    "CES0500000003": ("Avg hourly earnings, private ($)", "M"),
    "CPIAUCSL": ("Consumer Price Index", "M"),
    "USREC": ("NBER recession indicator", "M"),
    # Weekly unemployment insurance claims (the most real-time labor signal)
    "ICSA": ("Initial jobless claims", "W"),
    "CCSA": ("Continuing jobless claims", "W"),
}

# FRED-style id -> BLS series id (national, seasonally adjusted)
NATIONAL_BLS = {
    "JTSJOL": "JOL", "JTSHIL": "HIL", "JTSQUL": "QUL", "JTSLDL": "LDL",
    "JTSJOR": "JOR", "JTSHIR": "HIR", "JTSQUR": "QUR", "JTSLDR": "LDR",
    "UNRATE": "LNS14000000", "U6RATE": "LNS13327709", "UNEMPLOY": "LNS13000000",
    "PAYEMS": "CES0000000001", "CES0500000003": "CES0500000003", "CPIAUCSL": "CUSR0000SA0",
}


def national_series_id(fred_id: str) -> str:
    code = NATIONAL_BLS[fred_id]
    return f"JTS000000000000000{code}" if len(code) == 3 else code


# ---------------------------------------------------------------------------
# Industry & state detail from the BLS Public Data API (JOLTS).
# Series ID layout: JT + S + industry(6) + state(2) + area(5) + size(2) + element(2) + R/L
# ---------------------------------------------------------------------------
JOLTS_INDUSTRIES = {
    "110099": "Mining & logging",
    "230000": "Construction",
    "300000": "Manufacturing",
    "420000": "Wholesale trade",
    "440000": "Retail trade",
    "480099": "Transportation, warehousing & utilities",
    "510000": "Information",
    "510099": "Financial activities",
    "540099": "Professional & business services",
    "610000": "Private educational services",
    "620000": "Health care & social assistance",
    "700000": "Leisure & hospitality",
    "810000": "Other services",
    "900000": "Government",
}
INDUSTRY_ELEMENTS = {"JO": "openings_rate", "HI": "hires_rate", "LD": "layoffs_rate"}

STATES = {
    "01": ("AL", "Alabama"), "02": ("AK", "Alaska"), "04": ("AZ", "Arizona"),
    "05": ("AR", "Arkansas"), "06": ("CA", "California"), "08": ("CO", "Colorado"),
    "09": ("CT", "Connecticut"), "10": ("DE", "Delaware"), "11": ("DC", "District of Columbia"),
    "12": ("FL", "Florida"), "13": ("GA", "Georgia"), "15": ("HI", "Hawaii"),
    "16": ("ID", "Idaho"), "17": ("IL", "Illinois"), "18": ("IN", "Indiana"),
    "19": ("IA", "Iowa"), "20": ("KS", "Kansas"), "21": ("KY", "Kentucky"),
    "22": ("LA", "Louisiana"), "23": ("ME", "Maine"), "24": ("MD", "Maryland"),
    "25": ("MA", "Massachusetts"), "26": ("MI", "Michigan"), "27": ("MN", "Minnesota"),
    "28": ("MS", "Mississippi"), "29": ("MO", "Missouri"), "30": ("MT", "Montana"),
    "31": ("NE", "Nebraska"), "32": ("NV", "Nevada"), "33": ("NH", "New Hampshire"),
    "34": ("NJ", "New Jersey"), "35": ("NM", "New Mexico"), "36": ("NY", "New York"),
    "37": ("NC", "North Carolina"), "38": ("ND", "North Dakota"), "39": ("OH", "Ohio"),
    "40": ("OK", "Oklahoma"), "41": ("OR", "Oregon"), "42": ("PA", "Pennsylvania"),
    "44": ("RI", "Rhode Island"), "45": ("SC", "South Carolina"), "46": ("SD", "South Dakota"),
    "47": ("TN", "Tennessee"), "48": ("TX", "Texas"), "49": ("UT", "Utah"),
    "50": ("VT", "Vermont"), "51": ("VA", "Virginia"), "53": ("WA", "Washington"),
    "54": ("WV", "West Virginia"), "55": ("WI", "Wisconsin"), "56": ("WY", "Wyoming"),
}
STATE_ELEMENTS = {"JO": "openings_rate", "HI": "hires_rate", "LD": "layoffs_rate"}


def industry_series_id(industry_code: str, element: str) -> str:
    return f"JTS{industry_code}000000000{element}R"


def state_series_id(fips: str, element: str) -> str:
    return f"JTS000000{fips}0000000{element}R"


# Labor Market Health Score components: column -> direction (+1 higher is better)
HEALTH_COMPONENTS = {
    "openings_per_unemployed": +1,
    "JTSHIR": +1,
    "JTSQUR": +1,   # people quit when they are confident they can find a new job
    "JTSLDR": -1,
    "UNRATE": -1,
    "claims_monthly": -1,
}
SAHM_THRESHOLD = 0.50
