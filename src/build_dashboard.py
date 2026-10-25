"""Export analysis results to docs/data.js, which the static dashboard (docs/index.html) reads.

A .js file (window.DASHBOARD_DATA = {...}) is used instead of .json so the dashboard
also works when index.html is opened straight from disk, not only on GitHub Pages.
"""
from __future__ import annotations

import json
import math

import pandas as pd

from . import config as C


def _series(s: pd.Series, decimals: int = 2) -> list:
    s = s.dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), decimals)] for d, v in s.items()]


def _clean(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def build(m, weekly, industry, state, kpis, insights, meta) -> dict:
    col = lambda name, d=2: _series(m[name], d) if name in m else []
    recessions = []
    if "USREC" in m:
        rec = m["USREC"].fillna(0)
        start = None
        for d, v in rec.items():
            if v >= 1 and start is None:
                start = d
            elif v < 1 and start is not None:
                recessions.append([start.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d")])
                start = None
        if start is not None:
            recessions.append([start.strftime("%Y-%m-%d"), rec.index[-1].strftime("%Y-%m-%d")])

    recent_weekly = weekly[weekly.index >= weekly.index.max() - pd.DateOffset(years=5)] if len(weekly) else weekly
    data = {
        "updated": meta.get("fetched_at_utc", "unknown"),
        "failed_series": meta.get("failed_series", []),
        "kpis": kpis,
        "insights": insights,
        "recessions": recessions,
        "series": {
            "health_score": col("health_score", 1),
            "openings": col("JTSJOL", 0),
            "unemployed": col("UNEMPLOY", 0),
            "openings_per_unemployed": col("openings_per_unemployed", 3),
            "hires_rate": col("JTSHIR", 1),
            "quits_rate": col("JTSQUR", 1),
            "layoffs_rate": col("JTSLDR", 1),
            "unrate": col("UNRATE", 1),
            "u6rate": col("U6RATE", 1),
            "sahm": col("sahm_indicator", 2),
            "wage_growth": col("wage_growth_yoy", 2),
            "inflation": col("inflation_yoy", 2),
            "real_wage_growth": col("real_wage_growth_yoy", 2),
            "payroll_change": col("payroll_change", 0),
            "claims": _series(recent_weekly["ICSA"], 0) if "ICSA" in recent_weekly else [],
            "claims_4wk": _series(recent_weekly["ICSA_4wk"], 0) if "ICSA_4wk" in recent_weekly else [],
            "continuing_claims": _series(recent_weekly["CCSA"], 0) if "CCSA" in recent_weekly else [],
        },
        "industry": industry.round(2).to_dict(orient="records") if not industry.empty else [],
        "state": state.round(2).to_dict(orient="records") if not state.empty else [],
    }
    return _clean(data)


def write(data: dict):
    C.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, separators=(",", ":"))
    (C.DOCS_DIR / "data.js").write_text(f"window.DASHBOARD_DATA = {payload};\n")
    print(f"Dashboard data written to {C.DOCS_DIR / 'data.js'} ({len(payload) / 1024:.0f} KB)")


def run(results):
    write(build(*results))
