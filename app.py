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
st.set_page_config(page_title="万世ブーちゃんの音声ファイルから議事録作成だブーv2.9", page_icon="🐷", layout="centered")

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
    """Groq Whisper API で文字起こし（25MB制限あり・大容量ファイルは自動チャンク分割）"""
    from groq import Groq
    GROQ_MAX_MB = 24  # Groqの制限25MBより少し小さく設定
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)

    if file_size_mb > GROQ_MAX_MB:
        # 5分チャンクに分割して処理
        chunks = split_audio_to_chunks(audio_path, chunk_minutes=5)
        all_text = ""
        for chunk in chunks:
            client = Groq(api_key=GROQ_API_KEY)
            with open(chunk["path"], "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=f,
                    language="ja",
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
            try:
                for seg in result.segments:
                    adjusted_start = round(seg["start"] + chunk["start_sec"], 1)
                    all_text += "[" + str(adjusted_start) + "s] " + seg["text"].strip() + "\n"
            except Exception:
                text = getattr(result, "text", "") or ""
                all_text += text + "\n"
            try:
                os.remove(chunk["path"])
            except Exception:
                pass
        return all_text
    else:
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
# ヘッダー（bu-chan.png をbase64埋め込み）
# ================================================================
import base64 as _b64

def _get_header_img() -> str:
    """ローカルのbu-chan.pngをbase64で埋め込む（なければ絵文字フォールバック）"""
    _IMG_B64 = "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"
    return f'<img src="data:image/png;base64,{_IMG_B64}" style="width:80px;height:80px;object-fit:contain;" />'

_header_img = _get_header_img()
st.markdown(f"""
<div style='text-align:center;padding:16px 0 8px 0;'>
  {_header_img}
  <h1 style='margin:8px 0 2px 0;font-size:20px;'>万世ブーちゃんの音声ファイルから議事録作成だブーv2.9</h1>
  <p style='color:#888;font-size:12px;margin:0;'>音声をアップロードするだけで議事録を自動作成🐷</p>
</div>""", unsafe_allow_html=True)

check_ram_on_startup()

tab1, tab2 = st.tabs(["🎤 音声から作成", "📝 テキストから作成"])

# ================================================================
# タブ2: テキスト直接入力 → 議事録生成（常時稼働）
# ================================================================
with tab2:
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
# タブ1: 音声文字起こし（クラウドAPI）
# ================================================================
with tab1:
    st.markdown("#### 音声ファイルをアップロードして文字起こし＋議事録を作成します")

    # ---- エンジン選択 ----
    engine = st.radio(
        "🔧 文字起こしエンジンを選択",
        [
            "🤖 Groq Whisper（無料・高速・話者識別なし）",
            "🎯 AssemblyAI（話者識別あり・100時間無料）",
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
                GROQ_MAX_MB = 24
                if file_size_mb > GROQ_MAX_MB:
                    chunk_count = int(file_size_mb / GROQ_MAX_MB) + 1
                    st.info(f"📊 ファイルサイズ: {file_size_mb:.1f} MB　🔀 {chunk_count}チャンクに分割してGroqに送信します（25MB制限対応）")
                else:
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
                                # ローカル保存
                                try:
                                    save_to_drive(fb_g, minutes_html_g, legal_html_g, raw_text_g, [], [])
                                except Exception:
                                    pass
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
                                # ローカル保存
                                try:
                                    save_to_drive(fb_a, minutes_html_a, legal_html_a, raw_text_a, [], [])
                                except Exception:
                                    pass
                                show_download_section(fb_a, ts_a, minutes_html_a, legal_html_a, raw_text_a, key_prefix="aai")
                                play_completion_sound()
                            except Exception as e:
                                st.error(f"議事録生成エラー: {e}")

