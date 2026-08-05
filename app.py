from __future__ import annotations

import json
from html import escape
from io import BytesIO
from urllib.request import urlopen

import pandas as pd
import plotly.express as px
import streamlit as st


REMOTE_DATA_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "Energy-Data-Science/entsoe-realtime-data/data/"
)
ESTIMATED_CSV_BYTES_PER_ROW = 165
COUNTRY_LABELS = {
    "BE": "Belgium",
    "FR": "France",
    "DE": "Germany / Luxembourg",
    "NL": "Netherlands",
    "DK1": "Denmark DK1",
    "DK2": "Denmark DK2",
    "ES": "Spain",
    "PT": "Portugal",
}
COUNTRIES = tuple(COUNTRY_LABELS)
VARIABLES = (
    "actual_load",
    "forecast_load",
    "actual_solar_generation",
    "forecast_solar_generation",
    "actual_onshore_wind_generation",
    "forecast_onshore_wind_generation",
    "actual_offshore_wind_generation",
    "forecast_offshore_wind_generation",
    "day_ahead_price",
    "imbalance_price",
)


def remote_url(path_value: str) -> str:
    return f"{REMOTE_DATA_BASE_URL.rstrip('/')}/{path_value.lstrip('/')}"


@st.cache_data(ttl=60, show_spinner=False)
def read_remote_csv(path_value: str) -> pd.DataFrame:
    with urlopen(remote_url(path_value), timeout=15) as response:
        return pd.read_csv(BytesIO(response.read()))


@st.cache_data(ttl=60, show_spinner=False)
def read_remote_json(path_value: str) -> dict:
    with urlopen(remote_url(path_value), timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_remote_csv(path_value: str) -> pd.DataFrame:
    try:
        return read_remote_csv(path_value)
    except Exception as exc:
        st.warning(f"Could not read {path_value}: {exc}")
        return pd.DataFrame()


def normalize_snapshot_summary(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "collection_time_utc",
        "collection_time_local",
        "run_id",
        "country",
        "variable",
        "rows",
        "window_start_utc",
        "window_end_utc",
        "path",
    ]
    frame = frame.copy()
    for column in columns:
        if column not in frame.columns:
            frame[column] = 0 if column == "rows" else ""
    frame["country"] = frame["country"].astype(str)
    frame["variable"] = frame["variable"].astype(str)
    frame["rows"] = pd.to_numeric(frame["rows"], errors="coerce").fillna(0).astype("int64")
    return frame


def safe_remote_json(path_value: str) -> dict:
    try:
        return read_remote_json(path_value)
    except Exception:
        return {}


def format_bytes(size_bytes: float | int | None) -> str:
    if size_bytes is None or pd.isna(size_bytes):
        return "0.00 GB"

    size = float(size_bytes)
    gib = size / 1024**3
    if gib >= 0.01:
        return f"{gib:.2f} GB"
    return f"{size / 1024**2:.1f} MB"


def estimate_csv_bytes(rows: int | float) -> int:
    return int(float(rows or 0) * ESTIMATED_CSV_BYTES_PER_ROW)


def format_collection_time(value: str | None) -> str:
    if not value:
        return "No run yet"

    try:
        timestamp = pd.to_datetime(value, utc=True).tz_convert("Europe/Brussels")
        return timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return value


def safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def metric_tile(label: str, value: str, compact: bool = False) -> str:
    compact_class = " metric-value-compact" if compact else ""
    return (
        '<div class="metric-tile">'
        f'<div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value{compact_class}">{escape(value)}</div>'
        "</div>"
    )


def country_label(code: str) -> str:
    return f"{code} - {COUNTRY_LABELS.get(code, code)}"


def dashboard_countries(snapshot_summary: pd.DataFrame) -> tuple[str, ...]:
    available = []
    if not snapshot_summary.empty and "country" in snapshot_summary.columns:
        available = sorted(snapshot_summary["country"].dropna().astype(str).unique())
    ordered = list(COUNTRIES)
    for country in available:
        if country not in ordered:
            ordered.append(country)
    return tuple(ordered)


st.set_page_config(page_title="ENTSO-E Fetch Monitor", layout="wide")

st.markdown(
    """
    <style>
      .block-container {
        padding-top: 2rem;
      }
      .metric-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
        gap: 0.75rem;
        margin: 0.55rem 0 1.25rem;
      }
      .metric-tile {
        border: 1px solid rgba(17, 24, 39, 0.12);
        border-radius: 8px;
        padding: 0.8rem 0.9rem;
        min-height: 5.2rem;
        background: #f8fafc;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
      }
      .metric-label {
        color: #475569;
        font-size: 0.88rem;
        line-height: 1.2;
        margin-bottom: 0.35rem;
      }
      .metric-value {
        color: #0f172a;
        font-size: clamp(1.35rem, 2.3vw, 2rem);
        font-weight: 650;
        line-height: 1.12;
        overflow-wrap: anywhere;
      }
      .metric-value-compact {
        font-size: clamp(1rem, 1.55vw, 1.25rem);
      }
      .summary-section-title {
        color: inherit;
        font-size: 1.05rem;
        font-weight: 650;
        margin-top: 1.15rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("ENTSO-E 15-Minute Collection Monitor")
st.caption("Reading collected snapshots from the public GitHub data branch.")

status = safe_remote_json("data/status.json")
progress = safe_remote_json("data/progress.json")
snapshot_summary = safe_remote_csv("data/update_manifest.csv")
snapshot_summary = normalize_snapshot_summary(snapshot_summary)
latest_collection = None
latest_files = pd.DataFrame()

if not snapshot_summary.empty:
    snapshot_summary["country_label"] = snapshot_summary["country"].map(country_label)
    latest_collection = snapshot_summary["collection_time_utc"].max()
    latest_files = snapshot_summary[snapshot_summary["collection_time_utc"] == latest_collection].copy()

control_countries = dashboard_countries(snapshot_summary)

with st.sidebar:
    st.header("Controls")
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    selected_country = st.selectbox("Country", control_countries, format_func=country_label)
    selected_variable = st.selectbox("Variable", VARIABLES)
    st.caption("Data cache refreshes every 60 seconds. Use Refresh data for an immediate update.")

total_estimated_size_bytes = (
    estimate_csv_bytes(snapshot_summary["rows"].sum()) if not snapshot_summary.empty else 0
)
available_country_count = (
    snapshot_summary["country"].dropna().astype(str).nunique() if not snapshot_summary.empty else 0
)

st.markdown(
    '<div class="summary-section-title">Latest Run</div>'
    '<div class="metric-grid">'
    + metric_tile("Collection time", format_collection_time(status.get("collection_time_utc")), compact=True)
    + metric_tile("Succeeded tasks", f"{safe_int(status.get('ok_items')):,}")
    + metric_tile("Warnings", f"{safe_int(status.get('warning_items')):,}")
    + metric_tile("Errors", f"{safe_int(status.get('error_items')):,}")
    + "</div>"
    '<div class="summary-section-title">Total Snapshot Results</div>'
    '<div class="metric-grid">'
    + metric_tile("Snapshot files", f"{len(snapshot_summary):,}")
    + metric_tile(
        "Snapshot rows",
        f"{int(snapshot_summary['rows'].sum()) if not snapshot_summary.empty else 0:,}",
    )
    + metric_tile("Estimated CSV size", format_bytes(total_estimated_size_bytes))
    + metric_tile("Countries present", f"{available_country_count:,} / {len(control_countries):,}")
    + "</div>",
    unsafe_allow_html=True,
)
st.caption("CSV size is estimated from row counts to keep the public dashboard fast.")

if progress:
    if progress.get("status") == "run_complete":
        st.success(
            "Latest run complete: "
            f"{progress.get('ok_items', 0)} ok, "
            f"{progress.get('warning_items', 0)} warnings, "
            f"{progress.get('error_items', 0)} errors "
            f"at {progress.get('updated_at_utc')}"
        )
    else:
        st.info(
            "Current fetch: "
            f"{progress.get('country')} / {progress.get('variable')} "
            f"({progress.get('chunk_start')} to {progress.get('chunk_end')}) - "
            f"{progress.get('status')} at {progress.get('updated_at_utc')}"
        )

st.subheader("Latest Snapshot Collection")
if snapshot_summary.empty:
    st.info("No update snapshots are available yet.")
else:
    latest_files["csv_size_estimate"] = latest_files["rows"].map(estimate_csv_bytes).map(format_bytes)
    st.markdown(f"Latest collection: `{latest_collection}`")
    st.dataframe(
        latest_files[
            [
                "country",
                "country_label",
                "variable",
                "rows",
                "csv_size_estimate",
                "window_start_utc",
                "window_end_utc",
                "path",
            ]
        ]
        .sort_values(["country", "variable"]),
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Recent collection history", expanded=False):
        recent = snapshot_summary.sort_values("collection_time_utc", ascending=False).head(200)
        st.dataframe(
            recent[
                [
                    "collection_time_utc",
                    "country",
                    "country_label",
                    "variable",
                    "rows",
                    "window_start_utc",
                    "window_end_utc",
                    "path",
            ]
        ],
            use_container_width=True,
            hide_index=True,
        )

st.subheader("Snapshot Coverage")
if not snapshot_summary.empty:
    coverage = (
        snapshot_summary.groupby(["country", "variable"], as_index=False)
        .agg(
            collections=("collection_time_utc", "nunique"),
            rows=("rows", "sum"),
            latest_collection_utc=("collection_time_utc", "max"),
            latest_window_end_utc=("window_end_utc", "max"),
        )
        .sort_values(["country", "variable"])
    )
    coverage["country_label"] = coverage["country"].map(country_label)
    coverage["csv_size_estimate"] = coverage["rows"].map(estimate_csv_bytes).map(format_bytes)
    st.dataframe(
        coverage[
            [
                "country",
                "country_label",
                "variable",
                "collections",
                "rows",
                "csv_size_estimate",
                "latest_collection_utc",
                "latest_window_end_utc",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

st.subheader("Preview Latest Collection")
filtered = (
    snapshot_summary[
        (snapshot_summary.get("country") == selected_country)
        & (snapshot_summary.get("variable") == selected_variable)
    ]
    if not snapshot_summary.empty
    else pd.DataFrame()
)

if filtered.empty:
    st.info("No snapshot is available for the selected country and variable yet.")
else:
    options = filtered.sort_values("collection_time_utc", ascending=False)
    selected_collection = st.selectbox("Collection time", options["collection_time_utc"].tolist())
    preview_path = options.loc[
        options["collection_time_utc"] == selected_collection, "path"
    ].iloc[0]
    load_preview = st.button("Load preview", use_container_width=True)

    if not load_preview:
        st.info("Choose a collection time, then load the preview chart when needed.")
    else:
        frame = safe_remote_csv(preview_path)

        if frame.empty:
            st.info("The selected snapshot could not be loaded.")
        else:
            frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
            source_options = sorted(frame["source"].dropna().unique())
            selected_sources = st.multiselect(
                "Source columns",
                source_options,
                default=source_options[:3],
            )
            plot_frame = frame[frame["source"].isin(selected_sources)] if selected_sources else frame
            fig = px.line(
                plot_frame.tail(3000),
                x="timestamp_utc",
                y="value",
                color="source",
                title=f"{selected_country} - {selected_variable} - collected {selected_collection}",
            )
            st.plotly_chart(fig, use_container_width=True)

st.subheader("Recent Run Events")
if st.checkbox("Load recent run history", value=False):
    history = safe_remote_csv("data/run_history.csv")
    if history.empty:
        st.info("No run history yet.")
    else:
        st.dataframe(history.tail(100).iloc[::-1], use_container_width=True, hide_index=True)
else:
    st.caption("Run history is loaded on demand to keep the public dashboard lightweight.")
