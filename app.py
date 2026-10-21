import os
import time
import uuid
import pandas as pd
import streamlit as st
from datetime import datetime, timezone
from pathlib import Path

# Configure path imports
import sys
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import config
from src.database.sqlite import seed_database, get_connection
from src.pipeline_runner import PipelineRunner, AgentStatus, AgentStep

# Auto-seed SQLite master database if newly deployed or empty
if not config.DB_PATH.exists() or config.DB_PATH.stat().st_size == 0:
    seed_database()

# Set page layout and config
st.set_page_config(
    page_title="RetailPulse AI Operations Center",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Dark Glassmorphism NASA Theme)
st.markdown("""
<style>
    .stApp {
        background-color: #0d1117;
        color: #c9d1d9;
    }
    
    .main-title {
        font-family: 'Courier New', monospace;
        font-size: 2.5rem;
        font-weight: bold;
        color: #00E676;
        text-shadow: 0 0 10px rgba(0, 230, 118, 0.4);
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-family: 'Courier New', monospace;
        color: #8b949e;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    
    .badge {
        padding: 4px 10px;
        border-radius: 4px;
        font-size: 0.72rem;
        font-weight: bold;
        text-transform: uppercase;
        display: inline-block;
        font-family: monospace;
    }
    .badge-waiting { background: #21262d; border: 1px solid #30363d; color: #8b949e; }
    .badge-running { background: #0088cc; border: 1px solid #00B0FF; color: #ffffff; animation: pulse 1.5s infinite; }
    .badge-success { background: #1b4d3e; border: 1px solid #00E676; color: #00E676; }
    .badge-warning { background: #4d3e1b; border: 1px solid #FFD600; color: #FFD600; }
    .badge-failed { background: #4d1b24; border: 1px solid #FF1744; color: #FF1744; }
    .badge-skipped { background: #21262d; border: 1px solid #30363d; color: #8b949e; }
    .badge-approval { background: #3c1e5c; border: 1px solid #B388FF; color: #B388FF; animation: pulse 1.5s infinite; }
    
    @keyframes pulse {
        0% { opacity: 0.6; }
        50% { opacity: 1; }
        100% { opacity: 0.6; }
    }

    .shelf-container {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        background-color: #010409;
        border: 1px solid #21262d;
        padding: 10px;
        border-radius: 6px;
        margin-top: 10px;
    }
    .shelf-box {
        font-size: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)

# App state initialization
if "pipeline_stage" not in st.session_state:
    st.session_state.pipeline_stage = "idle"  # idle | pre_approval_running | waiting_approval | post_approval_running | completed
if "transaction_id" not in st.session_state:
    st.session_state.transaction_id = ""
if "agent_states" not in st.session_state:
    st.session_state.agent_states = {}
if "pre_approval_results" not in st.session_state:
    st.session_state.pre_approval_results = None
if "results" not in st.session_state:
    st.session_state.results = None
if "supplier_name" not in st.session_state:
    st.session_state.supplier_name = ""

agent_info = [
    ("Receiving", "Ingestion & Receiving Agent", "📥"),
    ("SKU", "SKU Standardization Agent", "🧠"),
    ("Audit", "Factual Contract Auditor", "🔎"),
    ("Decision", "AI Decision & Risk Engine", "⚖"),
    ("Inventory_Analysis", "Existing Inventory Analysis", "🔍"),
    ("Inventory_Optimization", "Inventory Optimization Agent", "🧠"),
    ("Warehouse_Allocation", "Warehouse Allocation Agent", "📦"),
    ("Inventory_Update", "Inventory Update Agent", "⚙️"),
    ("Floor", "Floor Operations Agent", "📦"),
    ("Procurement", "Procurement Agent", "🧾"),
    ("Warehouse_Health", "Warehouse Health Agent", "📊"),
    ("Executive_Reporting", "Executive Reporting Agent", "👔"),
    ("ERP_Export", "ERP Export Service", "🔌")
]

def get_badge_class(status):
    st_lower = status.lower()
    if st_lower == "waiting": return "badge-waiting"
    if st_lower == "running": return "badge-running"
    if st_lower == "success": return "badge-success"
    if st_lower == "complete": return "badge-success"
    if st_lower == "warning": return "badge-warning"
    if st_lower == "failed": return "badge-failed"
    if st_lower == "skipped": return "badge-skipped"
    if st_lower == "waiting_approval": return "badge-approval"
    return "badge-waiting"

def render_agent_card_ui(agent_id, display_name):
    """
    Renders a unified decentralized card widget for the agent containing header progress,
    current activity status, metrics badges, rolling mission logs, and the raw table grid.
    """
    state = st.session_state.agent_states[agent_id]
    status = state["status"]
    current_activity = state.get("current_activity", "")
    metrics = state.get("metrics", {})
    mission_log = state.get("mission_log", [])
    table_data = state.get("table_data", None)
    progress = state.get("progress", 0.0)
    
    badge_cls = get_badge_class(status)
    
    with st.container(border=True):
        # Header Row: Icon + Display Name + Status Badge + Progress %
        col_name, col_badge = st.columns([5, 2])
        with col_name:
            st.markdown(f"##### {display_name}")
        with col_badge:
            progress_text = f" | {int(progress * 100)}%" if status in ("RUNNING", "SUCCESS", "COMPLETE", "WARNING", "WAITING_APPROVAL") else ""
            st.markdown(f"<div style='text-align: right;'><span class='badge {badge_cls}'>{status}{progress_text}</span></div>", unsafe_allow_html=True)
            
        # Draw Progress bar and details if card is active or completed
        if status in ("RUNNING", "SUCCESS", "COMPLETE", "WARNING", "FAILED", "WAITING_APPROVAL"):
            # Header Progress Integration
            st.progress(progress)
            
            # Current Activity
            if current_activity:
                st.markdown(f"<div style='font-size:0.82rem; color:#f0f6fc; margin-bottom:5px;'>✨ <b>Current Activity:</b> <code>{current_activity}</code></div>", unsafe_allow_html=True)
                
            # Agent Metrics Grid
            if metrics:
                st.markdown("<div style='font-size:0.75rem; font-weight:bold; margin-top:10px; color:#8b949e;'>📊 AGENT METRICS</div>", unsafe_allow_html=True)
                cols = st.columns(len(metrics))
                for col, (m_key, m_val) in zip(cols, metrics.items()):
                    title_key = m_key.replace("_", " ").title()
                    if "confidence" in m_key.lower() and isinstance(m_val, (int, float)) and m_val <= 1.0:
                        val_str = f"{m_val * 100:.1f}%"
                    elif "valuation" in m_key.lower() or "value" in m_key.lower() or "delta" in m_key.lower():
                        val_str = f"${m_val:,.2f}"
                    else:
                        val_str = str(m_val)
                    col.metric(title_key, val_str)
                    
            # Mission Log (capped at last 20 entries)
            if mission_log:
                st.markdown("<div style='font-size:0.75rem; font-weight:bold; margin-top:10px; color:#8b949e;'>📂 MISSION LOG</div>", unsafe_allow_html=True)
                log_lines = []
                for entry in mission_log:
                    ts = entry.get("timestamp", "")
                    level = entry.get("level", "info")
                    msg = entry.get("message", "")
                    
                    if "T" in ts:
                        try:
                            ts_str = ts.split("T")[1][:8]
                        except:
                            ts_str = ts[:8]
                    else:
                        ts_str = ts[:8]
                        
                    indicator = "🔵"
                    if level == "success": indicator = "🟢"
                    elif level == "warning": indicator = "🟡"
                    elif level == "error": indicator = "🔴"
                    
                    log_lines.append(f"<div style='font-family:monospace; font-size:0.78rem; line-height:1.3;'>{indicator} <span style='color:#8b949e;'>{ts_str}</span> &nbsp; {msg}</div>")
                
                log_html = f"<div style='background-color:#010409; padding:8px; border-radius:4px; border:1px solid #21262d; max-height:150px; overflow-y:auto;'>{''.join(log_lines)}</div>"
                st.markdown(log_html, unsafe_allow_html=True)
                
            # Live data grid
            if table_data:
                st.markdown("<div style='font-size:0.75rem; font-weight:bold; margin-top:10px; color:#8b949e;'>📝 LIVE WORKPLACE DATA</div>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
        else:
            st.markdown("<span style='color:#8b949e; font-size:0.8rem; font-style:italic;'>Awaiting trigger...</span>", unsafe_allow_html=True)

def reset_pipeline():
    st.session_state.pipeline_stage = "idle"
    st.session_state.transaction_id = ""
    st.session_state.pre_approval_results = None
    st.session_state.results = None
    st.session_state.supplier_name = ""
    st.session_state.agent_states = {}
    for key, _, _ in agent_info:
        st.session_state.agent_states[key] = {
            "status": "WAITING",
            "current_activity": "Awaiting pipeline trigger...",
            "metrics": {},
            "mission_log": [],
            "table_data": None,
            "progress": 0.0
        }

# Initialize states if empty
if not st.session_state.agent_states:
    reset_pipeline()

# Sidebar - Settings & File Ingestion
with st.sidebar:
    st.image("https://img.icons8.com/nolan/96/brain.png", width=80)
    st.markdown("### Control Settings")
    
    if st.button("🔄 Reset SQLite Databases"):
        seed_database()
        st.success("SQLite schema seeded successfully!")
        
    st.markdown("---")
    st.markdown("### Step 1: Input Ingestion")
    
    mock_option = st.selectbox(
        "Select Demo Invoices:",
        ["[Mock] Vendor A (Excel - Overcharge/Expiry/Duplicates)", 
         "[Mock] Vendor B (CSV - Partial Accept)", 
         "[Mock] Vendor C (PDF - Clean Ingest)",
         "Upload Custom File..."]
    )
    
    uploaded_file = None
    custom_supplier = ""
    
    if mock_option == "Upload Custom File...":
        uploaded_file = st.file_uploader("Upload Supplier Invoice", type=["xlsx", "csv", "pdf"])
        custom_supplier = st.text_input("Enter Supplier Name:", placeholder="e.g. Jaxnation")
    
    st.markdown("---")
    st.markdown("### Step 2: Trigger Ingest")
    
    launch_btn = st.button("🚀 Launch AI Workforce", use_container_width=True)
    if st.button("🔄 Reset Pipeline / Clear UI", use_container_width=True):
        reset_pipeline()
        st.rerun()

# Title Panel
st.markdown("<h1 class='main-title'>RetailPulse AI Control Room</h1>", unsafe_allow_html=True)
st.markdown("<p class='subtitle'>🛰️ Enterprise Autonomous Warehouse Workforce — 12 Reasoning Agents & SQLite Source of Truth</p>", unsafe_allow_html=True)

# Layout Setup: Left Column (workforce execution 90% visual focus), Right Column (reports & review 10%)
col_pipeline, col_reports = st.columns([5, 3])

# Draw placeholders for the 13 agent cards in left column
with col_pipeline:
    st.subheader("🤖 Autonomous Agent Workforce")
    placeholders = {}
    for key, display_name, icon in agent_info:
        placeholders[key] = st.empty()

    # Initial state render
    for key, display_name, icon in agent_info:
        with placeholders[key].container():
            render_agent_card_ui(key, display_name)

# ----------------- PIPELINE START: PRE-APPROVAL STAGE -----------------
if launch_btn and st.session_state.pipeline_stage == "idle":
    reset_pipeline()
    st.session_state.pipeline_stage = "pre_approval_running"
    
    file_path_str = ""
    supplier_name = ""
    file_type = ""
    
    if mock_option.startswith("[Mock] Vendor A"):
        file_path_str = str(config.DATASETS_DIR / "vendor_a.xlsx")
        supplier_name = "Jaxnation"
        file_type = "xlsx"
    elif mock_option.startswith("[Mock] Vendor B"):
        file_path_str = str(config.DATASETS_DIR / "vendor_b.csv")
        supplier_name = "Jaxnation"
        file_type = "csv"
    elif mock_option.startswith("[Mock] Vendor C"):
        file_path_str = str(config.DATASETS_DIR / "vendor_c.pdf")
        supplier_name = "Feedmix"
        file_type = "pdf"
    else:
        if not uploaded_file:
            st.sidebar.error("Please upload custom invoice first.")
            st.session_state.pipeline_stage = "idle"
        elif not custom_supplier.strip():
            st.sidebar.error("Please specify supplier name.")
            st.session_state.pipeline_stage = "idle"
        else:
            file_type = uploaded_file.name.split(".")[-1].lower()
            temp_path = config.DATASETS_DIR / f"custom_upload_{uuid.uuid4().hex[:6]}.{file_type}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            file_path_str = str(temp_path)
            supplier_name = custom_supplier.strip()
            
    if st.session_state.pipeline_stage == "pre_approval_running":
        # Create a new unique transaction ID
        st.session_state.transaction_id = f"RP-2026-{uuid.uuid4().hex[:6].upper()}"
        tx_id = st.session_state.transaction_id
        st.session_state.supplier_name = supplier_name
        
        runner = PipelineRunner()
        pre_gen = runner.run_pre_approval(file_path_str, supplier_name, file_type, tx_id)
        
        # Stream intermediate logs
        pre_results = None
        try:
            while True:
                step = next(pre_gen)
                
                # Update session state for the specific agent card
                st.session_state.agent_states[step.agent] = {
                    "status": step.status,
                    "current_activity": step.current_activity,
                    "metrics": step.metrics,
                    "mission_log": [
                        {
                            "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
                            "level": e.level.value if hasattr(e.level, "value") else str(e.level),
                            "message": e.message
                        }
                        for e in step.mission_log
                    ],
                    "table_data": step.table_data,
                    "progress": step.progress
                }
                
                # Dynamic re-render inside execution loop
                with placeholders[step.agent].container():
                    render_agent_card_ui(step.agent, next(a[1] for a in agent_info if a[0] == step.agent))
        except StopIteration as e:
            pre_results = e.value
            
        st.session_state.pre_approval_results = pre_results
        st.session_state.pipeline_stage = "waiting_approval"
        st.rerun()

# ----------------- INTERACTIVE MANAGER REVIEW SCREEN & REPORT PANEL -----------------
with col_reports:
    st.subheader("📋 Operations Summary Panel")
    
    if st.session_state.pipeline_stage == "waiting_approval" and st.session_state.pre_approval_results:
        pre_res = st.session_state.pre_approval_results
        dec = pre_res["decision"]
        aud = pre_res["audit"]
        
        st.markdown("---")
        st.subheader("👔 Operations Manager Review Panel")
        st.write(f"**Transaction ID:** `{st.session_state.transaction_id}`")
        
        # Shipment decision summaries
        projections = []
        decision_rows = []
        
        conn = get_connection()
        cursor = conn.cursor()
        # Accepted items stock levels check
        for item in dec.items_accepted:
            cursor.execute("SELECT SUM(quantity) FROM inventory WHERE sku = ? AND status = 'ACTIVE'", (item.sku,))
            res_stock = cursor.fetchone()
            current_stock = res_stock[0] if (res_stock and res_stock[0]) else 0
            projections.append({
                "SKU": item.sku,
                "Incoming Qty": item.quantity,
                "Existing Stock": current_stock,
                "Projected Stock": current_stock + item.quantity
            })
            decision_rows.append({
                "SKU": item.sku,
                "Qty": item.quantity,
                "Action": "Accept",
                "Justification": "Pricing and freshness criteria matched contract standards."
            })
        # Rejected items
        for item in dec.items_rejected:
            cursor.execute("SELECT SUM(quantity) FROM inventory WHERE sku = ? AND status = 'ACTIVE'", (item.sku,))
            res_stock = cursor.fetchone()
            current_stock = res_stock[0] if (res_stock and res_stock[0]) else 0
            if not any(p["SKU"] == item.sku for p in projections):
                projections.append({
                    "SKU": item.sku,
                    "Incoming Qty": 0,
                    "Existing Stock": current_stock,
                    "Projected Stock": current_stock
                })
            decision_rows.append({
                "SKU": item.sku,
                "Qty": item.quantity,
                "Action": "Reject",
                "Justification": item.reason
            })
        conn.close()
        
        st.markdown("**1. Shipment Decision Summary**")
        st.dataframe(pd.DataFrame(decision_rows), use_container_width=True, hide_index=True)
        
        st.markdown("**2. Before / After Warehouse Projections**")
        st.dataframe(pd.DataFrame(projections), use_container_width=True, hide_index=True)
            
        st.markdown("---")
        btn_approve, btn_reject = st.columns(2)
        
        with btn_approve:
            if st.button("✅ Approve Shipment", use_container_width=True, type="primary"):
                st.session_state.pipeline_stage = "post_approval_running"
                st.rerun()
                
        with btn_reject:
            if st.button("❌ Reject Shipment", use_container_width=True):
                st.session_state.pipeline_stage = "post_approval_running"
                st.session_state.results = {"status": "REJECTED"}
                
                # Execute skipped downstream log updates
                runner = PipelineRunner()
                post_gen = runner.run_post_approval(st.session_state.transaction_id, st.session_state.supplier_name, pre_res, approved=False)
                for step in post_gen:
                    st.session_state.agent_states[step.agent] = {
                        "status": step.status,
                        "current_activity": step.current_activity,
                        "metrics": step.metrics,
                        "mission_log": [
                            {
                                "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
                                "level": e.level.value if hasattr(e.level, "value") else str(e.level),
                                "message": e.message
                            }
                            for e in step.mission_log
                        ],
                        "table_data": step.table_data,
                        "progress": step.progress
                    }
                st.session_state.pipeline_stage = "completed"
                st.rerun()

    # ----------------- POST-APPROVAL STAGE RUNNING -----------------
    if st.session_state.pipeline_stage == "post_approval_running" and st.session_state.pre_approval_results:
        tx_id = st.session_state.transaction_id
        supplier_name = st.session_state.supplier_name
        pre_res = st.session_state.pre_approval_results
        
        runner = PipelineRunner()
        post_gen = runner.run_post_approval(tx_id, supplier_name, pre_res, approved=True)
        
        post_results = None
        try:
            while True:
                step = next(post_gen)
                
                # Update session state for post-approval cards
                st.session_state.agent_states[step.agent] = {
                    "status": step.status,
                    "current_activity": step.current_activity,
                    "metrics": step.metrics,
                    "mission_log": [
                        {
                            "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
                            "level": e.level.value if hasattr(e.level, "value") else str(e.level),
                            "message": e.message
                        }
                        for e in step.mission_log
                    ],
                    "table_data": step.table_data,
                    "progress": step.progress
                }
                
                # Dynamic re-render inside loop
                with placeholders[step.agent].container():
                    render_agent_card_ui(step.agent, next(a[1] for a in agent_info if a[0] == step.agent))
        except StopIteration as e:
            post_results = e.value
            
        st.session_state.results = post_results
        st.session_state.pipeline_stage = "completed"
        st.rerun()

    # ----------------- FINAL TRANSACTIONS VIEW AND DOWNLOAD PANEL -----------------
    if st.session_state.pipeline_stage == "completed" and st.session_state.results:
        res = st.session_state.results
        
        st.markdown("---")
        st.subheader("🎯 Operations Center KPIs")
        
        if res.get("status") == "REJECTED":
            st.error(f"Intake Rejected by Manager. Shipment transaction is closed. ID: {st.session_state.transaction_id}")
        else:
            # Success KPIs
            st.metric("Total Billed Intake", f"${res['update']['current_inventory_value']:,.2f}")
            st.metric("Supplier Compliance Score", f"{res['executive']['supplier_score']:.1f} / 100.0")
            st.metric("Warehouse Capacity Utilization", f"{res['health']['utilization_pct']}%")
            st.metric("Dispatched Floor Workers", res["floor"]["task_count"])
                
            st.markdown("---")
            st.subheader("👔 Store Manager Executive Summary")
            st.info(res["executive"]["executive_summary"])
            
            # Shelf Box physics animation
            tasks_count = res["floor"]["task_count"]
            st.markdown(f"<div style='font-size:0.75rem; color:#8b949e;'>Dispatched Shelf Loading Progress:</div>", unsafe_allow_html=True)
            boxes_html = "".join([f"<div class='shelf-box'>📦</div>" for _ in range(min(tasks_count, 10))])
            st.markdown(f"<div class='shelf-container'>{boxes_html}</div>", unsafe_allow_html=True)

            st.markdown("---")
            st.subheader("📄 Generated Deliverable Documents")
            
            def get_download_btn(label: str, file_path_str: str, mime_type: str, btn_key: str):
                p = Path(file_path_str)
                if p.exists():
                    with open(p, "rb") as f:
                        btn_data = f.read()
                    st.download_button(
                        label=label,
                        data=btn_data,
                        file_name=p.name,
                        mime=mime_type,
                        key=btn_key,
                        use_container_width=True
                    )
                else:
                    st.markdown(f"<span style='color:#8b949e;'>⚠️ {p.name} (not generated)</span>", unsafe_allow_html=True)

            get_download_btn("📥 Export SQLite Inventory (Excel)", str(config.OUTPUTS_DIR / "master_inventory.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "dl_inv")
            get_download_btn("📄 Export Floor worker tasks (PDF)", str(config.OUTPUTS_DIR / "worker_tasks.pdf"), "application/pdf", "dl_tasks")
            get_download_btn("📄 Export Executive Summary report (PDF)", str(config.OUTPUTS_DIR / "manager_summary.pdf"), "application/pdf", "dl_mgr")
            get_download_btn("🔌 Export ERP Integration log (JSON)", str(config.OUTPUTS_DIR / "erp_export.json"), "application/json", "dl_erp")
            
            if res["procurement"].get("po_path"):
                get_download_btn("📝 Export Replenishment PO (DOCX)", res["procurement"]["po_path"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "dl_po")
            if res["procurement"].get("dispute_email_path"):
                get_download_btn("✉️ Export Pricing Dispute (TXT)", res["procurement"]["dispute_email_path"], "text/plain", "dl_dispute")
            if res["procurement"].get("notice_path"):
                get_download_btn("✉️ Export Rejection Notice (TXT)", res["procurement"]["notice_path"], "text/plain", "dl_notice")

        # SQLite Shipments History
        st.markdown("---")
        st.markdown("### 📊 Database Active Shipments Log")
        try:
            conn = get_connection()
            df_hist = pd.read_sql_query("SELECT id, supplier_name, date, status, risk_score FROM shipments ORDER BY rowid DESC LIMIT 5", conn)
            st.dataframe(df_hist, use_container_width=True)
            conn.close()
        except Exception as e:
            st.write("Could not retrieve shipments history: ", str(e))
