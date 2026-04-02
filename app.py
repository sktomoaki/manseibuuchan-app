import streamlit as st
import os, json, gc, psutil
from pathlib import Path
from datetime import date
import streamlit.components.v1 as components

# ================================================================
# 環境変数
# ================================================================
def _get_secret(key: str) -> str:
    """st.secrets → os.environ の順で取得（Streamlit Cloud・ローカル両対応）"""
    try:
        val = st.secrets.get(key, "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(key, "").strip()

ANTHROPIC_API_KEY  = _get_secret("ANTHROPIC_API_KEY")
GROQ_API_KEY       = _get_secret("GROQ_API_KEY")
ASSEMBLYAI_API_KEY = _get_secret("ASSEMBLYAI_API_KEY")
HF_TOKEN           = _get_secret("HF_TOKEN")
DRIVE_BASE         = _get_secret("DRIVE_BASE") or "/tmp/Claude"
CLAUDE_MODEL       = "claude-haiku-4-5-20251001"

import pathlib
pathlib.Path("/tmp/Claude").mkdir(parents=True, exist_ok=True)

WAV_FILE = "/tmp/meeting.wav"

# ================================================================
# ページ設定
# ================================================================
st.set_page_config(page_title="万世ぶーちゃん v2.8", page_icon="🐷", layout="centered")

# ================================================================
# 月次パスワード生成（フォールバック用）
# ================================================================
def _gen_monthly_pw():
    import hashlib as _h, datetime as _d
    _S = "ManseiBuuchan2024"
    _t = _d.datetime.now()
    _raw = _S + "_" + str(_t.year) + "_" + str(_t.month).zfill(2)
    _hx = _h.sha256(_raw.encode("utf-8")).hexdigest()
    _C = "ABCDEFGHJKMNPQRTVWXY2346789"
    return "".join(_C[int(_hx[i:i+2], 16) % len(_C)] for i in range(0, 16, 2))

# ================================================================
# 認証（Google OAuth → 月次パスワードにフォールバック）
# ================================================================
def check_auth():
    try:
        # Streamlit v1.37+ Google OAuth
        if not st.user.is_logged_in:
            st.markdown("""
<div style='text-align:center;padding:60px 0 40px;'>
  <span style='font-size:72px;'>🐷</span>
  <h1 style='font-size:24px;margin:16px 0 8px;'>万世ぶーちゃん</h1>
  <p style='color:#888;font-size:14px;'>AI議事録・文字起こし校正システム</p>
</div>""", unsafe_allow_html=True)
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.button("🔐 Google アカウントでログイン",
                          type="primary", use_container_width=True,
                          on_click=st.login, args=("google",))
            st.stop()

        # アクセス許可チェック
        allowed = list(st.secrets.get("allowed_emails", []))
        if allowed and st.user.email not in allowed:
            st.error(f"⛔ {st.user.email} はアクセス権限がありません。管理者にお問い合わせください。")
            st.button("別のアカウントでログイン", on_click=st.logout)
            st.stop()

        # サイドバーにユーザー情報
        with st.sidebar:
            st.markdown(f"👤 **{st.user.name}**")
            st.caption(st.user.email)
            st.button("ログアウト", use_container_width=True, on_click=st.logout)

    except AttributeError:
        # Google OAuth 未設定時は月次パスワードにフォールバック
        APP_PW = _gen_monthly_pw()
        if not st.session_state.get("authenticated"):
            st.title("🔑 ログイン")
            pw = st.text_input("パスワードを入力", type="password")
            if st.button("ログイン"):
                if pw == APP_PW:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("パスワードが違います")
            st.stop()

check_auth()

# ================================================================
# 起動時RAM確認・警告
# ================================================================
def check_ram_on_startup():
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024 ** 3)
    if available_gb < 4:
        st.error(f"🔴 RAMが不足しています（利用可能: {available_gb:.1f} GB）。")
    elif available_gb < 8:
        st.warning(f"🟡 RAMに余裕がありません（利用可能: {available_gb:.1f} GB）。")

# ================================================================
# 起動音
# ================================================================
def play_startup_sound():
    components.html("""
    <script>
    (function() {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const notes = [
            {freq: 1200, dur: 0.08, start: 0.0},
            {freq: 1400, dur: 0.08, start: 0.1},
            {freq: 1200, dur: 0.08, start: 0.2},
            {freq: 1400, dur: 0.08, start: 0.3},
            {freq: 1800, dur: 0.15, start: 0.45},
        ];
        notes.forEach(n => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain); gain.connect(ctx.destination);
            osc.type = 'sine';
            osc.frequency.value = n.freq;
            gain.gain.setValueAtTime(0.3, ctx.currentTime + n.start);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + n.start + n.dur);
            osc.start(ctx.currentTime + n.start);
            osc.stop(ctx.currentTime + n.start + n.dur + 0.05);
        });
    })();
    </script>
    """, height=1)

if not st.session_state.get("startup_sound_played"):
    play_startup_sound()
    st.session_state["startup_sound_played"] = True

# ================================================================
# セッション初期化
# ================================================================
DEFAULTS = {
    "step": 1, "audio_path": None, "file_base": "",
    "raw_text": "", "segments_data": None,
    "speaker_turns": None, "speaker_names": {}, "detected_speakers": [],
    "q_date": str(date.today()), "q_title": "", "q_place": "",
    "participants": "", "emphasis_items": "", "decisions": "",
    "pending_items": "", "mode": "議事録＋文字起こしデータ",
    "minutes_html": "", "legal_html": "",
    "drive_save_dir": "", "crash_recovered": False,
    "model_size": "medium",
    "speaker_map": {},
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ================================================================
# ユーティリティ
# ================================================================
def ram_info():
    mem = psutil.virtual_memory()
    pct = mem.percent
    color = "red" if pct > 85 else "orange" if pct > 70 else "green"
    return (f"<span style='color:{color};font-weight:bold;'>"
            f"RAM {mem.used/1e9:.1f}/{mem.total/1e9:.1f}GB ({pct:.0f}%)</span>")

def show_animal_progress(placeholder, pct, msg):
    w = 18
    filled = max(0, min(w - 1, int(w * pct / 100)))
    animal = '🐷' if (filled // 4) % 2 == 0 else '🐮'
    bar = '●' * filled + animal + '○' * (w - filled - 1)
    color = '#c0392b' if pct < 30 else '#e67e22' if pct < 70 else '#27ae60'
    placeholder.markdown(f"""
<div style='background:#fff8f0;border:2px solid #f0a500;border-radius:12px;
            padding:14px 18px;margin:8px 0;font-family:monospace;'>
  <div style='font-size:22px;letter-spacing:1px;'>{bar}</div>
  <div style='font-size:18px;font-weight:bold;color:{color};margin-top:6px;'>
    {pct}% 完了</div>
  <div style='font-size:13px;color:#666;margin-top:4px;'>{msg}</div>
</div>
""", unsafe_allow_html=True)

def estimate_transcription_time(file_size_bytes, model_name="medium"):
    mb = file_size_bytes / (1024 * 1024)
    speed_map = {"tiny": 5, "base": 8, "small": 12, "medium": 20, "large": 35, "large-v2": 40, "large-v3": 45}
    sec_per_mb = speed_map.get(model_name, 20)
    estimated_sec = mb * sec_per_mb
    if estimated_sec < 60:
        return f"約{int(estimated_sec)}秒"
    elif estimated_sec < 3600:
        return f"約{int(estimated_sec/60)}分{int(estimated_sec%60)}秒"
    else:
        return f"約{int(estimated_sec/3600)}時間{int((estimated_sec%3600)/60)}分"

def get_audio_duration_sec(audio_path: str) -> float:
    """音声ファイルの長さ（秒）を返す"""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0
    except Exception:
        return 0.0

def split_audio_to_chunks(audio_path: str, chunk_minutes: int = 10) -> list:
    """音声をN分ごとのチャンクに分割してリストで返す"""
    from pydub import AudioSegment
    audio = AudioSegment.from_file(audio_path)
    duration_ms = len(audio)
    chunk_ms = chunk_minutes * 60 * 1000
    chunks = []
    for i, start_ms in enumerate(range(0, duration_ms, chunk_ms)):
        end_ms = min(start_ms + chunk_ms, duration_ms)
        chunk = audio[start_ms:end_ms]
        chunk_path = f"/tmp/chunk_{i:03d}.wav"
        chunk.export(chunk_path, format="wav")
        chunks.append({
            "path": chunk_path,
            "start_sec": start_ms / 1000.0,
            "end_sec": end_ms / 1000.0,
            "index": i,
        })
        del chunk
    del audio
    gc.collect()
    return chunks

# ================================================================
# 文字起こし関数（クラウドAPI）
# ================================================================
def transcribe_groq(audio_path: str) -> str:
    """Groq Whisper API で文字起こし（無料・高速・話者識別なし）"""
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            language="ja",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    text = ""
    try:
        for seg in result.segments:
            text += "[" + str(round(seg["start"], 1)) + "s] " + seg["text"].strip() + "\n"
    except Exception:
        text = getattr(result, "text", "") or ""
    return text

def transcribe_assemblyai(audio_path: str, speakers_expected: int = 2) -> str:
    """AssemblyAI で文字起こし（話者識別あり・100時間無料）"""
    import assemblyai as aai
    aai.settings.api_key = ASSEMBLYAI_API_KEY
    config = aai.TranscriptionConfig(
        speech_models=["universal-2"],
        language_code="ja",
        speaker_labels=True,
        speakers_expected=speakers_expected,
    )
    transcriber = aai.Transcriber(config=config)
    transcript = transcriber.transcribe(audio_path)
    if transcript.status == aai.TranscriptStatus.error:
        raise Exception("AssemblyAI エラー: " + str(transcript.error))
    text = ""
    if transcript.utterances:
        for u in transcript.utterances:
            text += "[" + str(round(u.start / 1000, 1)) + "s] " + u.speaker + ": " + u.text + "\n"
    else:
        text = getattr(transcript, "text", "") or ""
    return text

# ================================================================
# Claude API 呼び出し
# ================================================================
def call_claude_minutes(raw_text, q_date, q_title, q_place,
                         participants, emphasis, decisions, pending):
    import anthropic as _ant
    api_key = _get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY が未設定です。Streamlit Cloud の Secrets に設定してください。")
    client = _ant.Anthropic(api_key=api_key)
    prompt = (
        "以下の会議の文字起こしテキストをもとに、HTMLフォーマットの議事録を作成してください。\n\n"
        "【会議情報】\n"
        "- 日時: " + q_date + "\n"
        "- 件名: " + q_title + "\n"
        "- 場所: " + q_place + "\n"
        "- 参加者: " + participants + "\n"
        "- 強調したい項目: " + emphasis + "\n"
        "- 決定事項（入力済み）: " + decisions + "\n"
        "- 未決定課題: " + pending + "\n\n"
        "【文字起こし（最大15000文字）】\n"
        + raw_text[:15000] + "\n\n"
        "【出力形式】\n"
        "- DOCTYPE〜</html>まで完全なHTML、UTF-8、A4印刷対応\n"
        "- セクション: 基本情報テーブル / 背景・経緯 / アジェンダ / 議論の要約 / 決定事項 / アクションアイテム（誰が・何を・いつまで） / 次回予定\n"
        "- 重要箇所は赤太字で強調\n"
        "- 「検討する」は禁止 → 「○○が△△までに結論を出す」に置き換え\n"
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text

def call_claude_legal(raw_text, q_title):
    import anthropic as _ant
    api_key = _get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY が未設定です。Streamlit Cloud の Secrets に設定してください。")
    client = _ant.Anthropic(api_key=api_key)
    prompt = (
        "以下の会議文字起こしを、読みやすく整形した「文字起こしデータHTML」を作成してください。\n\n"
        "件名: " + q_title + "\n\n"
        "【文字起こし】\n"
        + raw_text[:15000] + "\n\n"
        "【出力形式】\n"
        "- DOCTYPE〜</html>まで完全なHTML、A4印刷対応\n"
        "- 重要な発言・決定事項を5〜10点抽出し、タイムスタンプ・発言者・内容を表形式で整理\n"
        "- 責任認定・約束・謝罪・矛盾する発言・優越的地位の乱用を優先抽出\n"
        "- 重要度が高い箇所は赤背景または赤枠で強調\n"
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text

# ================================================================
# ZIP一括ダウンロード
# ================================================================
def create_zip_bundle(file_base, ts, minutes_html, legal_html, raw_text):
    """すべての出力ファイルをZIPにまとめる。フォルダ名に日時を含む。"""
    import io, zipfile
    folder = ts + "_" + (file_base or "議事録")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if minutes_html:
            zf.writestr(folder + "/" + file_base + "_議事録.html",
                        minutes_html.encode("utf-8"))
        if legal_html:
            zf.writestr(folder + "/" + file_base + "_文字起こしデータ.html",
                        legal_html.encode("utf-8"))
        if raw_text:
            zf.writestr(folder + "/" + file_base + "_文字起こし.txt",
                        raw_text.encode("utf-8"))
    buf.seek(0)
    return buf.getvalue(), folder + ".zip"

def show_download_section(file_base, ts, minutes_html, legal_html, raw_text, key_prefix=""):
    """ZIPボタン（大）＋個別ボタン（小）をまとめて表示する。"""
    zip_bytes, zip_name = create_zip_bundle(file_base, ts, minutes_html, legal_html, raw_text)
    st.markdown("---")
    st.markdown("#### 📦 ダウンロード")
    st.download_button(
        "📦 すべてまとめてダウンロード（ZIP）",
        data=zip_bytes,
        file_name=zip_name,
        mime="application/zip",
        type="primary",
        use_container_width=True,
        key=key_prefix + "_zip",
    )
    st.caption("↑ ZIPの中に議事録・文字起こしデータ・テキストがすべて入っています")
    with st.expander("個別にダウンロードする場合はこちら"):
        if minutes_html:
            st.download_button("📄 議事録 HTML",
                data=minutes_html.encode("utf-8"),
                file_name=file_base + "_議事録_" + ts + ".html",
                mime="text/html", use_container_width=True,
                key=key_prefix + "_min")
        if legal_html:
            st.download_button("📄 文字起こしデータ HTML",
                data=legal_html.encode("utf-8"),
                file_name=file_base + "_文字起こしデータ_" + ts + ".html",
                mime="text/html", use_container_width=True,
                key=key_prefix + "_leg")
        if raw_text:
            st.download_button("📝 文字起こし TXT",
                data=raw_text.encode("utf-8"),
                file_name=file_base + "_文字起こし_" + ts + ".txt",
                mime="text/plain", use_container_width=True,
                key=key_prefix + "_txt")

# ================================================================
# 完了通知音
# ================================================================
def play_completion_sound():
    components.html("""
    <div id="sound-container" style="text-align:center; padding:20px; background:#fff3cd; border-radius:10px; border:2px solid #ffc107;">
        <p style="font-size:24px;">🍚 処理が完了しました！</p>
        <button onclick="stopSound()" style="background:#ff6b6b; color:white; border:none; padding:10px 30px; font-size:18px; border-radius:20px; cursor:pointer;">
            ✅ 確認しました（音を止める）
        </button>
    </div>
    <script>
    let audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    let isPlaying = true;
    function playDonChime() {
        if (!isPlaying) return;
        const melody = [
            {freq: 523, dur: 0.3, start: 0.0},
            {freq: 659, dur: 0.3, start: 0.35},
            {freq: 784, dur: 0.3, start: 0.70},
            {freq: 1047, dur: 0.6, start: 1.05},
            {freq: 784, dur: 0.3, start: 1.75},
            {freq: 1047, dur: 0.8, start: 2.10},
        ];
        melody.forEach(n => {
            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.connect(gain); gain.connect(audioCtx.destination);
            osc.type = 'triangle';
            osc.frequency.value = n.freq;
            gain.gain.setValueAtTime(0.4, audioCtx.currentTime + n.start);
            gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + n.start + n.dur);
            osc.start(audioCtx.currentTime + n.start);
            osc.stop(audioCtx.currentTime + n.start + n.dur + 0.1);
        });
        if (isPlaying) { setTimeout(playDonChime, 3500); }
    }
    function stopSound() {
        isPlaying = false;
        audioCtx.close();
        document.getElementById('sound-container').innerHTML =
            '<p style="font-size:18px; color:green;">✅ 確認済み</p>';
    }
    playDonChime();
    </script>
    """, height=150)

# ================================================================
# ヘッダー
# ================================================================
st.markdown("""
<div style='text-align:center;padding:16px 0 8px 0;'>
  <span style='font-size:52px;'>🐷</span>
  <h1 style='margin:4px 0 2px 0;font-size:22px;'>万世ぶーちゃんの議事録サポートアプリ v2.6</h1>
  <p style='color:#888;font-size:12px;margin:0;'>テキストを貼り付けるだけで議事録を自動作成🐷</p>
</div>""", unsafe_allow_html=True)

check_ram_on_startup()
IS_COLAB = os.path.exists('/content')

tab1, tab2 = st.tabs(["📝 テキストから作成（すぐ使える）", "🎤 音声から作成"])

# ================================================================
# タブ1: テキスト直接入力 → 議事録生成（常時稼働）
# ================================================================
with tab1:
    st.markdown("#### 文字起こしテキストを貼り付けて議事録を作成します")

    with st.form("minutes_form"):
        raw_text = st.text_area(
            "📄 文字起こしテキスト",
            placeholder="例: ぶーちゃん: おはようございます。/ もーちゃん: よろしくお願いします。",
            height=200,
        )
        col1, col2 = st.columns(2)
        with col1:
            q_date  = st.text_input("📅 会議日時", placeholder="例: 2026年3月30日 10:00〜")
            q_place = st.text_input("📍 場所",     placeholder="例: 会議室A / Zoom")
        with col2:
            q_title = st.text_input("📌 会議タイトル", placeholder="例: 定例ミーティング")
            participants = st.text_area("👥 参加者",
                placeholder="例: ぶーちゃん社長（万世ぶーちゃん商事）/ もーちゃん部長（もーちゃん食品）",
                height=80)
        emphasis  = st.text_area("⭐ 強調したい項目",
            placeholder="例: 次回の搬入日程や費用負担についてまとめたい", height=60)
        decisions = st.text_area("✅ 決定事項",
            placeholder="例: 来月までにサンプルを提出する", height=60)
        pending   = st.text_area("📌 未決定の宿題事項",
            placeholder="例: もーちゃん食品から来週中に回答をもらう", height=60)
        mode = st.radio("出力スタイル 📝", ["議事録のみ", "議事録＋文字起こしデータ"], index=1)
        submitted = st.form_submit_button("🐷 議事録を作る", type="primary", use_container_width=True)

    if submitted:
        if not raw_text.strip():
            st.error("📄 文字起こしテキストを入力してください")
        elif not ANTHROPIC_API_KEY:
            st.error("ANTHROPIC_API_KEY が設定されていません。Streamlit Cloud の Secrets を確認してください。")
        else:
            with st.spinner("Claude が議事録を生成中... 🐷"):
                try:
                    minutes_html = call_claude_minutes(
                        raw_text, q_date, q_title, q_place,
                        participants, emphasis, decisions, pending
                    )
                    st.success("✅ 議事録が完成しました！")
                    from datetime import datetime
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_base = q_title.strip().replace(" ", "_") or "議事録"
                    legal_html = ""

                    if mode == "議事録＋文字起こしデータ":
                        with st.spinner("文字起こしデータを整理中..."):
                            try:
                                legal_html = call_claude_legal(raw_text, q_title)
                            except Exception as e:
                                st.warning(f"文字起こしデータ整理エラー: {e}")

                    show_download_section(file_base, ts, minutes_html, legal_html, raw_text, key_prefix="tab1")
                    play_completion_sound()

                except Exception as e:
                    st.error(f"議事録生成エラー: {e}")

# ================================================================
# タブ2: 音声文字起こし（クラウドAPI + Colab）
# ================================================================
with tab2:
    st.markdown("#### 音声ファイルをアップロードして文字起こし＋議事録を作成します")

    # ---- エンジン選択 ----
    engine = st.radio(
        "🔧 文字起こしエンジンを選択",
        [
            "🤖 Groq Whisper（無料・高速・話者識別なし）",
            "🎯 AssemblyAI（話者識別あり・100時間無料）",
            "🐷 Colab ローカル（Colab起動時のみ）",
        ],
        index=0,
    )

    # ---- Groq エンジン ----
    if engine == "🤖 Groq Whisper（無料・高速・話者識別なし）":
        if not GROQ_API_KEY:
            st.warning("""
⚠️ **GROQ_API_KEY が設定されていません**

1. [console.groq.com](https://console.groq.com) で無料アカウントを作成
2. API Keys → Create API Key で `gsk_...` キーを取得
3. Streamlit Cloud の Secrets に `GROQ_API_KEY = "gsk_..."` を追加
            """)
        else:
            st.info("💡 Groq Whisper は無料で高速に文字起こしできます。話者識別（誰が話したか）はありません。")
            uploaded = st.file_uploader("音声ファイルをアップロード",
                type=["m4a", "mp3", "wav", "mp4", "ogg", "flac"],
                key="groq_upload")

            if uploaded:
                file_size_mb = uploaded.size / (1024 * 1024)
                st.info(f"📊 ファイルサイズ: {file_size_mb:.1f} MB")

                mode_g = st.radio("出力スタイル 📝",
                    ["議事録のみ", "議事録＋文字起こしデータ"], index=1, key="mode_groq")
                col1, col2 = st.columns(2)
                with col1:
                    q_date_g  = st.text_input("📅 会議日時", placeholder="例: 2026年3月30日", key="date_g")
                    q_place_g = st.text_input("📍 場所", placeholder="例: 会議室A", key="place_g")
                with col2:
                    q_title_g = st.text_input("📌 タイトル", placeholder="例: 定例ミーティング", key="title_g")
                    participants_g = st.text_area("👥 参加者",
                        placeholder="例: ぶーちゃん、もーちゃん", height=68, key="part_g")
                emphasis_g  = st.text_area("⭐ 強調したい項目", height=56, key="emph_g",
                    placeholder="例: 費用負担について")
                decisions_g = st.text_area("✅ 決定事項", height=56, key="deci_g",
                    placeholder="例: 来月までにサンプル提出")
                pending_g   = st.text_area("📌 未決定の宿題事項", height=56, key="pend_g",
                    placeholder="例: もーちゃんから来週中に回答")

                if st.button("▶ 文字起こし＋議事録を作成（Groq）", type="primary"):
                    # 音声保存
                    raw_path = "/tmp/" + uploaded.name
                    with open(raw_path, "wb") as f:
                        f.write(uploaded.getvalue())
                    with st.spinner("🎤 Groq で文字起こし中... (通常30秒〜2分)"):
                        try:
                            raw_text_g = transcribe_groq(raw_path)
                            st.success("✅ 文字起こし完了！")
                            st.text_area("📄 文字起こし結果（確認・編集可）", value=raw_text_g, height=200,
                                key="groq_result")
                        except Exception as e:
                            st.error(f"文字起こしエラー: {e}")
                            raw_text_g = ""

                    if raw_text_g and ANTHROPIC_API_KEY:
                        with st.spinner("🐷 Claude が議事録を生成中..."):
                            try:
                                from datetime import datetime
                                ts_g = datetime.now().strftime("%Y%m%d_%H%M%S")
                                fb_g = q_title_g.strip().replace(" ", "_") or "議事録"
                                minutes_html_g = call_claude_minutes(
                                    raw_text_g, q_date_g, q_title_g, q_place_g,
                                    participants_g, emphasis_g, decisions_g, pending_g)
                                legal_html_g = ""
                                if mode_g == "議事録＋文字起こしデータ":
                                    legal_html_g = call_claude_legal(raw_text_g, q_title_g)
                                show_download_section(fb_g, ts_g, minutes_html_g, legal_html_g, raw_text_g, key_prefix="groq")
                                play_completion_sound()
                            except Exception as e:
                                st.error(f"議事録生成エラー: {e}")

    # ---- AssemblyAI エンジン ----
    elif engine == "🎯 AssemblyAI（話者識別あり・100時間無料）":
        if not ASSEMBLYAI_API_KEY:
            st.warning("""
⚠️ **ASSEMBLYAI_API_KEY が設定されていません**

1. [assemblyai.com](https://www.assemblyai.com) で無料アカウントを作成（100時間無料）
2. ダッシュボードから API Key を取得
3. Streamlit Cloud の Secrets に `ASSEMBLYAI_API_KEY = "..."` を追加
            """)
        else:
            st.info("💡 AssemblyAI は **話者識別（誰が話したか）** に対応しています。処理に1〜3分かかります。")
            uploaded_a = st.file_uploader("音声ファイルをアップロード",
                type=["m4a", "mp3", "wav", "mp4", "ogg", "flac"],
                key="aai_upload")

            if uploaded_a:
                file_size_mb_a = uploaded_a.size / (1024 * 1024)
                st.info(f"📊 ファイルサイズ: {file_size_mb_a:.1f} MB")

                speakers_n = st.number_input("👥 話者の人数（目安）", min_value=1, max_value=10, value=2, key="spk_n")
                mode_a = st.radio("出力スタイル 📝",
                    ["議事録のみ", "議事録＋文字起こしデータ"], index=1, key="mode_aai")
                col1a, col2a = st.columns(2)
                with col1a:
                    q_date_a  = st.text_input("📅 会議日時", placeholder="例: 2026年3月30日", key="date_a")
                    q_place_a = st.text_input("📍 場所", placeholder="例: 会議室A", key="place_a")
                with col2a:
                    q_title_a = st.text_input("📌 タイトル", placeholder="例: 定例ミーティング", key="title_a")
                    participants_a = st.text_area("👥 参加者",
                        placeholder="例: ぶーちゃん、もーちゃん", height=68, key="part_a")
                emphasis_a  = st.text_area("⭐ 強調したい項目", height=56, key="emph_a",
                    placeholder="例: 費用負担について")
                decisions_a = st.text_area("✅ 決定事項", height=56, key="deci_a",
                    placeholder="例: 来月までにサンプル提出")
                pending_a   = st.text_area("📌 未決定の宿題事項", height=56, key="pend_a",
                    placeholder="例: もーちゃんから来週中に回答")

                if st.button("▶ 文字起こし＋議事録を作成（AssemblyAI）", type="primary"):
                    raw_path_a = "/tmp/" + uploaded_a.name
                    with open(raw_path_a, "wb") as f:
                        f.write(uploaded_a.getvalue())
                    with st.spinner("🎤 AssemblyAI で文字起こし中... (通常1〜3分)"):
                        try:
                            raw_text_a = transcribe_assemblyai(raw_path_a, int(speakers_n))
                            st.success("✅ 文字起こし完了！（話者識別済み）")
                            st.text_area("📄 文字起こし結果（確認・編集可）", value=raw_text_a, height=200,
                                key="aai_result")
                        except Exception as e:
                            st.error(f"文字起こしエラー: {e}")
                            raw_text_a = ""

                    if raw_text_a and ANTHROPIC_API_KEY:
                        with st.spinner("🐷 Claude が議事録を生成中..."):
                            try:
                                from datetime import datetime
                                ts_a = datetime.now().strftime("%Y%m%d_%H%M%S")
                                fb_a = q_title_a.strip().replace(" ", "_") or "議事録"
                                minutes_html_a = call_claude_minutes(
                                    raw_text_a, q_date_a, q_title_a, q_place_a,
                                    participants_a, emphasis_a, decisions_a, pending_a)
                                legal_html_a = ""
                                if mode_a == "議事録＋文字起こしデータ":
                                    legal_html_a = call_claude_legal(raw_text_a, q_title_a)
                                show_download_section(fb_a, ts_a, minutes_html_a, legal_html_a, raw_text_a, key_prefix="aai")
                                play_completion_sound()
                            except Exception as e:
                                st.error(f"議事録生成エラー: {e}")

    # ---- Colab ローカルエンジン ----
    else:
        if not IS_COLAB:
            st.warning("""
🐷 **Colab ローカルモードは Colab 起動時のみ使えます**

以下の手順でお使いください：
1. [Colab を開く](https://colab.research.google.com/drive/1QYZcwJuFX47EPRnsEBLRzZjQOIM2TEI2) をクリック
2. Step 2 → Start Streamlit セルを実行（約30秒）
3. 音声ファイルをアップロードして文字起こし
4. 完了したテキストをコピー → 「📝 テキストから作成」タブに貼り付け

**または上記の Groq / AssemblyAI エンジンをお使いください（Colab 不要）**
            """)
        else:
            st.info("🐷 Colab ローカル Whisper + pyannote 話者識別モード")
            colab_defaults = {
                "step": 1, "audio_path": None, "file_base": "",
                "raw_text": "", "segments_data": [], "speaker_turns": [],
                "speaker_map": {}, "q_date": "", "q_title": "", "q_place": "",
                "participants": "", "emphasis_items": "", "decisions": "",
                "pending_items": "", "mode": "議事録＋文字起こしデータ",
                "minutes_html": "", "legal_html": "",
                "model_size": "medium",
            }
            for k, v in colab_defaults.items():
                if k not in st.session_state:
                    st.session_state[k] = v

            steps_label = ["音声アップ", "文字起こし中", "話者設定", "会議メモ入力", "生成完了"]
            st.progress((st.session_state.step - 1) / 4)
            st.caption(steps_label[st.session_state.step - 1])

            import glob as _glob
            backups = sorted(_glob.glob("/tmp/Claude/*.json"), reverse=True)[:5]
            if backups and st.session_state.step == 1:
                names = [os.path.basename(b) for b in backups]
                st.info(f"💾 以前の処理データが {len(backups)} 件見つかりました。")
                selected = st.selectbox("復旧するセッションを選択:", names)
                if st.button("🔄 このデータから再開する"):
                    with open(backups[names.index(selected)]) as bf:
                        bdata = json.load(bf)
                    for k, v in bdata.items():
                        st.session_state[k] = v
                    st.rerun()

            if st.session_state.step == 1:
                st.subheader("🎙 Step 1：音声ファイルをえらぶ")
                model_size = st.selectbox("Whisperモデル", ["medium", "small", "large-v2"], index=0)
                mode2 = st.radio("出力スタイル 📝", ["議事録のみ", "議事録＋文字起こしデータ"], index=1, key="mode_colab")
                st.session_state["mode"] = mode2
                uploaded_c = st.file_uploader("音声ファイルをアップロード",
                    type=["m4a", "mp3", "wav", "mp4", "ogg", "flac"], key="colab_upload")
                if uploaded_c:
                    file_size_mb_c = uploaded_c.size / (1024 * 1024)
                    est_time = estimate_transcription_time(uploaded_c.size, model_size)
                    # 一時保存して長さを取得
                    _tmp_path = "/tmp/_preview_" + uploaded_c.name
                    with open(_tmp_path, "wb") as _f:
                        _f.write(uploaded_c.getvalue())
                    dur_sec = get_audio_duration_sec(_tmp_path)
                    dur_str = (f"{int(dur_sec//3600)}時間{int((dur_sec%3600)//60)}分{int(dur_sec%60)}秒"
                               if dur_sec >= 3600 else
                               f"{int(dur_sec//60)}分{int(dur_sec%60)}秒"
                               if dur_sec >= 60 else f"{int(dur_sec)}秒")
                    chunk_count = max(1, int(dur_sec // 600) + (1 if dur_sec % 600 > 0 else 0))
                    chunk_msg = (f"　🔀 10分×{chunk_count}チャンクに分割して処理します"
                                 if dur_sec > 600 else "")
                    st.info(f"📊 ファイルサイズ: {file_size_mb_c:.1f} MB　🕐 音声の長さ: {dur_str}　⏱ 予想処理時間: {est_time}{chunk_msg}")
                if uploaded_c and st.button("▶ テキスト変換スタート", type="primary"):
                    from pydub import AudioSegment
                    file_base_c = Path(uploaded_c.name).stem
                    raw_path_c = "/tmp/" + uploaded_c.name
                    with open(raw_path_c, "wb") as f:
                        f.write(uploaded_c.getvalue())
                    audio = AudioSegment.from_file(raw_path_c)
                    audio.export("/tmp/meeting.wav", format="wav")
                    st.session_state.update({
                        "file_base": file_base_c, "model_size": model_size,
                        "mode": mode2, "audio_path": "/tmp/meeting.wav", "step": 2,
                    })
                    st.rerun()

            elif st.session_state.step == 2:
                st.subheader("⚙ Step 2：文字起こし中...")
                prog_ph = st.empty()
                chunk_info_ph = st.empty()
                show_animal_progress(prog_ph, 5, "準備中...")
                try:
                    from faster_whisper import WhisperModel

                    # 音声の長さを確認してチャンク分割を決定
                    audio_path = st.session_state.audio_path
                    dur_sec = get_audio_duration_sec(audio_path)
                    CHUNK_MINUTES = 10
                    use_chunks = dur_sec > CHUNK_MINUTES * 60

                    show_animal_progress(prog_ph, 15, "Whisperモデル読み込み中...")
                    wmodel = WhisperModel(st.session_state.model_size, device="cpu", compute_type="int8")

                    segments_data = []

                    if use_chunks:
                        # ── チャンク分割処理 ──────────────────
                        total_chunks_n = max(1, int(dur_sec // (CHUNK_MINUTES * 60)) +
                                            (1 if dur_sec % (CHUNK_MINUTES * 60) > 0 else 0))
                        chunk_info_ph.info(f"🔀 音声を {CHUNK_MINUTES}分×{total_chunks_n}チャンクに分割して処理します")
                        show_animal_progress(prog_ph, 20, f"音声を分割中... (全{total_chunks_n}チャンク)")
                        chunks = split_audio_to_chunks(audio_path, chunk_minutes=CHUNK_MINUTES)

                        for chunk in chunks:
                            ci = chunk["index"]
                            pct = 20 + int(60 * ci / total_chunks_n)
                            start_m = int(chunk["start_sec"] // 60)
                            end_m   = int(chunk["end_sec"] // 60)
                            show_animal_progress(prog_ph, pct,
                                f"チャンク {ci+1}/{total_chunks_n} 処理中... "
                                f"({start_m}〜{end_m}分)")
                            segs_iter, _ = wmodel.transcribe(
                                chunk["path"], language="ja", beam_size=5)
                            for s in segs_iter:
                                segments_data.append({
                                    "start": round(s.start + chunk["start_sec"], 2),
                                    "end":   round(s.end   + chunk["start_sec"], 2),
                                    "text":  s.text.strip(),
                                })
                            # チャンクファイルを即削除してメモリ節約
                            try:
                                os.remove(chunk["path"])
                            except Exception:
                                pass
                            gc.collect()
                            # 中間バックアップ保存
                            pathlib.Path("/tmp/Claude").mkdir(exist_ok=True)
                            with open("/tmp/Claude/" + st.session_state.file_base + "_backup.json", "w") as bk:
                                json.dump({"raw_text": "", "file_base": st.session_state.file_base,
                                           "segments_data": segments_data, "speaker_turns": []}, bk)
                        chunk_info_ph.success(f"✅ 全{total_chunks_n}チャンクの文字起こし完了！")
                    else:
                        # ── 通常処理（30分以内）───────────────
                        show_animal_progress(prog_ph, 40, "文字起こし中...")
                        segs_iter, _ = wmodel.transcribe(audio_path, language="ja", beam_size=5)
                        segments_data = [
                            {"start": s.start, "end": s.end, "text": s.text.strip()}
                            for s in segs_iter
                        ]

                    del wmodel
                    gc.collect()

                    # ── 話者識別 ──────────────────────────
                    show_animal_progress(prog_ph, 85, "話者識別中...")
                    mem = psutil.virtual_memory()
                    diarization = None
                    if mem.percent < 80:
                        try:
                            from pyannote.audio import Pipeline
                            from pyannote.audio.pipelines.utils.hook import ProgressHook
                            pipeline = Pipeline.from_pretrained(
                                "pyannote/speaker-diarization-3.1",
                                use_auth_token=HF_TOKEN)
                            with ProgressHook() as hook:
                                diarization = pipeline(audio_path, hook=hook)
                        except Exception as e:
                            st.warning(f"話者識別エラー（スキップ）: {e}")
                    else:
                        st.warning("⚠️ RAM不足のため話者識別をスキップしました")

                    show_animal_progress(prog_ph, 95, "テキスト整形中...")
                    speaker_turns = []
                    if diarization:
                        for turn, _, label in diarization.itertracks(yield_label=True):
                            speaker_turns.append({"start": turn.start, "end": turn.end, "speaker": label})

                    raw_text_built = ""
                    if speaker_turns:
                        for seg in segments_data:
                            spk = next((t["speaker"] for t in speaker_turns
                                if t["start"] <= seg["start"] < t["end"]), "不明")
                            raw_text_built += "[" + str(round(seg["start"], 1)) + "s] " + spk + ": " + seg["text"] + "\n"
                    else:
                        for seg in segments_data:
                            raw_text_built += "[" + str(round(seg["start"], 1)) + "s] " + seg["text"] + "\n"

                    st.session_state.update({
                        "raw_text": raw_text_built, "segments_data": segments_data,
                        "speaker_turns": speaker_turns, "step": 3,
                    })
                    pathlib.Path("/tmp/Claude").mkdir(exist_ok=True)
                    with open("/tmp/Claude/" + st.session_state.file_base + "_backup.json", "w") as bk:
                        json.dump({"raw_text": raw_text_built, "file_base": st.session_state.file_base,
                                   "segments_data": segments_data, "speaker_turns": speaker_turns}, bk)
                    show_animal_progress(prog_ph, 100, "🎉 完了！")
                    st.rerun()
                except Exception as e:
                    st.error(f"文字起こしエラー: {e}")

            elif st.session_state.step == 3:
                st.subheader("👥 Step 3：話している人の名前を設定")
                speakers = sorted(set(t["speaker"] for t in st.session_state.speaker_turns)) \
                    if st.session_state.speaker_turns else []
                speaker_map = {}
                for sp in speakers:
                    name = st.text_input(f"{sp} の名前（例: ぶーちゃん）:",
                        value=st.session_state.speaker_map.get(sp, ""), key=f"sp_{sp}")
                    speaker_map[sp] = name
                if st.button("▶ 次のステップへ", type="primary"):
                    new_text = st.session_state.raw_text
                    for sp, name in speaker_map.items():
                        if name:
                            new_text = new_text.replace(sp, name)
                    st.session_state["raw_text"] = new_text
                    st.session_state["speaker_map"] = speaker_map
                    st.session_state["step"] = 4
                    st.rerun()

            elif st.session_state.step == 4:
                st.subheader("📋 Step 4：会議のメモを入力")
                participants_c = st.text_area("参加者（氏名・所属）", value=st.session_state.participants,
                    placeholder="例: ぶーちゃん社長（万世ぶーちゃん商事）")
                emphasis_c  = st.text_area("強調したい項目", value=st.session_state.emphasis_items,
                    placeholder="例: 次回の搬入日程や費用負担についてまとめたい")
                decisions_c = st.text_area("決定事項", value=st.session_state.decisions,
                    placeholder="例: 来月までにサンプルを提出する")
                pending_c   = st.text_area("未決定の宿題事項", value=st.session_state.pending_items,
                    placeholder="例: もーちゃん食品から来週中に回答をもらう")
                col1c, col2c = st.columns(2)
                with col1c:
                    q_date_c  = st.text_input("会議日時", value=st.session_state.q_date)
                    q_place_c = st.text_input("場所", value=st.session_state.q_place)
                with col2c:
                    q_title_c = st.text_input("会議タイトル", value=st.session_state.q_title)
                mode3 = st.radio("出力スタイル 📝", ["議事録のみ", "議事録＋文字起こしデータ"],
                    index=0 if st.session_state.mode == "議事録のみ" else 1, key="mode3")
                if st.button("🐷 議事録を作る", type="primary"):
                    st.session_state.update({
                        "participants": participants_c, "emphasis_items": emphasis_c,
                        "decisions": decisions_c, "pending_items": pending_c,
                        "q_date": q_date_c, "q_title": q_title_c, "q_place": q_place_c,
                        "mode": mode3, "step": 5,
                    })
                    st.rerun()

            elif st.session_state.step == 5:
                st.subheader("✅ Step 5：かんたん生成＆ダウンロード")
                if not st.session_state.minutes_html:
                    with st.spinner("Claude API で議事録を生成中..."):
                        try:
                            minutes_html_c = call_claude_minutes(
                                st.session_state.raw_text, st.session_state.q_date,
                                st.session_state.q_title, st.session_state.q_place,
                                st.session_state.participants, st.session_state.emphasis_items,
                                st.session_state.decisions, st.session_state.pending_items,
                            )
                            st.session_state["minutes_html"] = minutes_html_c
                        except Exception as e:
                            st.error(f"議事録生成エラー: {e}")
                    if st.session_state.mode == "議事録＋文字起こしデータ":
                        with st.spinner("文字起こしデータを整理中..."):
                            try:
                                legal_html_c = call_claude_legal(
                                    st.session_state.raw_text, st.session_state.q_title)
                                st.session_state["legal_html"] = legal_html_c
                            except Exception as e:
                                st.warning(f"文字起こしデータ整理エラー: {e}")
                    play_completion_sound()

                fb_c = st.session_state.file_base
                from datetime import datetime as _dt
                ts_c = _dt.now().strftime("%Y%m%d_%H%M%S")
                show_download_section(fb_c, ts_c,
                    st.session_state.minutes_html,
                    st.session_state.legal_html,
                    st.session_state.raw_text,
                    key_prefix="colab")
                st.divider()
                col3c, col4c = st.columns(2)
                with col3c:
                    if st.button("🔄 別の音声ファイルを処理する"):
                        for k, v in colab_defaults.items():
                            st.session_state[k] = v
                        st.rerun()
                with col4c:
                    if st.button("✏️ 会議情報を修正して再生成"):
                        st.session_state["step"] = 4
                        st.session_state["minutes_html"] = ""
                        st.rerun()
