# Data Scraper

This is a **skeleton** to import official TN VED / tariff data from locally downloaded HTML/CSV/XML.
Adapt CSS selectors/parsers to the actual structure of your official dumps.

Example:

```bash
cd data/scraper
python -m venv .venv && source .venv/bin/activate
pip install beautifulsoup4 lxml
python tariff_scraper.py --source ./official_html --out ../../backend/tnved.db
```

Then run backend and query `/codes/*`, `/notes/*`, `/tariff/{code}`.
