"""End-to-end refresh: fetch -> analyze -> dashboard.

Usage:
    python -m src.pipeline            # full refresh (needs internet)
    python -m src.pipeline --offline  # re-run analysis on existing data/raw files
"""
import argparse

from . import analyze, build_dashboard, fetch_data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="skip downloading; reuse data/raw")
    args = parser.parse_args()
    if not args.offline:
        fetch_data.run()
    results = analyze.run()
    build_dashboard.run(results)
    print("Done. Open docs/index.html to view the dashboard.")


if __name__ == "__main__":
    main()
