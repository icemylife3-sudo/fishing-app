import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import date, datetime, timedelta
import os
import requests
import urllib.request
from PIL import Image, ImageDraw, ImageFont
# ★スマホ対応の画像クリック取得ライブラリに変更
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

def update_plan_dates(plan_id, start_date, end_date):
    db.collection("plans").document(plan_id).update({
        "start_date": str(start_date),
        "end_date": str(end_date)
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
# 地名検索＆天気予報モジュール
# ---------------------------------------------------------
def geocode_location_jp(location_name):
    if not location_name:
        return None, None, None
    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={location_name}&countrycodes=jp&limit=1"
        headers = {"User-Agent": "FishingApp/1.0"}
        res = requests.get(url, headers=headers).json()
        if res and len(res) > 0:
            target = res[0]
            display_name = target.get("display_name", "").split(",")[0]
            return float(target["lat"]), float(target["lon"]), display_name
    except Exception:
        pass
    
    try:
        url_alt = f"https://geocoding-api.open-meteo.com/v1/search?name={location_name}&count=1&language=ja&format=json"
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
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,weathercode,windspeed_10m,winddirection_10m&forecast_days=14&timezone=Asia%2FTokyo"
        else:
            end_d_str = (start_date_obj + timedelta(days=num_days)).strftime("%Y-%m-%d")
            url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={target_dates[0]}&end_date={end_d_str}&hourly=temperature_2m,weathercode,windspeed_10m,winddirection_10m&timezone=Asia%2FTokyo"
            
        res = requests.get(url).json()
        if "hourly" in res:
            df_h = pd.DataFrame({
                "time": res["hourly"]["time"],
                "temp": res["hourly"]["temperature_2m"],
                "code": res["hourly"]["weathercode"],
                "speed": res["hourly"]["windspeed_10m"],
                "deg": res["hourly"]["winddirection_10m"]
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
                    "dir": get_wind_direction_16(row["deg"])
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
selected_plan_name = sidebar.selectbox("現在の計画", plan_names)

current_plan = plans_df[plans_df["name"] == selected_plan_name].iloc[0]
plan_id = current_plan["id"]
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

sidebar.subheader("🗓️ 釣行日程の設定")
col_s1, col_s2 = sidebar.columns(2)
edit_start = col_s1.date_input("開始日", value=s_date_obj, key=f"edit_s_{plan_id}")
edit_end = col_s2.date_input("終了日", value=e_date_obj, key=f"edit_e_{plan_id}")

if edit_start != s_date_obj or edit_end != e_date_obj:
    update_plan_dates(plan_id, edit_start, edit_end)
    st.rerun()

s_date = str(edit_start)
e_date = str(edit_end)
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
        st.success(f"「{new_plan_name}」を作成しました！")
        st.rerun()

with sidebar.expander("🗑️ 計画を削除"):
    st.warning("一度削除すると復元できません。")
    confirm_del = st.checkbox("この計画を削除することを確認", key="confirm_delete_plan")
    if st.button("現在の計画を削除", key="btn_delete_plan", type="primary") and confirm_del:
        delete_plan(plan_id)
        st.success(f"「{selected_plan_name}」を削除しました。")
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
    "📖 簡易説明書 & 📄 しおり"
])

plan_doc_ref = db.collection("plans").document(plan_id)

# =========================================================
# ① 行程表の管理
# =========================================================
with tab1:
    st.header(f"🗓️ {selected_plan_name} ({s_date} 〜 {e_date})")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("予定の追加")
        sched_date = st.date_input("日付", value=s_date_obj, key="sched_date_input")
        sched_time = st.time_input("時間", key="sched_time_input")
        location = st.text_input("場所・施設名", placeholder="〇〇港 / フェリー乗り場", key="sched_loc_input")
        activity = st.text_area("内容・メモ", key="sched_act_input")
        if st.button("行程に追加", key="btn_add_sched"):
            if location or activity:
                dt_str = f"{sched_date} {sched_time.strftime('%H:%M')}"
                plan_doc_ref.collection("itinerary").add({
                    "date_time": dt_str, "location": location, "activity": activity, "created_at": datetime.now()
                })
                st.success("追加しました！")
                st.rerun()

    with col2:
        st.subheader("行程一覧")
        docs = plan_doc_ref.collection("itinerary").order_by("date_time").stream()
        itin_list = [{"id": doc.id, **doc.to_dict()} for doc in docs]
        if itin_list:
            for item in itin_list:
                item_id = item["id"]
                cols = st.columns([0.25, 0.25, 0.4, 0.1])
                cols[0].write(f"**{item.get('date_time', '')}**")
                cols[1].write(item.get("location", "-"))
                cols[2].write(item.get("activity", "-"))
                if cols[3].button("🗑️", key=f"del_itin_{item_id}"):
                    plan_doc_ref.collection("itinerary").document(item_id).delete()
                    st.rerun()
        else:
            st.info("登録されている行程はありません。")

# =========================================================
# ② 旅費管理・自動割り勘計算
# =========================================================
with tab2:
    st.header(f"💰 {selected_plan_name} - 旅費＆割り勘計算")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("支出の登録")
        exp_cat = st.selectbox("カテゴリ", ["交通費・渡航費", "船代・遊漁料", "宿泊費", "エサ・仕掛け", "食費・雑費", "その他"], key="exp_cat_select")
        exp_item = st.text_input("項目名", placeholder="〇〇丸 船代", key="exp_item_input")
        exp_amount = st.number_input("金額 (円)", min_value=0, step=100, key="exp_amount_input")
        exp_payer = st.selectbox("支払った人", members if members else ["未設定"], key="exp_payer_select")
        exp_memo = st.text_input("メモ", key="exp_memo_input")
        if st.button("支出を追加", key="btn_add_exp"):
            if exp_amount > 0 and exp_item:
                plan_doc_ref.collection("expenses").add({
                    "category": exp_cat, "item": exp_item, "amount": int(exp_amount),
                    "payer": exp_payer, "memo": exp_memo, "created_at": datetime.now()
                })
                st.success("支出を登録しました！")
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
                cols = st.columns([0.2, 0.3, 0.2, 0.2, 0.1])
                cols[0].write(f"**{exp.get('category', '')}**")
                cols[1].write(exp.get("item", "-"))
                cols[2].write(f"¥{exp.get('amount', 0):,}")
                cols[3].caption(f"支払: {exp.get('payer', '-')}")
                if cols[4].button("🗑️", key=f"del_exp_{e_id}"):
                    plan_doc_ref.collection("expenses").document(e_id).delete()
                    st.rerun()
            
            st.divider()
            st.subheader("👤 個人別の立替額サマリー")
            payer_summary = exp_df.groupby("payer")["amount"].sum().reset_index()
            payer_summary["精算(立替-均等負担)"] = payer_summary["amount"] - per_person
            st.dataframe(payer_summary.rename(columns={"payer": "支払者", "amount": "合計立替額"}), use_container_width=True)

# =========================================================
# ③ 個人別持ち物チェックリスト
# =========================================================
with tab3:
    st.header(f"✅ {selected_plan_name} - 個人別持ち物チェック")
    filter_member = st.selectbox("表示するメンバーで絞り込み", ["全員表示"] + members, key="chk_filter_select")
    col_a, col_b = st.columns([3, 1])
    with col_a:
        new_item = st.text_input("追加する持ち物", placeholder="ロッド、ライジャケなど", key="chk_new_item_input")
    with col_b:
        assignee = st.selectbox("担当者", ["全員 (各自持参)"] + members, key="chk_assignee_select")
        if st.button("持ち物を追加", key="btn_add_chk") and new_item:
            plan_doc_ref.collection("checklist").add({
                "item": new_item, "assignee": assignee, "checked": False, "created_at": datetime.now()
            })
            st.rerun()
    st.divider()
    docs = plan_doc_ref.collection("checklist").stream()
    chk_list = [{"id": doc.id, **doc.to_dict()} for doc in docs]
    if filter_member != "全員表示":
        chk_list = [c for c in chk_list if c.get("assignee") in [filter_member, "全員 (各自持参)"]]

    if chk_list:
        for chk in chk_list:
            item_id = chk["id"]
            is_checked = chk.get("checked", False)
            cols = st.columns([0.1, 0.6, 0.2, 0.1])
            new_status = cols[0].checkbox("", value=is_checked, key=f"chk_item_{item_id}")
            if new_status != is_checked:
                plan_doc_ref.collection("checklist").document(item_id).update({"checked": new_status})
                st.rerun()
            display_text = f"~~{chk['item']}~~" if new_status else chk['item']
            cols[1].markdown(f"**{display_text}**")
            cols[2].caption(f"担当: {chk.get('assignee', '-')}")
            if cols[3].button("🗑️", key=f"del_chk_{item_id}"):
                plan_doc_ref.collection("checklist").document(item_id).delete()
                st.rerun()
    else:
        st.info("該当する持ち物は登録されていません。")

# =========================================================
# ④ 釣果記録
# =========================================================
with tab4:
    st.header(f"🐟 {selected_plan_name} - 釣果ログ")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("釣果の追加")
        c_date = st.date_input("日付", value=date.today(), key="catch_date_input")
        c_loc = st.text_input("ポイント・釣場", placeholder="〇〇堤防 / 沖の根", key="catch_loc_input")
        c_species = st.text_input("魚種", placeholder="カンパチ / アオリイカ", key="catch_species_input")
        c_size = st.number_input("サイズ (cm)", min_value=0.0, step=0.5, key="catch_size_input")
        c_count = st.number_input("匹数", min_value=1, value=1, key="catch_count_input")
        c_lure = st.text_input("ヒットルアー・仕掛け", placeholder="MIU 2.2g / ジグ 60g", key="catch_lure_input")
        c_notes = st.text_area("状況・ヒットメモ", placeholder="潮動時にフォールでヒット", key="catch_notes_input")
        c_img = st.file_uploader("釣果写真", type=["jpg", "jpeg", "png"], key="catch_img_input")
        if st.button("釣果を記録", key="btn_add_catch"):
            if c_species:
                img_path = ""
                if c_img is not None:
                    saved_path = os.path.join("uploads", f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{c_img.name}")
                    save_optimized_image(c_img, saved_path)
                    img_path = saved_path
                plan_doc_ref.collection("catches").add({
                    "catch_date": str(c_date), "location": c_loc, "species": c_species, "size": float(c_size),
                    "count": int(c_count), "lure": c_lure, "notes": c_notes, "image_path": img_path, "created_at": datetime.now()
                })
                st.success("釣果を登録しました！")
                st.rerun()

    with col2:
        st.subheader("釣果ギャラリー・履歴")
        docs = plan_doc_ref.collection("catches").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
        catches_list = [{"id": doc.id, **doc.to_dict()} for doc in docs]
        if catches_list:
            for catch in catches_list:
                c_id = catch["id"]
                with st.expander(f"🐟 {catch.get('catch_date', '')} - {catch.get('species', '')} ({catch.get('size', 0)}cm / {catch.get('count', 0)}匹) @ {catch.get('location', '')}"):
                    c_col1, c_col2, c_col3 = st.columns([1, 1.8, 0.2])
                    with c_col1:
                        if catch.get("image_path") and os.path.exists(catch["image_path"]):
                            st.image(catch["image_path"], use_container_width=True)
                        else:
                            st.caption("写真なし")
                    with c_col2:
                        st.write(f"**ヒットルアー/仕掛け:** {catch.get('lure', '-')}")
                        st.write(f"**状況・メモ:** {catch.get('notes', '-')}")
                    with c_col3:
                        if st.button("🗑️", key=f"del_catch_{c_id}"):
                            plan_doc_ref.collection("catches").document(c_id).delete()
                            st.rerun()
        else:
            st.info("登録されている釣果はありません。")

# =========================================================
# ⑤ ポイントマップ (【最終形態】スマホタップ＆レスポンシブ完全対応版)
# =========================================================
with tab5:
    st.header(f"🗺️ {selected_plan_name} - ポイントマップ")
    
    temp_pin_key = f"temp_pin_{plan_id}"
    map_cnt_key = f"map_key_cnt_{plan_id}"
    
    if temp_pin_key not in st.session_state:
        st.session_state[temp_pin_key] = None
    if map_cnt_key not in st.session_state:
        st.session_state[map_cnt_key] = 0
    
    map_doc = plan_doc_ref.collection("map_config").document("current").get()
    current_map_path = map_doc.to_dict().get("image_path") if map_doc.exists else ""

    st.subheader("1. 釣場画像・図面の管理")
    col_u1, col_u2 = st.columns([2, 1])
    with col_u1:
        map_img_file = st.file_uploader("航空写真やマップ画像を選択 (JPEG/PNG)", type=["jpg", "jpeg", "png"], key="map_img_file_picker")
        if map_img_file is not None:
            if st.button("💾 マップ画像を確定・保存", key="btn_confirm_map_img", type="primary"):
                saved_map_path = os.path.join("uploads", f"map_{plan_id}.jpg")
                save_optimized_image(map_img_file, saved_map_path)
                plan_doc_ref.collection("map_config").document("current").set({"image_path": saved_map_path})
                st.success("マップ画像を保存しました！")
                st.rerun()
    with col_u2:
        if current_map_path and os.path.exists(current_map_path):
            if st.button("🗑️ 現在のマップ画像を削除", key="btn_del_map_img"):
                try:
                    os.remove(current_map_path)
                except Exception:
                    pass
                plan_doc_ref.collection("map_config").document("current").delete()
                st.success("マップ画像を削除しました。")
                st.rerun()

    st.divider()

    pins_docs = plan_doc_ref.collection("pins").stream()
    pins_list = [{"id": d.id, **d.to_dict()} for d in pins_docs]
    show_all_pins = st.toggle("全ピンを一括表示/非表示", value=True, key="toggle_all_pins")
    
    if current_map_path and os.path.exists(current_map_path):
        st.subheader("📍 画像上をタップ/クリックしてピンを設置")
        st.caption("💡 **ヒント:** スマホでも画面にピッタリ収まります。画像をタップするとオレンジ色の「仮ピン」が置かれます。")
        
        font = get_jp_font(15)
        base_img = Image.open(current_map_path).convert("RGB")
        w, h = base_img.size

        draw_img = base_img.copy()
        draw = ImageDraw.Draw(draw_img)
        
        # 保存済みのピンを描画
        if show_all_pins:
            for p in pins_list:
                if p.get("visible", True):
                    px = int((p.get("x", 50) / 100.0) * w)
                    py = int((p.get("y", 50) / 100.0) * h)
                    r = max(8, int(w * 0.015))
                    draw.ellipse((px - r, py - r, px + r, py + r), fill="#e74c3c", outline="#ffffff", width=2)
                    
                    label_text = f" {p.get('title', 'ポイント')} "
                    if hasattr(font, "getbbox"):
                        bbox = font.getbbox(label_text)
                        text_w = bbox[2] - bbox[0]
                        text_h = bbox[3] - bbox[1]
                    else:
                        text_w = len(label_text) * 15
                        text_h = 16
                        
                    draw.rectangle([px + r + 4, py - r - 2, px + r + 4 + text_w + 4, py - r + text_h + 4], fill="#222222")
                    draw.text((px + r + 8, py - r), label_text, fill="#ffffff", font=font)

        # 仮ピンの描画
        if st.session_state[temp_pin_key]:
            tx, ty = st.session_state[temp_pin_key]
            px = int((tx / 100.0) * w)
            py = int((ty / 100.0) * h)
            r = max(10, int(w * 0.02))
            
            draw.ellipse((px - r, py - r, px + r, py + r), fill="#ff9f43", outline="#ffffff", width=3)
            
            temp_label = " 新規ピン配置中... "
            if hasattr(font, "getbbox"):
                bbox = font.getbbox(temp_label)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            else:
                text_w = len(temp_label) * 15
                text_h = 16
            draw.rectangle([px + r + 4, py - r - 2, px + r + 4 + text_w + 4, py - r + text_h + 4], fill="#ff9f43")
            draw.text((px + r + 8, py - r), temp_label, fill="#ffffff", font=font)

        # 合成済み画像を保存
        rendered_temp_path = os.path.join("uploads", f"temp_single_map_{plan_id}.jpg")
        draw_img.save(rendered_temp_path, "JPEG", quality=85)

        # ★ スマホ対応の画像クリック取得モジュールを使用
        canvas_key = f"perfect_map_canvas_{plan_id}_{st.session_state[map_cnt_key]}"
        
        value = streamlit_image_coordinates(
            rendered_temp_path,
            key=canvas_key,
            use_column_width=True, # ★ スマホの画面幅に合わせて自動リサイズ（はみ出さない）
        )

        # タップを検知したら座標を保存して画面をリフレッシュ
        if value is not None:
            click_x = value.get("x", 0)
            click_y = value.get("y", 0)
            
            # 取得したピクセル座標をパーセントに変換
            calc_x = round((click_x / float(w)) * 100, 1)
            calc_y = round((click_y / float(h)) * 100, 1)
            
            st.session_state[temp_pin_key] = (calc_x, calc_y)
            st.session_state[map_cnt_key] += 1
            st.rerun()

        # 仮ピンが存在する場合のみフォームを表示
        if st.session_state[temp_pin_key]:
            calc_x, calc_y = st.session_state[temp_pin_key]
            
            with st.form("new_pin_form_popup"):
                st.info(f"📍 選択された位置: 横 {calc_x}% / 縦 {calc_y}% （別の場所をタップすると移動します）")
                col_p1, col_p2 = st.columns(2)
                p_name = col_p1.text_input("ポイント名", placeholder="例: 1番船着き場", key="pop_p_name")
                p_icon = col_p2.selectbox("アイコン", ["📍 ポイント", "🎯 ヒット実績", "⚠️ 危険・注意", "⚓ 渡船・集合"], key="pop_p_icon")
                p_memo = st.text_area("詳細メモ（水深・ヒットルアー・注意点など）", placeholder="例: 水深6m、手前5mに根あり。下げ潮で実績あり。", key="pop_p_memo")
                
                btn_sub = st.form_submit_button("📌 このピンを確定して保存", type="primary")
                if btn_sub and p_name:
                    plan_doc_ref.collection("pins").add({
                        "title": p_name, "memo": p_memo, "icon": p_icon.split()[0],
                        "x": float(calc_x), "y": float(calc_y), "visible": True, "created_at": datetime.now()
                    })
                    st.session_state[temp_pin_key] = None
                    st.success(f"「{p_name}」をマップに登録しました！")
                    st.rerun()
            
            if st.button("❌ 選択をキャンセルしてピンを消す", key="cancel_temp_pin"):
                st.session_state[temp_pin_key] = None
                st.session_state[map_cnt_key] += 1
                st.rerun()

    else:
        st.info("上のエリアからマップ・航空写真画像を選択し、「💾 マップ画像を確定・保存」を押すとマップが表示されます。")

    if pins_list:
        st.subheader("📋 ポイント一覧・編集・詳細メモ")
        for pin in pins_list:
            p_id = pin["id"]
            with st.expander(f"{pin.get('icon', '📍')} **{pin.get('title', '')}** (位置: 横{pin.get('x')}% / 縦{pin.get('y')}%)"):
                col_e1, col_e2, col_e3 = st.columns([0.1, 0.45, 0.45])
                cur_vis = pin.get("visible", True)
                new_vis = col_e1.checkbox("表示", value=cur_vis, key=f"pin_vis_{p_id}")
                if new_vis != cur_vis:
                    plan_doc_ref.collection("pins").document(p_id).update({"visible": new_vis})
                    st.rerun()
                edit_name = col_e2.text_input("ポイント名編集", value=pin.get("title", ""), key=f"edit_name_{p_id}")
                edit_memo = col_e3.text_area("メモ編集", value=pin.get("memo", ""), key=f"edit_memo_{p_id}")
                btn_cols = st.columns([1, 1, 8])
                if btn_cols[0].button("💾 保存", key=f"save_pin_{p_id}"):
                    plan_doc_ref.collection("pins").document(p_id).update({"title": edit_name, "memo": edit_memo})
                    st.success("ピン情報を更新しました！")
                    st.rerun()
                if btn_cols[1].button("🗑️ 削除", key=f"del_pin_{p_id}"):
                    plan_doc_ref.collection("pins").document(p_id).delete()
                    st.rerun()

# =========================================================
# ⑥ 天気・風予報（3時間おきグラフィカル表示）
# =========================================================
with tab6:
    st.header("🌤️ 釣場ポイントのピンポイント気象・風予報")
    itin_docs = plan_doc_ref.collection("itinerary").order_by("date_time").stream()
    itin_list = [d.to_dict() for d in itin_docs]
    default_loc = ""
    default_date = s_date_obj
    if itin_list:
        default_loc = itin_list[0].get("location", "")
        try:
            default_date = datetime.strptime(itin_list[0].get("date_time", "").split()[0], "%Y-%m-%d").date()
        except:
            pass

    if "num_forecast_days" not in st.session_state:
        st.session_state.num_forecast_days = 1

    col_s1, col_s2, col_s3, col_btn1, col_btn2 = st.columns([2.5, 1.5, 1, 0.5, 0.5])
    search_query = col_s1.text_input("釣場・スポット名を入力", value=default_loc, placeholder="例: 奥多摩湖、神津島など", key="weather_search_input")
    target_date = col_s2.date_input("日付を選択（過去・未来対応）", value=default_date, key="target_date_select")
    
    if "target_coords" not in st.session_state or st.session_state.target_coords is None:
        if default_loc:
            lat, lon, found_name = geocode_location_jp(default_loc)
            if lat and lon:
                st.session_state.target_coords = {"lat": lat, "lon": lon, "name": found_name}

    if col_s3.button("検索＆確定", key="btn_confirm_loc"):
        if search_query:
            lat, lon, found_name = geocode_location_jp(search_query)
            if lat and lon:
                st.session_state.target_coords = {"lat": lat, "lon": lon, "name": found_name}
                st.success(f"「{found_name}」の情報を取得しました！")
            else:
                st.error("指定されたスポットが見つかりませんでした。")

    if col_btn1.button("＋ 1日"):
        st.session_state.num_forecast_days = min(7, st.session_state.num_forecast_days + 1)
        st.rerun()
    if col_btn2.button("ー 1日"):
        st.session_state.num_forecast_days = max(1, st.session_state.num_forecast_days - 1)
        st.rerun()

    st.divider()
    if st.session_state.get("target_coords"):
        coords = st.session_state.target_coords
        n_days = st.session_state.num_forecast_days
        st.subheader(f"📍 {coords['name']} の気象予報・実績 (3時間ごと / {target_date} から {n_days} 日間)")
        weather_cards = fetch_weather_3h_smart(coords["lat"], coords["lon"], target_date, num_days=n_days)
        if weather_cards:
            cols = st.columns(4)
            for idx, w in enumerate(weather_cards):
                with cols[idx % 4]:
                    st.markdown(f"""
                    <div style="background: #f0f4f8; border-radius: 10px; padding: 12px; margin-bottom: 12px; border-left: 4px solid #2a5298; text-align: center;">
                        <span style="font-size: 12px; color: #666; font-weight: bold;">{w['date_time']}</span>
                        <div style="font-size: 36px; margin: 4px 0;">{w['icon']}</div>
                        <div style="font-size: 13px; font-weight: bold; color: #333;">{w['desc']}</div>
                        <hr style="margin: 8px 0; border: none; border-top: 1px solid #ddd;"/>
                        <div style="font-size: 14px; color: #d35400;">🌡️ <b>{w['temp']}</b></div>
                        <div style="font-size: 13px; color: #2980b9;">🚩 風: <b>{w['dir']} ({w['speed']})</b></div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.warning("指定された日付の気象データを取得できませんでした。")
    else:
        st.info("👆 行程表に登録された場所の予報が自動セットされます。別の場所を見る場合は検索欄に入力して「検索＆確定」を押してください。")

# =========================================================
# ⑦ 簡易説明書 & 📄 デザイン強化版 遠征しおり
# =========================================================
with tab7:
    st.header("📖 簡易説明書 & 📄 遠征のしおり発行")
    st.subheader("📄 遠征のしおり（1枚デザイン・レポート）")
    if "show_report_card" not in st.session_state:
        st.session_state.show_report_card = False

    col_rep1, col_rep2 = st.columns([1, 1])
    if col_rep1.button("📄 しおり（レポート）を生成・表示", key="btn_gen_report", type="primary"):
        st.session_state.show_report_card = True

    if st.session_state.show_report_card:
        if col_rep2.button("🙈 しおりを非表示にする（閉じる）", key="btn_hide_report"):
            st.session_state.show_report_card = False
            st.rerun()

        exp_docs = plan_doc_ref.collection("expenses").stream()
        exp_list = [d.to_dict() for d in exp_docs]
        total_exp = sum([int(e.get("amount", 0)) for e in exp_list])
        per_person = int(total_exp / len(members)) if members else 0
        
        catches_docs = plan_doc_ref.collection("catches").stream()
        catches_list = [d.to_dict() for d in catches_docs]
        itin_docs = plan_doc_ref.collection("itinerary").order_by("date_time").stream()
        itin_list = [d.to_dict() for d in itin_docs]
        
        big_fish_title = "-"
        if catches_list:
            sorted_catches = sorted(catches_list, key=lambda x: float(x.get("size", 0)), reverse=True)
            big_fish_title = f"{sorted_catches[0].get('species', '-')} ({sorted_catches[0].get('size', 0)}cm)"

        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #eef2f3 0%, #8e9eab 100%); border-radius: 12px; padding: 20px; color: #333; margin-bottom: 20px;">
            <h2 style="color: #1e3c72; margin-top: 0;">🎣 {selected_plan_name} 遠征レポート</h2>
            <p>🗓️ {s_date} 〜 {e_date} | 👥 メンバー: {', '.join(members)}</p>
            <hr/>
            <p>💰 <b>総費用:</b> ¥{total_exp:,} (1人あたり: ¥{per_person:,})</p>
            <p>🏆 <b>ビッグワン:</b> {big_fish_title}</p>
        </div>
        """, unsafe_allow_html=True)

        st.subheader("🗓️ 旅の行程一覧")
        if itin_list:
            for itin in itin_list:
                st.write(f"- **{itin.get('date_time')}** @ {itin.get('location')} : {itin.get('activity')}")
        else:
            st.caption("行程未登録")

        st.subheader("🐟 釣果アーカイブ")
        if catches_list:
            for c in catches_list:
                st.write(f"- **{c.get('catch_date')}** : {c.get('species')} ({c.get('size')}cm) @ {c.get('location')}")
        else:
            st.caption("釣果未登録")

    st.divider()
    st.subheader("📖 アプリの簡易ガイド")
    with st.expander("📁 1. 釣行計画の追加・切り替え", expanded=False):
        st.write("* 左側サイドバーから計画の選択・作成・削除を行えます。")
    with st.expander("🗓️ 2. 行程表の使い方", expanded=False):
        st.write("* 集合時間や出港予定などを登録・削除できます。")
    with st.expander("💰 3. 旅費割り勘計算の使い方", expanded=False):
        st.write("* 支出を登録すると、1人あたりの精算額が自動計算されます。")
    with st.expander("🗺️ 4. ポイントマップの使い方", expanded=False):
        st.write("* 画像を選択して「確定・保存」で登録。画像をタップするとオレンジ色の「仮ピン」が置かれます。フォームから保存することで確定され、過去のタップ跡は一切残りません。")
    with st.expander("🌤️ 5. ピンポイント天気・風予報の使い方", expanded=False):
        st.write("* 3時間おきの大きな天気アイコンと気温・風速が確認できます。")
