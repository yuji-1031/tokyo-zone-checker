# -*- coding: utf-8 -*-

import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
import warnings
import sys
# ▼▼▼ 変更/追加箇所 ▼▼▼
import os # ファイルパス操作のためにosモジュールをインポート
# ▲▲▲ 変更/追加箇所 ▲▲▲
import pyproj
import pydeck as pdk
import traceback # エラー詳細表示のためにインポート
import requests
import urllib.parse
import datetime

# --- Streamlit ページ設定 ---
# アプリ全体の基本的な設定 (ページの幅やタイトル)
st.set_page_config(layout="wide", page_title="東京都 用途地域チェッカー")

# --- 設定 ---

# ▼▼▼ 変更/追加箇所：シェイプファイルのパス指定方法を変更 ▼▼▼
# このPythonスクリプトファイル(app.py)がある場所の絶対パスを取得
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# シェイプファイルが入っているフォルダの名前 (実際のフォルダ名に合わせてください)
# 例: プロジェクトフォルダ内に 'shapefiles' というフォルダを作った場合
SHAPEFILE_DIR = "shapefiles"
# シェイプファイルの名前
SHAPEFILE_NAME = "用途地域.shp"
# スクリプトの場所、フォルダ名、ファイル名を結合して、シェイプファイルの完全なパスを作成
# これにより、どこで実行しても正しい場所を指すようになります (相対パス指定)
shapefile_path = os.path.join(APP_ROOT, SHAPEFILE_DIR, SHAPEFILE_NAME)
# ▲▲▲ 変更/追加箇所 ▲▲▲

# 用途地域コードと名称の対応辞書 (変更なし)
youto_code_map = {
    1: "第1種低層住居専用地域", 2: "第2種低層住居専用地域",
    3: "第1種中高層住居専用地域", 4: "第2種中高層住居専用地域",
    5: "第1種住居地域", 6: "第2種住居地域", 7: "準住居地域",
    8: "近隣商業地域", 9: "商業地域", 10: "準工業地域",
    11: "工業地域", 12: "工業専用地域"
}
# シェイプファイル内で用途地域コードが格納されているカラム名 (変更なし)
youto_column_name = 'TUP3F1'

# --- 関数定義 ---

# ▼▼▼ 変更/追加箇所：シェイプファイル読み込み関数を改善 ▼▼▼
@st.cache_resource # シェイプファイルの読み込みは重いのでキャッシュする
def load_shapefile(path):
    """指定されたパスのシェイプファイルを読み込み、空間インデックスを作成して返す"""
    # 1. ファイルが実際に存在するかチェック (デプロイ時に特に重要)
    if not os.path.exists(path):
        st.error(f"エラー: シェイプファイルが見つかりません！\n探しているパス: {path}")
        # 存在しない場合、どのフォルダを見ているか、その中身は何か、デバッグ情報として表示試行
        try:
            folder_path = os.path.dirname(path)
            st.warning(f"'{folder_path}' フォルダの中身を確認します (存在すれば):")
            # listdirの結果が空でないか確認
            dir_contents = os.listdir(folder_path)
            if dir_contents:
                st.warning(dir_contents)
            else:
                st.warning("フォルダは空か、アクセスできません。")
        except FileNotFoundError:
            st.warning(f"フォルダ '{os.path.dirname(path)}' 自体が見つかりません。")
        except Exception as e:
            st.warning(f"フォルダ内容の確認中にエラーが発生しました: {e}")
        return None # ファイルがないのでNoneを返して終了

    # 2. ファイルが存在する場合、geopandasで読み込みを試行
    try:
        gdf = gpd.read_file(path, encoding='cp932') # Shift-JISで読み込み
        gdf.sindex # 空間検索を高速化するためのインデックスを作成 (エラーが出なければOK)
        print(f"シェイプファイル読み込み成功: {path}") # サーバーログ用
        return gdf # 読み込んだGeoDataFrameを返す
    except FileNotFoundError: # geopandas内部でもファイルが見つからないエラーがありうる
         print(f"エラー: シェイプファイルが見つかりません (geopandas読み込み時): {path}")
         st.error(f"エラー: シェイプファイルを読み込めませんでした。パスを確認してください: {path}")
         return None
    except Exception as e: # その他の予期せぬエラー
        print(f"予期せぬエラー（シェイプファイル読み込み中）: {e}")
        traceback.print_exc() # 詳細なエラーログをサーバーのコンソールに出力
        # Streamlit画面にもエラーを表示
        st.error(f"シェイプファイル読み込み中に予期せぬエラーが発生しました。\n"
                 f"ファイルパス: {path}\n"
                 f"エラー詳細: {e}")
        return None # エラー発生時はNoneを返す
# ▲▲▲ 変更/追加箇所 ▲▲▲

@st.cache_data # 住所→座標変換の結果はキャッシュする
def geocode_address(address):
    """住所文字列から緯度経度を取得する (国土地理院API)"""
    if not address:
        return None, None, "住所が入力されていません。"
    print(f"地理院地図APIでジオコーディング実行: {address}") # サーバーログ用
    try:
        encoded_address = urllib.parse.quote(address)
        url = f"https://msearch.gsi.go.jp/address-search/AddressSearch?q={encoded_address}"
        response = requests.get(url, timeout=10) # 10秒でタイムアウト
        response.raise_for_status() # HTTPエラーがあれば例外発生
        data = response.json()

        if data and len(data) > 0:
            coordinates = data[0].get("geometry", {}).get("coordinates")
            if coordinates and len(coordinates) == 2:
                longitude, latitude = coordinates
                address_detail = data[0].get("properties", {}).get("title", address)
                print(f"地理院地図 ジオコーディング成功: Lat={latitude}, Lon={longitude}") # サーバーログ用
                return latitude, longitude, f"地理院地図によるジオコーディング成功: {address_detail}"
            else:
                print(f"地理院地図 座標取得失敗: {address}")
                return None, None, "エラー: 地理院地図APIから座標データを取得できませんでした。"
        else:
            print(f"地理院地図 住所見つからず: {address}")
            return None, None, f"エラー: 住所「{address}」を地理院地図で見つけられませんでした。"
    except requests.exceptions.Timeout:
        print(f"地理院地図API タイムアウト: {address}")
        return None, None, "エラー: 地理院地図APIへの接続がタイムアウトしました。"
    except requests.exceptions.RequestException as e:
        print(f"地理院地図API 接続エラー: {e}")
        return None, None, f"エラー: 地理院地図APIへの接続に失敗しました: {e}"
    except Exception as e:
        print(f"地理院地図API 予期せぬエラー: {e}")
        traceback.print_exc() # サーバーログ用
        return None, None, f"予期せぬエラー（地理院地図ジオコーディング）: {e}"

def find_and_display_zone(latitude, longitude, gdf):
    """指定された緯度経度で空間検索し、結果をStreamlit上に表示する"""
    if gdf is None:
        st.error("シェイプファイルが読み込まれていないため、検索を実行できません。")
        return
    if latitude is None or longitude is None or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        st.warning("有効な緯度経度が指定されていません。")
        return

    st.info(f"検索座標 (WGS84): Latitude={latitude:.6f}, Longitude={longitude:.6f}")
    try:
        # 1. 検索点をGeoDataFrameに変換 (WGS84座標系: EPSG:4326)
        point_geom_wgs84 = Point(longitude, latitude)
        point_gdf_wgs84 = gpd.GeoDataFrame([1], geometry=[point_geom_wgs84], crs="EPSG:4326")

        # 2. シェイプファイルの座標参照系(CRS)を取得
        target_crs = gdf.crs
        if target_crs is None:
            st.error("シェイプファイルの座標参照系(CRS)が不明です。検索を実行できません。")
            # .prjファイルがあるか確認を促すメッセージなどを追加しても良い
            return

        # 3. 検索点の座標系をシェイプファイルに合わせる
        point_gdf_proj = point_gdf_wgs84.to_crs(target_crs)
        point_proj = point_gdf_proj.geometry.iloc[0] # 変換後のジオメトリを取得
        st.write(f"シェイプファイルの座標系 ({target_crs}) に変換しました: X={point_proj.x:.4f}, Y={point_proj.y:.4f}")

        # 4. 空間検索 (指定した点が含まれるポリゴンを探す)
        print(f"空間検索実行: 点={point_proj}") # サーバーログ用
        # GeoDataFrameの空間インデックスを利用して効率的に検索
        possible_matches_index = list(gdf.sindex.query(point_proj, predicate='contains'))
        possible_matches = gdf.iloc[possible_matches_index]
        # 厳密な包含判定
        containing_polygon = possible_matches[possible_matches.geometry.contains(point_proj)]
        print(f"検索結果ポリゴン数: {len(containing_polygon)}") # サーバーログ用

        # 5. 結果の表示
        st.subheader("検索結果")
        if not containing_polygon.empty:
            st.success("指定された地点は以下の用途地域に含まれます。")
            # 複数のポリゴンに重なって含まれる場合も考慮してループ処理
            for index, row in containing_polygon.iterrows():
                 with st.container(border=True): # 結果を枠で囲む
                    # 用途地域名を取得
                    youto_code = row.get(youto_column_name, None)
                    youto_name = youto_code_map.get(youto_code, f"不明なコード({youto_code})") if youto_code is not None else "取得不可"
                    st.markdown(f"**用途地域:** {youto_name} (コード: {youto_code})")

                    # その他の属性情報を表示 (エラーが出ても止まらないようにtry-except)
                    cols = st.columns(2)
                    with cols[0]:
                        try:
                            val = row.get('TUP3F3', None) # 容積率
                            st.metric(label="容積率 (TUP3F3)", value=f"{int(val)}%" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="容積率 (TUP3F3)", value=f"{val} (数値変換エラー)")
                        try:
                            val = row.get('TUP3F5', None) # 外壁後退
                            st.metric(label="外壁後退距離 (TUP3F5)", value=f"{float(val):.1f}m" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="外壁後退距離 (TUP3F5)", value=f"{val} (数値変換エラー)")
                        try:
                            val = row.get('TUP3F7', None) # 特例容積率
                            st.metric(label="特例容積率区域 (TUP3F7)", value="該当" if val == 1 else ("非該当" if val == 0 else "N/A"))
                        except: st.metric(label="特例容積率区域 (TUP3F7)", value=f"{val} (エラー)")
                    with cols[1]:
                        try:
                            val = row.get('TUP3F4', None) # 建ぺい率
                            st.metric(label="建ぺい率 (TUP3F4)", value=f"{int(val)}%" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="建ぺい率 (TUP3F4)", value=f"{val} (数値変換エラー)")
                        try:
                            val = row.get('TUP3F6', None) # 最低敷地面積
                            st.metric(label="敷地面積最低限度 (TUP3F6)", value=f"{int(val)}㎡" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="敷地面積最低限度 (TUP3F6)", value=f"{val} (数値変換エラー)")
                        try:
                            val = row.get('TAKASA', None) # 高さ制限
                            st.metric(label="高さ最高限度 (TAKASA)", value=f"{int(val)}m" if val is not None else "N/A")
                        except (ValueError, TypeError): st.metric(label="高さ最高限度 (TAKASA)", value=f"{val} (数値変換エラー)")

            # --- 地図表示 (pydeck) ---
            st.subheader("地図表示")
            try:
                # 検索地点のデータを準備 (WGS84座標系)
                point_data_for_deck = point_gdf_wgs84[['geometry']].copy() # geometryカラムだけコピー
                # 座標を [経度, 緯度] のリスト形式に変換して新しい列 'coordinates' を作成
                point_data_for_deck['coordinates'] = point_data_for_deck.geometry.apply(lambda p: [p.x, p.y])

                # ポイント(検索地点)を表示するレイヤー
                point_layer = pdk.Layer(
                    "ScatterplotLayer",
                    data=point_data_for_deck,
                    get_position="coordinates", # 'coordinates'列を使う
                    get_color="[255, 0, 0, 200]", # 色を赤色に変更 (RGBA)
                    get_radius=15, # ピンのサイズ
                    radius_min_pixels=7, # ズームアウトしても見える最小サイズ
                    pickable=True, # クリックイベント用 (ここではツールチップのみ)
                )

                # --- ★オプション: 該当ポリゴンも表示する場合★ ---
                # # ポリゴンをWGS84に変換
                # polygon_disp_gdf = containing_polygon.to_crs("EPSG:4326")
                # # GeoJSON形式に変換してpydeckで使えるようにする
                # polygon_geojson = polygon_disp_gdf.__geo_interface__
                # polygon_layer = pdk.Layer(
                #     "GeoJsonLayer",
                #     data=polygon_geojson,
                #     opacity=0.3, # 透明度
                #     stroked=True, # 境界線を描画するか
                #     filled=True, # 塗りつぶすか
                #     extruded=False, # 立体表示はしない
                #     wireframe=True, # ワイヤーフレーム表示
                #     get_fill_color='[255, 255, 0, 90]', # 塗りつぶし色 (黄色、半透明)
                #     get_line_color=[255, 255, 0, 200], # 境界線の色
                #     get_line_width=5,
                #     line_width_min_pixels=1,
                #     pickable=True,
                # )
                # # ↑ポリゴン表示する場合、下のDeckのlayersリストにも polygon_layer を追加する
                # ------------------------------------------------

                # 地図の初期視点を設定
                view_state = pdk.ViewState(
                    latitude=latitude,
                    longitude=longitude,
                    zoom=16, # ズームレベル (大きいほど拡大)
                    pitch=45, # 地図の傾き角度
                    bearing=0 # 地図の回転角度
                )

                # pydeckの地図オブジェクトを作成
                deck = pdk.Deck(
                    # layers=[point_layer, polygon_layer], # ポリゴンも表示する場合
                    layers=[point_layer], # ポイントレイヤーのみ表示
                    initial_view_state=view_state,
                    map_style='mapbox://styles/mapbox/light-v10', # 地図のスタイル
                    tooltip={"text": f"検索地点\nLat: {latitude:.6f}\nLon: {longitude:.6f}"} # ポイントにマウスオーバーした時の表示
                 )
                st.pydeck_chart(deck) # Streamlit上に地図を表示
                st.success("地図表示完了 (pydeck)")

            except ImportError:
                st.info("地図表示ライブラリ `pydeck` が見つかりません。簡易地図を表示します。")
                map_df = pd.DataFrame({'lat': [latitude], 'lon': [longitude]})
                st.map(map_df, zoom=16)
            except Exception as map_e:
                st.warning(f"pydeck地図表示中にエラーが発生しました: {map_e}")
                traceback.print_exc() # サーバーログ用
                st.info("簡易地図を表示します。")
                map_df = pd.DataFrame({'lat': [latitude], 'lon': [longitude]})
                st.map(map_df, zoom=16)

        else: # if not containing_polygon.empty: のelse (データが見つからなかった場合)
            st.warning("指定された座標に対応する用途地域データが見つかりませんでした。")
            # データがない場合でも、検索地点だけは地図に表示
            st.subheader("地図表示 (検索地点)")
            try:
                map_df = pd.DataFrame({'lat': [latitude], 'lon': [longitude]})
                st.map(map_df, zoom=16)
            except Exception as map_e:
                st.warning(f"簡易地図表示中にエラー: {map_e}")

    except Exception as e: # find_and_display_zone関数全体の予期せぬエラー
        st.error(f"予期せぬエラー（空間検索・表示処理中）: {e}")
        traceback.print_exc() # サーバーログ用

# --- Streamlit アプリケーションの UI 構築 ---

st.title("東京都 用途地域チェッカー")
st.caption("住所または緯度経度を入力して、東京都の用途地域情報を検索します。")

# --- シェイプファイルの読み込み実行 ---
# ▼▼▼ 変更/追加箇所：読み込み結果のチェックを強化 ▼▼▼
gdf_youto = load_shapefile(shapefile_path)

# 読み込みが成功したかチェック
if gdf_youto is None:
    # load_shapefile関数内で既にエラーメッセージは表示されているはず
    st.error("シェイプファイルの読み込みに失敗したため、アプリケーションを開始できません。")
    st.warning(f"確認されたシェイプファイルパス: {shapefile_path}")
    st.warning(f"上記のパスにシェイプファイル一式 (最低でも .shp, .shx, .dbf) が存在するか確認してください。")
    st.stop() # 処理を中断
else:
    # 読み込み成功した場合のみ、情報を表示
    with st.expander("シェイプファイル情報"):
        st.success(f"シェイプファイル読み込み完了: {os.path.basename(shapefile_path)}")
        st.write(f"座標参照系(CRS): {gdf_youto.crs}")
        st.write(f"データ(ポリゴン)数: {len(gdf_youto)}")
        st.write(f"属性カラム数: {len(gdf_youto.columns)}")
        # ファイルの最終更新日時を表示 (エラーが出てもアプリは止めない)
        try:
            mod_time = os.path.getmtime(shapefile_path)
            dt_object = datetime.datetime.fromtimestamp(mod_time)
            st.write(f"ファイル最終更新日時: {dt_object.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            st.write(f"ファイル更新日時の取得に失敗しました: {e}")
# ▲▲▲ 変更/追加箇所 ▲▲▲

# --- 入力UI ---
search_method = st.radio(
    "検索方法を選択:",
    ("住所で検索", "緯度経度で検索"),
    horizontal=True,
    key="search_method" # セッション状態で管理するためのキー
)

latitude, longitude = None, None # 緯度経度の初期化
address = ""
manual_lat, manual_lon = None, None

# 検索ボタンが押されたかどうかの状態を管理 (ページ再読み込み後も維持される)
if 'search_clicked' not in st.session_state:
    st.session_state.search_clicked = False

search_button_pressed = False # 今回の実行でボタンが押されたかどうかのフラグ

if search_method == "住所で検索":
    address = st.text_input(
        "住所を入力してください (例: 東京都千代田区九段北4-1-3):",
        key="address_input", # セッション状態で管理するためのキー
        # 前回入力した住所を保持する場合 (好みによる)
        # value=st.session_state.get('last_address', '')
    )
    if st.button("住所から検索実行", key="geocode_search_button"):
        if address:
            # st.session_state.last_address = address # 住所を記憶する場合
            st.session_state.search_clicked = True # 検索実行フラグを立てる
            search_button_pressed = True # ボタンが押されたことを記録
            # 住所検索時は手動入力の緯度経度をクリア (任意)
            st.session_state.manual_lat = None
            st.session_state.manual_lon = None
            # 住所から緯度経度を取得
            with st.spinner("地理院地図APIで座標を検索中..."):
                latitude, longitude, geo_message = geocode_address(address)
            st.info(geo_message) # ジオコーディングの結果メッセージを表示
            if latitude is None or longitude is None:
                st.error("座標を取得できなかったため、検索を実行できません。")
                st.session_state.search_clicked = False # 失敗したらフラグを下ろす
        else:
            st.warning("住所を入力してください。")
            st.session_state.search_clicked = False # 住所が空ならフラグを下ろす
elif search_method == "緯度経度で検索":
    col1, col2 = st.columns(2)
    with col1:
        # number_inputのvalueには前回入力値をst.session_stateから取得して設定
        manual_lat = st.number_input(
            "緯度 (Latitude) を入力:",
            format="%.6f", # 小数点以下6桁まで表示
            value=st.session_state.get('manual_lat', None), # 前回値を復元
            # value=35.6812, # デフォルト値を設定したい場合
            help="例: 35.692669",
            key="lat_input"
        )
        st.session_state.manual_lat = manual_lat # 入力値をセッション状態に保存
    with col2:
        manual_lon = st.number_input(
            "経度 (Longitude) を入力:",
            format="%.6f",
            value=st.session_state.get('manual_lon', None), # 前回値を復元
            # value=139.7671, # デフォルト値を設定したい場合
            help="例: 139.740238",
            key="lon_input"
        )
        st.session_state.manual_lon = manual_lon # 入力値をセッション状態に保存

    latitude = manual_lat
    longitude = manual_lon

    if st.button("緯度経度で検索実行", key="latlon_search_button"):
        # 有効な緯度経度か簡易チェック
        if latitude is not None and longitude is not None and -90 <= latitude <= 90 and -180 <= longitude <= 180:
            st.session_state.search_clicked = True # 検索実行フラグを立てる
            search_button_pressed = True # ボタンが押されたことを記録
            # st.session_state.last_address = "" # 住所入力をクリアする場合 (任意)
        else:
             st.warning("有効な緯度と経度を入力してください。")
             st.session_state.search_clicked = False # 無効な値ならフラグを下ろす

# --- 検索実行と結果表示 ---
# search_clickedフラグが立っている場合に検索を実行
# (ボタンが押された直後か、またはラジオボタン切り替え等で再実行されたがフラグが残っている場合)
if st.session_state.search_clicked:
    # 緯度経度が有効な場合のみ検索関数を呼び出す
    if latitude is not None and longitude is not None and latitude != 0 and longitude != 0:
         # 検索実行中にスピナーを表示
        with st.spinner("用途地域を検索中..."):
            find_and_display_zone(latitude, longitude, gdf_youto)
    elif search_button_pressed:
        # ボタンが押されたのに緯度経度が無効だった場合 (主に住所検索失敗時)
        # メッセージは既に入力部分で表示されているはずなので、ここでは何もしないか、
        # 必要なら追加のメッセージを表示
        pass
    else:
        # ボタンが押されたわけではないが、フラグが立ったまま緯度経度が無効な場合
        # (例: 緯度経度入力で無効な値を入力してボタンを押さずにラジオボタンを切り替えたなど)
        st.warning("検索を実行するための有効な座標がありません。")

    # 検索実行後にクリック状態をリセットするかどうか (必要に応じてコメントアウト解除)
    # これを有効にすると、検索後に入力値を変えずに他の操作（ラジオボタン等）をしても再検索されない
    # st.session_state.search_clicked = False

# --- フッター ---
st.divider() # 区切り線
st.caption(
    "注意: このアプリケーションは提供されたデータに基づいて情報を表示します。"
    "最新の情報や正確な情報については、必ず東京都都市整備局等の公式情報をご確認ください。"
    "ジオコーディングには国土地理院 住所検索APIを使用しています。"
)