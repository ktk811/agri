import streamlit as st
import subprocess

st.title("Debugging Streamlit Environment")

# Check installed packages
installed_packages = subprocess.run(["pip", "list"], capture_output=True, text=True)
st.text(installed_packages.stdout)

# Try installing earthengine-api
if st.button("Install Earth Engine API"):
    result = subprocess.run(["pip", "install", "earthengine-api"], capture_output=True, text=True)
    st.text(result.stdout)
