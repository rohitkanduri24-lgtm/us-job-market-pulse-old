"""Download raw labor-market data from the BLS Public Data API (plus optional FRED API claims).

Writes:
  data/raw/fred.csv          long format: series_id, date, value (national series; FRED-style ids)
  data/raw/bls_industry.csv  long format: series_id, industry_code, element, date, value
  data/raw/bls_state.csv     long format: series_id, fips, element, date, value
  data/raw/metadata.json     fetch timestamp + any series that failed

Weekly claims need a free FRED_API_KEY (optional). Set BLS_API_KEY (free at https://data.bls.gov/registrationEngine/) for larger
requests; without it the v1 API is used (25 series per call, 10 years).
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import time
import urllib.error
import urllib.request

import pandas as pd

from . import config as C

USER_AGENT = "us-job-market-pulse/1.0 (open-source labor market dashboard)"


def _http(url: str, payload: dict | None = None, retries: int = 3) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries - 1:
                raise
            wait = 3 * 2 ** attempt
            print(f"    retrying in {wait}s ({type(exc).__name__})", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


# ----------------------------------------------------------------------------- FRED
def parse_fred_csv(raw: bytes, series_id: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), na_values=".")
    if df.shape[1] != 2:
        raise ValueError(f"Unexpected FRED response for {series_id}: columns={list(df.columns)}")
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["series_id"] = series_id
    return df.dropna(subset=["value"])[["series_id", "date", "value"]]


def fetch_fred_api(series_ids, api_key: str) -> tuple[pd.DataFrame, list[str]]:
    """Optional: weekly claims etc. via FRED's official API (needs a free FRED_API_KEY)."""
    frames, failed = [], []
    for sid in series_ids:
        print(f"  FRED API  {sid}", flush=True)
        try:
            url = ("https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={sid}&api_key={api_key}&file_type=json&observation_start=2000-01-01")
            obs = json.loads(_http(url, retries=2))["observations"]
            df = pd.DataFrame(obs)[["date", "value"]]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df["series_id"] = sid
            frames.append(df.dropna(subset=["value"])[["series_id", "date", "value"]])
        except Exception as exc:
            print(f"    !! failed: {type(exc).__name__}", flush=True)
            failed.append(sid)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["series_id", "date", "value"])), failed


def recession_series() -> pd.DataFrame:
    """NBER US recession months (published, fixed dates) as a 0/1 monthly series."""
    spans = [("2001-04-01", "2001-11-01"), ("2008-01-01", "2009-06-01"), ("2020-03-01", "2020-04-01")]
    idx = pd.date_range("2000-12-01", pd.Timestamp.today().normalize().replace(day=1), freq="MS")
    val = pd.Series(0.0, index=idx)
    for s, e in spans:
        val[(val.index >= s) & (val.index <= e)] = 1.0
    return pd.DataFrame({"series_id": "USREC", "date": idx, "value": val.values})


# ----------------------------------------------------------------------------- BLS
def parse_bls_response(resp: dict) -> pd.DataFrame:
    if resp.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {resp.get('message')}")
    rows = []
    for series in resp["Results"]["series"]:
        for obs in series.get("data", []):
            period = obs["period"]
            if not period.startswith("M") or period == "M13":
                continue
            try:
                value = float(obs["value"])
            except (TypeError, ValueError):
                continue
            rows.append({
                "series_id": series["seriesID"],
                "date": pd.Timestamp(int(obs["year"]), int(period[1:]), 1),
                "value": value,
            })
    return pd.DataFrame(rows, columns=["series_id", "date", "value"])


def fetch_bls(series_ids: list[str], windows: list[tuple[int, int]] | None = None) -> tuple[pd.DataFrame, list[str]]:
    key = os.environ.get("BLS_API_KEY", "").strip()
    url = f"https://api.bls.gov/publicAPI/{'v2' if key else 'v1'}/timeseries/data/"
    per_call, years = (50, 20) if key else (25, 10)
    end = dt.date.today().year
    windows = windows or [(end - years + 1, end)]
    frames = []
    for i in range(0, len(series_ids), per_call):
        batch = series_ids[i:i + per_call]
        for start, stop in windows:
            print(f"  BLS   {len(batch)} series ({start}-{stop})", flush=True)
            payload = {"seriesid": batch, "startyear": str(start), "endyear": str(stop)}
            if key:
                payload["registrationkey"] = key
            resp = json.loads(_http(url, payload))
            for note in resp.get("message", []):
                print(f"    note: {note}", flush=True)
            frames.append(parse_bls_response(resp))
            time.sleep(1)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["series_id", "date", "value"])
    df = df.drop_duplicates(["series_id", "date"])
    failed = sorted(set(series_ids) - set(df["series_id"]))
    return df, failed


def run() -> dict:
    C.RAW_DIR.mkdir(parents=True, exist_ok=True)
    print("Fetching national series from the BLS API ...", flush=True)
    nat_ids = {C.national_series_id(sid): sid for sid in C.NATIONAL_BLS}
    end_year = dt.date.today().year
    nat, nat_failed = fetch_bls(list(nat_ids), windows=[(2001, 2010), (2011, 2020), (2021, end_year)])
    nat["series_id"] = nat["series_id"].map(nat_ids)
    nat_failed = [nat_ids[s] for s in nat_failed]
    if nat.empty:
        raise SystemExit("No national data downloaded from BLS.")
    frames = [nat, recession_series()]
    fred_failed = []
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    if fred_key:
        print("Fetching weekly claims from the FRED API ...", flush=True)
        claims, fred_failed = fetch_fred_api(["ICSA", "CCSA"], fred_key)
        frames.append(claims)
    else:
        print("FRED_API_KEY not set - skipping weekly jobless claims.", flush=True)
    pd.concat(frames, ignore_index=True).to_csv(C.RAW_DIR / "fred.csv", index=False)
    fred_failed = nat_failed + fred_failed

    print("Fetching industry detail from BLS ...", flush=True)
    ind_ids = {C.industry_series_id(code, el): (code, el)
               for code in C.JOLTS_INDUSTRIES for el in C.INDUSTRY_ELEMENTS}
    ind, ind_failed = fetch_bls(list(ind_ids))
    ind["industry_code"] = ind["series_id"].map(lambda s: ind_ids[s][0])
    ind["element"] = ind["series_id"].map(lambda s: ind_ids[s][1])
    ind.to_csv(C.RAW_DIR / "bls_industry.csv", index=False)

    print("Fetching state detail from BLS ...", flush=True)
    st_ids = {C.state_series_id(fips, el): (fips, el)
              for fips in C.STATES for el in C.STATE_ELEMENTS}
    st, st_failed = fetch_bls(list(st_ids))
    st["fips"] = st["series_id"].map(lambda s: st_ids[s][0])
    st["element"] = st["series_id"].map(lambda s: st_ids[s][1])
    st.to_csv(C.RAW_DIR / "bls_state.csv", index=False)

    meta = {
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "failed_series": fred_failed + ind_failed + st_failed,
    }
    (C.RAW_DIR / "metadata.json").write_text(json.dumps(meta, indent=2))
    if meta["failed_series"]:
        print(f"Warning: {len(meta['failed_series'])} series unavailable: {meta['failed_series']}")
    print("Fetch complete.")
    return meta


if __name__ == "__main__":
    run()
