
# TCG Metagame Trends

This project analyzes Pokemon TCG Pocket tournament data to visualize metagame trends.
It focuses on identifying deck archetypes based on exact card composition rather than predefined labels.

## Setup

1. **Install dependencies**:
   ```bash
   uv sync
   ```

2. **Setup Data**:
   Ensure you have the tournament data and card database available.
   Run the setup script if you have access to the reference workspace:
   ```bash
   bash setup_data.sh
   ```
   Or place data manually:
   - `data/tournaments/`: Directory structure `YYYY/MM/DD/tournament_id/` containing JSON files.
   - `data/cards.json`: Card database JSON array.

3. **Run the App**:
   ```bash
   uv run streamlit run app.py
   ```

## Design

- **Data Analysis**: Scans tournament data, computes deck signatures (hashes of card lists), and aggregates daily usage.
- **Visualization**: Displays 100% stacked area charts of archetype share over time.
- **Drill-down**: Inspect specific deck lists, win rates, and card composition changes.

## Acknowledgments

This project uses tournament data provided by the [play.limitlesstcg.com](https://play.limitlesstcg.com) API.
