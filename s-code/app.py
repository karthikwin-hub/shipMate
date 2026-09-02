import streamlit as st
import os
import json
import datetime
from git_manager import GitManager
from runner import CommandRunner
from checklist_engine import ChecklistEngine
from remote_deployer import RemoteDeployer
from notifications import NotificationManager

st.set_page_config(page_title="ShipMate | Pipeline Dashboard", page_icon="🚢", layout="wide")

# Custom SVG Logo & Header
st.markdown("""
<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px;">
    <svg width="50" height="50" viewBox="0 0 80 80">
        <polygon points="40,4 72,22 72,58 40,76 8,58 8,22" fill="#3B82F6"/>
        <path d="M22,35 L40,52 L58,35 L50,35 L40,44 L30,35 Z" fill="#FFFFFF"/>
        <circle cx="40" cy="58" r="4.5" fill="#10B981"/>
    </svg>
    <div>
        <h1 style="margin:0; font-size: 26px; font-weight: 800;">Ship<span style="color:#3B82F6;">Mate</span></h1>
        <p style="margin:0; font-size: 12px; color:#64748B; font-weight:600; letter-spacing:1px;">CROSS-ENVIRONMENT QA & DEPLOYMENT GATEWAY</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Project Selector
repo_dir = st.text_input("📁 Target Repository Path", value=os.getcwd())

if not os.path.exists(repo_dir) or not os.path.exists(os.path.join(repo_dir, ".git")):
    st.error("Please provide a valid local Git repository folder path.")
    st.stop()

# Initialize Helpers
git = GitManager(repo_dir)
runner = CommandRunner(repo_dir)
checklist = ChecklistEngine(repo_dir)
notifier = NotificationManager()

identity = git.get_git_identity()

# Top Header Card
with st.container():
    c1, c2, c3 = st.columns([2, 1, 1])
    c1.markdown(f"**👤 Git User:** `{identity['name']}` `<{identity['email']}>` | **🌿 Branch:** `{identity['branch']}`")
    c2.markdown(f"**📦 Stack:** `{runner.detect_stack()}`")
    c3.markdown(f"**🔗 Remote:** `{identity['remote'][:30]}...`")

# Override Identity Expander
with st.expander("⚙️ Git Identity & PR Inspection"):
    st.write(f"**GitHub PR:** {git.get_pr_status()}")
    new_name = st.text_input("Override Git Name", value=identity['name'])
    new_email = st.text_input("Override Git Email", value=identity['email'])
    if st.button("Save Local Identity Override"):
        ok, msg = git.set_local_identity(new_name, new_email)
        if ok: st.success(msg)
        else: st.error(msg)

st.divider()

# 3-Stage Pipeline Layout
tabs = st.tabs(["🚀 Stage 1: Dev (Windows)", "🧪 Stage 2: QA (Linux)", "🚢 Stage 3: Prod (Oracle VM)", "📜 Audit History"])

# --- STAGE 1: DEV ---
with tabs[0]:
    st.subheader("Stage 1: Shift-Left Validations & PR Creation")
    commit_msg = st.text_input("Commit Message", placeholder="feat: add new feature")
    if st.button("Run Pre-Flight & Ship"):
        if not commit_msg:
            st.error("Please provide a commit message.")
        else:
            with st.spinner("Checking secrets & running tests..."):
                leaks = git.scan_for_secrets()
                if leaks:
                    st.error(f"🚨 Blocked: Potential secrets found in diff: {', '.join(leaks)}")
                else:
                    test_cmd = runner.get_test_command()
                    st.code(f"Running: {test_cmd}")
                    try:
                        for line in runner.run_stream(test_cmd):
                            st.text(line)
                        for line in runner.run_stream(f'git add -A && git commit -m "{commit_msg}" && git push origin {identity["branch"]}'):
                            st.text(line)
                        st.success("✅ Changes committed and pushed! Open your PR via GitHub.")
                    except Exception as e:
                        st.error(f"Execution failed: {e}")

# --- STAGE 2: QA ---
with tabs[1]:
    st.subheader("Stage 2: Verification, App Launch & Checklist")
    chk_data = checklist.load_checklist()
    
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📥 Pull Branch & Install Dependencies"):
            inst_cmd = runner.get_install_command()
            st.code(f"Running: git pull && {inst_cmd}")
            for line in runner.run_stream(f"git pull && {inst_cmd}"):
                st.text(line)
            st.success("Dependencies installed.")

    with col_b:
        if st.button("🧪 Run Full Automated Test Suite"):
            for line in runner.run_stream(runner.get_test_command()):
                st.text(line)
            st.success("All automated tests passed!")

    st.markdown("#### Dynamic QA Checklist")
    qa_checks = chk_data.get("qa_checklist", [])
    qa_all_passed = True
    for item in qa_checks:
        c_checked = st.checkbox(item['label'], key=item['id'])
        if not c_checked: qa_all_passed = False

    st.button("✅ Approve & Merge to Main", disabled=not qa_all_passed)

# --- STAGE 3: PROD ---
with tabs[2]:
    st.subheader("Stage 3: Production Deployment to Oracle Cloud VM")
    ssh_host = st.text_input("Oracle VM Host / IP", placeholder="129.153.x.x")
    ssh_user = st.text_input("SSH User", value="ubuntu")
    ssh_key = st.text_input("SSH Key Path", value="~/.ssh/id_rsa")
    remote_path = st.text_input("Remote App Directory", value="/var/www/myapp")
    health_url = st.text_input("Health Check URL", value="http://my-domain.com/health")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🚢 Deploy to Live with Auto-Rollback"):
            deployer = RemoteDeployer(ssh_host, ssh_user, ssh_key, remote_path, health_url)
            with st.spinner("Backing up DB, pulling main, and restarting services..."):
                ok, msg = deployer.deploy_with_auto_rollback()
                if ok:
                    st.success(msg)
                    notifier.send_webhook("Production Deployment Success", f"App live at {health_url}", True)
                else:
                    st.error(msg)
                    notifier.send_webhook("Production Deployment FAILED", msg, False)

    with c2:
        if st.button("🚨 Emergency Rollback"):
            deployer = RemoteDeployer(ssh_host, ssh_user, ssh_key, remote_path, health_url)
            deployer.execute_ssh_cmd("git checkout $(cat .last_stable_commit) && (docker compose restart || true)")
            st.warning("Rolled back Oracle VM to previous stable commit.")

# --- AUDIT HISTORY ---
with tabs[3]:
    st.subheader("📜 Pipeline Audit Trail")
    audit_file = "workflow_audit.json"
    if os.path.exists(audit_file):
        with open(audit_file, "r") as f:
            st.json(json.load(f))
    else:
        st.info("No audit logs recorded yet.")