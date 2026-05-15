"""Streamlit dashboard for ContextOS. Launch via `contextos dashboard`."""
from __future__ import annotations

import polars as pl
import streamlit as st

from contextos import __version__
from contextos.dashboard import queries
from contextos.settings import get_settings

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

st.set_page_config(page_title="ContextOS", page_icon="🧊", layout="wide")

settings = get_settings()
db_path = settings.db_path

# Live refresh — every 2s, capped at 1800 ticks (1h) before the user must click.
if st_autorefresh is not None:
    st_autorefresh(interval=2000, limit=1800, key="contextos-tick")

st.title("ContextOS")
st.caption(f"v{__version__} · ledger: `{db_path}`")

if not db_path.exists():
    st.warning(
        "Ledger not found yet. Start the daemon and make at least one API call "
        "through the proxy, then this page will populate."
    )
    st.stop()

# ---------- KPI strip ----------
t = queries.totals(db_path)
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
    rows = queries.sessions(db_path, limit=50)
    if not rows:
        st.info("No sessions yet.")
        st.stop()
    df = pl.DataFrame(rows)
    st.dataframe(
        df.select([
            "session_id", "ide", "model", "started_at",
            "raw_tokens", "sent_tokens", "saved", "reduction_pct", "savings_usd",
        ]).to_pandas(),
        use_container_width=True,
        hide_index=True,
    )

with right:
    st.subheader("By IDE")
    by_ide = queries.by_dimension(db_path, "ide")
    if by_ide:
        st.bar_chart(
            pl.DataFrame(by_ide).to_pandas().set_index("key")[["saved"]],
            use_container_width=True,
        )

    st.subheader("By model")
    by_model = queries.by_dimension(db_path, "model")
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
mm = queries.memory_map(db_path, selected)
if not mm:
    st.info("This session has no turns recorded yet.")
else:
    mm_df = pl.DataFrame(mm)
    # Color-coded heat bar chart per turn. Stacked by heat.
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
