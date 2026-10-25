-- Example analyst queries against data/job_market.db (SQLite).
-- Run:  sqlite3 data/job_market.db < sql/insights.sql
-- or open the .db in DB Browser for SQLite / DBeaver / VS Code SQLite extension.

.headers on
.mode column

-- 1) Last 12 months of the core labor market indicators
SELECT date,
       ROUND(JTSJOL / 1000.0, 2)               AS openings_mil,
       ROUND(UNEMPLOY / 1000.0, 2)             AS unemployed_mil,
       ROUND(openings_per_unemployed, 2)       AS openings_per_unemployed,
       UNRATE                                  AS unemployment_rate,
       JTSQUR                                  AS quits_rate,
       JTSLDR                                  AS layoffs_rate,
       health_score
FROM national_monthly
ORDER BY date DESC
LIMIT 12;

-- 2) How does today compare with each year's average? (yearly trend)
SELECT substr(date, 1, 4)                      AS year,
       ROUND(AVG(openings_per_unemployed), 2)  AS avg_openings_per_unemployed,
       ROUND(AVG(UNRATE), 1)                   AS avg_unemployment_rate,
       ROUND(AVG(JTSQUR), 2)                   AS avg_quits_rate,
       ROUND(AVG(health_score), 0)             AS avg_health_score
FROM national_monthly
GROUP BY year
ORDER BY year;

-- 3) Months when the Sahm Rule recession indicator was triggered (>= 0.50)
SELECT date, ROUND(sahm_indicator, 2) AS sahm_indicator, UNRATE
FROM national_monthly
WHERE sahm_indicator >= 0.50
ORDER BY date;

-- 4) Industries ranked by net hiring (hires rate minus layoffs rate)
SELECT industry, openings_rate, openings_rate_yoy_change, hires_rate, layoffs_rate, net_hiring_rate
FROM industry_latest
ORDER BY net_hiring_rate DESC;

-- 5) Ten states with the highest layoff rates, and how they changed in a year
SELECT state_name, layoffs_rate, layoffs_rate_yoy_change, openings_rate
FROM state_latest
ORDER BY layoffs_rate DESC
LIMIT 10;

-- 6) Weekly jobless claims: latest 8 weeks vs the same weeks one year earlier
SELECT cur.date, cur.ICSA AS initial_claims, prev.ICSA AS year_ago,
       ROUND(100.0 * (cur.ICSA - prev.ICSA) / prev.ICSA, 1) AS pct_change
FROM claims_weekly cur
LEFT JOIN claims_weekly prev ON prev.date = date(cur.date, '-364 days')
ORDER BY cur.date DESC
LIMIT 8;
