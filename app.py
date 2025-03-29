###########################################
# app.py
# A single-file solution:
#  - Fetches real weather data using Nominatim (for geocoding) and Open-Meteo.
#  - Retrieves real NDVI data from Google Earth Engine (Sentinel-2 imagery) over the last 30 days,
#    computed over a 5 km region to capture regional variability.
#  - Retrieves real soil data from SoilGrids (ISRIC) to automatically determine soil type.
#  - Computes a rule-based irrigation recommendation:
#         Irrigation = max(0, 25 + (Temperature - 20) - (AvgRainfall over next 3 hrs))
#         (Tab 1 uses only weather data; NDVI is used only in Tab 2)
#  - Provides a Streamlit web interface with three tabs:
#      1. "Irrigation & Satellite" – shows irrigation recommendation and a satellite view.
#      2. "Fertilizer & Pesticide Recommendations" – shows fertilizer/pesticide advice (using real NDVI and user-selected soil type)
#         and a live list of nearby agro-shops.
#      3. "Inventory Management" – allows the farmer to input crop produce and pesticide inventory.
###########################################
import sys
import importlib.metadata

installed_packages = {pkg.metadata["Name"].lower() for pkg in importlib.metadata.distributions()}
if "earthengine-api" not in installed_packages:
    print("⚠️ Earth Engine API is NOT installed!")
import ee  # This should work now
import streamlit as st
import streamlit.components.v1 as components
import requests
import numpy as np
import pandas as pd
import ee
import datetime

# ---------------------------
# 0. INITIALIZE EARTH ENGINE
# ---------------------------
try:
    ee.Initialize(project='ee-soveetprusty')
except Exception as e:
    ee.Authenticate()
    ee.Initialize(project='ee-soveetprusty')

# ---------------------------
# 1. USER SETTINGS
# ---------------------------
# For satellite view: enter your Google Maps Embed API key here (optional).
GOOGLE_MAPS_EMBED_API_KEY = "AIzaSyAWHIWaKtmhnRfXL8_FO7KXyuWq79MKCvs"  # Replace with your key

default_crop_prices = {
    "Wheat": 20,
    "Rice": 25,
    "Maize": 18,
    "Sugarcane": 30,
    "Cotton": 40
}

soil_types = ["Sandy", "Loamy", "Clay", "Silty"]
soil_map = {"Sandy": 0, "Loamy": 1, "Clay": 2, "Silty": 3}
soil_adjustments = {"Sandy": 5, "Loamy": 0, "Clay": -5, "Silty": -2}

# ---------------------------
# 2. HELPER FUNCTIONS (Weather, NDVI, Soil, Shops)
# ---------------------------

def get_weather_data(city_name):
    """
    Fetch current weather data (temperature and precipitation) for a given Indian city.
    Uses Nominatim for geocoding and Open-Meteo for weather.
    Returns: current_temp, humidity, current_precip, lat, lon, hourly_precip (list), hourly_times (list)
    """
    geo_url = "https://nominatim.openstreetmap.org/search"
    params_geo = {"city": city_name, "country": "India", "format": "json"}
    r_geo = requests.get(geo_url, params=params_geo, headers={"User-Agent": "Mozilla/5.0"})
    if r_geo.status_code != 200 or not r_geo.json():
        return None, None, None, None, None, None, None
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
        return None, None, None, lat, lon, None, None
    wdata = r_wth.json()
    current_temp = wdata["current_weather"]["temperature"]
    current_time = wdata["current_weather"]["time"]
    hourly_times = wdata["hourly"]["time"]
    hourly_precip = wdata["hourly"]["precipitation"]
    current_precip = hourly_precip[hourly_times.index(current_time)] if current_time in hourly_times else 0
    humidity = None
    return current_temp, humidity, current_precip, lat, lon, hourly_precip, hourly_times

def get_real_ndvi(lat, lon):
    """
    Retrieve real NDVI using Google Earth Engine.
    Uses Sentinel-2 imagery over the last 30 days and computes the median NDVI
    over a 5 km buffer around the point.
    """
    point = ee.Geometry.Point(lon, lat)
    region = point.buffer(5000)  # 5 km
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
    """
    Retrieve real soil data from SoilGrids API (ISRIC) for the given location.
    Determines the dominant topsoil fraction (0-5cm) among sand, clay, and silt.
    """
    url = "https://rest.isric.org/soilgrids/v2.0/properties/query"
    params = {
        "lat": lat,
        "lon": lon,
        "property": "sand,clay,silt",
        "depth": "0-5cm"
    }
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
    except Exception as e:
        return None

def reverse_geocode(lat, lon):
    """
    Reverse geocode to get a human-readable address from lat/lon using Nominatim.
    """
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1}
    r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code == 200:
        return r.json().get("display_name", "Address not available")
    return "Address not available"

def get_live_shop_list(lat, lon):
    """
    Fetch nearby shop nodes using the Overpass API and filter for agriculture-related keywords.
    Returns a DataFrame with Serial Number, Shop Name, Category, and Full Address.
    If address tags are missing, uses reverse geocoding.
    """
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
    shops = []
    for elem in elements:
        tags = elem.get("tags", {})
        name = tags.get("name", "").strip()
        shop_tag = tags.get("shop", "").strip()
        if not name:
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
    """
    Apply styling to the shops DataFrame for display.
    """
    shops_df_renamed = shops_df.rename(columns={"Name": "Shop Name", "Type": "Category", "Address": "Full Address"})
    styled_df = shops_df_renamed.style.set_properties({"border": "1px solid #ddd", "padding": "6px"})\
                           .set_table_styles([
                               {"selector": "th", "props": [("background-color", "#f2f2f2"),
                                                            ("font-weight", "bold"),
                                                            ("text-align", "center")]},
                               {"selector": "td", "props": [("text-align", "left"),
                                                            ("vertical-align", "top")]}
                           ])
    return styled_df

def get_fertilizer_pesticide_recommendations(ndvi, soil_type):
    """
    Generate fertilizer and pesticide recommendations based on NDVI and soil type.
    """
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
        fert += " (Sandy: add extra organic matter & water)"
    elif soil_type == "Clay":
        fert += " (Clay: ensure drainage, avoid overwatering)"
    elif soil_type == "Loamy":
        fert += " (Loamy: balanced approach)"
    elif soil_type == "Silty":
        fert += " (Silty: moderate water-holding capacity)"
    
    return fert, pest

# ---------------------------
# 3. STREAMLIT APP (3 tabs)
# ---------------------------
def main():
    st.title("AI-Driven Agriculture Insights (Real Data)")
    st.write(
        """
        This demo provides:
        - Real-time weather data (via Open-Meteo)
        - Real NDVI data from Google Earth Engine (Sentinel-2 imagery over the last 30 days) in Tab 2
        - A simple, temperature & rainfall-based irrigation recommendation in Tab 1 (no NDVI)
        - Fertilizer and pesticide recommendations in Tab 2 (using real NDVI & user-selected soil type)
        - A satellite view and live nearby agro-shops
        - Inventory management for crops and pesticides
        """
    )
    
    st.sidebar.title("Inputs")
    city_name = st.sidebar.text_input("Enter Indian City Name:", "Mumbai")
    
    # Create three tabs
    tab1, tab2, tab3 = st.tabs([
        "Irrigation & Satellite",
        "Fertilizer & Pesticide Recommendations",
        "Inventory Management"
    ])
    
    # TAB 1: Irrigation & Satellite (no NDVI or soil selection)
    with tab1:
        temp, humidity, current_precip, lat, lon, hourly_precip, hourly_times = get_weather_data(city_name)
        if temp is None:
            st.error("Could not fetch weather data. Please check the city name.")
        else:
            # Calculate average rainfall over next 3 hours from available hourly data
            # Here we assume the last 3 entries represent near-future forecasts
            if hourly_precip and len(hourly_precip) >= 3:
                avg_rain = np.mean(hourly_precip[-3:])
            else:
                avg_rain = current_precip
            
            # Revised irrigation formula:
            # Irrigation = max(0, 25 + (Temperature - 20) - AvgRain)
            irrigation_req = max(0, 25 + (temp - 20) - avg_rain)
            
            st.subheader(f"Weather in {city_name}")
            st.write(f"*Temperature:* {temp} °C")
            st.write(f"*Current Rain:* {current_precip} mm")
            st.write(f"*Avg Forecast Rain (next 3 hrs):* {avg_rain:.2f} mm")
            
            st.subheader("Irrigation Recommendation (Temperature & Rain Based)")
            st.write(f"*Recommended Irrigation:* {irrigation_req:.2f} mm")
            if irrigation_req > 40:
                st.warning("High water requirement! Your crop is likely under stress.")
            elif irrigation_req > 10:
                st.info("Moderate water requirement.")
            else:
                st.success("Low water requirement.")
            
            st.subheader("Satellite View")
            if GOOGLE_MAPS_EMBED_API_KEY:
                maps_url = (f"https://www.google.com/maps/embed/v1/view?"
                            f"key={GOOGLE_MAPS_EMBED_API_KEY}&center={lat},{lon}"
                            f"&zoom=18&maptype=satellite")
                components.html(f'<iframe width="100%" height="450" src="{maps_url}" frameborder="0" style="border:0" allowfullscreen></iframe>', height=450)
            else:
                st.info("Google Maps Embed API key not provided. Satellite view unavailable.")
    
    # TAB 2: Fertilizer & Pesticide Recommendations (using real NDVI and user-selected soil type)
    with tab2:
        temp, humidity, rain, lat, lon, _, _ = get_weather_data(city_name)
        if temp is None:
            st.error("Could not fetch weather data. Please check the city name.")
        else:
            try:
                ndvi_val = get_real_ndvi(lat, lon)
            except Exception as e:
                st.error("Error fetching NDVI data from Google Earth Engine.")
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
            
            st.subheader("Nearby Agro-Shops (Live Data)")
            shops_df = get_live_shop_list(lat, lon)
            if shops_df.empty:
                st.info("No nearby agro-shops found. (OSM data might be incomplete.)")
            else:
                styled_df = style_shops_dataframe(shops_df)
                st.dataframe(styled_df, use_container_width=True)
    
    # TAB 3: Inventory Management
    with tab3:
        st.subheader("Crop Inventory Management")
        crop_selected = st.selectbox("Select a Crop:", list(default_crop_prices.keys()))
        quantity = st.number_input("Enter Quantity (in kg):", min_value=0, value=0, step=1)
        price = st.number_input("Enter Market Price (per kg):", min_value=0, value=default_crop_prices[crop_selected], step=1)
        if st.button("Add Crop to Inventory", key='crop_add'):
            st.session_state.setdefault("crop_inventory", []).append({
                "Crop": crop_selected,
                "Quantity (kg)": quantity,
                "Price (per kg)": price
            })
        if "crop_inventory" in st.session_state and st.session_state["crop_inventory"]:
            st.write("### Current Crop Inventory")
            df_crop = pd.DataFrame(st.session_state["crop_inventory"])
            # Reset index to start from 1
            df_crop.index = range(1, len(df_crop) + 1)
            st.dataframe(df_crop)
            # Calculate and display total price of crop inventory
            total_price = (df_crop["Quantity (kg)"] * df_crop["Price (per kg)"]).sum()
            st.write(f"*Total Inventory Price:* {total_price}")

        st.subheader("Pesticide Inventory Management")
        pesticide_name = st.text_input("Enter Pesticide Name:", key='pest_name')
        pesticide_qty = st.number_input("Enter Quantity (liters/kg):", min_value=0, value=0, step=1, key='pest_qty')
        if st.button("Add Pesticide to Inventory", key='pest_add'):
            st.session_state.setdefault("pesticide_inventory", []).append({
                "Pesticide": pesticide_name,
                "Quantity": pesticide_qty
            })
        if "pesticide_inventory" in st.session_state and st.session_state["pesticide_inventory"]:
            st.write("### Current Pesticide Inventory")
            df_pest = pd.DataFrame(st.session_state["pesticide_inventory"])
            # Reset index to start from 1
            df_pest.index = range(1, len(df_pest) + 1)
            st.dataframe(df_pest)

    
    st.sidebar.write("---")
    st.sidebar.write("*Data Sources:* Open-Meteo, GEE, SoilGrids (ISRIC), Overpass API")
    st.sidebar.write("*Tab 1:* Irrigation based on temperature and forecast rain.")
    st.sidebar.write("*Tab 2:* Fertilizer/Pesticide using real NDVI & user-selected soil type.")
    st.sidebar.write("*Tab 3:* Inventory management for crops and pesticides.")

if __name__ == "_main_":
    main()
