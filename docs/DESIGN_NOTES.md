# Power BI presentation system

The polished edition retains all seven analytical pages and the eight source tables. Dark blue headings and pale blue panels establish a consistent visual hierarchy. Each page has an editable MarketPulse masthead. Field labels explain units and data availability; model error scores use four decimals so small differences are visible.

Anomalies are split into an initial flag table and supporting evidence. The latest risk table includes data availability to avoid presenting old indicator readings as current. Forecast values use percentage formatting: probability for direction, return for regression. The underlying values and selection criteria are unchanged.

The original release is preserved for rollback. Build the polished edition with `scripts/build_powerbi.py --output dashboards/MarketPulsePolished`, while that report is closed in Desktop. Validate it with `scripts/verify_powerbi.py --output dashboards/MarketPulsePolished`. The generator writes the managed report definition; manual report edits should be saved separately before regeneration.

Use the presentation guide for the narrative and the health launcher to verify the published snapshot and its database provenance. Integrity and freshness are different: successful verification does not imply that every indicator is current.
