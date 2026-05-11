---
title: DAIOE Years Explorer
emoji: 🤖
colorFrom: indigo
colorTo: blue
sdk: docker
app_file: app.py
pinned: false
---

# DAIOE Years Explorer: Swedish Occupations

An interactive Shiny app for exploring AI exposure and employment trends across Swedish occupations, built on the [DAIOE](https://www.ai-econlab.com/ai-exposure-daioe) index linked to [SCB's Swedish Occupational Register](https://www.scb.se/en/finding-statistics/statistics-by-subject-area/labour-market/labour-force-supply/the-swedish-occupational-register-with-statistics/).

## Features

- **Occupation View**: Select an occupation by SSYK level and year to see employment statistics and % changes (1, 3, 5-year)
- **AI Exposure**: Ranked bar chart of AI sub-domain exposure scores with percentile rankings and exposure levels
- **Employment by Age Group**: Line chart of annual employment % change by age group over a custom year range
- **Comparison View**: Benchmark multiple occupations side by side with an annual employment % change chart, summary table, and AI exposure radar chart
- **Download**: Filter and export the full dataset as CSV, Parquet, or Excel

## Data Sources

| Data | Source |
|------|--------|
| AI Exposure Index | [DAIOE - AI Econ Lab](https://www.ai-econlab.com/ai-exposure-daioe) |
| Employment Statistics | [Swedish Occupational Register, SCB](https://www.scb.se/en/finding-statistics/statistics-by-subject-area/labour-market/labour-force-supply/the-swedish-occupational-register-with-statistics/) |
