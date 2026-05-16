"""Streamlit dashboard for ContextOS. Launch via `contextos dashboard`."""
from __future__ import annotations

import polars as pl
import streamlit as st

from contextos import __version__
from contextos.dashboard import queries
from contextos.dashboard.queries import DaemonUnreachable
from contextos.settings import get_settings

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

st.set_page_config(page_title="ContextOS", page_icon="🧊", layout="wide")

settings = get_settings()
base_url = f"http://{settings.proxy_host}:{settings.proxy_port}"

if st_autorefresh is not None:
    st_autorefresh(interval=2000, limit=1800, key="contextos-tick")

st.title("ContextOS")
st.caption(f"v{__version__} · daemon: `{base_url}`")

try:
    t = queries.totals(base_url)
except DaemonUnreachable as e:
    st.error(
        f"Cannot reach the daemon at {base_url}.\n\n"
        "Start it with `contextos start` in another terminal, then refresh."
    )
    st.caption(f"Details: {e}")
    st.stop()

# ---------- KPI strip ----------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Sessions", f"{t.sessions:,}")
k2.metric("Raw tokens in", f"{t.raw_tokens:,}")
k3.metric("Sent tokens", f"{t.sent_tokens:,}")
k4.metric("Saved", f"{t.saved_tokens:,}", f"{t.reduction_pct:.1f}%")
k5.metric("Savings (USD)", f"${t.savings_usd:,.2f}")

st.divider()

# ---------- Sessions table ----------
left, right = st.columns([3, 2])

with left:
    st.subheader("Recent sessions")
    rows = queries.sessions(base_url, limit=50)
    if not rows:
        st.info("No sessions yet. Make a call from your IDE — this page auto-refreshes.")
        st.stop()
    df = pl.DataFrame(rows)
    st.dataframe(
        df.select([
            "session_id", "ide", "model", "started_at",
            "raw_tokens", "sent_tokens", "saved", "reduction_pct", "savings_usd",
        ]).to_pandas(),
        use_container_width=True, hide_index=True,
    )

with right:
    st.subheader("By IDE")
    by_ide = queries.by_dimension(base_url, "ide")
    if by_ide:
        st.bar_chart(
            pl.DataFrame(by_ide).to_pandas().set_index("key")[["saved"]],
            use_container_width=True,
        )

    st.subheader("By model")
    by_model = queries.by_dimension(base_url, "model")
    if by_model:
        st.bar_chart(
            pl.DataFrame(by_model).to_pandas().set_index("key")[["savings_usd"]],
            use_container_width=True,
        )

st.divider()

# ---------- Per-session memory map ----------
st.subheader("Memory map")
session_ids = [r["session_id"] for r in rows]
selected = st.selectbox("Session", session_ids, index=0)
mm = queries.memory_map(base_url, selected)
if not mm:
    st.info("This session has no turns recorded yet.")
else:
    mm_df = pl.DataFrame(mm)
    heat_order = ["HOT", "WARM", "COLD", "DEAD"]
    pivot = (
        mm_df.with_columns(pl.lit(1).alias("count"))
             .pivot(values="count", index="turn_index", on="heat", aggregate_function="sum")
             .fill_null(0)
    )
    cols_present = [h for h in heat_order if h in pivot.columns]
    st.bar_chart(
        pivot.to_pandas().set_index("turn_index")[cols_present],
        use_container_width=True,
    )
    st.caption("HOT = last 5 turns · WARM = within 15 · COLD = older. "
               "Heat is derived from turn position; live classification matches.")
