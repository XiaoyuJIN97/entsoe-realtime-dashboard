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
COUNTRIES = ("BE", "FR", "DE")
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
        margin: 1rem 0 1.4rem;
      }
      .metric-tile {
        border: 1px solid rgba(128, 128, 128, 0.28);
        border-radius: 8px;
        padding: 0.8rem 0.9rem;
        min-height: 5.2rem;
        background: rgba(128, 128, 128, 0.08);
      }
      .metric-label {
        color: rgba(250, 250, 250, 0.74);
        font-size: 0.88rem;
        line-height: 1.2;
        margin-bottom: 0.35rem;
      }
      .metric-value {
        color: rgb(250, 250, 250);
        font-size: clamp(1.35rem, 2.3vw, 2rem);
        font-weight: 650;
        line-height: 1.12;
        overflow-wrap: anywhere;
      }
      .metric-value-compact {
        font-size: clamp(1rem, 1.55vw, 1.25rem);
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("ENTSO-E 15-Minute Collection Monitor")
st.caption("Reading collected snapshots from the public GitHub data branch.")

with st.sidebar:
    st.header("Controls")
    if st.button("Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    selected_country = st.selectbox("Country", COUNTRIES)
    selected_variable = st.selectbox("Variable", VARIABLES)
    st.caption("Data cache refreshes every 60 seconds. Use Refresh data for an immediate update.")

status = safe_remote_json("data/status.json")
progress = safe_remote_json("data/progress.json")
snapshot_summary = safe_remote_csv("data/update_manifest.csv")
latest_collection = None
latest_files = pd.DataFrame()

if not snapshot_summary.empty:
    latest_collection = snapshot_summary["collection_time_utc"].max()
    latest_files = snapshot_summary[snapshot_summary["collection_time_utc"] == latest_collection].copy()

total_estimated_size_bytes = (
    estimate_csv_bytes(snapshot_summary["rows"].sum()) if not snapshot_summary.empty else 0
)

st.markdown(
    '<div class="metric-grid">'
    + metric_tile("Last collection", format_collection_time(status.get("collection_time_utc")), compact=True)
    + metric_tile("OK", f"{safe_int(status.get('ok_items')):,}")
    + metric_tile("Warnings", f"{safe_int(status.get('warning_items')):,}")
    + metric_tile("Errors", f"{safe_int(status.get('error_items')):,}")
    + metric_tile("Snapshot files", f"{len(snapshot_summary):,}")
    + metric_tile(
        "Snapshot rows",
        f"{int(snapshot_summary['rows'].sum()) if not snapshot_summary.empty else 0:,}",
    )
    + metric_tile("Estimated CSV size", format_bytes(total_estimated_size_bytes))
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
                "variable",
                "rows",
                "csv_size_estimate",
                "window_start_utc",
                "window_end_utc",
                "path",
            ]
        ]
        .sort_values(["country", "variable"]),
        width="stretch",
        hide_index=True,
    )
    with st.expander("Recent collection history", expanded=False):
        recent = snapshot_summary.sort_values("collection_time_utc", ascending=False).head(200)
        st.dataframe(
            recent[
                [
                    "collection_time_utc",
                    "country",
                    "variable",
                    "rows",
                    "window_start_utc",
                    "window_end_utc",
                    "path",
                ]
            ],
            width="stretch",
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
    coverage["csv_size_estimate"] = coverage["rows"].map(estimate_csv_bytes).map(format_bytes)
    st.dataframe(
        coverage[
            [
                "country",
                "variable",
                "collections",
                "rows",
                "csv_size_estimate",
                "latest_collection_utc",
                "latest_window_end_utc",
            ]
        ],
        width="stretch",
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
    load_preview = st.button("Load preview", width="stretch")

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
            st.plotly_chart(fig, width="stretch")

st.subheader("Recent Run Events")
history = safe_remote_csv("data/run_history.csv")
if history.empty:
    st.info("No run history yet.")
else:
    st.dataframe(history.tail(100).iloc[::-1], width="stretch", hide_index=True)
