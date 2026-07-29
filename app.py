import os
import time
import uuid
import pandas as pd
import streamlit as st
from datetime import datetime, date, timedelta
from pathlib import Path

# Configure path imports
import sys
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import config
from src.database.sqlite import seed_database, get_connection
from src.orchestrator import IntakeOrchestrator
from src.tools.excel_tools import read_excel, read_csv
from src.tools.pdf_tools import read_pdf

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
    /* Dark theme overrides */
    .stApp {
        background-color: #0d1117;
        color: #c9d1d9;
    }
    
    /* Neon titles */
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
    
    /* Control room status cards */
    .agent-card {
        background: rgba(22, 27, 34, 0.7);
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 12px;
        transition: all 0.3s ease;
    }
    .agent-card:hover {
        border-color: #00B0FF;
        box-shadow: 0 0 12px rgba(0, 176, 255, 0.2);
    }
    
    /* Event logs terminal styling */
    .terminal-box {
        background-color: #010409;
        border: 1px solid #21262d;
        border-radius: 6px;
        font-family: 'Courier New', Courier, monospace;
        color: #39FF14;
        padding: 15px;
        height: 380px;
        overflow-y: auto;
        font-size: 0.85rem;
        white-space: pre-wrap;
    }
    
    /* Indicator badges */
    .badge {
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: bold;
        text-transform: uppercase;
        display: inline-block;
    }
    .badge-pending { background: #30363d; color: #8b949e; }
    .badge-active { background: #00B0FF; color: #ffffff; animation: pulse 1.5s infinite; }
    .badge-complete { background: #00E676; color: #0d1117; }
    .badge-violation { background: #FFD600; color: #0d1117; }
    .badge-rejected { background: #FF1744; color: #ffffff; }
    
    @keyframes pulse {
        0% { opacity: 0.6; }
        50% { opacity: 1; }
        100% { opacity: 0.6; }
    }
    
    /* Box packaging visual styles */
    .shelf-container {
        display: flex;
        gap: 8px;
        margin: 10px 0;
        background: #161b22;
        padding: 10px;
        border-radius: 6px;
        border: 1px dashed #30363d;
    }
    .shelf-box {
        width: 32px;
        height: 32px;
        background: #8b949e;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1rem;
        animation: dropIn 0.5s ease forwards;
    }
    @keyframes dropIn {
        from { transform: translateY(-20px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
    }
</style>
""", unsafe_allow_html=True)

# App state initialization
if "pipeline_running" not in st.session_state:
    st.session_state.pipeline_running = False
if "pipeline_completed" not in st.session_state:
    st.session_state.pipeline_completed = False
if "agent_states" not in st.session_state:
    st.session_state.agent_states = {
        "Receiving": {"status": "pending", "time": None, "summary": "Ready in queue."},
        "SKU": {"status": "pending", "time": None, "summary": "Ready in queue."},
        "Audit": {"status": "pending", "time": None, "summary": "Ready in queue."},
        "Decision": {"status": "pending", "time": None, "summary": "Ready in queue."},
        "Floor": {"status": "pending", "time": None, "summary": "Ready in queue."},
        "Procurement": {"status": "pending", "time": None, "summary": "Ready in queue."},
        "Manager": {"status": "pending", "time": None, "summary": "Ready in queue."}
    }
if "event_logs" not in st.session_state:
    st.session_state.event_logs = []
if "results" not in st.session_state:
    st.session_state.results = None

def append_log(agent_name: str, message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_line = f"[{timestamp}] [{agent_name.upper()}] {message}"
    st.session_state.event_logs.append(log_line)

def reset_pipeline():
    st.session_state.pipeline_running = False
    st.session_state.pipeline_completed = False
    st.session_state.event_logs = []
    st.session_state.results = None
    for k in st.session_state.agent_states:
        st.session_state.agent_states[k] = {
            "status": "pending",
            "time": None,
            "summary": "Ready in queue."
        }

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
    st.markdown("### Step 2: Trigger Workforce")
    
    launch_btn = st.button("🚀 Launch AI Workforce", use_container_width=True)
    if st.button("🔄 Reset Pipeline / Clear UI", use_container_width=True):
        reset_pipeline()
        st.rerun()

# Title Panel
st.markdown("<h1 class='main-title'>RetailPulse Operations Center</h1>", unsafe_allow_html=True)
st.markdown("<p class='subtitle'>📡 NASA-Style Mission Control for 7 Cooperative AI Ingestion Agents</p>", unsafe_allow_html=True)

# Layout Setup
col_pipeline, col_terminal = st.columns([5, 3])

agent_info = [
    ("Receiving", "📥 Ingestion & Receiving Agent", "📥"),
    ("SKU", "🧠 SKU Standardization Intelligence", "🧠"),
    ("Audit", "🔎 Factual Contract Auditor (Python Facts)", "🔎"),
    ("Decision", "⚖ AI Decision & Risk Engine", "⚖"),
    ("Floor", "📦 Floor Operations & Stocking Router", "📦"),
    ("Procurement", "🧾 Procurement Filing & Disputes Clerk", "🧾"),
    ("Manager", "👔 Store Manager Summary & PDF Compiler", "👔")
]

def render_card_html(display_name, status, summary, elapsed=None):
    border_color = "#30363d"
    status_badge = ""
    
    if status == "pending":
        status_badge = f"<span class='badge badge-pending'>Pending</span>"
    elif status == "active":
        border_color = "#00B0FF"
        status_badge = f"<span class='badge badge-active'>Active</span>"
    elif status == "completed":
        border_color = "#00E676"
        time_info = f" in {elapsed:.2f}s" if elapsed else ""
        status_badge = f"<span class='badge badge-complete'>Complete{time_info}</span>"
    elif status == "rejected":
        border_color = "#FF1744"
        status_badge = f"<span class='badge badge-rejected'>Rejected</span>"
        
    return f"""
    <div class="agent-card" style="border-color: {border_color}">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-weight:bold; font-size:1rem; color: #f0f6fc;">{display_name}</span>
            {status_badge}
        </div>
        <div style="font-size:0.85rem; color:#8b949e; margin-top:5px;">
            {summary}
        </div>
    </div>
    """

# Pipeline slots in main column
with col_pipeline:
    st.subheader("🤖 Live Multi-Agent Pipeline Status")
    placeholders = {}
    for key, display_name, icon in agent_info:
        placeholders[key] = st.empty()

    # Pre-populate slots with current session state
    for key, display_name, icon in agent_info:
        state = st.session_state.agent_states[key]
        placeholders[key].markdown(render_card_html(display_name, state["status"], state["summary"], state["time"]), unsafe_allow_html=True)
        
        # If floor tasks completed, render physical box animations
        if key == "Floor" and state["status"] == "completed" and st.session_state.results:
            tasks_count = st.session_state.results["floor"]["task_count"]
            st.markdown(f"<div style='font-size:0.75rem; color:#8b949e;'>Physical stock routing active:</div>", unsafe_allow_html=True)
            boxes_html = "".join([f"<div class='shelf-box'>📦</div>" for _ in range(min(tasks_count, 10))])
            st.markdown(f"<div class='shelf-container'>{boxes_html}</div>", unsafe_allow_html=True)

# Terminal Log Feed slot in right column
with col_terminal:
    st.subheader("💻 Control Room Log Feed")
    log_placeholder = st.empty()
    
    def update_logs_ui():
        logs_content = "\n".join(st.session_state.event_logs) if st.session_state.event_logs else "SYSTEM STATE: Idle. Awaiting launch signal..."
        log_placeholder.markdown(f"<div class='terminal-box'>{logs_content}</div>", unsafe_allow_html=True)
        
    update_logs_ui()
    
    if st.button("Clear Logs", use_container_width=True):
        st.session_state.event_logs = []
        update_logs_ui()

# ----------------- EXECUTE SEQUENTIAL PIPELINE ON CLICK -----------------
if launch_btn and not st.session_state.pipeline_running:
    reset_pipeline()
    st.session_state.pipeline_running = True
    
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
            st.session_state.pipeline_running = False
        elif not custom_supplier.strip():
            st.sidebar.error("Please specify supplier name.")
            st.session_state.pipeline_running = False
        else:
            file_type = uploaded_file.name.split(".")[-1].lower()
            temp_path = config.DATASETS_DIR / f"custom_upload_{uuid.uuid4().hex[:6]}.{file_type}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            file_path_str = str(temp_path)
            supplier_name = custom_supplier.strip()
            
    if st.session_state.pipeline_running:
        append_log("System", f"Workforce session triggered for Supplier: {supplier_name} ({file_type.upper()})")
        update_logs_ui()
        orch = IntakeOrchestrator()
        
        # --- 1. RECEIVING ---
        st.session_state.agent_states["Receiving"]["status"] = "active"
        st.session_state.agent_states["Receiving"]["summary"] = "Extracting details from invoice..."
        placeholders["Receiving"].markdown(render_card_html("📥 Ingestion & Receiving Agent", "active", "Extracting details from invoice..."), unsafe_allow_html=True)
        append_log("Receiving", f"Started processing file: {Path(file_path_str).name}")
        update_logs_ui()
        time.sleep(0.5)
        
        start = time.time()
        try:
            receiving_out = orch.receiving.execute(file_path_str, supplier_name, file_type)
            elapsed = time.time() - start
            summary = f"Extracted {len(receiving_out.items)} items from supplier {receiving_out.supplier}."
            st.session_state.agent_states["Receiving"]["status"] = "completed"
            st.session_state.agent_states["Receiving"]["time"] = elapsed
            st.session_state.agent_states["Receiving"]["summary"] = summary
            placeholders["Receiving"].markdown(render_card_html("📥 Ingestion & Receiving Agent", "completed", summary, elapsed), unsafe_allow_html=True)
            append_log("Receiving", f"Completed. Found {len(receiving_out.items)} line items.")
            update_logs_ui()
        except Exception as e:
            append_log("Receiving", f"FAILED: {str(e)}")
            st.session_state.pipeline_running = False
            update_logs_ui()

        # --- 2. SKU ---
        if st.session_state.pipeline_running:
            st.session_state.agent_states["SKU"]["status"] = "active"
            st.session_state.agent_states["SKU"]["summary"] = "Standardizing product codes via semantic catalog matches..."
            placeholders["SKU"].markdown(render_card_html("🧠 SKU Standardization Intelligence", "active", "Standardizing product codes..."), unsafe_allow_html=True)
            append_log("SKU", "Matching invoice line items with products database...")
            update_logs_ui()
            time.sleep(0.5)
            
            start = time.time()
            try:
                sku_out = orch.sku.execute(receiving_out)
                elapsed = time.time() - start
                clean_matches = sum(1 for i in sku_out.items if i.matched_product_id not in ("UNKNOWN", "REVIEW"))
                review_flags = sum(1 for i in sku_out.items if i.matched_product_id == "REVIEW")
                unknown_flags = sum(1 for i in sku_out.items if i.matched_product_id == "UNKNOWN")
                
                summary = f"Mapped catalog: {clean_matches} verified, {review_flags} needs review, {unknown_flags} completely unknown."
                st.session_state.agent_states["SKU"]["status"] = "completed"
                st.session_state.agent_states["SKU"]["time"] = elapsed
                st.session_state.agent_states["SKU"]["summary"] = summary
                placeholders["SKU"].markdown(render_card_html("🧠 SKU Standardization Intelligence", "completed", summary, elapsed), unsafe_allow_html=True)
                append_log("SKU", f"Reconciliation done. Mapped: {clean_matches} OK, {review_flags} REVIEW, {unknown_flags} UNKNOWN.")
                update_logs_ui()
            except Exception as e:
                append_log("SKU", f"FAILED: {str(e)}")
                st.session_state.pipeline_running = False
                update_logs_ui()

        # --- 3. AUDIT ---
        if st.session_state.pipeline_running:
            st.session_state.agent_states["Audit"]["status"] = "active"
            st.session_state.agent_states["Audit"]["summary"] = "Verifying prices, checking freshness expirations, and duplicates..."
            placeholders["Audit"].markdown(render_card_html("🔎 Factual Contract Auditor (Python Facts)", "active", "Verifying prices, expirations and duplicates..."), unsafe_allow_html=True)
            append_log("Audit", "Compiling python-based contract baseline pricing violations...")
            update_logs_ui()
            time.sleep(0.5)
            
            start = time.time()
            try:
                audit_out = orch.audit.execute(sku_out)
                elapsed = time.time() - start
                violations_count = len(audit_out.violations)
                
                summary = "No baseline violations found." if violations_count == 0 else f"Detected {violations_count} contract/expiry discrepancies."
                st.session_state.agent_states["Audit"]["status"] = "completed"
                st.session_state.agent_states["Audit"]["time"] = elapsed
                st.session_state.agent_states["Audit"]["summary"] = summary
                placeholders["Audit"].markdown(render_card_html("🔎 Factual Contract Auditor (Python Facts)", "completed", summary, elapsed), unsafe_allow_html=True)
                append_log("Audit", f"Audit complete. Logged {violations_count} infraction flags.")
                update_logs_ui()
            except Exception as e:
                append_log("Audit", f"FAILED: {str(e)}")
                st.session_state.pipeline_running = False
                update_logs_ui()

        # --- 4. DECISION ---
        if st.session_state.pipeline_running:
            st.session_state.agent_states["Decision"]["status"] = "active"
            st.session_state.agent_states["Decision"]["summary"] = "Determining shipment accept/reject disposition..."
            placeholders["Decision"].markdown(render_card_html("⚖ AI Decision & Risk Engine", "active", "Determining shipment disposition..."), unsafe_allow_html=True)
            append_log("Decision", "Reasoning shipment accept/reject and calculating risk score...")
            update_logs_ui()
            time.sleep(0.5)
            
            start = time.time()
            try:
                decision_out = orch.decision.execute(audit_out, sku_out)
                elapsed = time.time() - start
                
                summary = f"Disposition: {decision_out.disposition}. Risk Rating: {decision_out.risk_score}/10."
                st.session_state.agent_states["Decision"]["status"] = "completed"
                st.session_state.agent_states["Decision"]["time"] = elapsed
                st.session_state.agent_states["Decision"]["summary"] = summary
                placeholders["Decision"].markdown(render_card_html("⚖ AI Decision & Risk Engine", "completed", summary, elapsed), unsafe_allow_html=True)
                append_log("Decision", f"Shipment disposition decided: {decision_out.disposition} (Risk Score: {decision_out.risk_score}/10.0)")
                update_logs_ui()
            except Exception as e:
                append_log("Decision", f"FAILED: {str(e)}")
                st.session_state.pipeline_running = False
                update_logs_ui()

        # --- 5. FLOOR ---
        if st.session_state.pipeline_running:
            st.session_state.agent_states["Floor"]["status"] = "active"
            st.session_state.agent_states["Floor"]["summary"] = "Calculating placement aisles and drafting instructions..."
            placeholders["Floor"].markdown(render_card_html("📦 Floor Operations & Stocking Router", "active", "Calculating placement aisles..."), unsafe_allow_html=True)
            append_log("Floor", "Mapping inventory items into storage locations...")
            update_logs_ui()
            time.sleep(0.5)
            
            start = time.time()
            try:
                floor_out = orch.floor.execute(decision_out)
                elapsed = time.time() - start
                
                summary = f"Created {floor_out.task_count} layouts (saved to outputs/worker_tasks.pdf)."
                st.session_state.agent_states["Floor"]["status"] = "completed"
                st.session_state.agent_states["Floor"]["time"] = elapsed
                st.session_state.agent_states["Floor"]["summary"] = summary
                placeholders["Floor"].markdown(render_card_html("📦 Floor Operations & Stocking Router", "completed", summary, elapsed), unsafe_allow_html=True)
                append_log("Floor", f"Worker stocking layouts compiled. Placed items count: {floor_out.task_count}")
                update_logs_ui()
            except Exception as e:
                append_log("Floor", f"FAILED: {str(e)}")
                st.session_state.pipeline_running = False
                update_logs_ui()

        # --- 6. PROCUREMENT ---
        if st.session_state.pipeline_running:
            st.session_state.agent_states["Procurement"]["status"] = "active"
            st.session_state.agent_states["Procurement"]["summary"] = "Generating PO files and supplier notice mail drafts..."
            placeholders["Procurement"].markdown(render_card_html("🧾 Procurement Filing & Disputes Clerk", "active", "Generating PO and disputes notices..."), unsafe_allow_html=True)
            append_log("Procurement", "Drafting purchase orders, notices and discrepancy disputes...")
            update_logs_ui()
            time.sleep(0.5)
            
            start = time.time()
            try:
                procurement_out = orch.procurement.execute(decision_out, audit_out)
                elapsed = time.time() - start
                
                docs = []
                if procurement_out.po_path: docs.append("PO Word file")
                if procurement_out.dispute_email_path: docs.append("Dispute email")
                if procurement_out.notice_path: docs.append("Rejection notice")
                
                summary = f"Filing complete. Created: {', '.join(docs)}."
                st.session_state.agent_states["Procurement"]["status"] = "completed"
                st.session_state.agent_states["Procurement"]["time"] = elapsed
                st.session_state.agent_states["Procurement"]["summary"] = summary
                placeholders["Procurement"].markdown(render_card_html("🧾 Procurement Filing & Disputes Clerk", "completed", summary, elapsed), unsafe_allow_html=True)
                append_log("Procurement", f"Procurement sheets drafted: {', '.join(docs)}")
                update_logs_ui()
            except Exception as e:
                append_log("Procurement", f"FAILED: {str(e)}")
                st.session_state.pipeline_running = False
                update_logs_ui()

        # --- 7. MANAGER ---
        if st.session_state.pipeline_running:
            st.session_state.agent_states["Manager"]["status"] = "active"
            st.session_state.agent_states["Manager"]["summary"] = "Compiling dashboard executive summary and manager PDF..."
            placeholders["Manager"].markdown(render_card_html("👔 Store Manager Summary & PDF Compiler", "active", "Compiling manager report..."), unsafe_allow_html=True)
            append_log("Manager", "Synthesizing executive summary metrics...")
            update_logs_ui()
            time.sleep(0.5)
            
            start = time.time()
            try:
                manager_out = orch.manager.execute(
                    receiving_out, sku_out, audit_out, decision_out, floor_out, procurement_out
                )
                elapsed = time.time() - start
                
                # SQLite Log
                shipment_id = f"SHIP_{uuid.uuid4().hex[:8].upper()}"
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO shipments (id, supplier_name, date, status, decision_reason, total_amount, risk_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (shipment_id, supplier_name, datetime.now().strftime("%Y-%m-%d"), decision_out.disposition, decision_out.reasoning, audit_out.total_billed, decision_out.risk_score)
                )
                
                # Excel Inventory Log
                from src.tools.excel_tools import write_excel
                excel_path = str(config.OUTPUTS_DIR / "master_inventory.xlsx")
                inventory_data = []
                for item in decision_out.items_accepted:
                    inventory_data.append({
                        "SKU": item.sku,
                        "Quantity": item.quantity,
                        "Price": item.price,
                        "Supplier": supplier_name,
                        "Date": datetime.now().strftime("%Y-%m-%d")
                    })
                if not inventory_data:
                    inventory_data.append({"SKU": "None", "Quantity": 0, "Price": 0.0, "Supplier": supplier_name, "Date": datetime.now().strftime("%Y-%m-%d")})
                write_excel(inventory_data, excel_path)
                
                conn.commit()
                conn.close()
                
                summary = f"Summary compiled. Saved to manager_summary.pdf (Supplier score: {manager_out.supplier_score})."
                st.session_state.agent_states["Manager"]["status"] = "completed"
                st.session_state.agent_states["Manager"]["time"] = elapsed
                st.session_state.agent_states["Manager"]["summary"] = summary
                placeholders["Manager"].markdown(render_card_html("👔 Store Manager Summary & PDF Compiler", "completed", summary, elapsed), unsafe_allow_html=True)
                append_log("Manager", f"Workforce intake pipeline completely successfully finished. Shipment ID: {shipment_id}")
                update_logs_ui()
                
                # Save final session results
                st.session_state.results = {
                    "shipment_id": shipment_id,
                    "supplier_name": supplier_name,
                    "receiving": receiving_out.dict(),
                    "sku": sku_out.dict(),
                    "audit": audit_out.dict(),
                    "decision": decision_out.dict(),
                    "floor": floor_out.dict(),
                    "procurement": procurement_out.dict(),
                    "manager": manager_out.dict()
                }
                st.session_state.pipeline_completed = True
                st.session_state.pipeline_running = False
                st.rerun()
                
            except Exception as e:
                append_log("Manager", f"FAILED: {str(e)}")
                st.session_state.pipeline_running = False
                update_logs_ui()

# ----------------- DISPLAY METRICS & DOWNLOADS -----------------
if st.session_state.pipeline_completed and st.session_state.results:
    res = st.session_state.results
    
    st.markdown("---")
    st.subheader("🎯 Operations Center Dashboard Metrics")
    
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    with kpi1:
        st.metric("Total Bill Amount", f"${res['audit']['total_billed']:.2f}")
    with kpi2:
        st.metric("Supplier Score Card", f"{res['manager']['supplier_score']:.1f} / 100")
    with kpi3:
        st.metric("Risk Assessment", f"{res['decision']['risk_score']:.1f} / 10.0")
    with kpi4:
        st.metric("Discrepancies Found", len(res['audit']['violations']))
    with kpi5:
        st.metric("Final Disposition", res['decision']['disposition'])

    st.markdown("---")
    
    col_reasoning, col_outputs = st.columns([5, 3])
    
    with col_reasoning:
        st.subheader("⚖️ AI Decision Reasoning & Details")
        disp = res['decision']['disposition']
        
        st.markdown(f"**Justification Statement:**")
        if disp == "ACCEPT":
            st.success(res['decision']['reasoning'])
        elif disp in ("PARTIAL_ACCEPT", "HUMAN_REVIEW"):
            st.warning(res['decision']['reasoning'])
        else:
            st.error(res['decision']['reasoning'])
            
        st.markdown("### 💬 Real-Time Agent Thoughts Log")
        with st.expander("📥 Receiving Agent Details"):
            st.write("Parsed supplier items:")
            st.json(res['receiving']['items'])
        with st.expander("🧠 SKU Standardizer Details"):
            st.write("Fuzzy mapped SKU pairings:")
            st.json(res['sku']['items'])
        with st.expander("🔎 Audit Violations Log"):
            st.write("Contract audit findings details:")
            st.json(res['audit']['violations'])
            
    with col_outputs:
        st.subheader("📄 Generated Output Documents")
        
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

        get_download_btn("📥 Download Inventory Excel Workbook", str(config.OUTPUTS_DIR / "master_inventory.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "dl_inv")
        get_download_btn("📄 Download Worker Instructions (PDF)", str(config.OUTPUTS_DIR / "worker_tasks.pdf"), "application/pdf", "dl_tasks")
        get_download_btn("📄 Download Store Manager Summary (PDF)", str(config.OUTPUTS_DIR / "manager_summary.pdf"), "application/pdf", "dl_mgr")
        
        if res["procurement"].get("po_path"):
            get_download_btn("📝 Download Purchase Order (DOCX)", res["procurement"]["po_path"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "dl_po")
        if res["procurement"].get("dispute_email_path"):
            get_download_btn("✉️ Download Dispute Email Draft (TXT)", res["procurement"]["dispute_email_path"], "text/plain", "dl_dispute")
        if res["procurement"].get("notice_path"):
            get_download_btn("✉️ Download Rejection Notice Draft (TXT)", res["procurement"]["notice_path"], "text/plain", "dl_notice")
            
    # Render Database Shipments History Log at full page width
    st.markdown("---")
    st.markdown("### 📊 Database Shipments History Log")
    try:
        conn = get_connection()
        df_hist = pd.read_sql_query("SELECT id, supplier_name, date, status, risk_score FROM shipments ORDER BY rowid DESC LIMIT 5", conn)
        st.dataframe(df_hist, use_container_width=True)
        conn.close()
    except Exception as e:
        st.write("Could not retrieve shipments history: ", str(e))
