import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import date, datetime, timedelta
import os
import requests
import streamlit.components.v1 as components
import base64

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

# ---------------------------------------------------------
# 地名検索（国内高精度対応）
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

def get_weather_desc(code):
    mapping = {
        0: "☀️ 晴天", 1: "🌤️ ほぼ晴れ", 2: "⛅ 時々曇り", 3: "☁️ 曇り",
        45: "🌫️ 霧", 48: "🌫️ 着氷性の霧",
        51: "🌧️ 小雨", 53: "🌧️ 雨", 55: "🌧️ 強い雨",
        61: "☔ 雨", 63: "☔ やや強い雨", 65: "☔ 激しい雨",
        80: "🌦️ にわか雨", 81: "🌦️ 強いにわか雨", 82: "⛈️ 激しいにわか雨"
    }
    return mapping.get(code, "☁️ 天気")

@st.cache_data(ttl=3600)
def fetch_weather_for_dates(lat, lon, start_date_obj, num_days=1):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=weathercode,windspeed_10m,winddirection_10m&forecast_days=14&timezone=Asia%2FTokyo"
        res = requests.get(url).json()
        
        if "hourly" in res:
            df_h = pd.DataFrame({
                "time": res["hourly"]["time"],
                "code": res["hourly"]["weathercode"],
                "speed": res["hourly"]["windspeed_10m"],
                "deg": res["hourly"]["winddirection_10m"]
            })
            
            target_dates = [(start_date_obj + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
            
            df_filtered = df_h[df_h["time"].apply(lambda x: x.split("T")[0] in target_dates)].copy()
            if not df_filtered.empty:
                df_filtered["日付・時間"] = df_filtered["time"].apply(lambda x: f"{x.split('T')[0][5:]} {x.split('T')[1][:5]}")
                df_filtered["天気"] = df_filtered["code"].apply(get_weather_desc)
                df_filtered["風速"] = df_filtered["speed"].apply(lambda x: f"{x:.1f} m/s")
                df_filtered["風向き"] = df_filtered["deg"].apply(get_wind_direction_16)
                return df_filtered[["日付・時間", "天気", "風速", "風向き"]]
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

# 日付データの取得と検証
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

# 日程変更UI
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

# 新規計画の追加
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

# 計画の削除
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
                    "date_time": dt_str,
                    "location": location,
                    "activity": activity,
                    "created_at": datetime.now()
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
                    "category": exp_cat,
                    "item": exp_item,
                    "amount": int(exp_amount),
                    "payer": exp_payer,
                    "memo": exp_memo,
                    "created_at": datetime.now()
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
            st.dataframe(
                payer_summary.rename(columns={"payer": "支払者", "amount": "合計立替額"}),
                use_container_width=True
            )

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
                "item": new_item,
                "assignee": assignee,
                "checked": False,
                "created_at": datetime.now()
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
                plan_doc_ref.collection("checklist").document(item_id).update({
                    "checked": new_status
                })
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
                    os.makedirs("uploads", exist_ok=True)
                    img_path = os.path.join("uploads", f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{c_img.name}")
                    with open(img_path, "wb") as f:
                        f.write(c_img.getbuffer())
                
                plan_doc_ref.collection("catches").add({
                    "catch_date": str(c_date),
                    "location": c_loc,
                    "species": c_species,
                    "size": float(c_size),
                    "count": int(c_count),
                    "lure": c_lure,
                    "notes": c_notes,
                    "image_path": img_path,
                    "created_at": datetime.now()
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
# ⑤ ポイントマップ
# =========================================================
with tab5:
    st.header(f"🗺️ {selected_plan_name} - ポイントマップ")
    
    col_map1, col_map2 = st.columns([1.2, 1])
    
    with col_map1:
        st.subheader("1. 釣場画像・図面の登録")
        map_img_file = st.file_uploader("航空写真やマップ画像をアップロード", type=["jpg", "jpeg", "png"], key="map_img_upload")
        
        map_doc = plan_doc_ref.collection("map_config").document("current").get()
        current_map_path = map_doc.to_dict().get("image_path") if map_doc.exists else ""
        
        if map_img_file is not None:
            os.makedirs("uploads", exist_ok=True)
            saved_map_path = os.path.join("uploads", f"map_{plan_id}_{map_img_file.name}")
            with open(saved_map_path, "wb") as f:
                f.write(map_img_file.getbuffer())
            plan_doc_ref.collection("map_config").document("current").set({"image_path": saved_map_path})
            st.success("マップ画像を登録しました！")
            st.rerun()
            
    with col_map2:
        st.subheader("2. ピン（ポイントメモ）の打刻")
        pin_title = st.text_input("ポイント名", placeholder="例: 1番船着き場 / 手前の根", key="pin_title_in")
        pin_memo = st.text_input("状況・メモ", placeholder="例: 手前5m根掛かり注意 / 水深6m", key="pin_memo_in")
        pin_icon = st.selectbox("アイコンタイプ", ["📍 ポイント", "🎯 ヒット実績", "⚠️ 危険・注意", "⚓ 渡船・集合"], key="pin_icon_in")
        
        col_pos1, col_pos2 = st.columns(2)
        pos_x = col_pos1.slider("位置 (横方向 %)", 0, 100, 50, key="pin_x_in")
        pos_y = col_pos2.slider("位置 (縦方向 %)", 0, 100, 50, key="pin_y_in")
        
        if st.button("ピンを設置", key="btn_add_pin") and pin_title:
            plan_doc_ref.collection("pins").add({
                "title": pin_title,
                "memo": pin_memo,
                "icon": pin_icon.split()[0],
                "x": pos_x,
                "y": pos_y,
                "visible": True,
                "created_at": datetime.now()
            })
            st.success(f"「{pin_title}」にピンを打刻しました！")
            st.rerun()

    st.divider()

    pins_docs = plan_doc_ref.collection("pins").stream()
    pins_list = [{"id": d.id, **d.to_dict()} for d in pins_docs]
    
    col_ctrl1, col_ctrl2 = st.columns([1, 2])
    show_all_pins = col_ctrl1.toggle("全ピンを一括表示/非表示", value=True, key="toggle_all_pins")
    
    if current_map_path and os.path.exists(current_map_path):
        st.subheader("📍 ポイントマップ プレビュー")
        
        with open(current_map_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
        
        pins_html = ""
        if show_all_pins:
            for p in pins_list:
                if p.get("visible", True):
                    pins_html += f"""
                    <div style="position: absolute; left: {p.get('x', 50)}%; top: {p.get('y', 50)}%; transform: translate(-50%, -50%); cursor: pointer;" title="{p.get('title')} ({p.get('memo')})">
                        <span style="font-size: 24px;">{p.get('icon', '📍')}</span>
                        <span style="background: rgba(0,0,0,0.75); color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; white-space: nowrap;">{p.get('title')}</span>
                    </div>
                    """
        
        map_container_html = f"""
        <div style="position: relative; width: 100%; max-width: 900px; margin: 0 auto; border: 2px solid #ddd; border-radius: 8px; overflow: hidden;">
            <img src="data:image/png;base64,{encoded_string}" style="width: 100%; display: block;" />
            {pins_html}
        </div>
        """
        components.html(map_container_html, height=500, scrolling=True)
    else:
        st.info("上のエリアからマップ・航空写真画像をアップロードすると、ここにピン付きマップが表示されます。")

    if pins_list:
        st.subheader("📋 ポイント一覧・表示切替・削除")
        for pin in pins_list:
            p_id = pin["id"]
            cols = st.columns([0.1, 0.3, 0.4, 0.1, 0.1])
            
            cur_vis = pin.get("visible", True)
            new_vis = cols[0].checkbox("", value=cur_vis, key=f"pin_vis_{p_id}")
            if new_vis != cur_vis:
                plan_doc_ref.collection("pins").document(p_id).update({"visible": new_vis})
                st.rerun()
                
            cols[1].write(f"{pin.get('icon', '📍')} **{pin.get('title', '')}**")
            cols[2].caption(pin.get("memo", "-"))
            cols[3].caption(f"X:{pin.get('x')}% / Y:{pin.get('y')}%")
            
            if cols[4].button("🗑️", key=f"del_pin_{p_id}"):
                plan_doc_ref.collection("pins").document(p_id).delete()
                st.rerun()

# =========================================================
# ⑥ 天気・風予報（行程表と自動連動・保持版）
# =========================================================
with tab6:
    st.header("🌤️ 釣場ポイントのピンポイント天気・風予報")
    
    # 行程表から最新の場所・日付を自動取得して初期保持
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
    target_date = col_s2.date_input("開始日を選択", value=default_date, key="target_date_select")
    
    # 初回表示時に自動で座標を固定保持
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

    if col_btn1.button("＋ 1日", help="表示日数を1日増やします"):
        st.session_state.num_forecast_days = min(7, st.session_state.num_forecast_days + 1)
        st.rerun()

    if col_btn2.button("ー 1日", help="表示日数を1日減らします"):
        st.session_state.num_forecast_days = max(1, st.session_state.num_forecast_days - 1)
        st.rerun()

    st.divider()

    if st.session_state.get("target_coords"):
        coords = st.session_state.target_coords
        n_days = st.session_state.num_forecast_days
        
        st.subheader(f"📍 {coords['name']} の予報 (表示期間: {target_date} から {n_days} 日間)")
        
        df_weather = fetch_weather_for_dates(coords["lat"], coords["lon"], target_date, num_days=n_days)
        
        if df_weather is not None and not df_weather.empty:
            st.dataframe(df_weather, use_container_width=True, hide_index=True)
        else:
            st.warning("指定された日付の予報データがありません。（※今日から14日以内を選択してください）")
    else:
        st.info("👆 行程表に登録された場所の予報が自動セットされます。別の場所を見る場合は検索欄に入力して「検索＆確定」を押してください。")

# =========================================================
# ⑦ 簡易説明書 & 📄 遠征のしおり発行
# =========================================================
with tab7:
    st.header("📖 簡易説明書 & 📄 遠征のしおり発行")
    
    st.subheader("📄 遠征のしおり（レポート）の発行")
    st.caption("釣行完了後、以下のボタンを押すと全体の思い出や割り勘精算結果をまとめた「しおりカード」が生成されます。")
    
    if st.button("📄 しおり（レポート）を生成・表示", key="btn_generate_report", type="primary"):
        exp_docs = plan_doc_ref.collection("expenses").stream()
        exp_list = [d.to_dict() for d in exp_docs]
        total_exp = sum([int(e.get("amount", 0)) for e in exp_list])
        per_person = int(total_exp / len(members)) if members else 0
        
        catches_docs = plan_doc_ref.collection("catches").stream()
        catches_list = [d.to_dict() for d in catches_docs]
        
        max_size = 0.0
        big_fish = "-"
        if catches_list:
            sorted_catches = sorted(catches_list, key=lambda x: float(x.get("size", 0)), reverse=True)
            max_size = sorted_catches[0].get("size", 0)
            big_fish = f"{sorted_catches[0].get('species', '-')} ({max_size}cm)"
            
        report_html = f"""
        <div style="background: #f8f9fa; border: 2px solid #2b5c8f; border-radius: 12px; padding: 24px; font-family: sans-serif; max-width: 800px; margin: 0 auto;">
            <div style="text-align: center; border-bottom: 2px solid #2b5c8f; padding-bottom: 12px; margin-bottom: 20px;">
                <h1 style="color: #2b5c8f; margin: 0;">🎣 {selected_plan_name} 遠征しおり</h1>
                <p style="color: #666; margin: 5px 0 0 0;">🗓️ {s_date} 〜 {e_date} | 👥 {', '.join(members)}</p>
            </div>
            
            <div style="display: flex; gap: 15px; margin-bottom: 20px;">
                <div style="flex: 1; background: #eef5fc; padding: 15px; border-radius: 8px; text-align: center;">
                    <span style="font-size: 12px; color: #555;">💰 総費用 (1人あたり)</span>
                    <h3 style="margin: 5px 0; color: #2b5c8f;">¥{total_exp:,} (¥{per_person:,})</h3>
                </div>
                <div style="flex: 1; background: #fff3cd; padding: 15px; border-radius: 8px; text-align: center;">
                    <span style="font-size: 12px; color: #555;">🏆 ビッグワン記録</span>
                    <h3 style="margin: 5px 0; color: #856404;">{big_fish}</h3>
                </div>
            </div>
            
            <h3 style="color: #2b5c8f; border-left: 4px solid #2b5c8f; padding-left: 8px;">🐟 釣果ハイライト ({len(catches_list)}件)</h3>
            <ul style="line-height: 1.8; color: #333;">
        """
        for c in catches_list[:5]:
            report_html += f"<li><b>{c.get('catch_date')}</b> - {c.get('species')} {c.get('size')}cm ({c.get('location')}) - {c.get('lure')}</li>"
            
        report_html += """
            </ul>
            <div style="text-align: right; margin-top: 20px; font-size: 12px; color: #888;">
                Generated by 共有釣行管理アプリ
            </div>
        </div>
        """
        
        components.html(report_html, height=450, scrolling=True)
        st.info("💡 上の「しおりカード」をスマホでスクリーンショット撮影すると、LINE等で簡単に共有できます！")

    st.divider()

    st.subheader("📖 アプリの簡易ガイド")
    
    with st.expander("📁 1. 釣行計画の追加・切り替え", expanded=False):
        st.write("""
        * **切り替え**: 左側サイドバーの「現在の計画」からいつでも過去・未来の遠征を選択できます。
        * **日程更新**: サイドバーの「開始日・終了日」を変更するとリアルタイムで全体に反映されます。
        * **新規追加**: サイドバーの「➕ 新しい計画を追加」から仲間との遠征を追加できます。
        """)

    with st.expander("🗓️ 2. 行程表の使い方", expanded=False):
        st.write("""
        * 集合時間、フェリー乗船、出港時間、宿泊先の予定を登録できます。
        * 各予定の右側にある **ゴミ箱アイコン（🗑️）** で不要になった予定を即座に削除できます。
        """)

    with st.expander("💰 3. 旅費割り勘計算の使い方", expanded=False):
        st.write("""
        * 船代、高速代、ガソリン代、エサ代を「誰が払ったか」と一緒に登録するだけ！
        * 1人あたりの平均負担額と、個人ごとの「立替・精算金額」が自動計算されます。
        """)

    with st.expander("🗺️ 4. ポイントマップの使い方", expanded=False):
        st.write("""
        * 航空写真や釣り場マップ画像をアップロードし、X%・Y%のスライダーでピンを打刻できます。
        * 「全ピン一括表示/非表示」トグルスイッチや、個別のチェックボックスでマップの見やすさを自由に調整可能です。
        """)

    with st.expander("🌤️ 5. ピンポイント天気・風予報の使い方", expanded=False):
        st.write("""
        * 行程表に登録した場所と日付が自動的にセットされて表示・固定保存されます。
        * 「＋1日」「ー1日」ボタンで表示日数を調整し、釣り場の風速・風向き・天気をピンポイントで確認できます。
        """)
