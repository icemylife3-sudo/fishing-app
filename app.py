import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import date, datetime, timedelta
import os
import requests
import urllib.request
import urllib.parse
import base64
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates

# ---------------------------------------------------------
# ページ設定 & 自動翻訳無効化ヘッダー
# ---------------------------------------------------------
st.set_page_config(page_title="共有釣行管理アプリ", page_icon="🎣", layout="wide")

st.markdown("""
    <html lang="ja">
    <head>
        <meta name="google" content="notranslate">
        <meta http-equiv="Content-Language" content="ja">
    </head>
    </html>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# トースト通知（自動消去メッセージ）の処理
# ---------------------------------------------------------
if "toast_msg" not in st.session_state:
    st.session_state.toast_msg = None

if st.session_state.toast_msg:
    st.toast(st.session_state.toast_msg, icon="✅")
    st.session_state.toast_msg = None

# ---------------------------------------------------------
# 日本語フォントの自動読み込み（文字化け完全対策）
# ---------------------------------------------------------
@st.cache_resource
def get_jp_font(size=14):
    font_paths = [
        "C:\\Windows\\Fonts\\meiryo.ttc",       
        "C:\\Windows\\Fonts\\msgothic.ttc",     
        "C:\\Windows\\Fonts\\yuGothM.ttc",      
        "/System/Library/Fonts/Hiragino Sans W4.ttc", 
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    ]
    
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                pass
                
    font_path = "NotoSansCJKjp-Regular.otf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf"
            urllib.request.urlretrieve(url, font_path)
        except Exception:
            pass
            
    try:
        return ImageFont.truetype(font_path, size)
    except:
        return ImageFont.load_default()

# ---------------------------------------------------------
# Firebase 初期化
# ---------------------------------------------------------
@st.cache_resource
def init_firebase():
    key_path = "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
        else:
            try:
                if "firebase" in st.secrets:
                    cred_dict = dict(st.secrets["firebase"])
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                else:
                    st.error("⚠️ Streamlit Secrets に [firebase] の設定が見つかりません。")
                    st.stop()
            except Exception as e:
                st.error(f"⚠️ Firebaseの初期化に失敗しました。Secretsの設定を確認してください。\nエラー: {e}")
                st.stop()
            
    return firestore.client()

db = init_firebase()

# ---------------------------------------------------------
# Firestore データ操作
# ---------------------------------------------------------
def get_plans():
    docs = db.collection("plans").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    plans = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        plans.append(d)
    return pd.DataFrame(plans)

def create_plan(name, start_date, end_date, members_list):
    db.collection("plans").add({
        "name": name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "members": members_list,
        "created_at": datetime.now()
    })

# ★ 修正: 計画情報をフルで更新する関数に変更
def update_plan_details(plan_id, name, start_date, end_date, members_list):
    db.collection("plans").document(plan_id).update({
        "name": name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "members": members_list
    })

def delete_plan(plan_id):
    db.collection("plans").document(plan_id).delete()

def save_optimized_image(uploaded_file, save_path, max_width=800):
    os.makedirs("uploads", exist_ok=True)
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(float(img.height) * ratio)
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
    img.save(save_path, "JPEG", quality=75)

# ---------------------------------------------------------
# 地名検索モジュール (国土地理院API強化版)
# ---------------------------------------------------------
def geocode_location_jp(location_name):
    if not location_name:
        return None, None, None
    
    try:
        url_gsi = f"https://msearch.gsi.go.jp/address/search?q={urllib.parse.quote(location_name)}"
        res_gsi = requests.get(url_gsi).json()
        if res_gsi and len(res_gsi) > 0:
            coords = res_gsi[0]["geometry"]["coordinates"]
            title = res_gsi[0]["properties"]["title"]
            return float(coords[1]), float(coords[0]), title
    except Exception:
        pass
        
    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(location_name)}&countrycodes=jp&limit=1"
        headers = {"User-Agent": "FishingApp/1.0"}
        res = requests.get(url, headers=headers).json()
        if res and len(res) > 0:
            target = res[0]
            display_name = target.get("display_name", "").split(",")[0]
            return float(target["lat"]), float(target["lon"]), display_name
    except Exception:
        pass
    
    try:
        url_alt = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(location_name)}&count=1&language=ja&format=json"
        res_alt = requests.get(url_alt).json()
        if "results" in res_alt and len(res_alt["results"]) > 0:
            target = res_alt["results"][0]
            return target["latitude"], target["longitude"], target.get("name", location_name)
    except Exception:
        pass
        
    return None, None, None

def get_wind_direction_16(deg):
    val = int((deg / 22.5) + 0.5)
    arr = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東", "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    return arr[(val % 16)]

def get_weather_icon_and_desc(code):
    mapping = {
        0: ("☀️", "晴天"), 1: ("🌤️", "ほぼ晴れ"), 2: ("⛅", "時々曇り"), 3: ("☁️", "曇り"),
        45: ("🌫️", "霧"), 48: ("🌫️", "着氷性の霧"),
        51: ("🌧️", "小雨"), 53: ("🌧️", "雨"), 55: ("🌧️", "強い雨"),
        61: ("☔", "雨"), 63: ("☔", "やや強い雨"), 65: ("☔", "激しい雨"),
        80: ("🌦️", "にわか雨"), 81: ("🌦️", "強いにわか雨"), 82: ("⛈️", "激しいにわか雨")
    }
    return mapping.get(code, ("☁️", "曇り"))

@st.cache_data(ttl=3600)
def fetch_weather_3h_smart(lat, lon, start_date_obj, num_days=1):
    try:
        today_obj = date.today()
        target_dates = [(start_date_obj + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
        
        if start_date_obj >= today_obj - timedelta(days=2):
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,weathercode,windspeed_10m,winddirection_10m,precipitation&forecast_days=14&timezone=Asia%2FTokyo"
        else:
            end_d_str = (start_date_obj + timedelta(days=num_days)).strftime("%Y-%m-%d")
            url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={target_dates[0]}&end_date={end_d_str}&hourly=temperature_2m,weathercode,windspeed_10m,winddirection_10m,precipitation&timezone=Asia%2FTokyo"
            
        res = requests.get(url).json()
        if "hourly" in res:
            df_h = pd.DataFrame({
                "time": res["hourly"]["time"],
                "temp": res["hourly"]["temperature_2m"],
                "code": res["hourly"]["weathercode"],
                "speed": res["hourly"]["windspeed_10m"],
                "deg": res["hourly"]["winddirection_10m"],
                "precip": res["hourly"].get("precipitation", 0)
            })
            df_filtered = df_h[df_h["time"].apply(lambda x: x.split("T")[0] in target_dates)].copy()
            df_filtered["hour"] = df_filtered["time"].apply(lambda x: int(x.split("T")[1].split(":")[0]))
            df_3h = df_filtered[df_filtered["hour"] % 3 == 0].copy()
            
            results = []
            for _, row in df_3h.iterrows():
                icon, desc = get_weather_icon_and_desc(row["code"])
                date_part = row["time"].split("T")[0][5:]
                time_part = row["time"].split("T")[1][:5]
                results.append({
                    "date_time": f"{date_part} {time_part}",
                    "icon": icon,
                    "desc": desc,
                    "temp": f"{row['temp']:.1f}℃",
                    "speed": f"{row['speed']:.1f} m/s",
                    "dir": get_wind_direction_16(row["deg"]),
                    "precip": f"{row['precip']:.1f}"
                })
            return results
    except Exception:
        pass
    return None

# ---------------------------------------------------------
# アプリメイン UI
# ---------------------------------------------------------
st.title("🎣 チーム釣行・遠征総合管理アプリ")

plans_df = get_plans()

if plans_df.empty:
    create_plan("神津島遠征A計画", date.today(), date.today() + timedelta(days=2), ["A", "B", "C"])
    st.rerun()

sidebar = st.sidebar
sidebar.header("📁 釣行計画の選択")

plan_names = plans_df["name"].tolist()

url_params = st.query_params
url_plan_id = url_params.get("plan")

default_index = 0
if url_plan_id:
    match_indices = plans_df.index[plans_df['id'] == url_plan_id].tolist()
    if match_indices:
        default_index = match_indices[0]

selected_plan_name = sidebar.selectbox("現在の計画", plan_names, index=default_index)

current_plan = plans_df[plans_df["name"] == selected_plan_name].iloc[0]
plan_id = current_plan["id"]

if url_plan_id != plan_id:
    st.query_params["plan"] = plan_id

members = current_plan.get("members", [])
raw_start = current_plan.get("start_date")
raw_end = current_plan.get("end_date")

try:
    s_date_obj = datetime.strptime(str(raw_start), "%Y-%m-%d").date() if raw_start else date.today()
except ValueError:
    s_date_obj = date.today()

try:
    e_date_obj = datetime.strptime(str(raw_end), "%Y-%m-%d").date() if raw_end else s_date_obj + timedelta(days=1)
except ValueError:
    e_date_obj = s_date_obj + timedelta(days=1)

# ★ 修正: 現在の計画情報をフルで編集できるように機能追加
sidebar.subheader("⚙️ 現在の計画の設定")
with sidebar.expander("✏️ 計画名・日程・参加者の編集", expanded=False):
    edit_name = st.text_input("計画名", value=current_plan.get("name", ""), key=f"edit_name_{plan_id}")
    col_s1, col_s2 = st.columns(2)
    edit_start = col_s1.date_input("開始日", value=s_date_obj, key=f"edit_s_{plan_id}")
    edit_end = col_s2.date_input("終了日", value=e_date_obj, key=f"edit_e_{plan_id}")
    edit_members_str = st.text_input("参加者 (カンマ区切り)", value=", ".join(members), key=f"edit_m_{plan_id}")
    
    if st.button("💾 変更を保存", key=f"btn_update_plan_{plan_id}", type="primary"):
        m_list = [m.strip() for m in edit_members_str.split(",") if m.strip()]
        update_plan_details(plan_id, edit_name, edit_start, edit_end, m_list)
        st.session_state.toast_msg = "計画情報を更新しました！"
        st.rerun()

sidebar.markdown(f"🗓️ **期間:** {s_date_obj} 〜 {e_date_obj}")
sidebar.markdown(f"👥 **参加者 ({len(members)}名):** {', '.join(members)}")

with sidebar.expander("➕ 新しい計画を追加"):
    new_plan_name = st.text_input("計画名", placeholder="例: 八丈島遠征", key="new_plan_name_input")
    col_d1, col_d2 = st.columns(2)
    new_start_date = col_d1.date_input("開始日", value=date.today(), key="new_start_d")
    new_end_date = col_d2.date_input("終了日", value=date.today() + timedelta(days=1), key="new_end_d")
    new_members_str = st.text_input("参加者 (カンマ区切り)", placeholder="例: A, B, C", key="new_members_input")
    
    if st.button("計画を作成", key="btn_create_plan") and new_plan_name and new_members_str:
        m_list = [m.strip() for m in new_members_str.split(",") if m.strip()]
        create_plan(new_plan_name, new_start_date, new_end_date, m_list)
        st.session_state.toast_msg = f"「{new_plan_name}」を作成しました！"
        st.rerun()

with sidebar.expander("🗑️ 計画を削除"):
    st.warning("一度削除すると復元できません。")
    confirm_del = st.checkbox("この計画を削除することを確認", key="confirm_delete_plan")
    if st.button("現在の計画を削除", key="btn_delete_plan", type="primary") and confirm_del:
        delete_plan(plan_id)
        st.query_params.clear()
        st.session_state.toast_msg = f"「{selected_plan_name}」を削除しました。"
        st.rerun()

st.divider()

# ---------------------------------------------------------
# タブ構成
# ---------------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗓️ 行程表", 
    "💰 旅費割り勘管理", 
    "✅ 個人別持ち物チェック", 
    "🐟 釣果記録（写真付）",
    "🗺️ ポイントマップ",
    "🌤️ 天気・風予報",
    "📖 操作マニュアル & しおり"
])

plan_doc_ref = db.collection("plans").document(plan_id)

# =========================================================
# ① 行程表の管理
# =========================================================
with tab1:
    st.header(f"🗓️ {selected_plan_name} ({s_date_obj} 〜 {e_date_obj})")
    col1, col2 = st.columns([1, 2.5])
    with col1:
        st.subheader("予定の追加")
        sched_date = st.date_input("日付", value=s_date_obj, key=f"sched_date_input_{plan_id}")
        sched_time = st.time_input("時間", key=f"sched_time_input_{plan_id}")
        location = st.text_input("場所・施設名", placeholder="〇〇港 / フェリー乗り場", key=f"sched_loc_input_{plan_id}")
        activity = st.text_area("内容・メモ", key=f"sched_act_input_{plan_id}")
        if st.button("行程に追加", key=f"btn_add_sched_{plan_id}"):
            if location or activity:
                dt_str = f"{sched_date} {sched_time.strftime('%H:%M')}"
                plan_doc_ref.collection("itinerary").add({
                    "date_time": dt_str, "location": location, "activity": activity, "created_at": datetime.now()
                })
                st.session_state.toast_msg = "行程を追加しました！"
                st.rerun()

    with col2:
        st.subheader("行程一覧")
        docs = plan_doc_ref.collection("itinerary").order_by("date_time").stream()
        itin_list = [{"id": doc.id, **doc.to_dict()} for doc in docs]
        if itin_list:
            for item in itin_list:
                item_id = item["id"]
                cols = st.columns([0.25, 0.6, 0.15])
                cols[0].write(f"**{item.get('date_time', '')}**")
                
                loc_html = f"<div style='line-height: 1.4;'><strong style='font-size: 1.1em; color: #2a5298;'>📍 {item.get('location', '-')}</strong>"
                act_text = item.get("activity", "")
                if act_text:
                    loc_html += f"<br><span style='color: #666; font-size: 0.9em; margin-left: 20px;'>{act_text}</span>"
                loc_html += "</div>"
                cols[1].markdown(loc_html, unsafe_allow_html=True)
                
                with cols[2]:
                    with st.popover("🗑️"):
                        st.write("削除しますか？")
                        if st.button("削除実行", key=f"del_itin_{item_id}", type="primary"):
                            plan_doc_ref.collection("itinerary").document(item_id).delete()
                            st.session_state.toast_msg = "行程を削除しました"
                            st.rerun()
        else:
            st.info("登録されている行程はありません。")

# =========================================================
# ② 旅費管理
# =========================================================
with tab2:
    st.header(f"💰 {selected_plan_name} - 旅費＆割り勘計算")
    col1, col2 = st.columns([1, 2.5])
    with col1:
        st.subheader("支出の登録")
        exp_cat = st.selectbox("カテゴリ", ["交通費・渡航費", "船代・遊漁料", "宿泊費", "エサ・仕掛け", "食費・雑費", "その他"], key=f"exp_cat_select_{plan_id}")
        exp_item = st.text_input("項目名", placeholder="〇〇丸 船代", key=f"exp_item_input_{plan_id}")
        exp_amount = st.number_input("金額 (円)", min_value=0, step=100, key=f"exp_amount_input_{plan_id}")
        exp_payer = st.selectbox("支払った人", members if members else ["未設定"], key=f"exp_payer_select_{plan_id}")
        exp_memo = st.text_input("メモ", key=f"exp_memo_input_{plan_id}")
        if st.button("支出を追加", key=f"btn_add_exp_{plan_id}"):
            if exp_amount > 0 and exp_item:
                plan_doc_ref.collection("expenses").add({
                    "category": exp_cat, "item": exp_item, "amount": int(exp_amount),
                    "payer": exp_payer, "memo": exp_memo, "created_at": datetime.now()
                })
                st.session_state.toast_msg = "支出を登録しました！"
                st.rerun()

    with col2:
        docs = plan_doc_ref.collection("expenses").stream()
        exp_list = [{"id": doc.id, **doc.to_dict()} for doc in docs]
        exp_df = pd.DataFrame(exp_list)
        total_amount = exp_df["amount"].sum() if not exp_df.empty and "amount" in exp_df.columns else 0
        num_members = len(members)
        per_person = total_amount / num_members if num_members > 0 else 0
        
        st.subheader("📊 割り勘計算サマリー")
        m1, m2, m3 = st.columns(3)
        m1.metric("総支出", f"¥{total_amount:,}")
        m2.metric("参加人数", f"{num_members}名")
        m3.metric("1人あたりの支払額", f"¥{int(per_person):,}")
        
        if exp_list:
            st.subheader("支出明細")
            for exp in exp_list:
                e_id = exp["id"]
                cols = st.columns([0.35, 0.3, 0.25, 0.1])
                cols[0].markdown(f"**{exp.get('category', '')}**<br><span style='font-size:0.9em;'>{exp.get('item', '-')}</span>", unsafe_allow_html=True)
                cols[1].markdown(f"**¥{exp.get('amount', 0):,}**<br><span style='font-size:0.85em; color:#555;'>👤 {exp.get('payer', '-')}</span>", unsafe_allow_html=True)
                cols[2].markdown(f"<span style='font-size:0.85em; color:#777;'>📝 {exp.get('memo', '')}</span>", unsafe_allow_html=True)
                
                with cols[3]:
                    with st.popover("⚙️"):
                        st.markdown("**✏️ 内容の編集**")
                        cats = ["交通費・渡航費", "船代・遊漁料", "宿泊費", "エサ・仕掛け", "食費・雑費", "その他"]
                        current_cat = exp.get("category", "その他")
                        e_cat = st.selectbox("カテゴリ", cats, index=cats.index(current_cat) if current_cat in cats else 5, key=f"ecat_{e_id}")
                        e_item = st.text_input("項目名", value=exp.get("item", ""), key=f"eitm_{e_id}")
                        e_amt = st.number_input("金額", value=exp.get("amount", 0), step=100, key=f"eamt_{e_id}")
                        current_payer = exp.get("payer", "")
                        e_payer = st.selectbox("支払った人", members if members else ["未設定"], index=members.index(current_payer) if current_payer in members else 0, key=f"epay_{e_id}")
                        e_memo = st.text_input("メモ", value=exp.get("memo", ""), key=f"emem_{e_id}")
                        
                        if st.button("💾 上書き保存", key=f"eupd_{e_id}"):
                            plan_doc_ref.collection("expenses").document(e_id).update({
                                "category": e_cat, "item": e_item, "amount": int(e_amt), "payer": e_payer, "memo": e_memo
                            })
                            st.session_state.toast_msg = "支出情報を更新しました！"
                            st.rerun()
                            
                        st.divider()
                        st.markdown("**🗑️ データの削除**")
                        if st.button("削除実行", key=f"edel_{e_id}", type="primary"):
                            plan_doc_ref.collection("expenses").document(e_id).delete()
                            st.session_state.toast_msg = "支出を削除しました"
                            st.rerun()
            
            st.divider()
            st.subheader("👤 個人別の立替額サマリー")
            payer_summary = exp_df.groupby("payer")["amount"].sum().reset_index()
            payer_summary["精算(立替-均等負担)"] = payer
