###########################################
# app.py
# A single-file solution with integrated MongoDB (Dark Mode – Dramatic UI)
#  - Shows login/register pages until user logs in.
#  - Presents main app once logged in, with a Logout button in sidebar.
###########################################

import os
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

import streamlit as st
import streamlit.components.v1 as components
import requests
import numpy as np
import pandas as pd
import ee
import datetime
import pymongo
import bcrypt
from urllib.parse import quote_plus

# ---------------------------
# CUSTOM CSS: FULL SCREEN BACKGROUND, GLASSMORPHISM, MODERN TYPOGRAPHY
# ---------------------------
custom_css = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

html, body {
    height: 100%;
    margin: 0;
    padding: 0;
    font-family: 'Inter', sans-serif;
    background: url('https://images.unsplash.com/photo-1518837695005-2083093ee35b?ixlib=rb-4.0.3&auto=format&fit=crop&w=1950&q=80') no-repeat center center fixed;
    background-size: cover;
}
.overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.75);
    z-index: -1;
}
header {
    text-align: center;
    padding: 2rem 0;
    color: #f0f0f0;
}
header h1 {
    font-size: 3.5rem;
    margin: 0;
}
header p {
    font-size: 1.3rem;
    margin: 0.5rem 0 0;
    color: #aaa;
}

.card {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 2rem;
    margin: 2rem auto;
    max-width: 400px;
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(5px);
    -webkit-backdrop-filter: blur(5px);
    border: 1px solid rgba(255, 255, 255, 0.3);
}
.stTextInput>div>div>input {
    background-color: rgba(255,255,255,0.1) !important;
    border: 1px solid rgba(255,255,255,0.3) !important;
    color: #f0f0f0;
}
.stButton>button {
    background-color: #4a90e2;
    color: #fff;
    border: none;
    padding: 0.8rem 1.6rem;
    border-radius: 10px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: background-color 0.3s ease;
}
.stButton>button:hover {
    background-color: #357ABD;
}
.sidebar .css-1d391kg {
    background: rgba(0,0,0,0.85);
    padding: 1rem;
    border-radius: 12px;
}
hr {
    border: 1px solid #444;
}
a {
    color: #4a90e2;
    text-decoration: none;
}
a:hover {
    text-decoration: underline;
}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)
st.markdown("<div class='overlay'></div>", unsafe_allow_html=True)

# ---------------------------
# HEADER BANNER
# ---------------------------
def show_header():
    st.markdown(
        """
        <header>
            <h1>Agrinfo</h1>
            <p>Unleash AI-Driven Insights for Your Farm</p>
        </header>
        """, 
        unsafe_allow_html=True
    )

# ---------------------------
# 0. INITIALIZE EARTH ENGINE
# ---------------------------
try:
    ee.Initialize(project='ee-kartik081105')
except Exception as e:
    ee.Authenticate()
    ee.Initialize(project='ee-kartik081105')

# ---------------------------
# 1. SET UP MONGODB CONNECTION
# ---------------------------
username = quote_plus("soveetprusty")
password = quote_plus("@Noobdamaster69")
connection_string = f"mongodb+srv://{username}:{password}@cluster0.bjzstq0.mongodb.net/?retryWrites=true&w=majority"
client = pymongo.MongoClient(connection_string)
db = client["agri_app"]
farmers_col = db["farmers"]
crop_inventory_col = db["crop_inventory"]
pesticide_inventory_col = db["pesticide_inventory"]

# ---------------------------
# 2. USER SETTINGS & INVENTORY DEFAULTS
# ---------------------------
GOOGLE_MAPS_EMBED_API_KEY = "AIzaSyAWHIWaKtmhnRfXL8_FO7KXyuWq79MKCvs"  # Replace with your key

default_crop_prices = {
    "Wheat": 20,
    "Rice": 25,
    "Maize": 18,
    "Sugarcane": 30,
    "Cotton": 40
}

soil_types = ["Sandy", "Loamy", "Clay", "Silty"]

# ---------------------------
# 3. HELPER FUNCTIONS (Weather, NDVI, Soil, Shops)
# ---------------------------
def get_weather_data(city_name):
    geo_url = "https://nominatim.openstreetmap.org/search"
    params_geo = {"city": city_name, "country": "India", "format": "json"}
    r_geo = requests.get(geo_url, params=params_geo, headers={"User-Agent": "Mozilla/5.0"})
    if r_geo.status_code != 200 or not r_geo.json():
        return None, None, None, None, None, None
    geo_data = r_geo.json()[0]
    lat = float(geo_data["lat"])
    lon = float(geo_data["lon"])
    weather_url = "https://api.open-meteo.com/v1/forecast"
    params_weather = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
        "hourly": "precipitation",
        "timezone": "Asia/Kolkata"
    }
    r_wth = requests.get(weather_url, params=params_weather)
    if r_wth.status_code != 200:
        return None, None, lat, lon, None, None
    wdata = r_wth.json()
    current_temp = wdata["current_weather"]["temperature"]
    current_time = wdata["current_weather"]["time"]
    hourly_times = wdata["hourly"]["time"]
    hourly_precip = wdata["hourly"]["precipitation"]
    current_precip = hourly_precip[hourly_times.index(current_time)] if current_time in hourly_times else 0
    return current_temp, current_precip, lat, lon, hourly_precip, hourly_times

def get_real_ndvi(lat, lon):
    point = ee.Geometry.Point(lon, lat)
    region = point.buffer(5000)
    today = datetime.date.today()
    start_date = str(today - datetime.timedelta(days=30))
    end_date = str(today)
    s2 = ee.ImageCollection('COPERNICUS/S2') \
            .filterBounds(region) \
            .filterDate(start_date, end_date) \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
    def add_ndvi(image):
        ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
        return image.addBands(ndvi)
    s2 = s2.map(add_ndvi)
    ndvi_image = s2.select('NDVI').median()
    ndvi_dict = ndvi_image.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, scale=30)
    ndvi_value = ee.Number(ndvi_dict.get('NDVI')).getInfo()
    return ndvi_value

def get_soil_type(lat, lon):
    url = "https://rest.isric.org/soilgrids/v2.0/properties/query"
    params = {"lat": lat, "lon": lon, "property": "sand,clay,silt", "depth": "0-5cm"}
    r = requests.get(url, params=params)
    if r.status_code != 200:
        return None
    try:
        data = r.json()
        layers = data.get("properties", {}).get("layers", [])
        sand = clay = silt = None
        for layer in layers:
            name = layer.get("name", "").lower()
            if not layer.get("depths"):
                continue
            mean_val = layer["depths"][0].get("values", {}).get("mean", None)
            if mean_val is None:
                continue
            if "sand" in name:
                sand = mean_val
            elif "clay" in name:
                clay = mean_val
            elif "silt" in name:
                silt = mean_val
        if sand is None or clay is None or silt is None:
            return None
        if sand >= clay and sand >= silt:
            return "Sandy"
        elif clay >= sand and clay >= silt:
            return "Clay"
        elif silt >= sand and silt >= clay:
            return "Silty"
        else:
            return "Loamy"
    except Exception:
        return None

def reverse_geocode(lat, lon):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1}
    r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code == 200:
        return r.json().get("display_name", "Address not available")
    return "Address not available"

def get_live_shop_list(lat, lon):
    overpass_url = "http://overpass-api.de/api/interpreter"
    query = f"""
    [out:json];
    node(around:10000, {lat}, {lon})["shop"];
    out body;
    """
    r = requests.post(overpass_url, data=query)
    if r.status_code != 200:
        return pd.DataFrame()
    data = r.json()
    elements = data.get("elements", [])
    keywords = ["agro", "farm", "agr", "hort", "garden", "agriculture"]
    exclusions = ["clothes", "apparel", "fashion", "footwear"]
    shops = []
    for elem in elements:
        tags = elem.get("tags", {})
        name = tags.get("name", "").strip()
        shop_tag = tags.get("shop", "").strip()
        if not name:
            continue
        if any(exc in name.lower() for exc in exclusions):
            continue
        if not (any(k in name.lower() for k in keywords) or any(k in shop_tag.lower() for k in keywords)):
            continue
        addr_full = tags.get("addr:full", "").strip()
        if addr_full:
            address = addr_full
        else:
            address_parts = []
            if tags.get("addr:housenumber", "").strip():
                address_parts.append(tags.get("addr:housenumber", "").strip())
            if tags.get("addr:street", "").strip():
                address_parts.append(tags.get("addr:street", "").strip())
            if tags.get("addr:city", "").strip():
                address_parts.append(tags.get("addr:city", "").strip())
            if address_parts:
                address = ", ".join(address_parts)
            else:
                address = reverse_geocode(elem.get("lat"), elem.get("lon"))
        shops.append({"Name": name, "Type": shop_tag, "Address": address})
    df = pd.DataFrame(shops)
    if not df.empty:
        df.index = np.arange(1, len(df) + 1)
        df.index.name = "No."
    return df

def style_shops_dataframe(shops_df):
    shops_df_renamed = shops_df.rename(columns={"Name": "Shop Name", "Type": "Category", "Address": "Full Address"})
    styled_df = shops_df_renamed.style.set_properties({"border": "1px solid #444", "padding": "6px"})\
                           .set_table_styles([
                               {"selector": "th", "props": [("background-color", "#2c2c2c"),
                                                            ("font-weight", "bold"),
                                                            ("text-align", "center"),
                                                            ("color", "#e0e0e0")]},
                               {"selector": "td", "props": [("text-align", "left"),
                                                            ("vertical-align", "top"),
                                                            ("color", "#e0e0e0")]}
                           ])
    return styled_df

def get_fertilizer_pesticide_recommendations(ndvi, soil_type):
    if ndvi < 0.5:
        fert = "High NPK mix (Urea, DAP, MOP)"
        pest = "Broad-spectrum insecticide (e.g., Chlorpyrifos)"
    elif ndvi < 0.7:
        fert = "Moderate NPK mix (Balanced fertilizer)"
        pest = "Targeted pesticide (e.g., Imidacloprid)"
    else:
        fert = "Minimal fertilizer needed"
        pest = "No pesticide required"
    
    if soil_type == "Sandy":
        fert += " (Add extra organic matter & water)"
    elif soil_type == "Clay":
        fert += " (Ensure drainage, avoid overwatering)"
    elif soil_type == "Loamy":
        fert += " (Balanced approach)"
    elif soil_type == "Silty":
        fert += " (Moderate water-holding capacity)"
    
    return fert, pest

# ---------------------------
# 4. FARMER AUTHENTICATION FUNCTIONS
# ---------------------------
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

def register_farmer(username, password):
    if farmers_col.find_one({"username": username}):
        return False, "Username already exists."
    hashed_pw = hash_password(password)
    farmers_col.insert_one({"username": username, "password": hashed_pw})
    return True, "Registration successful."

def login_farmer(username, password):
    user = farmers_col.find_one({"username": username})
    if user and check_password(password, user["password"]):
        return True, "Login successful."
    return False, "Invalid username or password."

# ---------------------------
# 5. STREAMLIT APP: PAGE FUNCTIONS
# ---------------------------
def show_login():
    """Display the login page."""
    show_header()
    st.markdown("<div style='text-align:center; font-size:1.2rem; margin-bottom:1rem;'>Log in to access your personalized insights.</div>", unsafe_allow_html=True)
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        success, msg = login_farmer(username, password)
        if success:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.page = "main"
        else:
            st.error(msg)
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;'>Don't have an account? <a href='#' style='color:#4a90e2;' onclick=\"window.parent.postMessage({page:'register'}, '*')\">Register here</a></div>", unsafe_allow_html=True)
    if st.button("Go to Registration"):
        st.session_state.page = "register"

def show_register():
    """Display the registration page."""
    show_header()
    st.markdown("<div style='text-align:center; font-size:1.2rem; margin-bottom:1rem;'>Create your account to start exploring.</div>", unsafe_allow_html=True)
    username = st.text_input("Choose a Username")
    password = st.text_input("Choose a Password", type="password")
    if st.button("Register"):
        success, msg = register_farmer(username, password)
        if success:
            st.success(msg)
            st.markdown("<div style='text-align:center;'>Please login with your new credentials.</div>", unsafe_allow_html=True)
            st.session_state.page = "login"
        else:
            st.error(msg)
    st.markdown("<hr>", unsafe_allow_html=True)
    if st.button("Back to Login"):
        st.session_state.page = "login"

def show_main_app():
    """Display the main application if logged in."""
    show_header()
    with st.sidebar:
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.page = "login"
    st.markdown("<div style='text-align:center; font-size:1.1rem; margin-bottom:1rem;'>Welcome, <strong>{}</strong>! Dive into your insights below.</div>".format(st.session_state.username), unsafe_allow_html=True)
    st.write(
        """
        *Features:*
        - Real-time weather data via Open-Meteo
        - NDVI data from Sentinel-2 imagery (last 30 days)
        - Irrigation recommendations based on temperature and rainfall
        - Fertilizer and pesticide suggestions
        - Satellite view and nearby agro-shops
        - Inventory management for crops and pesticides
        """
    )
    st.sidebar.title("Inputs")
    city_name = st.sidebar.text_input("Enter Indian City Name:", "Mumbai")
    tab1, tab2, tab3 = st.tabs([
        "Irrigation & Satellite",
        "Fertilizer & Pesticide",
        "Inventory Management"
    ])
    with tab1:
        temp, current_precip, lat, lon, hourly_precip, hourly_times = get_weather_data(city_name)
        if temp is None:
            st.error("Could not fetch weather data. Check city name.")
        else:
            avg_rain = np.mean(hourly_precip[-3:]) if hourly_precip and len(hourly_precip) >= 3 else current_precip
            irrigation_req = max(0, 25 + (temp - 20) - avg_rain)
            st.subheader(f"Weather in {city_name}")
            st.write(f"*Temperature:* {temp} °C")
            st.write(f"*Current Rain:* {current_precip} mm")
            st.write(f"*Avg Forecast Rain (next 3 hrs):* {avg_rain:.2f} mm")
            st.subheader("Irrigation Recommendation")
            st.write(f"*Recommended Irrigation:* {irrigation_req:.2f} mm")
            if irrigation_req > 40:
                st.warning("High water requirement! Your crop is stressed.")
            elif irrigation_req > 10:
                st.info("Moderate water requirement.")
            else:
                st.success("Low water requirement.")
            st.subheader("Satellite View")
            if GOOGLE_MAPS_EMBED_API_KEY:
                maps_url = (f"https://www.google.com/maps/embed/v1/view?"
                            f"key={GOOGLE_MAPS_EMBED_API_KEY}&center={lat},{lon}"
                            f"&zoom=18&maptype=satellite")
                components.html(f'<iframe width="100%" height="450" src="{maps_url}" frameborder="0" allowfullscreen></iframe>', height=450)
            else:
                st.info("Google Maps Embed API key not provided.")
    with tab2:
        temp, current_precip, lat, lon, _, _ = get_weather_data(city_name)
        if temp is None:
            st.error("Could not fetch weather data. Check city name.")
        else:
            try:
                ndvi_val = get_real_ndvi(lat, lon)
            except Exception:
                st.error("Error fetching NDVI data.")
                ndvi_val = None
            if ndvi_val is not None:
                soil_selected = st.selectbox("Select Soil Type:", soil_types, key='soil_for_fert')
                st.subheader("Fertilizer & Pesticide Recommendations")
                fertilizer, pesticide = get_fertilizer_pesticide_recommendations(ndvi_val, soil_selected)
                st.write(f"*Soil Type:* {soil_selected}")
                st.write(f"*Real NDVI:* {ndvi_val:.2f}")
                st.write(f"*Fertilizer Recommendation:* {fertilizer}")
                st.write(f"*Pesticide Recommendation:* {pesticide}")
            else:
                st.error("NDVI data unavailable.")
            st.subheader("Nearby Agro-Shops")
            shops_df = get_live_shop_list(lat, lon)
            if shops_df.empty:
                st.info("No nearby agro-shops found.")
            else:
                styled_df = style_shops_dataframe(shops_df)
                st.dataframe(styled_df, use_container_width=True)
    with tab3:
        st.subheader("Crop Inventory Management")
        crop_selected = st.selectbox("Select a Crop:", list(default_crop_prices.keys()))
        quantity = st.number_input("Enter Quantity (in kg):", min_value=0, value=0, step=1)
        price = st.number_input("Enter Market Price (per kg):", min_value=0, value=default_crop_prices[crop_selected], step=1)
        if st.button("Add Crop", key='crop_add'):
            crop_inventory_col.insert_one({
                "username": st.session_state.username,
                "crop": crop_selected,
                "quantity": quantity,
                "price": price
            })
            st.success("Crop inventory added.")
        user_crops = list(crop_inventory_col.find({"username": st.session_state.username}, {"_id": 0}))
        if user_crops:
            st.write("### Current Crop Inventory")
            df_crop = pd.DataFrame(user_crops)
            df_crop.index = range(1, len(df_crop) + 1)
            st.dataframe(df_crop)
            total_price = (df_crop["quantity"] * df_crop["price"]).sum()
            st.write(f"*Total Inventory Price:* {total_price}")
        st.subheader("Pesticide Inventory Management")
        pesticide_name = st.text_input("Enter Pesticide Name:", key='pest_name')
        pesticide_qty = st.number_input("Enter Quantity (liters/kg):", min_value=0, value=0, step=1, key='pest_qty')
        if st.button("Add Pesticide", key='pest_add'):
            pesticide_inventory_col.insert_one({
                "username": st.session_state.username,
                "pesticide": pesticide_name,
                "quantity": pesticide_qty
            })
            st.success("Pesticide inventory added.")
        user_pesticides = list(pesticide_inventory_col.find({"username": st.session_state.username}, {"_id": 0}))
        if user_pesticides:
            st.write("### Current Pesticide Inventory")
            df_pest = pd.DataFrame(user_pesticides)
            df_pest.index = range(1, len(df_pest) + 1)
            st.dataframe(df_pest)

# ---------------------------
# 6. MAIN LOGIC: PAGE ROUTER
# ---------------------------
def main():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "page" not in st.session_state:
        st.session_state.page = "login"

    if st.session_state.logged_in and st.session_state.page == "main":
        show_main_app()
    elif st.session_state.page == "register":
        show_register()
    else:
        show_login()

if __name__ == "__main__":
    main()
