import streamlit as st

st.set_page_config(page_title="Dolly Test", page_icon="🎯")
st.title("🎯 Global Account Review Agent")
st.write("App is running!")

# Test 1: Can we import our modules?
try:
    from src.google.auth import get_google_credentials
    st.success("Imports OK")
except Exception as e:
    st.error(f"Import failed: {e}")

# Test 2: Can we read secrets?
try:
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "NOT SET")
    st.success(f"Anthropic key: {api_key[:10]}...")
except Exception as e:
    st.error(f"Secrets failed: {e}")

# Test 3: Can we get Google credentials?
try:
    creds = get_google_credentials()
    st.success(f"Google auth OK: {creds.service_account_email}")
except Exception as e:
    st.error(f"Google auth failed: {e}")

# Test 4: Can we list Drive files?
try:
    from src.google.drive_client import build_drive_service
    from src.utils.config_loader import load_regions_config
    drive_svc = build_drive_service(creds)
    config = load_regions_config()
    folder_id = config["drive"]["shared_folder_id"]

    resp = drive_svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(name)",
        pageSize=5,
    ).execute()
    files = resp.get("files", [])
    st.success(f"Drive access OK: {len(files)} files found")
    for f in files:
        st.write(f"  - {f['name']}")
except Exception as e:
    st.error(f"Drive access failed: {e}")
