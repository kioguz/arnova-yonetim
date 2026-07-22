import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import re
import io
import html
import streamlit.components.v1 as components
from streamlit_option_menu import option_menu

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Arnova Site Yönetimi", page_icon="🏢", layout="wide", initial_sidebar_state="collapsed")

# --- PDF YAZDIRMA İÇİN CSS ---
st.markdown("""
<style>
@media print {
    [data-testid="stSidebar"] { display: none !important; }
    header { display: none !important; }
    .stButton { display: none !important; }
}
</style>
""", unsafe_allow_html=True)

# TÜRKÇE KARAKTER SORUNU ÇÖZÜCÜ
def turkce_upper(metin):
    if not isinstance(metin, str): return str(metin)
    return str(metin).replace('i', 'İ').replace('ı', 'I').replace('ş', 'Ş').replace('ğ', 'Ğ').replace('ü', 'Ü').replace('ö', 'Ö').replace('ç', 'Ç').upper()

# AKILLI TUTAR TEMİZLEME MOTORU
def tutar_temizle(val):
    if pd.isna(val): return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).strip()
    if ',' in val_str and '.' in val_str:
        if val_str.rfind(',') > val_str.rfind('.'): val_str = val_str.replace('.', '').replace(',', '.')
        else: val_str = val_str.replace(',', '')
    elif ',' in val_str: val_str = val_str.replace(',', '.')
    try: return float(val_str)
    except: return 0.0

# EVRENSEL TARİH SÜZGECİ
def tarih_temizle(tarih_val):
    if pd.isna(tarih_val) or str(tarih_val).strip() == "": return str(datetime.now().date())
    try:
        dt = pd.to_datetime(tarih_val, dayfirst=True)
        return dt.strftime('%Y-%m-%d')
    except: return str(datetime.now().date())

# GİDER KATEGORİLERİ
KATEGORILER = [
    "Tamirat Arıza Bakım Yedek Parça Giderleri", "Hizmet Alınan Personel Maliyeti", "Asansör İşletme Giderleri", 
    "Site Temizlik Şirketi Gideri", "Aydem (Elektrik Giderleri)", "Aski (Su Giderleri)", "Banka Havale Masrafları",
    "Havuz Bakım ve Kimyasal Giderleri", "Diğer Giderler"
]

# --- VERİTABANI BAĞLANTISI (YEREL + BULUT HİBRİT KÖPRÜSÜ) ---
def get_db_connection():
    try:
        import libsql_experimental as libsql
        if "TURSO_DATABASE_URL" in st.secrets and "TURSO_AUTH_TOKEN" in st.secrets:
            url = st.secrets["TURSO_DATABASE_URL"]
            token = st.secrets["TURSO_AUTH_TOKEN"]
            conn = libsql.connect("arnova.db", sync_url=url, auth_token=token)
            conn.sync()
            return conn
    except Exception:
        pass
    
    # Yerel SQLite Geri Dönüş (Fallback) Modu
    conn = sqlite3.connect('arnova.db', check_same_thread=False, timeout=15.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except:
        pass
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar (id INTEGER PRIMARY KEY, kullanici_adi TEXT, sifre TEXT, rol TEXT, daire_id TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS daireler (id TEXT PRIMARY KEY, blok TEXT, daire_no TEXT, ev_sahibi TEXT, kiraci TEXT, bakiye REAL, ev_sahibi_tel TEXT, kiraci_tel TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS islemler (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, tutar REAL, islem_tipi TEXT, aciklama TEXT, daire_id TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS ayarlar (ayar_adi TEXT PRIMARY KEY, deger TEXT)''')
        
        c.execute("SELECT * FROM kullanicilar WHERE rol='admin'")
        if not c.fetchone(): c.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, daire_id) VALUES ('yonetici', 'arnova123', 'admin', 'TÜMÜ')")
        
        c.execute("SELECT * FROM kullanicilar WHERE rol='gozlemci'")
        if not c.fetchone(): c.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, daire_id) VALUES ('gozlemci', 'arnova_izle', 'gozlemci', 'TÜMÜ')")
        
        c.execute("SELECT deger FROM ayarlar WHERE ayar_adi='otomatik_aidat_tutari'")
        if not c.fetchone(): c.execute("INSERT INTO ayarlar (ayar_adi, deger) VALUES ('otomatik_aidat_tutari', '1000')")
        
        c.execute("SELECT deger FROM ayarlar WHERE ayar_adi='son_aidat_ayi'")
        if not c.fetchone(): c.execute("INSERT INTO ayarlar (ayar_adi, deger) VALUES ('son_aidat_ayi', '')")
        
        c.execute("SELECT id FROM daireler")
        daireler = c.fetchall()
        for d in daireler:
            daire_id = d[0]
            c.execute("SELECT * FROM kullanicilar WHERE daire_id=?", (daire_id,))
            if not c.fetchone(): c.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, daire_id) VALUES (?, '12345', 'sakin', ?)", (daire_id, daire_id))
        conn.commit()
    except Exception as e: conn.rollback(); st.error(f"Veritabanı başlatılırken hata oluştu: {e}")
    finally: conn.close()

init_db()

# --- GİRİŞ SİSTEMİ ---
if 'giris_yapildi' not in st.session_state:
    st.session_state['giris_yapildi'] = False
    st.session_state['rol'] = None
    st.session_state['kullanici'] = None
    st.session_state['daire_id'] = None

def giris_kontrol(kullanici_adi, sifre):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT rol, daire_id FROM kullanicilar WHERE kullanici_adi=? AND sifre=?", (kullanici_adi.strip(), sifre.strip()))
    kullanici = c.fetchone()
    conn.close()
    
    if kullanici:
        st.session_state['giris_yapildi'] = True
        st.session_state['rol'] = kullanici[0]
        st.session_state['kullanici'] = kullanici_adi.strip()
        st.session_state['daire_id'] = kullanici[1]
        st.rerun()
    else: st.error("⚠️ Kullanıcı adı veya şifre hatalı!")

def cikis_yap():
    st.session_state['giris_yapildi'] = False
    st.session_state['rol'] = None
    st.session_state['kullanici'] = None
    st.session_state['daire_id'] = None
    st.rerun()

# --- ARAYÜZ ---
if not st.session_state['giris_yapildi']:
    st.write("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<h1 style='text-align:center; color:#0056b3;'>🏢 Arnova Yönetim Portalı</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center; color:#6c757d;'>Sisteme Giriş Yapın</p>", unsafe_allow_html=True)
        with st.form("giris_formu"):
            k_adi = st.text_input("👤 Kullanıcı Adı")
            sifre = st.text_input("🔑 Şifre", type="password")
            st.write("")
            if st.form_submit_button("Sisteme Giriş Yap", use_container_width=True): giris_kontrol(k_adi, sifre)
else:
    with st.sidebar:
        st.markdown("<h2 style='text-align:center; color:#0056b3;'>🏢 ARNOVA SİTESİ</h2>", unsafe_allow_html=True)
        rol_isim = "YÖNETİCİ" if st.session_state['rol'] == 'admin' else ("DENETÇİ" if st.session_state['rol'] == 'gozlemci' else "SAKİN")
        st.info(f"👤 Kullanıcı: **{st.session_state['kullanici'].upper()}**\n\n🛡️ Yetki: **{rol_isim}**")
        
        if st.session_state['rol'] == 'admin':
            secim = option_menu(
                menu_title="Ana Menü",
                options=["Ana Dashboard", "Banka & Excel Yükle", "Onay Bekleyen & Dağıtım", "Cari ve Daire Yönetimi", "Manuel Gelir/Gider", "💸 Toplu Borçlandırma", "📄 Makbuz & Belge Çıktısı", "Yönetim Raporları", "Sistem Şifreleri", "⚙️ Yönetici Ayarları"],
                icons=["house", "cloud-upload", "check2-circle", "people", "wallet2", "cash-stack", "printer", "bar-chart-line", "key", "gear"],
                menu_icon="cast", default_index=0,
                styles={"container": {"padding": "0!important", "background-color": "transparent"}, "icon": {"color": "#0056b3", "font-size": "18px"}, "nav-link": {"font-size": "15px", "text-align": "left", "margin":"0px", "--hover-color": "#e2e6ea"}, "nav-link-selected": {"background-color": "#0056b3", "color": "white", "font-weight": "bold"}}
            )
        elif st.session_state['rol'] == 'gozlemci':
            secim = option_menu("Denetçi Menüsü", ["Ana Dashboard", "Yönetim Raporları", "Tüm İşlem ve Cari Geçmişi"], icons=["house", "bar-chart-line", "search"], default_index=0)
        else:
            secim = option_menu("Ana Menü", ["Dairem (Borç/Alacak Durumu)"], icons=["house"], default_index=0)
            
        st.write("")
        st.button("🚪 Sistemi Kapat (Çıkış)", on_click=cikis_yap, use_container_width=True)

    # =========================================================
    # OTOMATİK AİDAT MOTORU
    # =========================================================
    if st.session_state['rol'] == 'admin':
        bugun = datetime.now()
        if bugun.day >= 1:
            conn_motor = get_db_connection()
            c_motor = conn_motor.cursor()
            try:
                c_motor.execute("SELECT deger FROM ayarlar WHERE ayar_adi='otomatik_aidat_tutari'")
                aidat_ayar = c_motor.fetchone()
                aidat_tutari = float(aidat_ayar[0]) if aidat_ayar else 0.0
                
                c_motor.execute("SELECT deger FROM ayarlar WHERE ayar_adi='son_aidat_ayi'")
                son_ay_ayar = c_motor.fetchone()
                
                if aidat_tutari > 0:
                    guncel_yil = bugun.year
                    guncel_ay = bugun.month
                    
                    if not son_ay_ayar or son_ay_ayar[0] == "":
                        aylar_tr_isim = {1:"Ocak", 2:"Şubat", 3:"Mart", 4:"Nisan", 5:"Mayıs", 6:"Haziran", 7:"Temmuz", 8:"Ağustos", 9:"Eylül", 10:"Ekim", 11:"Kasım", 12:"Aralık"}
                        aciklama = f"[{aylar_tr_isim[guncel_ay]} {guncel_yil}] Otomatik Standart Aidat Tahakkuku"
                        c_motor.execute("SELECT id FROM daireler")
                        for d in c_motor.fetchall():
                            c_motor.execute("UPDATE daireler SET bakiye = ROUND(bakiye - ?, 2) WHERE id=?", (aidat_tutari, d[0]))
                            c_motor.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Borçlandırma (Aidat)', ?, ?)", (bugun.strftime("%Y-%m-01"), aidat_tutari, aciklama, d[0]))
                        
                        c_motor.execute("UPDATE ayarlar SET deger=? WHERE ayar_adi='son_aidat_ayi'", (f"{guncel_yil}-{guncel_ay:02d}",))
                        conn_motor.commit()
                    else:
                        son_ay_str = son_ay_ayar[0]
                        son_yil, son_ay_num = map(int, son_ay_str.split('-'))
                        hedef_ay = son_ay_num + 1; hedef_yil = son_yil
                        if hedef_ay > 12: hedef_ay = 1; hedef_yil += 1
                            
                        aylar_tr_isim = {1:"Ocak", 2:"Şubat", 3:"Mart", 4:"Nisan", 5:"Mayıs", 6:"Haziran", 7:"Temmuz", 8:"Ağustos", 9:"Eylül", 10:"Ekim", 11:"Kasım", 12:"Aralık"}
                        islem_yapildi = False
                        c_motor.execute("SELECT id FROM daireler")
                        tum_daireler = c_motor.fetchall()
                        
                        while (hedef_yil < guncel_yil) or (hedef_yil == guncel_yil and hedef_ay <= guncel_ay):
                            aciklama = f"[{aylar_tr_isim[hedef_ay]} {hedef_yil}] Otomatik Standart Aidat Tahakkuku"
                            tarih_str = f"{hedef_yil}-{hedef_ay:02d}-01"
                            for d in tum_daireler:
                                c_motor.execute("UPDATE daireler SET bakiye = ROUND(bakiye - ?, 2) WHERE id=?", (aidat_tutari, d[0]))
                                c_motor.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Borçlandırma (Aidat)', ?, ?)", (tarih_str, aidat_tutari, aciklama, d[0]))
                            son_islem_str = f"{hedef_yil}-{hedef_ay:02d}"
                            hedef_ay += 1
                            if hedef_ay > 12: hedef_ay = 1; hedef_yil += 1
                            islem_yapildi = True
                            
                        if islem_yapildi:
                            c_motor.execute("UPDATE ayarlar SET deger=? WHERE ayar_adi='son_aidat_ayi'", (son_islem_str,))
                            conn_motor.commit()
                            st.success("🔔 BİLGİ SİSTEMİ: Yönetim portalına giriş yapılmayan geçmiş ayların aidatları başarıyla hesaplanıp sisteme borç olarak yansıtıldı.")
            except Exception as e: conn_motor.rollback() 
            finally: conn_motor.close()

    # ---------------------------------------------------------
    # SİTE SAKİNİ ÖZEL EKRANI
    # ---------------------------------------------------------
    if secim == "Dairem (Borç/Alacak Durumu)":
        st.title(f"🏠 {st.session_state['daire_id']} Numaralı Cari Durumu")
        conn = get_db_connection()
        d_id = st.session_state['daire_id']
        df_daire = pd.read_sql_query(f"SELECT bakiye FROM daireler WHERE id='{d_id}'", conn)
        if not df_daire.empty:
            bakiye = round(df_daire['bakiye'][0], 2)
            if bakiye < 0: st.error(f"### ⚠️ Güncel Borcunuz: {abs(bakiye):,.2f} TL")
            elif bakiye == 0: st.success("### ✅ Güncel Borcunuz Bulunmamaktadır. (0.00 TL)")
            else: st.info(f"### ℹ️ Fazladan Ödemeniz (Alacaklı Bakiyeniz): {bakiye:,.2f} TL")
        with st.container(border=True):
            st.subheader("📝 Geçmiş İşlemleriniz")
            df_islemler = pd.read_sql_query(f"SELECT tarih as Tarih, tutar as Tutar, islem_tipi as İşlem, aciklama as Açıklama FROM islemler WHERE daire_id='{d_id}' ORDER BY id DESC", conn)
            st.dataframe(df_islemler, use_container_width=True)
        conn.close()

    # ---------------------------------------------------------
    # ANA DASHBOARD
    # ---------------------------------------------------------
    elif secim == "Ana Dashboard":
        st.title("Yönetici Özet Paneli")
        conn = get_db_connection()
        
        df_tum_islemler = pd.read_sql_query("SELECT tarih, tutar, islem_tipi FROM islemler", conn)
        bu_ay_gelir, bu_ay_gider = 0.0, 0.0
        aylar_tr = {"January": "Ocak", "February": "Şubat", "March": "Mart", "April": "Nisan", "May": "Mayıs", "June": "Haziran", "July": "Temmuz", "August": "Ağustos", "September": "Eylül", "October": "Ekim", "November": "Kasım", "December": "Aralık"}
        ay_ing, yil = datetime.now().strftime('%B'), datetime.now().strftime('%Y')
        ay_ismi_tr = f"{aylar_tr.get(ay_ing, ay_ing)} {yil}"
        
        if not df_tum_islemler.empty:
            df_tum_islemler['tarih'] = pd.to_datetime(df_tum_islemler['tarih'], dayfirst=True, errors='coerce')
            simdi = datetime.now()
            bu_ayin_basi = simdi.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            df_bu_ay = df_tum_islemler[df_tum_islemler['tarih'] >= bu_ayin_basi]
            gelir_tipleri = ['Otomatik Tahsilat', 'Manuel Tahsilat', 'Elden Tahsilat', 'Çoklu Dağıtım']
            bu_ay_gelir = df_bu_ay[df_bu_ay['islem_tipi'].isin(gelir_tipleri)]['tutar'].sum()
            bu_ay_gider = df_bu_ay[df_bu_ay['islem_tipi'] == 'Gider']['tutar'].sum()

        with st.container(border=True):
            st.subheader(f"📅 BU AYIN ÖZETİ ({ay_ismi_tr})")
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("📥 Bu Ay Toplanan Gelir", f"{bu_ay_gelir:,.2f} TL")
            with c2: st.metric("📤 Bu Ay Çıkan Gider", f"{bu_ay_gider:,.2f} TL")
            with c3:
                net_fark = round(float(bu_ay_gelir - bu_ay_gider), 2)
                st.metric("⚖️ Bu Ayki Net Kasa", f"{net_fark:,.2f} TL", delta=f"{net_fark:,.2f} TL" if net_fark != 0 else None)
        
        with st.container(border=True):
            st.subheader("🏢 TÜM ZAMANLAR (Genel Kasa)")
            df_gelir = pd.read_sql_query("SELECT SUM(tutar) as toplam FROM islemler WHERE islem_tipi IN ('Otomatik Tahsilat', 'Manuel Tahsilat', 'Elden Tahsilat', 'Çoklu Dağıtım')", conn)
            toplam_gelir = df_gelir['toplam'][0] if pd.notna(df_gelir['toplam'][0]) else 0.0
            df_gider = pd.read_sql_query("SELECT SUM(tutar) as toplam FROM islemler WHERE islem_tipi='Gider'", conn)
            toplam_gider = df_gider['toplam'][0] if pd.notna(df_gider['toplam'][0]) else 0.0
            net_kasa = round(toplam_gelir - toplam_gider, 2)
            
            df_borc = pd.read_sql_query("SELECT SUM(bakiye) as toplam_alacak FROM daireler WHERE bakiye < 0", conn)
            toplam_alacak = abs(df_borc['toplam_alacak'][0]) if pd.notna(df_borc['toplam_alacak'][0]) else 0.0

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("💵 Toplam Tahsilat", f"{toplam_gelir:,.2f} TL")
            col2.metric("💸 Toplam Çıkan Gider", f"{toplam_gider:,.2f} TL")
            col3.metric("🏦 GENEL NET KASA", f"{net_kasa:,.2f} TL")
            col4.metric("📉 Piyasadan Alacaklar", f"{toplam_alacak:,.2f} TL")
        
        with st.container(border=True):
            st.subheader("🎯 SİTE SAKİNLERİ ÖDEME DURUMU")
            c = conn.cursor()
            c.execute("SELECT deger FROM ayarlar WHERE ayar_adi='otomatik_aidat_tutari'")
            ayar_sonucu = c.fetchone()
            kayitli_aidat = float(ayar_sonucu[0]) if ayar_sonucu else 1000.0
            standart_aidat = st.number_input("Aidat/Borç Hesaplaması İçin Standart Tutarı Girin (TL):", value=kayitli_aidat, step=100.0, key="dash_aidat")
            
            df_daire_borc = pd.read_sql_query("SELECT id, bakiye FROM daireler", conn)
            borclular = df_daire_borc[df_daire_borc['bakiye'] <= -1.0].copy()
            borcsuzlar = df_daire_borc[df_daire_borc['bakiye'] > -1.0]
            
            st.success(f"✅ **{len(borcsuzlar)} Dairenin/Carinin** hiçbir borcu yok.")
            
            if not borclular.empty:
                borclular['kac_ay'] = (borclular['bakiye'].abs() / standart_aidat).round().astype(int)
                borclular.loc[(borclular['kac_ay'] == 0) & (borclular['bakiye'] <= -1.0), 'kac_ay'] = 1 
                grup = borclular.groupby('kac_ay').size().reset_index(name='daire_sayisi')
                for index, row in grup.iterrows():
                    st.error(f"⚠️ **{row['daire_sayisi']} Dairenin/Carinin** tam {row['kac_ay']} ay ödeme borcu var.")
        
        with st.container(border=True):
            st.subheader("🏘️ Cari ve Dairelerin Detaylı Durumu")
            df_daireler = pd.read_sql_query("SELECT id as Daire_Kodu, ev_sahibi as Ev_Sahibi, kiraci as Kiraci, ROUND(bakiye, 2) as Güncel_Bakiye FROM daireler", conn)
            def color_negative_red(val):
                color = 'red' if (isinstance(val, (int, float)) and val < 0) else ''
                return f'color: {color}'
            styled_df = df_daireler.style.map(color_negative_red, subset=['Güncel_Bakiye']).format({'Güncel_Bakiye': "{:,.2f} TL"})
            st.dataframe(styled_df, use_container_width=True, height=400)
        conn.close()

    # ---------------------------------------------------------
    # DENETÇİ (GÖZLEMCİ) ÖZEL EKRANI
    # ---------------------------------------------------------
    elif secim == "Tüm İşlem ve Cari Geçmişi":
        st.title("👁️ Denetçi İnceleme Paneli")
        st.info("Bu alanda sitenin tüm geçmiş işlemlerini ve güncel daire kayıtlarını inceleyebilirsiniz. Denetçi yetkisiyle veri değiştirme işlemi yapılamaz.")
        conn = get_db_connection()
        with st.container(border=True):
            st.subheader("📂 Tüm Kasa ve İşlem Geçmişi")
            df_tum_islem = pd.read_sql_query("SELECT tarih as Tarih, tutar as Tutar, islem_tipi as İşlem_Tipi, aciklama as Açıklama, daire_id as İlgili_Cari FROM islemler ORDER BY id DESC", conn)
            st.dataframe(df_tum_islem, use_container_width=True, height=400)
        with st.container(border=True):
            st.subheader("🏘️ Tüm Daire ve Cari Kayıtları")
            df_tum_daire = pd.read_sql_query("SELECT id as Daire_Kodu, blok as Blok, daire_no as Daire_No, ev_sahibi as Ev_Sahibi, ev_sahibi_tel as Ev_Tel, kiraci as Kiracı, kiraci_tel as Kiracı_Tel, ROUND(bakiye, 2) as Güncel_Bakiye FROM daireler ORDER BY id ASC", conn)
            st.dataframe(df_tum_daire, use_container_width=True, height=400)
        conn.close()
            
    # ---------------------------------------------------------
    # 💸 TOPLU BORÇLANDIRMA
    # ---------------------------------------------------------
    elif secim == "💸 Toplu Borçlandırma":
        st.title("💸 Toplu Borçlandırma ve Faiz Merkezi")
        st.info("Bu ekrandan siteye veya belirli gruplara tek tuşla borç yazabilir, borcunu ödemeyenlere yasal gecikme faizi yansıtabilirsiniz.")
        
        tab1, tab2, tab3, tab4 = st.tabs(["⚙️ Otomatik Aidat", "➕ Ek Aidat", "🔨 Demirbaş", "📈 Gecikme Zammı (Faiz)"])
        
        with tab1:
            st.subheader("⚙️ Otomatik Standart Aidat Ayarları")
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT deger FROM ayarlar WHERE ayar_adi='otomatik_aidat_tutari'")
            ayar_sonucu = c.fetchone()
            mevcut_aidat = float(ayar_sonucu[0]) if ayar_sonucu else 1000.0
            
            st.write("Sistem, her ayın 1'inde aşağıdaki tutarı **otomatik olarak** tüm dairelere borç yazar.")
            with st.form("otomatik_aidat_form"):
                yeni_aidat = st.number_input("Standart Aylık Aidat Tutarı (TL):", value=mevcut_aidat, step=100.0)
                if st.form_submit_button("💾 Güncelle", type="primary"):
                    try:
                        c.execute("UPDATE ayarlar SET deger=? WHERE ayar_adi='otomatik_aidat_tutari'", (str(yeni_aidat),))
                        conn.commit()
                        st.success(f"Otomatik aidat tutarı {yeni_aidat:,.2f} TL olarak güncellendi! Bir sonraki ayın 1'inde yeni tutar kesilecek.")
                        st.rerun()
                    except Exception as e:
                        conn.rollback(); st.error(f"Hata: {e}")
            conn.close()
            
        with tab2:
            st.subheader("➕ Ek Aidat Tahakkuku")
            st.warning("Buradan gireceğiniz tutar, anında **TÜM DAİRELERİN** bakiyesinden borç olarak düşülecektir.")
            with st.form("ek_aidat_form"):
                ek_tutar = st.number_input("Eklenecek Ek Aidat Tutarı (TL):", min_value=1.0, step=100.0)
                ek_tarih = st.date_input("Tahakkuk Tarihi:")
                ek_aciklama = st.text_input("Açıklama (Örn: Temmuz Ek Yakıt Farkı)")
                if st.form_submit_button("🚀 Tüm Siteye Borç Yaz", type="primary"):
                    if ek_aciklama.strip():
                        conn = get_db_connection()
                        c = conn.cursor()
                        try:
                            tarih_str = tarih_temizle(str(ek_tarih))
                            c.execute("SELECT id FROM daireler")
                            tum = c.fetchall()
                            for d in tum:
                                d_id = d[0]
                                c.execute("UPDATE daireler SET bakiye = ROUND(bakiye - ?, 2) WHERE id=?", (ek_tutar, d_id))
                                c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Ek Aidat Borcu', ?, ?)", (tarih_str, ek_tutar, ek_aciklama.strip(), d_id))
                            conn.commit()
                            st.success(f"İşlem Başarılı! {len(tum)} adet daireye {ek_tutar:,.2f} TL ek aidat borcu yazıldı.")
                        except Exception as e:
                            conn.rollback(); st.error(f"Kritik hata, işlem tamamen geri alındı! {e}")
                        finally: conn.close()
                    else: st.error("Lütfen bir açıklama girin.")
                    
        with tab3:
            st.subheader("🔨 Demirbaş Ödemesi (Akıllı Dağıtım)")
            st.info("Bu işlem; kiracısı olan daireleri atlamaz! Eğer dairede kiracı varsa, sistem otomatik olarak bir 'Ev Sahibi' carisi açar ve demirbaşı sadece mülk sahibine borç yazar.")
            with st.form("demirbas_form"):
                db_tutar = st.number_input("Demirbaş Tutarı (TL):", min_value=1.0, step=100.0)
                db_tarih = st.date_input("Tahakkuk Tarihi (Demirbaş):")
                db_aciklama = st.text_input("Açıklama (Örn: Çatı Yalıtım Demirbaş Payı)")
                if st.form_submit_button("🔨 Ev Sahiplerine Borç Yaz", type="primary"):
                    if db_aciklama.strip():
                        conn = get_db_connection()
                        c = conn.cursor()
                        try:
                            tarih_str = tarih_temizle(str(db_tarih))
                            c.execute("SELECT id, ev_sahibi, kiraci FROM daireler WHERE id NOT LIKE '%EV SAHİBİ%' AND id NOT LIKE '%EV SAHIBI%'")
                            ana_daireler = c.fetchall()
                            islem_sayisi = 0
                            if ana_daireler:
                                for d in ana_daireler:
                                    ana_id, ev_sahibi_adi, kiraci_adi = d[0], d[1], d[2]
                                    if not kiraci_adi or kiraci_adi.strip() == "": hedef_id = ana_id
                                    else:
                                        hedef_id = f"{ana_id} (EV SAHİBİ)"
                                        c.execute("SELECT id FROM daireler WHERE id=?", (hedef_id,))
                                        if not c.fetchone():
                                            c.execute("INSERT INTO daireler (id, blok, daire_no, ev_sahibi, kiraci, bakiye, ev_sahibi_tel, kiraci_tel) VALUES (?, '', '', ?, '', 0.0, '', '')", (hedef_id, ev_sahibi_adi.strip() if ev_sahibi_adi else ""))
                                            c.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, daire_id) VALUES (?, '12345', 'sakin', ?)", (hedef_id, hedef_id))
                                    c.execute("UPDATE daireler SET bakiye = ROUND(bakiye - ?, 2) WHERE id=?", (db_tutar, hedef_id))
                                    c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Demirbaş Borcu', ?, ?)", (tarih_str, db_tutar, db_aciklama.strip(), hedef_id))
                                    islem_sayisi += 1
                                conn.commit()
                                st.success(f"✅ Harika! {islem_sayisi} adet ev sahibine {db_tutar:,.2f} TL demirbaş borcu eksiksiz yansıtıldı.")
                            else: st.warning("Sistemde işlem yapılacak daire bulunamadı.")
                        except Exception as e:
                            conn.rollback(); st.error(f"Kritik hata, işlem tamamen geri alındı! {e}")
                        finally: conn.close()
                    else: st.error("Lütfen bir açıklama girin.")

        with tab4:
            st.subheader("📈 Gecikme Zammı (Faiz) Uygulama")
            st.info("Kat Mülkiyeti Kanunu (KMK) gereği ödenmeyen aidatlara yasal gecikme zammı (faiz) işletebilirsiniz.")
            
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id, bakiye FROM daireler WHERE bakiye <= -1.0") 
            borclular = c.fetchall()
            
            if not borclular:
                st.success("🎉 Harika! Sistemde borcu olan (gecikmede) hiçbir daire bulunmamaktadır.")
            else:
                borclu_sozluk = {d[0]: abs(d[1]) for d in borclular}
                hedef_secim = st.radio("Faiz Kime Uygulanacak?", ["Seçili Tek Bir Daireye (Örn: İcra / Avukat Öncesi)", "Borcu Olan TÜM Dairelere (Toplu Faiz İşlet)"])
                
                with st.form("faiz_formu"):
                    faiz_orani = st.number_input("Uygulanacak Faiz Oranı (%):", min_value=0.1, value=5.0, step=0.5, format="%.1f")
                    secilen_daire = None
                    if hedef_secim == "Seçili Tek Bir Daireye (Örn: İcra / Avukat Öncesi)":
                        secilen_daire = st.selectbox("İşlem Yapılacak Daire/Cari:", options=list(borclu_sozluk.keys()), format_func=lambda x: f"{x} (Mevcut Borç: {borclu_sozluk[x]:,.2f} TL)")
                        
                    aciklama = st.text_input("Açıklama Metni:", value=f"KMK %{faiz_orani} Gecikme Tazminatı (Faizi)")
                    
                    if st.form_submit_button("🚀 Faizi Hesapla ve Borca Ekle", type="primary"):
                        try:
                            tarih_str = tarih_temizle(str(datetime.now().date()))
                            if hedef_secim == "Seçili Tek Bir Daireye (Örn: İcra / Avukat Öncesi)":
                                mevcut_borc = borclu_sozluk[secilen_daire]
                                faiz_tutari = round(mevcut_borc * (faiz_orani / 100), 2)
                                c.execute("UPDATE daireler SET bakiye = ROUND(bakiye - ?, 2) WHERE id = ?", (faiz_tutari, secilen_daire))
                                c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Gecikme Faizi', ?, ?)", (tarih_str, faiz_tutari, aciklama.strip(), secilen_daire))
                                st.success(f"✅ {secilen_daire} carisine {faiz_tutari:,.2f} TL tutarında gecikme zammı başarıyla işlendi!")
                            else:
                                uygulanan_sayi = 0
                                toplam_islenen_faiz = 0
                                for d_id, d_borc in borclu_sozluk.items():
                                    faiz_tutari = round(d_borc * (faiz_orani / 100), 2)
                                    c.execute("UPDATE daireler SET bakiye = ROUND(bakiye - ?, 2) WHERE id = ?", (faiz_tutari, d_id))
                                    c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Gecikme Faizi', ?, ?)", (tarih_str, faiz_tutari, aciklama.strip(), d_id))
                                    uygulanan_sayi += 1
                                    toplam_islenen_faiz += faiz_tutari
                                st.success(f"✅ İşlem Başarılı! {uygulanan_sayi} adet borçlu daireye toplam {toplam_islenen_faiz:,.2f} TL tutarında gecikme zammı toplu olarak yansıtıldı.")
                            conn.commit()
                        except Exception as e:
                            conn.rollback(); st.error(f"İşlem tamamlanamadı, geri alındı: {e}")
            conn.close()

    # ---------------------------------------------------------
    # BANKA YÜKLEME 
    # ---------------------------------------------------------
    elif secim == "Banka & Excel Yükle":
        st.title("📁 Veri Yükleme Merkezi")
        st.info("İş Bankası, Akbank, QNB vb. bankalardan indirdiğiniz Excel ekstresini buraya yükleyin.")
        bank_file = st.file_uploader("Banka Excel Ekstresini Seçin", type=['xlsx', 'xls'], key="banka_yukle")
        if bank_file:
            if st.button("🚀 Banka Ekstresini İşle ve Eşleştir", use_container_width=True, type="primary"):
                with st.spinner("Yapay Zeka analiz ediyor ve mükerrer kayıtları süzüyor..."):
                    try:
                        df_raw = pd.read_excel(bank_file)
                        baslik_satiri = 0
                        for i in range(min(25, len(df_raw))):
                            satir_metni = " ".join([str(val).upper() for val in df_raw.iloc[i].values])
                            if any(k in satir_metni for k in ["TUTAR", "TUTARI", "BAKIYE", "BORÇ", "ALACAK"]) and any(k in satir_metni for k in ["AÇIKLAMA", "ACIKLAMA", "İŞLEM", "ISLEM"]):
                                baslik_satiri = i + 1; break
                                
                        df_bank = pd.read_excel(bank_file, skiprows=baslik_satiri)
                        df_bank = df_bank.loc[:, ~df_bank.columns.astype(str).str.contains('^Unnamed')]
                        df_bank.columns = [str(col).strip().replace('*', '').upper() for col in df_bank.columns]
                        
                        tutar_kolonu = next((col for col in df_bank.columns if any(k in col for k in ["TUTAR", "TUTARI", "NET"])), None)
                        aciklama_kolonu = next((col for col in df_bank.columns if any(k in col for k in ["AÇIKLAMA", "ACIKLAMA", "İŞLEM", "ISLEM", "DETAY"])), None)
                        tarih_kolonu = next((col for col in df_bank.columns if any(k in col for k in ["TARİH", "TARIH", "SAAT", "ZAMAN"])), None)
                        
                        if not tutar_kolonu or not aciklama_kolonu:
                            st.error("Hata: 'Tutar' veya 'Açıklama' sütunları otomatik algılanamadı.")
                        else:
                            df_bank[tutar_kolonu] = df_bank[tutar_kolonu].apply(tutar_temizle)
                            conn = get_db_connection()
                            c = conn.cursor()
                            yeni_eklenen_gider, yeni_eklenen_otomatik, yeni_eklenen_coklu, yeni_eklenen_onay, atlanan_mukerrer = 0, 0, 0, 0, 0
                            
                            try:
                                for idx, row in df_bank.dropna(subset=[tutar_kolonu]).iterrows():
                                    tutar = float(row[tutar_kolonu])
                                    if tutar == 0.0: continue
                                    
                                    aciklama = turkce_upper(row[aciklama_kolonu])
                                    tarih_ham = row[tarih_kolonu] if tarih_kolonu else None
                                    tarih = tarih_temizle(tarih_ham)
                                    
                                    c.execute("SELECT id FROM islemler WHERE tarih = ? AND tutar = ? AND aciklama = ?", (tarih, abs(tutar), aciklama))
                                    if c.fetchone():
                                        atlanan_mukerrer += 1
                                        continue 
                                    
                                    if tutar < 0:
                                        harcama_tutari = abs(tutar)
                                        kategori = None
                                        if any(k in aciklama for k in ["AYDEM", "ELEKTR", "ENERYA"]): kategori = "Aydem (Elektrik Giderleri)"
                                        elif any(k in aciklama for k in ["ASKİ", "ASKI", "SU FATU", "AYDIN SU", "BÜYÜKŞEHİR"]): kategori = "Aski (Su Giderleri)"
                                        elif any(k in aciklama for k in ["ASANSÖR", "ASANSOR"]): kategori = "Asansör İşletme Giderleri"
                                        elif any(k in aciklama for k in ["SGK", "MAAŞ", "MAAS", "PERSONEL", "BORDRO"]): kategori = "Hizmet Alınan Personel Maliyeti"
                                        elif any(k in aciklama for k in ["TEMİZLİK", "TEMIZLIK", "ÇÖP"]): kategori = "Site Temizlik Şirketi Gideri"
                                        elif any(k in aciklama for k in ["EFT", "HAVALE", "BSMV", "MASRAF", "ÜCRET", "UCRET", "KESTİ", "KESTI"]): kategori = "Banka Havale Masrafları"
                                        elif any(k in aciklama for k in ["HAVUZ", "KİMYASAL", "KIMYASAL"]): kategori = "Havuz Bakım ve Kimyasal Giderleri"
                                        
                                        if kategori:
                                            c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Gider', ?, 'SİTE GENELİ')", (tarih, harcama_tutari, f"[{kategori}] {aciklama}"))
                                            yeni_eklenen_gider += 1
                                        else:
                                            c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Gider Beklemede', ?, 'SİTE GENELİ')", (tarih, harcama_tutari, aciklama))
                                            yeni_eklenen_gider += 1
                                            
                                    elif tutar > 0:
                                        sender = aciklama.split('*')[0].strip() if '*' in aciklama else aciklama
                                        c.execute("SELECT id FROM daireler WHERE ev_sahibi = ? OR kiraci = ?", (sender, sender))
                                        eslesen_daireler = c.fetchall()
                                        if len(eslesen_daireler) == 1:
                                            d_id = eslesen_daireler[0][0]
                                            c.execute("UPDATE daireler SET bakiye = ROUND(bakiye + ?, 2) WHERE id = ?", (tutar, d_id))
                                            c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Otomatik Tahsilat', ?, ?)", (tarih, tutar, aciklama, d_id))
                                            yeni_eklenen_otomatik += 1
                                        elif len(eslesen_daireler) > 1:
                                            c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Çoklu Beklemede', ?, ?)", (tarih, tutar, aciklama, sender))
                                            yeni_eklenen_coklu += 1
                                        else:
                                            c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Onay Bekliyor', ?, ?)", (tarih, tutar, aciklama, "BİLİNMİYOR"))
                                            yeni_eklenen_onay += 1
                                            
                                conn.commit()
                                st.success("✅ Banka Ekstresi Analizi Tamamlandı!")
                                st.info(f"🛡️ **Mükerrer Koruması:** Daha önce yüklenmiş olan **{atlanan_mukerrer} adet** işlem atlandı.")
                                col_s1, col_s2 = st.columns(2)
                                with col_s1:
                                    st.write(f"🟢 **Otomatik Aidat:** {yeni_eklenen_otomatik}")
                                    st.write(f"📉 **Eklenen Gider:** {yeni_eklenen_gider}")
                                with col_s2:
                                    st.write(f"🟡 **Çoklu Bekleyen:** {yeni_eklenen_coklu}")
                                    st.write(f"🔴 **Eşleşmeyen Gelir:** {yeni_eklenen_onay}")
                            except Exception as e:
                                conn.rollback(); st.error(f"İşlem sırasında kritik hata oluştu, veritabanı geri alındı: {e}")
                            finally:
                                conn.close()
                    except Exception as e:
                        st.error(f"Ekstre dosyası okunamadı: {e}")

    # ---------------------------------------------------------
    # ONAY BEKLEYENLER / GİDER SINIFLANDIRMA / DAĞITIM
    # ---------------------------------------------------------
    elif secim == "Onay Bekleyen & Dağıtım":
        st.title("✅ Onay Bekleyenler ve Akıllı Dağıtım")
        conn = get_db_connection()
        c = conn.cursor()
        tab1, tab2, tab3 = st.tabs(["🪄 Esnek Çoklu Dağıtım", "🔄 Eşleşmeyen Gelirler", "📤 TOPLU GİDER DÜZELTME"])
        
        with tab1:
            st.subheader("Toplu Para Gönderenler")
            df_coklu = pd.read_sql_query("SELECT id, tarih, tutar, aciklama, daire_id as Gonderen FROM islemler WHERE islem_tipi='Çoklu Beklemede'", conn)
            if not df_coklu.empty:
                islem_id = st.selectbox("Dağıtılacak Toplu Ödemeyi Seçin:", options=df_coklu['id'].tolist(), format_func=lambda x: f"{df_coklu[df_coklu['id']==x]['Gonderen'].values[0]} - Tutar: {df_coklu[df_coklu['id']==x]['tutar'].values[0]:,.2f} TL")
                secilen_islem = df_coklu[df_coklu['id'] == islem_id].iloc[0]
                ana_tutar = float(secilen_islem['tutar'])
                gonderen_isim = secilen_islem['Gonderen']
                
                c.execute("SELECT id, ev_sahibi FROM daireler")
                tum_daireler_listesi = c.fetchall()
                daire_sozlugu = {d[0]: f"{d[0]} ({d[1]})" for d in tum_daireler_listesi}
                
                c.execute("SELECT id FROM daireler WHERE ev_sahibi=? OR kiraci=?", (gonderen_isim, gonderen_isim))
                otomatik_bulunanlar = [d[0] for d in c.fetchall()]
                
                st.info(f"💰 **Dağıtılacak Toplam Havuz:** {ana_tutar:,.2f} TL")
                secilen_daireler = st.multiselect("Paylaştırılacak Cariler?", options=list(daire_sozlugu.keys()), default=otomatik_bulunanlar, format_func=lambda x: daire_sozlugu[x])
                
                if secilen_daireler:
                    with st.form("dagitim_sihirbazi"):
                        dagitim_miktarlari = {}
                        for d_kodu in secilen_daireler:
                            c.execute("SELECT bakiye FROM daireler WHERE id=?", (d_kodu,))
                            d_bakiye = c.fetchone()[0]
                            d_borc = abs(d_bakiye) if d_bakiye < 0 else 0.0
                            dagitim_miktarlari[d_kodu] = st.number_input(f"{d_kodu} (Mevcut Borcu: {d_borc:,.2f} TL)", min_value=0.0, max_value=ana_tutar, step=100.0)
                            
                        kalan = ana_tutar - sum(dagitim_miktarlari.values())
                        if kalan > 0: st.warning(f"⚠️ Kalan Dağıtılmamış Tutar: {kalan:,.2f} TL")
                        elif kalan < 0: st.error(f"❌ HATA: Fazla dağıtım yaptınız!")
                        else: st.success("✅ Sıfırlandı, onaylayabilirsiniz.")
                        
                        if st.form_submit_button("✔️ Parayı Dağıt"):
                            toplam_dagitilan = sum(dagitim_miktarlari.values())
                            if abs(toplam_dagitilan - ana_tutar) < 0.1:
                                try:
                                    for daire, miktar in dagitim_miktarlari.items():
                                        if miktar > 0:
                                            c.execute("UPDATE daireler SET bakiye = ROUND(bakiye + ?, 2) WHERE id = ?", (miktar, daire))
                                            c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Çoklu Dağıtım', ?, ?)", (secilen_islem['tarih'], miktar, f"{gonderen_isim} Toplu Ödemesinden Ayrılan", daire))
                                    c.execute("UPDATE islemler SET islem_tipi = 'Kapatıldı' WHERE id = ?", (int(islem_id),))
                                    conn.commit()
                                    st.success("Başarıyla paylaştırıldı!")
                                    st.rerun()
                                except Exception as e:
                                    conn.rollback(); st.error(f"Hata oluştu, geri alındı: {e}")
                            else:
                                st.error("Dağıttığınız tutar, gelen paraya eşit olmalıdır!")
            else:
                st.success("✅ Bekleyen toplu işlem yok.")
                
        with tab2:
            st.subheader("İsimden Eşleşmeyen Gelirler")
            df_bekleyen = pd.read_sql_query("SELECT id, tarih, tutar, aciklama FROM islemler WHERE islem_tipi='Onay Bekliyor'", conn)
            if df_bekleyen.empty:
                st.success("✅ Bekleyen tekli gelir yok.")
            else:
                st.dataframe(df_bekleyen, use_container_width=True)
                c.execute("SELECT id, ev_sahibi, kiraci FROM daireler")
                daire_sec = {d[0]: f"{d[0]} ({d[1]})" for d in c.fetchall()}
                with st.form("tekli_eslestir"):
                    t_id = st.selectbox("İşlemi Seç", options=df_bekleyen['id'].tolist(), format_func=lambda x: f"ID: {x} - Tutar: {df_bekleyen[df_bekleyen['id']==x]['tutar'].values[0]} TL")
                    t_daire = st.selectbox("Cariye Ata", options=list(daire_sec.keys()), format_func=lambda x: daire_sec[x])
                    if st.form_submit_button("✔️ Cariye İşle", type="primary"):
                        try:
                            t_tutar = float(df_bekleyen[df_bekleyen['id']==t_id]['tutar'].values[0])
                            c.execute("UPDATE daireler SET bakiye = ROUND(bakiye + ?, 2) WHERE id = ?", (t_tutar, t_daire))
                            c.execute("UPDATE islemler SET islem_tipi = 'Manuel Tahsilat', daire_id = ? WHERE id = ?", (t_daire, int(t_id)))
                            conn.commit()
                            st.success("Para aktarıldı!")
                            st.rerun()
                        except Exception as e:
                            conn.rollback(); st.error(f"Hata oluştu, geri alındı: {e}")

        with tab3:
            st.subheader("🔍 Toplu Gider Atama")
            df_tum_giderler = pd.read_sql_query("SELECT id, tarih, tutar, aciklama FROM islemler WHERE islem_tipi IN ('Gider', 'Gider Beklemede') ORDER BY id DESC", conn)
            if not df_tum_giderler.empty:
                def get_kategori_kontrol(text):
                    match = re.search(r'\[(.*?)\]', text)
                    return match.group(1) if match else "Diğer Giderler"
                
                df_tum_giderler['Mevcut_Kategori'] = df_tum_giderler['aciklama'].apply(get_kategori_kontrol)
                df_gider_duzeltme = df_tum_giderler[df_tum_giderler['Mevcut_Kategori'] == 'Diğer Giderler']
                
                if df_gider_duzeltme.empty:
                    st.success("✅ Sınıflandırılmamış ('Diğer') harcama kalmadı.")
                else:
                    benzersiz_liste = df_gider_duzeltme['aciklama'].unique().tolist()
                    secilen_listeden = st.selectbox("📌 İşlenmeyen Giderler Listesi:", ["-- Seç veya Ara --"] + benzersiz_liste)
                    arama_kelimesi = st.text_input("🔍 Kelime ile Ara:")
                    df_gider_duzeltme['arama_metni'] = df_gider_duzeltme['aciklama'].apply(turkce_upper)
                    
                    if arama_kelimesi: query = turkce_upper(arama_kelimesi); df_filtrelenmis = df_gider_duzeltme[df_gider_duzeltme['arama_metni'].str.contains(query, na=False)].copy()
                    elif secilen_listeden != "-- Seç veya Ara --": df_filtrelenmis = df_gider_duzeltme[df_gider_duzeltme['aciklama'] == secilen_listeden].copy()
                    else: df_filtrelenmis = df_gider_duzeltme.copy()
                    
                    if not df_filtrelenmis.empty:
                        varsayilan_secim = st.checkbox("Listedeki Tüm Tikleri Seç", value=False)
                        df_filtrelenmis.insert(0, 'Seç', varsayilan_secim)
                        duzenlenmis_df = st.data_editor(df_filtrelenmis[['Seç', 'tarih', 'tutar', 'aciklama', 'id']], hide_index=True, column_config={"Seç": st.column_config.CheckboxColumn("Seç (Tik)")}, disabled=["tarih", "tutar", "aciklama"], use_container_width=True)
                        with st.form("toplu_atama_formu"):
                            secilen_kategori = st.selectbox("Hangi Kategoriye Aktarılsın?", KATEGORILER)
                            if st.form_submit_button("🚀 TİKLİ OLANLARI ATA", type="primary"):
                                secilen_idler = duzenlenmis_df[duzenlenmis_df['Seç'] == True]['id'].tolist()
                                if secilen_idler:
                                    try:
                                        for g_id in secilen_idler:
                                            eski_aciklama = df_gider_duzeltme[df_gider_duzeltme['id'] == g_id]['aciklama'].values[0]
                                            temiz_aciklama = re.sub(r'\[.*?\]\s*', '', eski_aciklama)
                                            c.execute("UPDATE islemler SET islem_tipi='Gider', aciklama=? WHERE id=?", (f"[{secilen_kategori}] {temiz_aciklama}", int(g_id)))
                                        conn.commit()
                                        st.success("Giderler güncellendi.")
                                        st.rerun()
                                    except Exception as e:
                                        conn.rollback(); st.error(f"Hata: {e}")
                                else:
                                    st.error("En az bir gidere tik koyun!")
        conn.close()

    # ---------------------------------------------------------
    # CARİ VE DAİRE YÖNETİMİ
    # ---------------------------------------------------------
    elif secim == "Cari ve Daire Yönetimi":
        st.title("👥 Cari ve Tapu Yönetim Merkezi")
        conn = get_db_connection()
        c = conn.cursor()
        tab1, tab2, tab3, tab4 = st.tabs(["🔄 Mevcut Bilgileri Güncelle", "➕ Yeni Cari Aç", "📦 Devir/Tahliye İşlemleri", "🛠️ İşlem Düzeltme / Silme"])
        
        with tab1:
            st.subheader("Cari Güncelleme")
            c.execute("SELECT id, ev_sahibi, kiraci, ev_sahibi_tel, kiraci_tel FROM daireler")
            tum = c.fetchall()
            if tum:
                d_soz = {d[0]: d for d in tum}
                s_id = st.selectbox("İşlem Yapılacak Cariyi Seçin:", options=list(d_soz.keys()))
                if s_id:
                    mevcut = d_soz[s_id]
                    with st.form("kisi_guncelleme_formu"):
                        c1, c2 = st.columns(2)
                        with c1: 
                            y_ev = st.text_input("Ev Sahibi İsim", value=mevcut[1])
                            y_ev_tel = st.text_input("Ev Sahibi Telefon", value=mevcut[3])
                        with c2: 
                            y_ki = st.text_input("Kiracı İsim", value=mevcut[2])
                            y_ki_tel = st.text_input("Kiracı Telefon", value=mevcut[4])
                        if st.form_submit_button("💾 Bilgileri Güncelle", type="primary"):
                            try:
                                c.execute('''UPDATE daireler SET ev_sahibi=?, ev_sahibi_tel=?, kiraci=?, kiraci_tel=? WHERE id=?''', (y_ev.upper().strip(), y_ev_tel.strip(), y_ki.upper().strip(), y_ki_tel.strip(), s_id))
                                conn.commit()
                                st.success(f"{s_id} güncellendi!")
                                st.rerun()
                            except Exception as e:
                                conn.rollback(); st.error(f"Hata: {e}")
                            
        with tab2:
            st.subheader("Yeni Bağımsız Bölüm veya Alt Cari Oluştur")
            with st.form("yeni_daire_formu"):
                y_id = st.text_input("Daire veya Cari Kodu (Örn: B-12)")
                y_ev = st.text_input("Kişinin/Ev Sahibinin Adı Soyadı")
                y_ki = st.text_input("Kiracı Adı Soyadı")
                y_bakiye = st.number_input("Başlangıç Bakiyesi (- borç, + alacak)", value=0.0)
                if st.form_submit_button("➕ Sisteme Ekle", type="primary"):
                    if y_id.strip():
                        try:
                            c.execute("INSERT INTO daireler (id, blok, daire_no, ev_sahibi, kiraci, bakiye, ev_sahibi_tel, kiraci_tel) VALUES (?, ?, ?, ?, ?, ?, '', '')", (y_id.upper().strip(), "", "", y_ev.upper().strip(), y_ki.upper().strip(), float(y_bakiye)))
                            c.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, daire_id) VALUES (?, '12345', 'sakin', ?)", (y_id.upper().strip(), y_id.upper().strip()))
                            conn.commit()
                            st.success(f"{y_id.upper().strip()} eklendi.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(f"'{y_id.upper().strip()}' kodlu daire zaten var.")
                        except Exception as e:
                            conn.rollback(); st.error(f"Hata: {e}")
                    else:
                        st.warning("Daire kodu boş bırakılamaz.")
                        
        with tab3:
            st.subheader("📦 Devir İşlemleri")
            c.execute("SELECT id, ev_sahibi, kiraci FROM daireler WHERE id NOT LIKE '%EV SAHİBİ%' AND id NOT LIKE '%EV SAHIBI%'")
            d_listesi = {d[0]: d for d in c.fetchall()}
            sec_d = st.selectbox("İşlem Yapılacak Daire/Cari:", options=list(d_listesi.keys()), key="tahliye_sec")
            if sec_d:
                col_sat, col_kir = st.columns(2)
                with col_sat:
                    st.write(f"Mevcut Sahip: **{d_listesi[sec_d][1]}**")
                    with st.form("ev_satildi_formu"):
                        yeni_sahip = st.text_input("YENİ Ev Sahibinin Adı:")
                        if st.form_submit_button("🏠 Eski Sahibini Sil, Devret", type="primary"):
                            if yeni_sahip.strip():
                                try:
                                    c.execute("UPDATE daireler SET ev_sahibi=? WHERE id=?", (yeni_sahip.upper().strip(), sec_d))
                                    alt_cari_id = f"{sec_d} (EV SAHİBİ)"
                                    c.execute("SELECT bakiye FROM daireler WHERE id=?", (alt_cari_id,))
                                    alt_cari = c.fetchone()
                                    if alt_cari:
                                        c.execute("UPDATE daireler SET ev_sahibi=? WHERE id=?", (yeni_sahip.upper().strip(), alt_cari_id))
                                        if alt_cari[0] < -1.0:
                                            st.warning(f"⚠️ Bilgi: Bu dairenin eski sahibinden devreden {abs(alt_cari[0]):,.2f} TL demirbaş borcu bulunmaktadır. Yeni mülk sahibine devredildi.")
                                    conn.commit()
                                    st.success("Tapu devri ve alt cari güncellemeleri başarılı!")
                                    st.rerun()
                                except Exception as e: 
                                    conn.rollback(); st.error(f"Hata: {e}")
                with col_kir:
                    st.write(f"Mevcut Kiracı: **{d_listesi[sec_d][2]}**")
                    with st.form("kiraci_cikti_formu"):
                        yeni_kiraci = st.text_input("YENİ Kiracının Adı:")
                        if st.form_submit_button("📦 Eski Kiracıyı Çıkar, Ata", type="primary"):
                            try:
                                c.execute("UPDATE daireler SET kiraci=? WHERE id=?", (yeni_kiraci.upper().strip(), sec_d))
                                conn.commit()
                                st.success("Tahliye başarılı!")
                                st.rerun()
                            except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
                            
        with tab4:
            st.subheader("🛠️ Akıllı İşlem Düzeltme (Ters Kayıt)")
            st.info("💡 Buradan sildiğiniz işlemin tutarı, ilgili dairenin bakiyesinden otomatik olarak geri çekilir veya borcuna geri eklenir.")
            df_tum_islem = pd.read_sql_query("SELECT id, tarih, tutar, islem_tipi, aciklama, daire_id FROM islemler ORDER BY id DESC LIMIT 100", conn)
            
            if not df_tum_islem.empty:
                st.dataframe(df_tum_islem, use_container_width=True)
                with st.form("islem_sil_formu"):
                    silinecek_id = st.number_input("Silmek İstediğiniz İşlem ID Numarası:", min_value=1, step=1)
                    if st.form_submit_button("🗑️ İşlemi Sil ve Bakiyeyi Geri Al", type="primary"):
                        try:
                            c.execute("SELECT tutar, islem_tipi, daire_id FROM islemler WHERE id = ?", (int(silinecek_id),))
                            islem = c.fetchone()
                            
                            if islem:
                                islem_tutar, islem_tipi, islem_daire_id = islem
                                if islem_tipi in ['Çoklu Dağıtım', 'Kapatıldı', 'Çoklu Beklemede']:
                                    st.error("❌ GÜVENLİK İHLALİ: Toplu dağıtım işlemlerini buradan silemezsiniz!")
                                else:
                                    gelir_tipleri = ['Otomatik Tahsilat', 'Manuel Tahsilat', 'Elden Tahsilat']
                                    borc_tipleri = ['Borçlandırma (Aidat)', 'Ek Aidat Borcu', 'Demirbaş Borcu', 'Gecikme Faizi']
                                    
                                    if islem_tipi in gelir_tipleri:
                                        c.execute("UPDATE daireler SET bakiye = ROUND(bakiye - ?, 2) WHERE id = ?", (islem_tutar, islem_daire_id))
                                    elif islem_tipi in borc_tipleri:
                                        c.execute("UPDATE daireler SET bakiye = ROUND(bakiye + ?, 2) WHERE id = ?", (islem_tutar, islem_daire_id))
                                        
                                    c.execute("DELETE FROM islemler WHERE id = ?", (int(silinecek_id),))
                                    conn.commit()
                                    st.success(f"✅ ID {silinecek_id} numaralı işlem silindi ve bakiyeler düzeltildi!")
                                    st.rerun()
                            else:
                                st.error("Bu ID numarasına ait bir işlem bulunamadı.")
                        except Exception as e:
                            conn.rollback(); st.error(f"Hata oluştu: {e}")
            else:
                st.warning("Görüntülenecek işlem geçmişi bulunmuyor.")
        conn.close()

    # ---------------------------------------------------------
    # MANUEL İŞLEMLER
    # ---------------------------------------------------------
    elif secim == "Manuel Gelir/Gider":
        st.title("💸 Manuel İşlem Merkezi")
        conn = get_db_connection()
        c = conn.cursor()
        tab1, tab2 = st.tabs(["📥 Elden Nakit", "📤 Arıza / Fatura Gideri"])
        with tab1:
            c.execute("SELECT id, ev_sahibi FROM daireler")
            d_sec = {d[0]: d[0] for d in c.fetchall()}
            with st.form("gelir_formu"):
                g_daire = st.selectbox("Parayı Veren", options=list(d_sec.keys()))
                g_tarih = st.date_input("Tarih")
                g_tutar = st.number_input("Tutar (TL)", min_value=0.0)
                g_aciklama = st.text_input("Açıklama")
                if st.form_submit_button("📥 Gelir Ekle", type="primary"):
                    try:
                        tarih_str = tarih_temizle(str(g_tarih))
                        c.execute("UPDATE daireler SET bakiye = ROUND(bakiye + ?, 2) WHERE id = ?", (g_tutar, g_daire))
                        c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Elden Tahsilat', ?, ?)", (tarih_str, g_tutar, g_aciklama.strip(), g_daire))
                        conn.commit()
                        st.success("İşlem kaydedildi! 'Makbuz & Belge Çıktısı' menüsünden makbuz kesebilirsiniz.")
                    except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
        with tab2:
            with st.form("gider_formu"):
                kategori = st.selectbox("Kategori", KATEGORILER)
                f_tarih = st.date_input("Harcama Tarihi")
                f_tutar = st.number_input("Tutar (TL)", min_value=0.0)
                f_aciklama = st.text_input("Detay")
                if st.form_submit_button("📤 Gider Düş", type="primary"):
                    try:
                        tarih_str = tarih_temizle(str(f_tarih))
                        c.execute("INSERT INTO islemler (tarih, tutar, islem_tipi, aciklama, daire_id) VALUES (?, ?, 'Gider', ?, 'SİTE GENELİ')", (tarih_str, f_tutar, f"[{kategori}] {f_aciklama.strip()}"))
                        conn.commit()
                        st.success("Gider işlendi! 'Makbuz & Belge Çıktısı' menüsünden pusula kesebilirsiniz.")
                    except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
        conn.close()

    # ---------------------------------------------------------
    # RESMİ BELGELER (MAKBUZ VE GİDER PUSULASI)
    # ---------------------------------------------------------
    elif secim == "📄 Makbuz & Belge Çıktısı":
        st.title("📄 Resmi Belge ve Çıktı Merkezi")
        st.info("Sisteme işlenmiş olan gelirler için 'Tahsilat Makbuzu', giderler için ise maliyeye uygun 'Gider Pusulası' oluşturabilirsiniz.")
        
        conn = get_db_connection()
        c = conn.cursor()
        
        tab1, tab2 = st.tabs(["🧾 Tahsilat Makbuzu (Gelirler)", "📄 Gider Pusulası (Giderler)"])
        
        with tab1:
            st.subheader("🧾 Tahsilat Makbuzu Oluştur")
            c.execute("SELECT id, tarih, tutar, aciklama, daire_id FROM islemler WHERE islem_tipi IN ('Otomatik Tahsilat', 'Manuel Tahsilat', 'Elden Tahsilat', 'Çoklu Dağıtım') ORDER BY id DESC LIMIT 100")
            tahsilatlar = c.fetchall()
            
            if not tahsilatlar:
                st.warning("Henüz sistemde kayıtlı bir tahsilat bulunmuyor.")
            else:
                tahsilat_options = {t[0]: f"Tarih: {t[1]} | Cari: {t[4]} | Tutar: {t[2]:,.2f} TL | İşlem No: {t[0]}" for t in tahsilatlar}
                secilen_tahsilat_id = st.selectbox("Makbuzu Kesilecek İşlemi Seçin:", options=list(tahsilat_options.keys()), format_func=lambda x: tahsilat_options[x])
                
                if st.button("🧾 Makbuzu Görüntüle ve Yazdır", type="primary"):
                    secilen_islem = next(t for t in tahsilatlar if t[0] == secilen_tahsilat_id)
                    t_id, t_tarih, t_tutar, t_aciklama, t_daire = secilen_islem
                    
                    c.execute("SELECT ev_sahibi, kiraci FROM daireler WHERE id = ?", (t_daire,))
                    kisi_bilgisi = c.fetchone()
                    kisi_adi = t_daire
                    if kisi_bilgisi:
                        if kisi_bilgisi[1]: kisi_adi = f"{kisi_bilgisi[1]} (Kiracı)"
                        elif kisi_bilgisi[0]: kisi_adi = f"{kisi_bilgisi[0]} (Ev Sahibi)"
                    
                    guvenli_aciklama = html.escape(str(t_aciklama))
                    guvenli_kisi = html.escape(str(kisi_adi))
                    
                    makbuz_html = f"""
                    <!DOCTYPE html>
                    <html lang="tr">
                    <head>
                        <meta charset="UTF-8">
                        <style>
                            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; color: #1E293B; }}
                            .makbuz-container {{ border: 2px solid #1E293B; padding: 40px; border-radius: 10px; max-width: 700px; margin: auto; background-color: #fff; position: relative; }}
                            .header {{ text-align: center; border-bottom: 3px solid #1E293B; padding-bottom: 15px; margin-bottom: 25px; }}
                            .header h2 {{ margin: 0; color: #1E293B; font-size: 26px; }}
                            .header h4 {{ margin: 5px 0 0 0; color: #64748B; font-weight: normal; }}
                            .title {{ text-align: center; font-size: 22px; font-weight: bold; letter-spacing: 3px; margin-bottom: 30px; text-decoration: underline; }}
                            .row {{ display: flex; margin-bottom: 15px; font-size: 16px; align-items: baseline; }}
                            .label {{ font-weight: bold; width: 180px; flex-shrink: 0; }}
                            .value {{ border-bottom: 1px dotted #cbd5e1; flex-grow: 1; padding-left: 10px; font-family: monospace; font-size: 18px; }}
                            .imza-area {{ display: flex; justify-content: space-between; margin-top: 60px; text-align: center; font-weight: bold; }}
                            .imza-box {{ width: 200px; }}
                            .btn-print {{ display: block; width: 100%; padding: 15px; background-color: #0056b3; color: white; border: none; font-size: 18px; cursor: pointer; border-radius: 8px; margin-bottom: 20px; font-weight: bold; }}
                            @media print {{
                                .btn-print {{ display: none !important; }}
                                body {{ padding: 0; background-color: white; }}
                                .makbuz-container {{ border: none; padding: 0; width: 100%; max-width: 100%; border-radius: 0; }}
                            }}
                        </style>
                    </head>
                    <body>
                        <button class="btn-print" onclick="window.print()">🖨️ Makbuzu PDF Olarak Kaydet / Yazdır</button>
                        <div class="makbuz-container">
                            <div class="header">
                                <h2>ARNOVA SİTESİ YÖNETİMİ</h2>
                                <h4>Site Yönetim Tahsilat Belgesi</h4>
                            </div>
                            <div class="title">TAHSİLAT MAKBUZU</div>
                            
                            <div class="row"><div class="label">Makbuz No:</div><div class="value">{t_id}</div></div>
                            <div class="row"><div class="label">Tarih:</div><div class="value">{t_tarih}</div></div>
                            <div class="row"><div class="label">Sayın:</div><div class="value">{guvenli_kisi}</div></div>
                            <div class="row"><div class="label">Daire / Kodu:</div><div class="value">{t_daire}</div></div>
                            <div class="row"><div class="label">Tahsil Edilen Tutar:</div><div class="value">{t_tutar:,.2f} TL</div></div>
                            <div class="row"><div class="label">Açıklama:</div><div class="value">{guvenli_aciklama}</div></div>
                            
                            <div class="imza-area">
                                <div class="imza-box"><p>Ödemeyi Yapan</p><br><br><br><p>İmza</p></div>
                                <div class="imza-box"><p>Tahsilatı Yapan (Yönetim)</p><br><br><br><p>Kaşe / İmza</p></div>
                            </div>
                        </div>
                    </body>
                    </html>
                    """
                    st.components.v1.html(makbuz_html, height=700, scrolling=True)

        with tab2:
            st.subheader("📄 Resmi Gider Pusulası Oluştur")
            c.execute("SELECT id, tarih, tutar, aciklama FROM islemler WHERE islem_tipi = 'Gider' ORDER BY id DESC LIMIT 100")
            giderler = c.fetchall()
            
            if not giderler:
                st.warning("Henüz sistemde kayıtlı bir gider bulunmuyor.")
            else:
                gider_options = {g[0]: f"Tarih: {g[1]} | Tutar: {g[2]:,.2f} TL | {g[3]}" for g in giderler}
                secilen_gider_id = st.selectbox("Pusulası Kesilecek Gideri Seçin:", options=list(gider_options.keys()), format_func=lambda x: gider_options[x])
                
                with st.form("gider_pusulasi_formu"):
                    st.write("📌 **Resmi Belge Bilgileri (Maliye İçin)**")
                    col_gp1, col_gp2 = st.columns(2)
                    with col_gp1:
                        gp_ad = st.text_input("Ödeme Yapılanın Adı / Unvanı:")
                        gp_tc = st.text_input("T.C. Kimlik veya Vergi No (İsteğe bağlı):")
                    with col_gp2:
                        gp_adres = st.text_input("Adresi (İsteğe bağlı):")
                        gp_stopaj = st.number_input("Gelir Vergisi Stopaj Oranı (%):", min_value=0, max_value=100, value=0, help="Eğer ödediğiniz tutar NET ise, sistem bu orana göre BRÜT tutarı maliyeye uygun hesaplar.")
                        
                    if st.form_submit_button("📄 Pusulayı Görüntüle ve Yazdır", type="primary"):
                        secilen_gider = next(g for g in giderler if g[0] == secilen_gider_id)
                        g_id, g_tarih, net_tutar, g_aciklama = secilen_gider
                        
                        if gp_stopaj > 0:
                            oran = gp_stopaj / 100.0
                            brut_tutar = net_tutar / (1 - oran)
                            kesinti_tutari = brut_tutar - net_tutar
                        else:
                            brut_tutar = net_tutar
                            kesinti_tutari = 0.0
                            
                        isin_mahiyeti = g_aciklama
                        match = re.search(r'\[(.*?)\]\s*(.*)', g_aciklama)
                        if match: isin_mahiyeti = f"{match.group(2)} ({match.group(1)})"
                            
                        guvenli_ad = html.escape(str(gp_ad))
                        guvenli_tc = html.escape(str(gp_tc))
                        guvenli_adres = html.escape(str(gp_adres))
                        guvenli_is = html.escape(str(isin_mahiyeti))
                            
                        pusula_html = f"""
                        <!DOCTYPE html>
                        <html lang="tr">
                        <head>
                            <meta charset="UTF-8">
                            <style>
                                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; color: #1E293B; }}
                                .pusula-container {{ border: 2px solid #1E293B; padding: 40px; border-radius: 10px; max-width: 700px; margin: auto; background-color: #fff; position: relative; }}
                                .header {{ text-align: center; border-bottom: 3px solid #1E293B; padding-bottom: 15px; margin-bottom: 25px; }}
                                .header h2 {{ margin: 0; color: #1E293B; font-size: 26px; }}
                                .title {{ text-align: center; font-size: 22px; font-weight: bold; letter-spacing: 3px; margin-bottom: 30px; text-decoration: underline; }}
                                .row {{ display: flex; margin-bottom: 15px; font-size: 15px; align-items: baseline; }}
                                .label {{ font-weight: bold; width: 200px; flex-shrink: 0; }}
                                .value {{ border-bottom: 1px dotted #cbd5e1; flex-grow: 1; padding-left: 10px; font-family: monospace; font-size: 16px; }}
                                .imza-area {{ display: flex; justify-content: space-between; margin-top: 50px; text-align: center; font-weight: bold; font-size: 14px;}}
                                .imza-box {{ width: 45%; border: 1px solid #ccc; padding: 20px; border-radius: 5px;}}
                                .btn-print {{ display: block; width: 100%; padding: 15px; background-color: #0056b3; color: white; border: none; font-size: 18px; cursor: pointer; border-radius: 8px; margin-bottom: 20px; font-weight: bold; }}
                                .maliye-kutusu {{ border: 2px solid #e2e8f0; padding: 15px; margin-top: 20px; border-radius: 5px; background-color: #f8fafc;}}
                                @media print {{
                                    .btn-print {{ display: none !important; }}
                                    body {{ padding: 0; background-color: white; }}
                                    .pusula-container {{ border: none; padding: 0; width: 100%; max-width: 100%; border-radius: 0; }}
                                }}
                            </style>
                        </head>
                        <body>
                            <button class="btn-print" onclick="window.print()">🖨️ Pusulayı PDF Olarak Kaydet / Yazdır</button>
                            <div class="pusula-container">
                                <div class="header"><h2>ARNOVA SİTESİ YÖNETİMİ</h2></div>
                                <div class="title">GİDER PUSULASI</div>
                                <div class="row"><div class="label">Pusula / İşlem No:</div><div class="value">{g_id}</div></div>
                                <div class="row"><div class="label">Tarih:</div><div class="value">{g_tarih}</div></div>
                                <div class="row"><div class="label">İşi Yapanın Adı/Unvanı:</div><div class="value">{guvenli_ad}</div></div>
                                <div class="row"><div class="label">T.C. Kimlik / Vergi No:</div><div class="value">{guvenli_tc}</div></div>
                                <div class="row"><div class="label">Adresi:</div><div class="value">{guvenli_adres}</div></div>
                                <div class="row"><div class="label">İşin Mahiyeti:</div><div class="value">{guvenli_is}</div></div>
                                
                                <div class="maliye-kutusu">
                                    <div class="row"><div class="label">Brüt Tutar:</div><div class="value">{brut_tutar:,.2f} TL</div></div>
                                    <div class="row"><div class="label">Gelir Vergisi (Stopaj) %{gp_stopaj}:</div><div class="value" style="color: red;">- {kesinti_tutari:,.2f} TL</div></div>
                                    <div class="row" style="font-size: 18px; font-weight: bold;"><div class="label">NET ÖDENEN TUTAR:</div><div class="value">{net_tutar:,.2f} TL</div></div>
                                </div>
                                
                                <div class="imza-area">
                                    <div class="imza-box"><p>Ödemeyi Yapan (Müşteri)</p><p style="font-weight: normal; font-size: 12px;">Arnova Sitesi Yönetimi</p><br><br><p>İmza</p></div>
                                    <div class="imza-box"><p>İşi Yapan (Hizmeti Veren)</p><p style="font-weight: normal; font-size: 12px;">Yukarıda yazılı net tutarı eksiksiz teslim aldım.</p><br><br><p>İmza</p></div>
                                </div>
                            </div>
                        </body>
                        </html>
                        """
                        st.components.v1.html(pusula_html, height=850, scrolling=True)
        conn.close()

    # ---------------------------------------------------------
    # PROFESYONEL RAPORLAMA VE PDF ÇIKTISI
    # ---------------------------------------------------------
    elif secim == "Yönetim Raporları":
        st.title("📊 Yönetim Raporlama Merkezi")
        conn = get_db_connection()
        c = conn.cursor()
        
        st.subheader("🗓️ Rapor Dönemi ve Kriterleri")
        col_filtre1, col_filtre2, col_filtre3 = st.columns(3)
        with col_filtre1: zaman_secimi = st.selectbox("Zaman Aralığı", ["Tüm Zamanlar", "Son 1 Ay", "Son 2 Ay", "Son 3 Ay", "Son 6 Ay", "Son 1 Yıl", "Özel Tarih Seç"])
        bugun = datetime.now()
        baslangic_tarihi = bugun; bitis_tarihi = bugun
        
        if zaman_secimi == "Tüm Zamanlar": baslangic_tarihi = datetime(2000, 1, 1)
        elif zaman_secimi == "Son 1 Ay": baslangic_tarihi = bugun - timedelta(days=30)
        elif zaman_secimi == "Son 2 Ay": baslangic_tarihi = bugun - timedelta(days=60)
        elif zaman_secimi == "Son 3 Ay": baslangic_tarihi = bugun - timedelta(days=90)
        elif zaman_secimi == "Son 6 Ay": baslangic_tarihi = bugun - timedelta(days=180)
        elif zaman_secimi == "Son 1 Yıl": baslangic_tarihi = bugun - timedelta(days=365)
            
        with col_filtre2:
            if zaman_secimi == "Özel Tarih Seç": baslangic_tarihi = st.date_input("Başlangıç", bugun - timedelta(days=30)); bitis_tarihi = st.date_input("Bitiş", bugun)
            else: st.info(f"Seçilen: {baslangic_tarihi.strftime('%d.%m.%Y')} - {bitis_tarihi.strftime('%d.%m.%Y')}")
                
        with col_filtre3:
            c.execute("SELECT deger FROM ayarlar WHERE ayar_adi='otomatik_aidat_tutari'")
            ayar_sonucu = c.fetchone()
            kayitli_aidat = float(ayar_sonucu[0]) if ayar_sonucu else 1000.0
            standart_aidat = st.number_input("Aidat Tutarı (Hesap İçin):", value=kayitli_aidat, step=100.0)
            
        st.subheader("🏢 Kurumlara Ödenmesi Gereken Borçlar")
        c1, c2, c3, c4 = st.columns(4)
        with c1: borc_asansor = st.number_input("Asansör Borcu (-)", value=0.0, step=100.0)
        with c2: borc_personel = st.number_input("Personel Borcu (-)", value=0.0, step=100.0)
        with c3: borc_aski = st.number_input("Aski Borcu (-)", value=0.0, step=100.0)
        with c4: borc_aydem = st.number_input("Aydem Borcu (-)", value=0.0, step=100.0)
        toplam_kurum_borcu = borc_asansor + borc_personel + borc_aski + borc_aydem
        st.divider()
        
        if st.button("📄 Raporu Oluştur", use_container_width=True, type="primary"):
            sorgu_gider = "SELECT tarih, aciklama, tutar FROM islemler WHERE islem_tipi='Gider'"
            sorgu_gelir = "SELECT tarih, tutar as top FROM islemler WHERE islem_tipi IN ('Otomatik Tahsilat', 'Manuel Tahsilat', 'Elden Tahsilat', 'Çoklu Dağıtım')"
            df_giderler = pd.read_sql_query(sorgu_gider, conn)
            df_gelir = pd.read_sql_query(sorgu_gelir, conn)
            bas_dt = pd.to_datetime(baslangic_tarihi); bit_dt = pd.to_datetime(bitis_tarihi) + pd.Timedelta(days=1, seconds=-1)
            
            if not df_giderler.empty:
                df_giderler['tarih'] = pd.to_datetime(df_giderler['tarih'], dayfirst=True, errors='coerce')
                df_giderler = df_giderler[(df_giderler['tarih'] >= bas_dt) & (df_giderler['tarih'] <= bit_dt)]
                toplam_gider = df_giderler['tutar'].sum()
            else: toplam_gider = 0
                
            if not df_gelir.empty:
                df_gelir['tarih'] = pd.to_datetime(df_gelir['tarih'], dayfirst=True, errors='coerce')
                df_gelir = df_gelir[(df_gelir['tarih'] >= bas_dt) & (df_gelir['tarih'] <= bit_dt)]
                toplam_gelir = df_gelir['top'].sum()
            else: toplam_gelir = 0
                
            net_bakiye = round(toplam_gelir - toplam_gider - toplam_kurum_borcu, 2)

            with st.container(border=True):
                st.markdown(f"<h2 style='text-align: center; color: #1E293B;'>ARNOVA SİTESİ YÖNETİMİ</h2>", unsafe_allow_html=True)
                st.markdown(f"<h4 style='text-align: center; color: #64748B;'>Mali Dönem Hesap Raporu ({baslangic_tarihi.strftime('%d.%m.%Y')} - {bitis_tarihi.strftime('%d.%m.%Y')})</h4>", unsafe_allow_html=True)
                st.divider()
                col_ozet1, col_ozet2 = st.columns([1, 1])
                with col_ozet1:
                    st.markdown("#### Genel Durum Özeti")
                    st.markdown(f"**Toplam Toplanan Gelir:** {toplam_gelir:,.2f} TL")
                    st.markdown(f"**Toplam Çıkan Gider:** {toplam_gider:,.2f} TL")
                    if net_bakiye >= 0: st.success(f"### Kasa Net Bakiye: {net_bakiye:,.2f} TL")
                    else: st.error(f"### Kasa Net Bakiye: {net_bakiye:,.2f} TL")
                with col_ozet2:
                    st.markdown("#### Döneme Ait Kurum Borçları")
                    st.markdown(f"- Asansör Borcu: **-{borc_asansor:,.2f} TL**")
                    st.markdown(f"- Personel Maliyeti: **-{borc_personel:,.2f} TL**")
                    st.markdown(f"- Aski Su Borcu: **-{borc_aski:,.2f} TL**")
                    st.markdown(f"- Aydem Elektrik Borcu: **-{borc_aydem:,.2f} TL**")
                    st.error(f"**Gelecek Döneme Devreden Borç:** -{toplam_kurum_borcu:,.2f} TL")
                
                st.divider()
                st.markdown("#### Gider Kalemleri Detay Tablosu")
                col_tablo, col_pasta = st.columns([1, 1.2])
                with col_tablo:
                    if not df_giderler.empty:
                        def get_kategori(text):
                            match = re.search(r'\[(.*?)\]', text)
                            return match.group(1) if match else "Diğer Giderler"
                        df_giderler['Gider Açıklaması'] = df_giderler['aciklama'].apply(get_kategori)
                        gider_tablosu = df_giderler.groupby('Gider Açıklaması')['tutar'].sum().reset_index()
                        gider_tablosu = gider_tablosu.rename(columns={'tutar': 'Harcanan Tutar (TL)'})
                        gider_tablosu = gider_tablosu.sort_values(by='Harcanan Tutar (TL)', ascending=False)
                        if toplam_gider > 0: gider_tablosu['Yüzde (%)'] = ((gider_tablosu['Harcanan Tutar (TL)'] / toplam_gider) * 100).round(2).astype(str) + "%"
                        else: gider_tablosu['Yüzde (%)'] = "0%"
                        st.dataframe(gider_tablosu, use_container_width=True, hide_index=True)
                    else:
                        gider_tablosu = pd.DataFrame()
                with col_pasta:
                    if not gider_tablosu.empty and toplam_gider > 0:
                        st.markdown("<p style='text-align: center; font-weight: bold; color:#1E293B;'>Gider Dağılımı</p>", unsafe_allow_html=True)
                        fig1, ax1 = plt.subplots(figsize=(8, 4.5))
                        fig1.patch.set_alpha(0.0); ax1.patch.set_alpha(0.0)
                        renkler = ['#2ecc71', '#e74c3c', '#3498db', '#f1c40f', '#9b59b6', '#34495e', '#e67e22', '#7f8c8d', '#1abc9c']
                        wedges, texts, autotexts = ax1.pie(gider_tablosu['Harcanan Tutar (TL)'], autopct='%1.1f%%', startangle=140, colors=renkler, wedgeprops={'edgecolor': 'white'})
                        etiketler = [f"{row['Gider Açıklaması']} ({row['Harcanan Tutar (TL)']:,.2f} TL)" for _, row in gider_tablosu.iterrows()]
                        ax1.legend(wedges, etiketler, title="Kategoriler", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
                        ax1.axis('equal'); st.pyplot(fig1, use_container_width=True)

                st.divider()
                st.markdown("#### Aidat Borç Durumu")
                col_borc_metin, col_borc_pasta = st.columns([1, 1.2])
                df_daireler = pd.read_sql_query("SELECT id, ROUND(bakiye, 2) as bakiye FROM daireler", conn)
                borclular = df_daireler[df_daireler['bakiye'] <= -1.0].copy()
                borcsuzlar = df_daireler[df_daireler['bakiye'] > -1.0]
                if not borclular.empty:
                    borclular['kac_ay'] = (borclular['bakiye'].abs() / standart_aidat).round().astype(int)
                    borclular.loc[(borclular['kac_ay'] == 0) & (borclular['bakiye'] <= -1.0), 'kac_ay'] = 1 
                    borclular['Durum'] = borclular['kac_ay'].apply(lambda x: "1 Ay Gecikmeli" if x == 1 else ("2 Ay Gecikmeli" if x == 2 else "3 Ay ve Üzeri Gecikmeli"))
                    borc_grup = borclular.groupby('Durum').size().reset_index(name='Daire Sayısı')
                else: borc_grup = pd.DataFrame(columns=['Durum', 'Daire Sayısı'])
                borcsuz_satir = pd.DataFrame([{'Durum': 'Borcu Yok / Düzenli Ödeyen', 'Daire Sayısı': len(borcsuzlar)}])
                final_borc_tablosu = pd.concat([borc_grup, borcsuz_satir], ignore_index=True)
                with col_borc_metin: st.dataframe(final_borc_tablosu, use_container_width=True, hide_index=True)
                with col_borc_pasta:
                    if not final_borc_tablosu.empty:
                        st.markdown("<p style='text-align: center; font-weight: bold; color:#1E293B;'>Ödeme Dağılımı</p>", unsafe_allow_html=True)
                        fig2, ax2 = plt.subplots(figsize=(8, 4.5))
                        fig2.patch.set_alpha(0.0); ax2.patch.set_alpha(0.0)
                        ren_sozlugu = {'Borcu Yok / Düzenli Ödeyen': '#2ecc71', '1 Ay Gecikmeli': '#f1c40f', '2 Ay Gecikmeli': '#e67e22', '3 Ay ve Üzeri Gecikmeli': '#e74c3c'}
                        secilen_renkler = [ren_sozlugu[durum] for durum in final_borc_tablosu['Durum']]
                        wedges_borc, _, _ = ax2.pie(final_borc_tablosu['Daire Sayısı'], autopct='%1.1f%%', startangle=90, colors=secilen_renkler, wedgeprops={'edgecolor': 'white'})
                        etiketler_borc = [f"{row['Durum']} ({row['Daire Sayısı']} Daire)" for _, row in final_borc_tablosu.iterrows()]
                        ax2.legend(wedges_borc, etiketler_borc, title="Borç Durumu", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
                        ax2.axis('equal'); st.pyplot(fig2, use_container_width=True)
                st.write("<br>", unsafe_allow_html=True)
                st.caption("Yukarıdaki tablo ve grafikler, resmi kasa kayıtları doğrultusunda hazırlanmıştır. Bilgilerinize sunulur.")
                st.markdown("**Arnova Site Yönetimi**")
            
            components.html("""<script>function printReport() { window.parent.print(); }</script><button onclick="printReport()" style="background-color:#0056b3; color:white; padding:12px 24px; border:none; border-radius:8px; cursor:pointer; font-weight:bold; width:100%; font-size:16px;">🖨️ Raporu PDF Olarak Kaydet (Yazdır)</button>""", height=60)
            
        st.divider()
        st.subheader("💾 Veritabanını Orijinal Formatında İndir")
        df_daireler_export = pd.read_sql_query("SELECT * FROM daireler", conn)
        df_export = pd.DataFrame()
        def get_blok(row):
            b = row.get('blok')
            if pd.isna(b) or not b: return f"Blok: {str(row['id']).split('-')[0]}" if "-" in str(row['id']) else ""
            return f"Blok: {b}"
        def get_daire(row):
            d = row.get('daire_no')
            if pd.isna(d) or not d: return f"Daire No: {str(row['id']).split('-')[1]}" if "-" in str(row['id']) else row['id']
            return f"Daire No: {d}"
            
        df_export['Git'] = ""
        df_export['Ev Sahibi Adı'] = df_daireler_export['ev_sahibi']
        df_export['Kiracı Adı'] = df_daireler_export['kiraci']
        df_export['Blok'] = df_daireler_export.apply(get_blok, axis=1)
        df_export['Daire'] = df_daireler_export.apply(get_daire, axis=1)
        df_export['Borç'] = -round(df_daireler_export['bakiye'], 2)
        df_export['Ev Sahibi Tel'] = df_daireler_export['ev_sahibi_tel']
        df_export['Kiracı Tel'] = df_daireler_export['kiraci_tel']

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name="Genel Toplam Bilgisi")
            pd.read_sql_query("SELECT * FROM islemler", conn).to_excel(writer, index=False, sheet_name="İşlem Geçmişi (Yedek)")
            
        st.download_button("Orijinal Formatta Excel İndir", output.getvalue(), "Arnova_Guncel_Durum.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        conn.close()

    # ---------------------------------------------------------
    # SİSTEM ŞİFRELERİ VE YETKİ YÖNETİMİ
    # ---------------------------------------------------------
    elif secim == "Sistem Şifreleri":
        st.title("🔑 Sistem Şifreleri ve Yetki Yönetimi")
        conn = get_db_connection()
        c = conn.cursor()
        tab1, tab2 = st.tabs(["👥 Daire/Sakin Şifreleri", "🛡️ Yönetici ve Denetçi Yetkileri"])
        
        with tab1:
            st.subheader("Daire (Sakin) Giriş Şifreleri")
            df_sifreler = pd.read_sql_query("SELECT kullanici_adi as 'Giriş (Cari Kodu)', sifre as 'Şifre' FROM kullanicilar WHERE rol='sakin'", conn)
            st.dataframe(df_sifreler, use_container_width=True)
            
            c.execute("SELECT kullanici_adi FROM kullanicilar WHERE rol='sakin'")
            sakin_listesi = [r[0] for r in c.fetchall()]
            if sakin_listesi:
                with st.form("sakin_sifre_degistir"):
                    secilen_sakin = st.selectbox("Şifresi Değişecek Cari:", sakin_listesi)
                    yeni_sifre = st.text_input("Yeni Şifre:")
                    if st.form_submit_button("Şifreyi Güncelle", type="primary"):
                        if yeni_sifre.strip():
                            try:
                                c.execute("UPDATE kullanicilar SET sifre=? WHERE kullanici_adi=? AND rol='sakin'", (yeni_sifre.strip(), secilen_sakin))
                                conn.commit()
                                st.success(f"{secilen_sakin} carisinin şifresi güncellendi!")
                                st.rerun()
                            except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
                        else: st.error("Yeni şifre girin.")
            
        with tab2:
            st.subheader("🛡️ Sistem Yöneticileri ve Denetçiler")
            df_yetkililer = pd.read_sql_query("SELECT kullanici_adi as 'Kullanıcı Adı', sifre as 'Şifre', rol as 'Yetki Seviyesi' FROM kullanicilar WHERE rol IN ('admin', 'gozlemci')", conn)
            df_yetkililer['Yetki Seviyesi'] = df_yetkililer['Yetki Seviyesi'].replace({'admin': 'Ana Yönetici (Admin)', 'gozlemci': 'Denetçi (Gözlemci)'})
            st.dataframe(df_yetkililer, use_container_width=True)
            
            col_ekle, col_sil = st.columns(2)
            with col_ekle:
                with st.container(border=True):
                    st.markdown("#### ➕ Yeni Yetkili Ekle")
                    with st.form("yetkili_ekle"):
                        y_kadi = st.text_input("Yeni Kullanıcı Adı:")
                        y_sifre = st.text_input("Yeni Şifre:")
                        y_rol = st.selectbox("Yetki Türü:", ["Denetçi (Gözlemci)", "Ana Yönetici (Admin)"])
                        if st.form_submit_button("Sisteme Ekle", type="primary"):
                            if y_kadi.strip() and y_sifre.strip():
                                rol_kodu = 'admin' if y_rol == "Ana Yönetici (Admin)" else 'gozlemci'
                                try:
                                    c.execute("SELECT id FROM kullanicilar WHERE kullanici_adi=?", (y_kadi.strip(),))
                                    if c.fetchone(): st.error("Bu kullanıcı adı zaten var!")
                                    else:
                                        c.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, daire_id) VALUES (?, ?, ?, 'TÜMÜ')", (y_kadi.strip(), y_sifre.strip(), rol_kodu))
                                        conn.commit(); st.success("Yeni yetkili eklendi!"); st.rerun()
                                except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
                            else: st.error("Boş bırakılamaz.")
                                
            with col_sil:
                with st.container(border=True):
                    st.markdown("#### 🗑️ Yetkili Sil veya Düzenle")
                    c.execute("SELECT kullanici_adi FROM kullanicilar WHERE rol IN ('admin', 'gozlemci')")
                    yetkili_listesi = [r[0] for r in c.fetchall()]
                    with st.form("yetkili_sil"):
                        silinecek_kadi = st.selectbox("İşlem Yapılacak Yetkili:", yetkili_listesi)
                        guncel_sifre = st.text_input("Şifresini Değiştir (Sileceksek boş bırakın):")
                        btn_guncelle = st.form_submit_button("Şifreyi Güncelle", type="primary")
                        btn_sil = st.form_submit_button("Seçilen Yetkiliyi Tamamen Sil")
                        
                        if btn_guncelle:
                            if guncel_sifre.strip():
                                try:
                                    c.execute("UPDATE kullanicilar SET sifre=? WHERE kullanici_adi=?", (guncel_sifre.strip(), silinecek_kadi))
                                    conn.commit(); st.success("Şifre güncellendi!"); st.rerun()
                                except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
                            else: st.error("Yeni şifre girin.")
                        if btn_sil:
                            if silinecek_kadi == st.session_state['kullanici']: st.error("Kendi hesabınızı silemezsiniz!")
                            elif len(yetkili_listesi) <= 1: st.error("Sistemde en az 1 yönetici kalmalıdır!")
                            else:
                                try:
                                    c.execute("DELETE FROM kullanicilar WHERE kullanici_adi=?", (silinecek_kadi,))
                                    conn.commit(); st.success("Yetkili silindi!"); st.rerun()
                                except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
        conn.close()

    # ---------------------------------------------------------
    # YÖNETİCİ ÖZEL AYARLAR VE MALİ TUTARLILIK DENETİMİ
    # ---------------------------------------------------------
    elif secim == "⚙️ Yönetici Ayarları":
        st.title("⚙️ Yönetici ve Sistem Ayarları")
        st.warning("⚠️ Lütfen bu alandaki işlemleri dikkatli kullanın.")
        
        tab_kurulum, tab_denetim, tab_yumusak, tab_sert = st.tabs(["🚀 Akıllı Excel Kurulumu", "⚖️ Mali Tutarlılık Denetimi", "🧹 Sadece İşlemleri Sıfırla", "🔥 Tam Format At (Sıfırla)"])
        
        with tab_kurulum:
            st.subheader("🚀 Sisteme İlk Kurulumu Yap (Esnek Excel Okuyucu)")
            st.info("Kendi oluşturduğunuz herhangi bir Excel dosyasını buraya yükleyin. Yapay zeka sütun başlıklarını okuyup eşleştirmeyi otomatik yapar.")
            kurulum_file = st.file_uploader("Kurulum Excel Dosyasını Seçin", type=['xlsx', 'xlsm'], key="kurulum_yukle")
            
            if kurulum_file:
                if st.button("🚀 Verileri Tara ve Sisteme Yükle", type="primary"):
                    with st.spinner("Sütunlar otomatik taranıyor ve daireler sisteme tanımlanıyor..."):
                        try:
                            df_setup = pd.read_excel(kurulum_file, sheet_name=0)
                            df_setup.columns = [str(c).strip().upper() for c in df_setup.columns]
                            
                            col_blok = next((c for c in df_setup.columns if any(k in c for k in ["BLOK", "BİNA", "BINA"])), None)
                            col_daire = next((c for c in df_setup.columns if any(k in c for k in ["DAİRE", "DAIRE", "KAPI", "NO"]) and "TEL" not in c), None)
                            col_ev_sahibi = next((c for c in df_setup.columns if any(k in c for k in ["EV SAHİBİ", "EV SAHIBI", "MALİK", "AD", "İSİM"]) and "KİRACI" not in c), None)
                            col_kiraci = next((c for c in df_setup.columns if any(k in c for k in ["KİRACI", "KIRACI"])), None)
                            col_borc = next((c for c in df_setup.columns if any(k in c for k in ["BORÇ", "BORC", "BAKİYE", "BAKIYE", "TUTAR"])), None)
                            col_ev_tel = next((c for c in df_setup.columns if any(k in c for k in ["TEL", "GSM"]) and any(k in c for k in ["EV", "SAHİBİ", "SAHIBI"])), None)
                            col_ki_tel = next((c for c in df_setup.columns if any(k in c for k in ["TEL", "GSM"]) and "KİRACI" in c), None)
                            if not col_ev_tel: col_ev_tel = next((c for c in df_setup.columns if any(k in c for k in ["TEL", "GSM"])), None)
                            
                            if not col_daire:
                                st.error("Hata: Dosyanızda 'Daire' veya 'Kapı No' sütunu bulunamadı!")
                            else:
                                conn = get_db_connection()
                                c = conn.cursor()
                                basarili = 0
                                
                                try:
                                    for idx, row in df_setup.iterrows():
                                        daire_val = str(row.get(col_daire, '')).replace('Daire No:', '').replace('Daire No: ', '').strip()
                                        if not daire_val or daire_val in ["NAN", "NONE"]: continue
                                        
                                        daire_id = daire_val
                                        blok_str = ""
                                        if col_blok:
                                            blok_val = str(row.get(col_blok, '')).replace('Blok:', '').replace('Blok: ', '').strip()
                                            if blok_val and blok_val not in ["NAN", "NONE"]:
                                                daire_id = f"{blok_val}-{daire_val}"; blok_str = blok_val
                                                
                                        borc_raw = pd.to_numeric(row.get(col_borc, 0) if col_borc else 0, errors='coerce')
                                        borc = 0.0 if pd.isna(borc_raw) else float(borc_raw)
                                        bakiye = -borc 
                                        
                                        ev = str(row.get(col_ev_sahibi, '') if col_ev_sahibi else '').strip()
                                        ev = "" if ev in ["0", "NAN", "NONE"] else ev
                                        ki = str(row.get(col_kiraci, '') if col_kiraci else '').strip()
                                        ki = "" if ki in ["0", "NAN", "NONE"] else ki
                                        ev_tel = str(row.get(col_ev_tel, '') if col_ev_tel else '').strip()
                                        ev_tel = "" if ev_tel in ["0", "NAN", "NONE"] else ev_tel
                                        ki_tel = str(row.get(col_ki_tel, '') if col_ki_tel else '').strip()
                                        ki_tel = "" if ki_tel in ["0", "NAN", "NONE"] else ki_tel
                                        
                                        c.execute("SELECT id FROM daireler WHERE id=?", (daire_id,))
                                        if not c.fetchone():
                                            c.execute("INSERT INTO daireler (id, blok, daire_no, ev_sahibi, kiraci, bakiye, ev_sahibi_tel, kiraci_tel) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (daire_id, blok_str, daire_val, ev, ki, bakiye, ev_tel, ki_tel))
                                            c.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, daire_id) VALUES (?, '12345', 'sakin', ?)", (daire_id, daire_id))
                                            basarili += 1
                                            
                                    conn.commit()
                                    st.success(f"✅ Başarılı! {basarili} adet daire sisteme tanımlandı.")
                                except Exception as e:
                                    conn.rollback()
                                    st.error(f"Aktarım iptal edildi: {e}")
                                finally:
                                    conn.close()
                        except Exception as e:
                            st.error(f"Kurulum sırasında hata oluştu: {e}")

        with tab_denetim:
            st.subheader("⚖️ Mali Tutarlılık Denetimi (Bakiye Eşitleyici)")
            st.info("Sistemde yarım kalmış bir işlem veya manuel veri girilirken oluşmuş bir hata ihtimaline karşı; bu buton tüm dairelerin bakiyelerini SIFIRDAN işlem geçmişine göre hesaplar ve eşitler.")
            with st.form("bakiye_denetim_formu"):
                st.warning("Bu işlem veritabanı boyutuna göre birkaç saniye sürebilir.")
                if st.form_submit_button("🚀 Tüm Bakiyeleri Check-Up Yap ve Eşitle", type="primary"):
                    conn = get_db_connection()
                    c = conn.cursor()
                    try:
                        c.execute("SELECT id FROM daireler")
                        tum_daireler = c.fetchall()
                        duzeltilen_sayi = 0
                        
                        gelir_tipleri = ('Otomatik Tahsilat', 'Manuel Tahsilat', 'Elden Tahsilat', 'Çoklu Dağıtım')
                        borc_tipleri = ('Borçlandırma (Aidat)', 'Ek Aidat Borcu', 'Demirbaş Borcu', 'Gecikme Faizi')
                        
                        for d in tum_daireler:
                            d_id = d[0]
                            c.execute(f"SELECT sum(tutar) FROM islemler WHERE daire_id=? AND islem_tipi IN {gelir_tipleri}", (d_id,))
                            toplam_gelir = c.fetchone()[0] or 0.0
                            
                            c.execute(f"SELECT sum(tutar) FROM islemler WHERE daire_id=? AND islem_tipi IN {borc_tipleri}", (d_id,))
                            toplam_borc = c.fetchone()[0] or 0.0
                            
                            gercek_bakiye = round(toplam_gelir - toplam_borc, 2)
                            c.execute("UPDATE daireler SET bakiye=? WHERE id=?", (gercek_bakiye, d_id))
                            duzeltilen_sayi += 1
                            
                        conn.commit()
                        st.success(f"✅ Sistem kusursuz şekilde denetlendi! Tam {duzeltilen_sayi} adet carinin bakiyesi geçmiş hesap dökümüne göre kuruşu kuruşuna eşitlendi.")
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Denetim sırasında hata oluştu: {e}")
                    finally:
                        conn.close()
                            
        with tab_yumusak:
            st.subheader("🧹 Sadece İşlemleri ve Kasayı Sıfırla (Daireler Kalır)")
            st.info("Kayıtlı daireleri ve kişileri SİLMEZ. Sadece geçmiş para hareketlerini temizler ve herkesin bakiyesini 0.00 TL yapar.")
            onay_kasa = st.checkbox("Evet, sadece işlem geçmişini sıfırlamak istiyorum.", key="onay_kasa")
            if st.button("🧹 SADECE KASAYI SIFIRLA", type="primary"):
                if onay_kasa:
                    conn = get_db_connection()
                    c = conn.cursor()
                    try:
                        c.execute("DELETE FROM islemler"); c.execute("UPDATE daireler SET bakiye = 0.0")
                        conn.commit(); st.success("✅ Sadece kasa ve işlemler başarıyla sıfırlandı!"); st.rerun()
                    except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
                    finally: conn.close()
                else: st.error("Lütfen önce onay kutucuğunu işaretleyin!")
                            
        with tab_sert:
            st.subheader("🔥 Fabrika Ayarlarına Dön (Her Şeyi Tamamen Sil)")
            st.error("DİKKAT: Bu buton sistemi İLK AÇILDIĞI BOMBOŞ HALİNE döndürür. Kasayla birlikte eklediğiniz TÜM DAİRELER, CARİLER, İSİMLER ve SAKİN ŞİFRELERİ kalıcı olarak SİLİNİR.")
            onay_tam = st.checkbox("Evet, tüm sistemi tamamen silmek ve ilk kurulduğu güne döndürmek istiyorum.", key="onay_tam")
            if st.button("🔥 SİSTEMİ KOMPLE SIFIRLA (FORMAT AT)", type="primary"):
                if onay_tam:
                    conn = get_db_connection()
                    c = conn.cursor()
                    try:
                        c.execute("DELETE FROM islemler"); c.execute("DELETE FROM daireler"); c.execute("DELETE FROM kullanicilar WHERE rol='sakin'")
                        conn.commit(); st.success("✅ Sistem başarıyla fabrika ayarlarına döndürüldü!"); st.rerun()
                    except Exception as e: conn.rollback(); st.error(f"Hata: {e}")
                    finally: conn.close()
                else: st.error("Lütfen önce tam sıfırlama onay kutucuğunu işaretleyin!")