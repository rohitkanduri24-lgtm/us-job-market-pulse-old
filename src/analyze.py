"""Turn raw downloads into analysis tables, KPIs and plain-English insights."""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

from . import config as C


# ----------------------------------------------------------------------------- load
def load_raw():
    fred = pd.read_csv(C.RAW_DIR / "fred.csv", parse_dates=["date"])
    ind = pd.read_csv(C.RAW_DIR / "bls_industry.csv", parse_dates=["date"], dtype={"industry_code": str})
    st = pd.read_csv(C.RAW_DIR / "bls_state.csv", parse_dates=["date"], dtype={"fips": str})
    if not st.empty:
        st["fips"] = st["fips"].str.zfill(2)
    meta_path = C.RAW_DIR / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return fred, ind, st, meta


# ----------------------------------------------------------------------------- national
def build_national(fred: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (monthly wide table with derived metrics, weekly claims table)."""
    weekly_ids = [k for k, (_, f) in C.FRED_SERIES.items() if f == "W"]
    monthly_ids = [k for k, (_, f) in C.FRED_SERIES.items() if f == "M"]

    weekly = (fred[fred.series_id.isin(weekly_ids)]
              .pivot_table(index="date", columns="series_id", values="value")
              .sort_index())
    if "ICSA" in weekly:
        weekly["ICSA_4wk"] = weekly["ICSA"].rolling(4).mean()

    m = (fred[fred.series_id.isin(monthly_ids)]
         .pivot_table(index="date", columns="series_id", values="value")
         .sort_index())
    m = m[m.index >= pd.Timestamp(C.HISTORY_START) - pd.DateOffset(years=2)]

    # Openings per unemployed person (the "V/U ratio"): >1 means more jobs than job seekers
    if {"JTSJOL", "UNEMPLOY"} <= set(m):
        m["openings_per_unemployed"] = m["JTSJOL"] / m["UNEMPLOY"]

    # Wages vs prices
    if {"CES0500000003", "CPIAUCSL"} <= set(m):
        m["wage_growth_yoy"] = m["CES0500000003"].pct_change(12, fill_method=None) * 100
        m["inflation_yoy"] = m["CPIAUCSL"].pct_change(12, fill_method=None) * 100
        m["real_wage_growth_yoy"] = ((1 + m["wage_growth_yoy"] / 100) /
                                     (1 + m["inflation_yoy"] / 100) - 1) * 100

    if "PAYEMS" in m:
        m["payroll_change"] = m["PAYEMS"].diff()
        m["payroll_change_3mo_avg"] = m["payroll_change"].rolling(3).mean()

    # Sahm rule: 3-mo avg unemployment minus its low over the prior 12 months
    if "UNRATE" in m:
        u3 = m["UNRATE"].rolling(3).mean()
        m["sahm_indicator"] = u3 - u3.shift(1).rolling(12).min()

    # Weekly claims -> monthly average so it can join the monthly table
    if "ICSA" in weekly:
        m["claims_monthly"] = weekly["ICSA"].resample("MS").mean().reindex(m.index)

    m["health_score"] = health_score(m)
    m = m[m.index >= pd.Timestamp(C.HISTORY_START)]
    return m, weekly


def health_score(m: pd.DataFrame) -> pd.Series:
    """0-100 score: average historical percentile of six indicators (direction-adjusted).

    100 = every indicator at its best level since 2001; 0 = every one at its worst.
    """
    cols = [c for c in C.HEALTH_COMPONENTS if c in m]
    if len(cols) < 3:
        return pd.Series(np.nan, index=m.index)
    hist = m.loc[m.index >= pd.Timestamp(C.HISTORY_START), cols]
    pct = pd.DataFrame(index=m.index)
    for c in cols:
        ranks = hist[c].rank(pct=True)
        if C.HEALTH_COMPONENTS[c] < 0:
            ranks = 1 - ranks + 1 / hist[c].notna().sum()
        pct[c] = ranks
    complete = pct[cols].notna().all(axis=1)
    return (pct[cols].mean(axis=1) * 100).where(complete).round(1)


def health_label(score: float) -> str:
    if pd.isna(score):
        return "n/a"
    if score >= 70:
        return "Hot"
    if score >= 55:
        return "Healthy"
    if score >= 40:
        return "Cooling"
    return "Weak"


# ----------------------------------------------------------------------------- detail tables
def _latest_with_yoy(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Wide table (one row per key) with latest value and change vs 12 months earlier."""
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot_table(index=keys + ["date"], columns="element", values="value").reset_index()
    wide = wide.rename(columns={**C.INDUSTRY_ELEMENTS, **C.STATE_ELEMENTS})
    latest_date = wide["date"].max()
    prior_date = latest_date - pd.DateOffset(years=1)
    cur = wide[wide.date == latest_date].set_index(keys)
    prev = wide[wide.date == prior_date].set_index(keys)
    metrics = [c for c in ("openings_rate", "hires_rate", "layoffs_rate") if c in cur]
    out = cur[metrics].copy()
    for c in metrics:
        out[f"{c}_yoy_change"] = (cur[c] - prev[c].reindex(cur.index)).round(2)
    if {"hires_rate", "layoffs_rate"} <= set(out):
        out["net_hiring_rate"] = (out["hires_rate"] - out["layoffs_rate"]).round(2)
    out["as_of"] = latest_date.strftime("%Y-%m")
    return out.reset_index()


def build_industry(ind: pd.DataFrame) -> pd.DataFrame:
    out = _latest_with_yoy(ind, ["industry_code"])
    if out.empty:
        return out
    out.insert(1, "industry", out["industry_code"].map(C.JOLTS_INDUSTRIES))
    return out.sort_values("openings_rate_yoy_change", ascending=False)


def build_state(st: pd.DataFrame) -> pd.DataFrame:
    out = _latest_with_yoy(st, ["fips"])
    if out.empty:
        return out
    out.insert(1, "state", out["fips"].map(lambda f: C.STATES[f][0]))
    out.insert(2, "state_name", out["fips"].map(lambda f: C.STATES[f][1]))
    return out.sort_values("layoffs_rate", ascending=False)


# ----------------------------------------------------------------------------- KPIs & insights
def _kpi(series: pd.Series, months_back: int = 12) -> dict:
    s = series.dropna()
    if s.empty:
        return {}
    last_date = s.index[-1]
    prior = s[s.index <= last_date - pd.DateOffset(months=months_back)]
    return {
        "value": float(s.iloc[-1]),
        "date": last_date.strftime("%Y-%m-%d"),
        "prior": float(prior.iloc[-1]) if not prior.empty else None,
    }


def build_kpis(m: pd.DataFrame, weekly: pd.DataFrame) -> dict:
    k = {}
    for col in ["health_score", "openings_per_unemployed", "UNRATE", "JTSLDR", "JTSQUR", "JTSHIR",
                "real_wage_growth_yoy", "sahm_indicator", "payroll_change_3mo_avg", "JTSJOL", "UNEMPLOY"]:
        if col in m:
            k[col] = _kpi(m[col])
    if "ICSA_4wk" in weekly:
        k["ICSA_4wk"] = _kpi(weekly["ICSA_4wk"])
    if "health_score" in k and k["health_score"]:
        k["health_score"]["label"] = health_label(k["health_score"]["value"])
    return k


def _fmt_month(d: str) -> str:
    return pd.Timestamp(d).strftime("%B %Y")


def build_insights(k: dict, industry: pd.DataFrame, state: pd.DataFrame) -> list[str]:
    out = []
    hs = k.get("health_score")
    if hs:
        direction = ""
        if hs.get("prior") is not None:
            diff = hs["value"] - hs["prior"]
            direction = f", {'up' if diff >= 0 else 'down'} {abs(diff):.0f} points from a year earlier"
        out.append(f"**Labor Market Health Score: {hs['value']:.0f}/100 ({hs['label']})** as of "
                   f"{_fmt_month(hs['date'])}{direction}.")
    vu = k.get("openings_per_unemployed")
    if vu:
        line = f"There are **{vu['value']:.2f} job openings per unemployed person**"
        if vu.get("prior") is not None:
            line += f" (vs {vu['prior']:.2f} a year ago)"
        line += (". More openings than job seekers." if vu["value"] >= 1
                 else ". Fewer openings than job seekers - a tougher market for applicants.")
        out.append(line)
    u = k.get("UNRATE")
    if u:
        chg = f", {u['value'] - u['prior']:+.1f} pts year over year" if u.get("prior") is not None else ""
        out.append(f"Unemployment rate: **{u['value']:.1f}%** in {_fmt_month(u['date'])}{chg}.")
    q = k.get("JTSQUR")
    if q:
        out.append(f"Quits rate: **{q['value']:.1f}%** - a gauge of worker confidence "
                   f"(it peaked near 3.0% in the 2021-22 \"Great Resignation\").")
    c = k.get("ICSA_4wk")
    if c:
        line = f"Initial jobless claims (4-week avg): **{c['value']:,.0f}** for the week of {c['date']}"
        if c.get("prior"):
            line += f" ({(c['value'] / c['prior'] - 1) * 100:+.1f}% vs a year ago)"
        out.append(line + ".")
    rw = k.get("real_wage_growth_yoy")
    if rw:
        word = "outpacing" if rw["value"] >= 0 else "falling behind"
        out.append(f"Real wage growth: **{rw['value']:+.1f}%** year over year - paychecks are {word} inflation.")
    s = k.get("sahm_indicator")
    if s:
        status = ("**triggered** (historically signals recession)" if s["value"] >= C.SAHM_THRESHOLD
                  else "not triggered")
        out.append(f"Sahm Rule recession indicator: **{s['value']:.2f}** - {status}; threshold is {C.SAHM_THRESHOLD:.2f}.")
    if not industry.empty and "openings_rate_yoy_change" in industry:
        ranked = industry.dropna(subset=["openings_rate_yoy_change"])
        if len(ranked) >= 2:
            top, bottom = ranked.iloc[0], ranked.iloc[-1]
            out.append(f"Hiring demand rose most in **{top.industry}** ({top.openings_rate_yoy_change:+.1f} pts openings rate) "
                       f"and fell most in **{bottom.industry}** ({bottom.openings_rate_yoy_change:+.1f} pts).")
    if not state.empty and "layoffs_rate" in state:
        hi = state.nlargest(3, "layoffs_rate")
        names = ", ".join(f"{r.state_name} ({r.layoffs_rate:.1f}%)" for r in hi.itertuples())
        out.append(f"Highest state layoff rates ({_fmt_month(state['as_of'].iloc[0] + '-01')}): {names}.")
    return out


# ----------------------------------------------------------------------------- outputs
def write_outputs(m, weekly, industry, state, kpis, insights, meta):
    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    C.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    m.round(4).to_csv(C.PROCESSED_DIR / "national_monthly.csv", index_label="date")
    weekly.round(1).to_csv(C.PROCESSED_DIR / "claims_weekly.csv", index_label="date")
    industry.to_csv(C.PROCESSED_DIR / "industry_latest.csv", index=False)
    state.to_csv(C.PROCESSED_DIR / "state_latest.csv", index=False)

    # SQLite database so the data can be explored with SQL (see sql/insights.sql)
    with sqlite3.connect(C.DB_PATH) as con:
        m.reset_index().assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d")) \
            .to_sql("national_monthly", con, if_exists="replace", index=False)
        weekly.reset_index().assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d")) \
            .to_sql("claims_weekly", con, if_exists="replace", index=False)
        industry.to_sql("industry_latest", con, if_exists="replace", index=False)
        state.to_sql("state_latest", con, if_exists="replace", index=False)

    updated = meta.get("fetched_at_utc", "unknown")
    md = ["# US Job Market Pulse - Latest Readout", "", f"_Data refreshed: {updated}_", ""]
    md += [f"- {line}" for line in insights]
    (C.REPORTS_DIR / "summary.md").write_text("\n".join(md) + "\n")
    update_readme(insights, updated)


def update_readme(insights: list[str], updated: str):
    start, end = "<!-- INSIGHTS:START -->", "<!-- INSIGHTS:END -->"
    if not C.README_PATH.exists():
        return
    text = C.README_PATH.read_text()
    if start not in text or end not in text:
        return
    block = "\n".join([start, f"_Auto-updated {updated}_", ""] + [f"- {i}" for i in insights] + [end])
    before = text.split(start)[0]
    after = text.split(end, 1)[1]
    C.README_PATH.write_text(before + block + after)


def run():
    fred, ind, st, meta = load_raw()
    m, weekly = build_national(fred)
    industry = build_industry(ind)
    state = build_state(st)
    kpis = build_kpis(m, weekly)
    insights = build_insights(kpis, industry, state)
    write_outputs(m, weekly, industry, state, kpis, insights, meta)
    print("Analysis complete:")
    for line in insights:
        print("  -", line.replace("**", ""))
    return m, weekly, industry, state, kpis, insights, meta


if __name__ == "__main__":
    run()
