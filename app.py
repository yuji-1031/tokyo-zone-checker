# -*- coding: utf-8 -*-

import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
import warnings
import sys
import os
import pyproj
import pydeck as pdk
import traceback
import requests
import urllib.parse
import datetime

# --- Streamlit ページ設定 ---
st.set_page_config(layout="wide", page_title="東京都 用途地域チェッカー")

# --- 設定 ---
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
SHAPEFILE_DIR = "shapefiles"
SHAPEFILE_NAME = "用途地域.shp"
shapefile_path = os.path.join(APP_ROOT, SHAPEFILE_DIR, SHAPEFILE_NAME)

youto_code_map = {
    1: "第1種低層住居専用地域", 2: "第2種低層住居専用地域",
    3: "第1種中高層住居専用地域", 4: "第2種中高層住居専用地域",
    5: "第1種住居地域", 6: "第2種住居地域", 7: "準住居地域",
    8: "近隣商業地域", 9: "商業地域", 10: "準工業地域",
    11: "工業地域", 12: "工業専用地域"
}
youto_column_name = 'TUP3F1'

# --- 関数定義 ---

@st.cache_resource
def load_shapefile(path):
    """指定されたパスのシェイプファイルを読み込み、空間インデックスを作成して返す"""
    if not os.path.exists(path):
        st.error(f"エラー: シェイプファイルが見つかりません！\n探しているパス: {path}")
        try:
            folder_path = os.path.dirname(path)
            st.warning(f"'{folder_path}' フォルダの中身を確認します (存在すれば):")
            dir_contents = os.listdir(folder_path)
            if dir_contents: st.warning(dir_contents)
            else: st.warning("フォルダは空か、アクセスできません。")
        except FileNotFoundError: st.warning(f"フォルダ '{os.path.dirname(path)}' 自体が見つかりません。")
        except Exception as e: st.warning(f"フォルダ内容の確認中にエラーが発生しました: {e}")
        return None
    try:
        gdf = gpd.read_file(path, encoding='cp932')
        gdf.sindex
        print(f"シェイプファイル読み込み成功: {path}")
        return gdf
    except FileNotFoundError:
         print(f"エラー: シェイプファイルが見つかりません (geopandas読み込み時): {path}")
         st.error(f"エラー: シェイプファイルを読み込めませんでした。パスを確認してください: {path}")
         return None
    except Exception as e:
        print(f"予期せぬエラー（シェイプファイル読み込み中）: {e}")
        traceback.print_exc()
        st.error(f"シェイプファイル読み込み中に予期せぬエラーが発生しました。\n"
                 f"ファイルパス: {path}\nエラー詳細: {e}")
        return None

@st.cache_data
def geocode_address(address):
    """住所文字列から緯度経度を取得する (国土地理院API)"""
    if not address: return None, None, "住所が入力されていません。"
    print(f"地理院地図APIでジオコーディング実行: {address}")
    try:
        encoded_address = urllib.parse.quote(address); url = f"https://msearch.gsi.go.jp/address-search/AddressSearch?q={encoded_address}"
        response = requests.get(url, timeout=10); response.raise_for_status(); data = response.json()
        if data and len(data) > 0:
            coordinates = data[0].get("geometry", {}).get("coordinates")
            if coordinates and len(coordinates) == 2: longitude, latitude = coordinates; address_detail = data[0].get("properties", {}).get("title", address); print(f"地理院地図 ジオコーディング成功: Lat={latitude}, Lon={longitude}"); return latitude, longitude, f"地理院地図によるジオコーディング成功: {address_detail}"
            else: print(f"地理院地図 座標取得失敗: {address}"); return None, None, "エラー: 地理院地図APIから座標データを取得できませんでした。"
        else: print(f"地理院地図 住所見つからず: {address}"); return None, None, f"エラー: 住所「{address}」を地理院地図で見つけられませんでした。"
    except requests.exceptions.Timeout: print(f"地理院地図API タイムアウト: {address}"); return None, None, "エラー: 地理院地図APIへの接続がタイムアウトしました。"
    except requests.exceptions.RequestException as e: print(f"地理院地図API 接続エラー: {e}"); return None, None, f"エラー: 地理院地図APIへの接続に失敗しました: {e}"
    except Exception as e: print(f"地理院地図API 予期せぬエラー: {e}"); traceback.print_exc(); return None, None, f"予期せぬエラー（地理院地図ジオコーディング）: {e}"

def find_and_display_zone(latitude, longitude, gdf):
    """指定された緯度経度で空間検索し、結果をStreamlit上に表示する"""
    if gdf is None: st.error("シェイプファイルが読み込まれていないため、検索を実行できません。"); return
    if latitude is None or longitude is None or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180): st.warning("有効な緯度経度が指定されていません。"); return

    st.info(f"検索座標 (WGS84): Latitude={latitude:.6f}, Longitude={longitude:.6f}")
    try:
        # 1. 検索点をGeoDataFrameに変換 (WGS84: EPSG:4326)
        point_geom_wgs84 = Point(longitude, latitude); point_gdf_wgs84 = gpd.GeoDataFrame([1], geometry=[point_geom_wgs84], crs="EPSG:4326")

        # 2. シェイプファイルのCRSを取得
        target_crs = gdf.crs
        if target_crs is None: st.error("シェイプファイルの座標参照系(CRS)が不明です。検索を実行できません。"); return

        # 3. 検索点の座標系をシェイプファイルに合わせる
        point_gdf_proj = point_gdf_wgs84.to_crs(target_crs); point_proj = point_gdf_proj.geometry.iloc[0]
        st.write(f"シェイプファイルの座標系 ({target_crs}) に変換しました: X={point_proj.x:.4f}, Y={point_proj.y:.4f}")

        # ▼▼▼ ここから空間検索ロジックを修正 ▼▼▼
        # 4. 空間検索 (指定した点が含まれる、または重なるポリゴンを探す)
        print(f"空間検索実行: 点={point_proj}") # サーバーログ用
        st.write(f"検索点 (投影座標系): {point_proj}") # Streamlit画面に検索点を表示（デバッグ用）

        # GeoDataFrameの空間インデックスを利用して候補を検索
        # predicate を 'contains' から 'intersects' に変更して、少し広く候補を探す
        try:
            possible_matches_index = list(gdf.sindex.query(point_proj, predicate='intersects')) # ★ intersects に変更
            st.write(f"空間インデックス検索 (intersects) の候補インデックス: {possible_matches_index}") # 候補インデックスを表示
            st.write(f"空間インデックス検索 (intersects) の候補数: {len(possible_matches_index)}") # 候補数を表示
        except Exception as sindex_err:
            st.error(f"空間インデックス検索中にエラーが発生しました: {sindex_err}")
            possible_matches_index = [] # エラー時は空リスト

        if not possible_matches_index:
             st.warning("空間インデックス検索 (intersects) で候補が見つかりませんでした。")
             containing_polygon = gpd.GeoDataFrame() # 空のGeoDataFrameを作成
        else:
            try:
                possible_matches = gdf.iloc[possible_matches_index]
                st.write(f"候補ポリゴン数: {len(possible_matches)}")

                # デバッグ用に候補ポリゴンの geometry タイプを表示
                # st.write(f"候補ポリゴンのGeometryタイプ:\n{possible_matches.geometry.geom_type}")

                # 厳密な包含判定 (contains) を試みる
                containing_polygon_strict = possible_matches[possible_matches.geometry.contains(point_proj)]
                st.write(f"厳密な包含判定 (contains) の結果数: {len(containing_polygon_strict)}") # containsの結果数を表示

                # もし contains で見つからなくても、intersects で候補があればそれを結果として採用する
                if not containing_polygon_strict.empty:
                    containing_polygon = containing_polygon_strict
                    st.info("厳密な包含判定 (contains) でポリゴンが見つかりました。")
                else:
                    # intersects した候補の中から、実際に点と交差するものだけを再フィルタリング (より安全)
                    intersecting_polygons = possible_matches[possible_matches.geometry.intersects(point_proj)]
                    if not intersecting_polygons.empty:
                         containing_polygon = intersecting_polygons # intersects したものを結果とする
                         st.warning("厳密な包含判定では見つかりませんでしたが、交差(intersects)するポリゴンを採用しました。")
                         st.write(f"採用したポリゴン数 (intersects): {len(containing_polygon)}")
                    else:
                         containing_polygon = gpd.GeoDataFrame() # intersectsでも見つからなかった
                         st.warning("空間インデックス(intersects)で候補はありましたが、厳密な交差判定では見つかりませんでした。")

            except Exception as filter_err:
                 st.error(f"候補ポリゴンのフィルタリング中にエラーが発生しました: {filter_err}")
                 containing_polygon = gpd.GeoDataFrame() # エラー時は空

        print(f"検索結果ポリゴン数 (最終): {len(containing_polygon)}") # サーバーログ用
        # ▲▲▲ ここまで空間検索ロジック修正 ▲▲▲

        # 5. 結果の表示
        st.subheader("検索結果")
        if not containing_polygon.empty:
            # 以前はここでst.successを表示していたが、intersectsの場合もあるのでメッセージを調整
            if '厳密な包含判定 (contains) でポリゴンが見つかりました。' in st.session_state.get('info_messages', []): # 仮のチェック方法
                 st.success("指定された地点は以下の用途地域に含まれます。")
            else:
                 st.warning("指定された地点に交差する以下の用途地域が見つかりました。(境界付近の可能性があります)")

            # 複数のポリゴンに重なって含まれる/交差する場合も考慮
            for index, row in containing_polygon.iterrows():
                 with st.container(border=True):
                    youto_code = row.get(youto_column_name, None); youto_name = youto_code_map.get(youto_code, f"不明なコード({youto_code})") if youto_code is not None else "取得不可"; st.markdown(f"**用途地域:** {youto_name} (コード: {youto_code})")
                    cols = st.columns(2)
                    with cols[0]:
                        try: val = row.get('TUP3F3', None); st.metric(label="容積率 (TUP3F3)", value=f"{int(val)}%" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="容積率 (TUP3F3)", value=f"{val} (数値変換エラー)")
                        try: val = row.get('TUP3F5', None); st.metric(label="外壁後退距離 (TUP3F5)", value=f"{float(val):.1f}m" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="外壁後退距離 (TUP3F5)", value=f"{val} (数値変換エラー)")
                        try: val = row.get('TUP3F7', None); st.metric(label="特例容積率区域 (TUP3F7)", value="該当" if val == 1 else ("非該当" if val == 0 else "N/A"))
                        except: st.metric(label="特例容積率区域 (TUP3F7)", value=f"{val} (エラー)")
                    with cols[1]:
                        try: val = row.get('TUP3F4', None); st.metric(label="建ぺい率 (TUP3F4)", value=f"{int(val)}%" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="建ぺい率 (TUP3F4)", value=f"{val} (数値変換エラー)")
                        try: val = row.get('TUP3F6', None); st.metric(label="敷地面積最低限度 (TUP3F6)", value=f"{int(val)}㎡" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="敷地面積最低限度 (TUP3F6)", value=f"{val} (数値変換エラー)")
                        try: val = row.get('TAKASA', None); st.metric(label="高さ最高限度 (TAKASA)", value=f"{int(val)}m" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="高さ最高限度 (TAKASA)", value=f"{val} (数値変換エラー)")

            # --- 地図表示 (pydeck) ---
            st.subheader("地図表示")
            try:
                point_data_for_deck = point_gdf_wgs84[['geometry']].copy()
                point_data_for_deck['coordinates'] = point_data_for_deck.geometry.apply(lambda p: [p.x, p.y])
                point_layer = pdk.Layer(
                    "ScatterplotLayer", data=point_data_for_deck, get_position="coordinates",
                    get_color="[255, 0, 0, 200]", get_radius=15, radius_min_pixels=7, pickable=True, )

                # ▼ オプション: 該当ポリゴンも表示する場合（intersectsで複数になる可能性あり）▼
                polygon_disp_gdf = containing_polygon.to_crs("EPSG:4326")
                polygon_geojson = polygon_disp_gdf.__geo_interface__
                polygon_layer = pdk.Layer(
                    "GeoJsonLayer", data=polygon_geojson, opacity=0.3, stroked=True, filled=True,
                    extruded=False, wireframe=True, get_fill_color='[255, 255, 0, 90]',
                    get_line_color=[255, 255, 0, 200], get_line_width=5, line_width_min_pixels=1, pickable=True,)
                # ▲▲▲

                view_state = pdk.ViewState(latitude=latitude, longitude=longitude, zoom=16, pitch=45, bearing=0)
                deck = pdk.Deck(
                    # ▼ ポリゴンも表示する場合は polygon_layer を追加 ▼
                    layers=[point_layer, polygon_layer],
                    initial_view_state=view_state, map_style='mapbox://styles/mapbox/light-v10',
                    tooltip={"text": f"検索地点\nLat: {latitude:.6f}\nLon: {longitude:.6f}"})
                st.pydeck_chart(deck)
                st.success("地図表示完了 (pydeck - ポイント＋該当エリア)") # メッセージ変更

            except ImportError:
                st.info("地図表示ライブラリ `pydeck` が見つかりません。簡易地図を表示します。")
                map_df = pd.DataFrame({'lat': [latitude], 'lon': [longitude]}); st.map(map_df, zoom=16)
            except Exception as map_e:
                st.warning(f"pydeck地図表示中にエラーが発生しました: {map_e}"); traceback.print_exc()
                st.info("簡易地図を表示します。"); map_df = pd.DataFrame({'lat': [latitude], 'lon': [longitude]}); st.map(map_df, zoom=16)

        else: # if not containing_polygon.empty: のelse (データが見つからなかった場合)
            # メッセージは検索ロジック内で表示済みのはず
            # st.warning("指定された座標に対応する用途地域データが見つかりませんでした。") # 重複するのでコメントアウト
            st.subheader("地図表示 (検索地点)"); map_df = pd.DataFrame({'lat': [latitude], 'lon': [longitude]}); st.map(map_df, zoom=16)

    except Exception as e: st.error(f"予期せぬエラー（空間検索・表示処理中）: {e}"); traceback.print_exc()

# --- Streamlit アプリケーションの UI 構築 ---

st.title("東京都 用途地域チェッカー")
st.caption("住所または緯度経度を入力して、東京都の用途地域情報を検索します。")

# --- シェイプファイルの読み込み実行 ---
gdf_youto = load_shapefile(shapefile_path)

if gdf_youto is None:
    st.error("シェイプファイルの読み込みに失敗したため、アプリケーションを開始できません。")
    st.warning(f"確認されたシェイプファイルパス: {shapefile_path}")
    st.warning(f"上記のパスにシェイプファイル一式 (最低でも .shp, .shx, .dbf) が存在するか確認してください。")
    st.stop()
else:
    # ▼▼▼ デバッグ用の sindex 情報表示をコメントアウト ▼▼▼
    # with st.expander("空間インデックス情報 (デバッグ用)"):
    #    st.help(gdf_youto.sindex)
    # ▲▲▲

    with st.expander("シェイプファイル情報"):
        st.success(f"シェイプファイル読み込み完了: {os.path.basename(shapefile_path)}")
        st.write(f"座標参照系(CRS): {gdf_youto.crs}")
        st.write(f"データ(ポリゴン)数: {len(gdf_youto)}")
        st.write(f"属性カラム数: {len(gdf_youto.columns)}")
        try: mod_time = os.path.getmtime(shapefile_path); dt_object = datetime.datetime.fromtimestamp(mod_time); st.write(f"ファイル最終更新日時: {dt_object.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e: st.write(f"ファイル更新日時の取得に失敗しました: {e}")

# --- 入力UI ---
search_method = st.radio(
    "検索方法を選択:", ("住所で検索", "緯度経度で検索"), horizontal=True, key="search_method")

latitude, longitude = None, None; address = ""; manual_lat, manual_lon = None, None
if 'search_clicked' not in st.session_state: st.session_state.search_clicked = False
search_button_pressed = False
# ▼ デバッグメッセージ保存用 ▼
if 'info_messages' not in st.session_state: st.session_state.info_messages = []

if search_method == "住所で検索":
    address = st.text_input("住所を入力してください (例: 東京都千代田区九段北4-1-3):", key="address_input")
    if st.button("住所から検索実行", key="geocode_search_button"):
        if address:
            st.session_state.search_clicked = True; search_button_pressed = True
            st.session_state.manual_lat = None; st.session_state.manual_lon = None
            st.session_state.info_messages = [] # メッセージリストをクリア
            with st.spinner("地理院地図APIで座標を検索中..."): latitude, longitude, geo_message = geocode_address(address)
            st.info(geo_message)
            if latitude is None or longitude is None: st.error("座標を取得できなかったため、検索を実行できません。"); st.session_state.search_clicked = False
        else: st.warning("住所を入力してください。"); st.session_state.search_clicked = False
elif search_method == "緯度経度で検索":
    col1, col2 = st.columns(2)
    with col1: manual_lat = st.number_input("緯度 (Latitude) を入力:", format="%.6f", value=st.session_state.get('manual_lat', None), help="例: 35.692669", key="lat_input"); st.session_state.manual_lat = manual_lat
    with col2: manual_lon = st.number_input("経度 (Longitude) を入力:", format="%.6f", value=st.session_state.get('manual_lon', None), help="例: 139.740238", key="lon_input"); st.session_state.manual_lon = manual_lon
    latitude = manual_lat; longitude = manual_lon
    if st.button("緯度経度で検索実行", key="latlon_search_button"):
        if latitude is not None and longitude is not None and -90 <= latitude <= 90 and -180 <= longitude <= 180:
             st.session_state.search_clicked = True; search_button_pressed = True
             st.session_state.info_messages = [] # メッセージリストをクリア
        else: st.warning("有効な緯度と経度を入力してください。"); st.session_state.search_clicked = False

# --- 検索実行と結果表示 ---
if st.session_state.search_clicked:
    if latitude is not None and longitude is not None and latitude != 0 and longitude != 0:
        with st.spinner("用途地域を検索中..."): find_and_display_zone(latitude, longitude, gdf_youto)
    elif search_button_pressed: pass
    else: st.warning("検索を実行するための有効な座標がありません。")
    # st.session_state.search_clicked = False # 必要ならコメントアウト解除

# --- フッター ---
st.divider()
st.caption(
    "注意: このアプリケーションは提供されたデータに基づいて情報を表示します。"
    "最新の情報や正確な情報については、必ず東京都都市整備局等の公式情報をご確認ください。"
    "ジオコーディングには国土地理院 住所検索APIを使用しています。"
)