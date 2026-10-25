#!/usr/bin/env bash
# One-time setup for US Job Market Pulse (macOS / Linux).
# Run from the project folder:   bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

REPO_NAME="us-job-market-pulse"
step() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }

step "Checking Python"
if ! command -v python3 >/dev/null; then
  echo "python3 not found. Install it from https://www.python.org/downloads/ and re-run."; exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9+ required"'
python3 --version

step "Creating virtual environment and installing packages"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

step "Running tests"
python -m pytest -q

step "Downloading live data from BLS and FRED and building the dashboard"
python -m src.pipeline

step "Opening the dashboard"
(open docs/index.html 2>/dev/null || xdg-open docs/index.html 2>/dev/null || true)

step "Setting up git"
if [ ! -d .git ]; then
  git init -q -b main
fi
git add -A
if git diff --cached --quiet; then
  echo "Nothing new to commit."
else
  git commit -q -m "Initial commit: US Job Market Pulse labor market analytics

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NU8mg6AYZwUkuzxCHprHLn"
  echo "Committed."
fi

step "Publishing to GitHub"
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  read -r -p "Create a PUBLIC GitHub repo '$REPO_NAME' and push? [y/N] " ans
  if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
    if git remote get-url origin >/dev/null 2>&1; then
      git push -u origin main
    else
      gh repo create "$REPO_NAME" --public --source . --push \
        --description "Weekly-refreshed US labor market dashboard: openings, layoffs, jobless claims, wages and a Health Score (Python, pandas, SQL, GitHub Actions)."
    fi
    OWNER="$(gh api user --jq .login)"
    gh api -X POST "repos/$OWNER/$REPO_NAME/pages" -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
      && echo "GitHub Pages enabled." || echo "GitHub Pages may already be on (or enable it under Settings > Pages)."
    gh repo edit "$OWNER/$REPO_NAME" --homepage "https://$OWNER.github.io/$REPO_NAME/" \
      --add-topic data-analytics --add-topic labor-market --add-topic python --add-topic dashboard --add-topic economics >/dev/null || true
    echo
    echo "Repo:       https://github.com/$OWNER/$REPO_NAME"
    echo "Dashboard:  https://$OWNER.github.io/$REPO_NAME/   (live in 1-2 minutes)"
  fi
else
  cat <<EOF
GitHub CLI not found or not signed in. Either:
  A) brew install gh && gh auth login     then run:  bash setup.sh   again
  B) Create an empty repo named $REPO_NAME on github.com (no README), then:
       git remote add origin https://github.com/<your-username>/$REPO_NAME.git
       git push -u origin main
     and turn on Settings > Pages > Branch: main, folder: /docs
EOF
fi
echo
echo "Done."
