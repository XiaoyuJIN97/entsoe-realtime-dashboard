from __future__ import annotations

import json
from urllib.request import urlopen

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components


REMOTE_DATA_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "Energy-Data-Science/entsoe-realtime-data/data/"
)

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
    return pd.read_csv(remote_url(path_value))


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


st.set_page_config(page_title="ENTSO-E Fetch Monitor", layout="wide")
components.html(
    """
    <script>
      setTimeout(function () {
        window.parent.location.reload();
      }, 30000);
    </script>
    """,
    height=0,
)

st.title("ENTSO-E 15-Minute Collection Monitor")
st.caption(f"Reading collected snapshots from {REMOTE_DATA_BASE_URL}")

with st.sidebar:
    st.header("Controls")
    selected_country = st.selectbox("Country", COUNTRIES)
    selected_variable = st.selectbox("Variable", VARIABLES)
    st.caption("Public dashboard mode: data is read from committed snapshots.")

status = safe_remote_json("data/status.json")
progress = safe_remote_json("data/progress.json")
snapshot_summary = safe_remote_csv("data/update_manifest.csv")

top = st.columns(6)
top[0].metric("Last collection", status.get("collection_time_utc", "No run yet"))
top[1].metric("OK", status.get("ok_items", 0))
top[2].metric("Warnings", status.get("warning_items", 0))
top[3].metric("Errors", status.get("error_items", 0))
top[4].metric("Snapshot files", f"{len(snapshot_summary):,}")
top[5].metric(
    "Snapshot rows",
    f"{int(snapshot_summary['rows'].sum()) if not snapshot_summary.empty else 0:,}",
)

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

st.subheader("Recent Snapshot Collections")
if snapshot_summary.empty:
    st.info("No update snapshots are available yet.")
else:
    latest_collection = snapshot_summary["collection_time_utc"].max()
    latest_files = snapshot_summary[snapshot_summary["collection_time_utc"] == latest_collection]
    st.markdown(f"Latest collection: `{latest_collection}`")
    st.dataframe(
        latest_files[["country", "variable", "rows", "window_start_utc", "window_end_utc", "path"]]
        .sort_values(["country", "variable"]),
        use_container_width=True,
        hide_index=True,
    )
    st.divider()
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
    st.dataframe(coverage, use_container_width=True, hide_index=True)

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
history = safe_remote_csv("data/run_history.csv")
if history.empty:
    st.info("No run history yet.")
else:
    st.dataframe(history.tail(100).iloc[::-1], use_container_width=True, hide_index=True)
