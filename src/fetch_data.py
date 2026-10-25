"""Download raw labor-market data from FRED and the BLS Public Data API.

Writes:
  data/raw/fred.csv          long format: series_id, date, value
  data/raw/bls_industry.csv  long format: series_id, industry_code, element, date, value
  data/raw/bls_state.csv     long format: series_id, fips, element, date, value
  data/raw/metadata.json     fetch timestamp + any series that failed

Set BLS_API_KEY (free at https://data.bls.gov/registrationEngine/) for larger
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


def _http(url: str, payload: dict | None = None, retries: int = 4) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries - 1:
                raise
            wait = 3 * 2 ** attempt
            print(f"    retrying in {wait}s ({exc})")
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


def fetch_fred(series_ids) -> tuple[pd.DataFrame, list[str]]:
    frames, failed = [], []
    for sid in series_ids:
        print(f"  FRED  {sid}")
        try:
            raw = _http(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
            frames.append(parse_fred_csv(raw, sid))
        except Exception as exc:  # keep going; report at the end
            print(f"    !! failed: {exc}")
            failed.append(sid)
        time.sleep(0.5)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), failed


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


def fetch_bls(series_ids: list[str]) -> tuple[pd.DataFrame, list[str]]:
    key = os.environ.get("BLS_API_KEY", "").strip()
    url = f"https://api.bls.gov/publicAPI/{'v2' if key else 'v1'}/timeseries/data/"
    per_call, years = (50, 20) if key else (25, 10)
    end = dt.date.today().year
    start = end - years + 1
    frames = []
    for i in range(0, len(series_ids), per_call):
        batch = series_ids[i:i + per_call]
        print(f"  BLS   {len(batch)} series ({start}-{end})")
        payload = {"seriesid": batch, "startyear": str(start), "endyear": str(end)}
        if key:
            payload["registrationkey"] = key
        resp = json.loads(_http(url, payload))
        for note in resp.get("message", []):
            print(f"    note: {note}")
        frames.append(parse_bls_response(resp))
        time.sleep(1)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["series_id", "date", "value"])
    failed = sorted(set(series_ids) - set(df["series_id"]))
    return df, failed


def run() -> dict:
    C.RAW_DIR.mkdir(parents=True, exist_ok=True)
    print("Fetching national series from FRED ...")
    fred, fred_failed = fetch_fred(C.FRED_SERIES.keys())
    if fred.empty:
        raise SystemExit("No FRED data downloaded - check your internet connection.")
    fred.to_csv(C.RAW_DIR / "fred.csv", index=False)

    print("Fetching industry detail from BLS ...")
    ind_ids = {C.industry_series_id(code, el): (code, el)
               for code in C.JOLTS_INDUSTRIES for el in C.INDUSTRY_ELEMENTS}
    ind, ind_failed = fetch_bls(list(ind_ids))
    ind["industry_code"] = ind["series_id"].map(lambda s: ind_ids[s][0])
    ind["element"] = ind["series_id"].map(lambda s: ind_ids[s][1])
    ind.to_csv(C.RAW_DIR / "bls_industry.csv", index=False)

    print("Fetching state detail from BLS ...")
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
