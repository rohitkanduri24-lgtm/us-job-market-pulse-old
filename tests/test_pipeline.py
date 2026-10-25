"""Tests run on synthetic data (no internet needed):  python -m pytest -q"""
import json

import numpy as np
import pandas as pd
import pytest

from src import analyze, build_dashboard, config as C, fetch_data


# ----------------------------------------------------------------------------- fixtures
def _fake_raw(raw_dir):
    rng = np.random.default_rng(7)
    months = pd.date_range("1999-01-01", "2026-08-01", freq="MS")
    n = len(months)
    trend = np.sin(np.linspace(0, 6, n))
    base = {
        "JTSJOL": 6500 + 2000 * trend, "JTSHIL": 5500 + 500 * trend, "JTSQUL": 3200 + 600 * trend,
        "JTSLDL": 1800 - 200 * trend, "JTSJOR": 4.2 + 1.2 * trend, "JTSHIR": 3.8 + 0.4 * trend,
        "JTSQUR": 2.2 + 0.4 * trend, "JTSLDR": 1.2 - 0.15 * trend, "UNRATE": 5.0 - 1.2 * trend,
        "U6RATE": 9.0 - 2 * trend, "UNEMPLOY": 7500 - 2000 * trend,
        "PAYEMS": np.linspace(130000, 159000, n), "CES0500000003": np.linspace(18, 36, n),
        "CPIAUCSL": np.linspace(165, 320, n), "USREC": (np.arange(n) % 120 < 8).astype(float),
    }
    rows = [{"series_id": k, "date": d, "value": v + rng.normal(0, 0.01)}
            for k, vals in base.items() for d, v in zip(months, vals)]
    weeks = pd.date_range("2015-01-03", "2026-10-17", freq="W-SAT")
    rows += [{"series_id": "ICSA", "date": d, "value": 220000 + rng.normal(0, 8000)} for d in weeks]
    rows += [{"series_id": "CCSA", "date": d, "value": 1800000 + rng.normal(0, 30000)} for d in weeks]
    pd.DataFrame(rows).to_csv(raw_dir / "fred.csv", index=False)

    bls_months = pd.date_range("2017-01-01", "2026-08-01", freq="MS")
    ind = [{"series_id": C.industry_series_id(code, el), "industry_code": code, "element": el,
            "date": d, "value": round(2 + rng.random() * 4, 1)}
           for code in C.JOLTS_INDUSTRIES for el in C.INDUSTRY_ELEMENTS for d in bls_months]
    pd.DataFrame(ind).to_csv(raw_dir / "bls_industry.csv", index=False)
    st = [{"series_id": C.state_series_id(f, el), "fips": f, "element": el,
           "date": d, "value": round(1 + rng.random() * 4, 1)}
          for f in C.STATES for el in C.STATE_ELEMENTS for d in bls_months]
    pd.DataFrame(st).to_csv(raw_dir / "bls_state.csv", index=False)
    (raw_dir / "metadata.json").write_text(json.dumps({"fetched_at_utc": "TEST", "failed_series": []}))


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name, sub in [("DATA_DIR", "data"), ("RAW_DIR", "data/raw"), ("PROCESSED_DIR", "data/processed"),
                      ("DOCS_DIR", "docs"), ("REPORTS_DIR", "reports")]:
        p = tmp_path / sub
        p.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(C, name, p)
    monkeypatch.setattr(C, "DB_PATH", tmp_path / "data" / "job_market.db")
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- INSIGHTS:START -->\nold\n<!-- INSIGHTS:END -->\noutro\n")
    monkeypatch.setattr(C, "README_PATH", readme)
    _fake_raw(C.RAW_DIR)
    return tmp_path


# ----------------------------------------------------------------------------- tests
def test_series_ids_have_bls_length():
    for code in C.JOLTS_INDUSTRIES:
        assert len(C.industry_series_id(code, "JO")) == 21
    for fips in C.STATES:
        sid = C.state_series_id(fips, "LD")
        assert len(sid) == 21 and sid[9:11] == fips
    assert C.state_series_id("37", "JO") == "JTS000000370000000JOR"


def test_parse_fred_csv_handles_missing_values():
    raw = b"observation_date,UNRATE\n2024-01-01,3.7\n2024-02-01,.\n2024-03-01,3.9\n"
    df = fetch_data.parse_fred_csv(raw, "UNRATE")
    assert list(df["value"]) == [3.7, 3.9]
    with pytest.raises(ValueError):
        fetch_data.parse_fred_csv(b"<html>a,b,c</html>\n1,2,3\n", "X")


def test_parse_bls_response_skips_annual_and_blank():
    resp = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "S1", "data": [
        {"year": "2025", "period": "M02", "value": "4.1"},
        {"year": "2025", "period": "M13", "value": "4.0"},
        {"year": "2025", "period": "M01", "value": "-"}]}]}}
    df = fetch_data.parse_bls_response(resp)
    assert len(df) == 1 and df.iloc[0]["date"] == pd.Timestamp("2025-02-01")


def test_sahm_rule_triggers_on_rising_unemployment():
    months = pd.date_range("2010-01-01", periods=24, freq="MS")
    u = [4.0] * 15 + [4.3, 4.6, 4.9, 5.2, 5.5, 5.8, 6.1, 6.4, 6.7]
    fred = pd.DataFrame({"series_id": "UNRATE", "date": months, "value": u})
    sahm = analyze.build_national(fred)[0]["sahm_indicator"]
    assert sahm.iloc[14] == pytest.approx(0.0)
    assert sahm.iloc[-1] >= C.SAHM_THRESHOLD


def test_full_pipeline_on_synthetic_data(project):
    results = analyze.run()
    m, weekly, industry, state, kpis, insights, meta = results
    assert m["health_score"].dropna().between(0, 100).all()
    assert m["openings_per_unemployed"].notna().any()
    assert len(industry) == len(C.JOLTS_INDUSTRIES)
    assert len(state) == len(C.STATES) and state["fips"].str.len().eq(2).all()
    assert kpis["health_score"]["label"] in {"Hot", "Healthy", "Cooling", "Weak"}
    assert len(insights) >= 6
    build_dashboard.run(results)
    js = (C.DOCS_DIR / "data.js").read_text()
    data = json.loads(js.split("=", 1)[1].strip().rstrip(";"))
    assert data["series"]["claims_4wk"] and data["recessions"]
    assert "\nold\n" not in C.README_PATH.read_text() and "outro" in C.README_PATH.read_text()
    assert (C.REPORTS_DIR / "summary.md").exists() and C.DB_PATH.exists()


def test_national_bls_ids_and_recession_series():
    ids = {C.national_series_id(s) for s in C.NATIONAL_BLS}
    assert len(ids) == len(C.NATIONAL_BLS)
    assert C.national_series_id("JTSJOL") == "JTS000000000000000JOL"
    assert all(len(C.national_series_id(s)) == 21 for s in C.NATIONAL_BLS if s.startswith("JTS"))
    rec = fetch_data.recession_series().set_index("date")["value"]
    assert rec["2020-03-01"] == 1 and rec["2019-01-01"] == 0 and rec["2009-06-01"] == 1


def test_pipeline_runs_without_claims(project):
    raw = pd.read_csv(C.RAW_DIR / "fred.csv")
    raw[~raw.series_id.isin(["ICSA", "CCSA"])].to_csv(C.RAW_DIR / "fred.csv", index=False)
    data = build_dashboard.build(*analyze.run())
    assert data["series"]["claims"] == [] and data["series"]["health_score"]
