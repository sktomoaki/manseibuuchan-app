import streamlit as st
import os, json, gc, psutil
from pathlib import Path
from datetime import date
import streamlit.components.v1 as components

# ---- 環境変数 ----
HF_TOKEN          = os.environ.get("HF_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DRIVE_BASE        = os.environ.get("DRIVE_BASE", "/tmp/Claude")
# ---- 月次パスワード自動生成 (v2.5) ----
def _gen_monthly_pw():
    import hashlib as _h, datetime as _d
    _S = "ManseiBuuchan2024"
    _t = _d.datetime.now()
    _raw = _S + "_" + str(_t.year) + "_" + str(_t.month).zfill(2)
    _hx = _h.sha256(_raw.encode("utf-8")).hexdigest()
    _C = "ABCDEFGHJKMNPQRTVWXY2346789"
    return "".join(_C[int(_hx[i:i+2], 16) % len(_C)] for i in range(0, 16, 2))
APP_PASSWORD = _gen_monthly_pw()
CLAUDE_MODEL      = "claude-haiku-4-5-20251001"

# ---- 必要ディレクトリ作成 ----
import pathlib
pathlib.Path("/tmp/Claude").mkdir(parents=True, exist_ok=True)

WAV_FILE          = "/tmp/meeting.wav"

# ---- ページ設定 ----
st.set_page_config(page_title="万世ぶーちゃん v2.5", page_icon="🐷", layout="centered")

# ---- パスワード保護 ----
if APP_PASSWORD:
    if not st.session_state.get("authenticated"):
        st.title("🔑 ログイン")
        pw = st.text_input("パスワードを入力", type="password")
        if st.button("ログイン"):
            if pw == APP_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("パスワードが違います")
        st.stop()

# ---- 起動時RAM確認・警告（修正2） ----
def check_ram_on_startup():
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024 ** 3)
    if available_gb < 4:
        st.error(f"🔴 RAMが不足しています（利用可能: {available_gb:.1f} GB）。アプリが起動しない場合はColabランタイムを再起動してください。")
    elif available_gb < 8:
        st.warning(f"🟡 RAMに余裕がありません（利用可能: {available_gb:.1f} GB）。重い処理では問題が起きる可能性があります。")
    else:
        st.success(f"🟢 RAM十分（利用可能: {available_gb:.1f} GB）")

check_ram_on_startup()

# ---- 起動時ピピピサウンド（修正3） ----
def play_startup_sound():
    """起動時にピピピピッピ音を鳴らす"""
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

# ---- セッション初期化 ----
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
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---- ユーティリティ ----
def ram_info():
    mem = psutil.virtual_memory()
    pct = mem.percent
    color = "red" if pct > 85 else "orange" if pct > 70 else "green"
    base = (f"<span style='color:{color};font-weight:bold;'>"
            f"RAM {mem.used/1e9:.1f}/{mem.total/1e9:.1f}GB ({pct:.0f}%)</span>")
    # GPU情報はセッション内でキャッシュ（torch初期化を1回だけにする）
    if "_gpu_info_html" not in st.session_state:
        gpu_html = ""
        try:
            import torch
            if torch.cuda.is_available():
                gm = torch.cuda.memory_reserved(0) / 1e9
                gt = torch.cuda.get_device_properties(0).total_memory / 1e9
                gpu_html = (f" &nbsp;<span style='color:#2980b9;font-weight:bold;'>"
                            f"🚀GPU {gm:.1f}/{gt:.1f}GB</span>")
        except Exception:
            pass
        st.session_state["_gpu_info_html"] = gpu_html
    base += st.session_state["_gpu_info_html"]
    return base

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

def merge_segments_with_speakers(segments, speaker_turns, name_map):
    results = []
    for seg in segments:
        s, e, txt = seg["start"], seg["end"], seg["text"]
        best_sp, best_ov = "SPEAKER_00", 0
        for turn in speaker_turns:
            ov = max(0, min(e, turn["end"]) - max(s, turn["start"]))
            if ov > best_ov:
                best_ov, best_sp = ov, turn["speaker"]
        results.append({"speaker": name_map.get(best_sp, best_sp),
                         "start": s, "end": e, "text": txt})
    return results

def build_raw_text(merged):
    lines, cur_sp = [], None
    for seg in merged:
        sp, txt = seg["speaker"], seg["text"].strip()
        if sp != cur_sp:
            lines.append(f"\n【{sp}】")
            cur_sp = sp
        lines.append(txt)
    return "\n".join(lines).strip()

def call_claude_minutes(raw_text, q_date, q_title, q_place,
                         participants, emphasis, decisions, pending):
    import anthropic as _ant
    client = _ant.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""以下の会議の文字起こしテキストをもとに、HTMLフォーマットの議事録を作成してください。

【会議情報】
- 日時: {q_date}
- 件名: {q_title}
- 場所: {q_place}
- 参加者: {participants}
- 強調したい項目: {emphasis}
- 決定事項（入力済み）: {decisions}
- 未決定課題: {pending}

【文字起こし（最大15000文字）】
{raw_text[:15000]}

【出力形式】
- DOCTYPE〜</html>まで完全なHTML、UTF-8、A4印刷対応
- セクション: 基本情報テーブル / 背景・経緯 / アジェンダ / 議論の要約 / 決定事項 / アクションアイテム（誰が・何を・いつまで） / 次回予定
- 重要箇所は赤太字で強調
- 「検討する」は禁止 → 「○○が△△までに結論を出す」に置き換え
"""
    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text

def call_claude_legal(raw_text, q_title):
    import anthropic as _ant
    client = _ant.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""以下の会議文字起こしを、読みやすく整形した「文字起こしデータHTML」を作成してください。

件名: {q_title}

【文字起こし】
{raw_text[:15000]}

【出力形式】
- DOCTYPE〜</html>まで完全なHTML、A4印刷対応
- 重要な発言・決定事項を5〜10点抽出し、タイムスタンプ・発言者・内容を表形式で整理
- 責任認定・約束・謝罪・矛盾する発言・優越的地位の乱用を優先抽出
- 重要度が高い箇所は赤背景または赤枠で強調
"""
    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text

def save_to_drive(file_base, minutes_html, legal_html, raw_text,
                   segments_data, speaker_turns):
    save_dir = os.path.join(DRIVE_BASE, "議事録アウトプット", file_base)
    os.makedirs(save_dir, exist_ok=True)
    saved = []
    def w(name, content):
        p = os.path.join(save_dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        saved.append(p)
    if minutes_html: w(f"{file_base}_議事録.html", minutes_html)
    if legal_html:   w(f"{file_base}_文字起こし.html", legal_html)
    if raw_text:     w(f"{file_base}_文字起こし.txt", raw_text)
    bak = {"segments": segments_data or [], "speaker_turns": speaker_turns or []}
    w(f"{file_base}_backup.json", json.dumps(bak, ensure_ascii=False, indent=2))
    return save_dir, saved

# ---- 完了通知音（修正6） ----
def play_completion_sound():
    """炊飯器完了音（確認ボタンを押すまで鳴り続ける）"""
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
        // 炊飯器のような完了チャイム音
        const melody = [
            {freq: 523, dur: 0.3, start: 0.0},   // ド
            {freq: 659, dur: 0.3, start: 0.35},   // ミ
            {freq: 784, dur: 0.3, start: 0.70},   // ソ
            {freq: 1047, dur: 0.6, start: 1.05},  // 高ド
            {freq: 784, dur: 0.3, start: 1.75},   // ソ
            {freq: 1047, dur: 0.8, start: 2.10},  // 高ド（長め）
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
        // 3.5秒後に再度繰り返し
        if (isPlaying) {
            setTimeout(playDonChime, 3500);
        }
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

# ---- ファイルサイズから予想処理時間を表示（修正5） ----
def estimate_transcription_time(file_size_bytes, model_name="medium"):
    """ファイルサイズからWhisper処理時間を推定"""
    # おおよその目安: 1MBあたりmediumモデルで約20秒（Colab環境）
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


# ================================================================
# ヘッダー
# ================================================================
st.markdown("""
<div style='text-align:center;padding:16px 0 8px 0;'>
  <span style='font-size:52px;'>🐷</span>
  <h1 style='margin:4px 0 2px 0;font-size:22px;'>万世ぶーちゃんの議事録サポートアプリ v2.5</h1>
  <p style='color:#888;font-size:12px;margin:0;'>テキストを貼り付けるだけで議事録を自動作成🐷</p>
</div>""", unsafe_allow_html=True)

check_ram_on_startup()
IS_COLAB = os.path.exists('/content')

tab1, tab2 = st.tabs(["📝 テキストから作成（すぐ使える）", "🎤 音声から作成（Colab専用）"])

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

                    st.markdown("#### 📄 議事録")
                    st.download_button("📄 議事録 HTML をダウンロード",
                        data=minutes_html.encode("utf-8"),
                        file_name=f"{file_base}_{ts}.html",
                        mime="text/html", use_container_width=True)

                    if mode == "議事録＋文字起こしデータ":
                        with st.spinner("文字起こしデータを整理中..."):
                            try:
                                legal_html = call_claude_legal(raw_text, q_title)
                                st.markdown("#### 📄 文字起こしデータ")
                                st.download_button("📄 文字起こしデータ HTML をダウンロード",
                                    data=legal_html.encode("utf-8"),
                                    file_name=f"{file_base}_文字起こし_{ts}.html",
                                    mime="text/html", use_container_width=True)
                            except Exception as e:
                                st.warning(f"文字起こしデータ整理エラー: {e}")

                    st.download_button("📝 文字起こし TXT をダウンロード",
                        data=raw_text.encode("utf-8"),
                        file_name=f"{file_base}_文字起こし_{ts}.txt",
                        mime="text/plain", use_container_width=True)
                    play_completion_sound()

                except Exception as e:
                    st.error(f"議事録生成エラー: {e}")

# ================================================================
# タブ2: 音声文字起こし（Colab専用）
# ================================================================
with tab2:
    if not IS_COLAB:
        st.warning("""
        🎤 **音声文字起こし機能は Colab 専用です**

        以下の手順で使えます：
        1. [Colab を開く](https://colab.research.google.com/drive/1QYZcwJuFX47EPRnsEBLRzZjQOIM2TEI2) をクリック
        2. Step 2 → Start Streamlit セルを実行（約30秒）
        3. 音声ファイルをアップロードして文字起こし
        4. 完了したテキストをコピー → 「📝 テキストから作成」タブに貼り付け
        """)
    else:
        DEFAULTS = {
            "step": 1, "audio_path": None, "file_base": "",
            "raw_text": "", "segments_data": [], "speaker_turns": [],
            "speaker_map": {}, "q_date": "", "q_title": "", "q_place": "",
            "participants": "", "emphasis_items": "", "decisions": "",
            "pending_items": "", "mode": "議事録＋文字起こしデータ",
            "minutes_html": "", "legal_html": "", "drive_save_dir": "",
            "model_size": "medium",
        }
        for k, v in DEFAULTS.items():
            if k not in st.session_state:
                st.session_state[k] = v

        steps_label = ["音声アップ", "文字起こし中", "話者設定", "会議メモ入力", "生成完了"]
        st.progress((st.session_state.step - 1) / 4)
        st.caption(steps_label[st.session_state.step - 1])

        import glob
        backups = sorted(glob.glob("/tmp/Claude/*.json"), reverse=True)[:5]
        if backups and st.session_state.step == 1:
            names = [os.path.basename(b) for b in backups]
            st.info(f"💾 以前の処理データが {len(backups)} 件見つかりました。")
            selected = st.selectbox("復旧するセッションを選択:", names)
            if st.button("🔄 このデータから再開する"):
                import json
                with open(backups[names.index(selected)]) as bf:
                    bdata = json.load(bf)
                for k, v in bdata.items():
                    st.session_state[k] = v
                st.rerun()

        if st.session_state.step == 1:
            st.subheader("🎙 Step 1：音声ファイルをえらぶ")
            model_size = st.selectbox("Whisperモデル", ["medium", "small", "large-v2"],
                index=0, help="medium推奨")
            mode2 = st.radio("出力スタイル 📝", ["議事録のみ", "議事録＋文字起こしデータ"], index=1)
            st.session_state["mode"] = mode2
            uploaded = st.file_uploader("音声ファイルをアップロード",
                type=["m4a", "mp3", "wav", "mp4", "ogg", "flac"])
            if uploaded:
                file_size_mb = uploaded.size / (1024 * 1024)
                est_time = estimate_transcription_time(uploaded.size, model_size)
                st.info(f"📊 ファイルサイズ: {file_size_mb:.1f} MB　⏱ 予想処理時間: {est_time}")
            if uploaded and st.button("▶ テキスト変換スタート", type="primary"):
                from pydub import AudioSegment
                file_base = Path(uploaded.name).stem
                raw_path = f"/tmp/{uploaded.name}"
                with open(raw_path, "wb") as f:
                    f.write(uploaded.getvalue())
                audio = AudioSegment.from_file(raw_path)
                audio.export("/tmp/meeting.wav", format="wav")
                st.session_state.update({
                    "file_base": file_base, "model_size": model_size,
                    "mode": mode2, "audio_path": "/tmp/meeting.wav", "step": 2,
                })
                st.rerun()

        elif st.session_state.step == 2:
            st.subheader("⚙ Step 2：文字起こし中...")
            prog_ph = st.empty()
            show_animal_progress(prog_ph, 10, "準備中...")
            try:
                from faster_whisper import WhisperModel
                show_animal_progress(prog_ph, 30, "Whisperモデル読み込み中...")
                wmodel = WhisperModel(st.session_state.model_size, device="cpu", compute_type="int8")
                show_animal_progress(prog_ph, 50, "文字起こし中...")
                segs_iter, _ = wmodel.transcribe(st.session_state.audio_path, language="ja", beam_size=5)
                segments = list(segs_iter)
                del wmodel
                import gc; gc.collect()
                show_animal_progress(prog_ph, 70, "話者識別中...")
                mem = __import__("psutil").virtual_memory()
                diarization = None
                if mem.percent < 80:
                    try:
                        from pyannote.audio import Pipeline
                        from pyannote.audio.pipelines.utils.hook import ProgressHook
                        pipeline = Pipeline.from_pretrained(
                            "pyannote/speaker-diarization-3.1",
                            use_auth_token=os.environ.get("HF_TOKEN", ""))
                        with ProgressHook() as hook:
                            diarization = pipeline(st.session_state.audio_path, hook=hook)
                    except Exception as e:
                        st.warning(f"話者識別エラー（スキップ）: {e}")
                else:
                    st.warning("⚠️ RAM不足のため話者識別をスキップしました")
                show_animal_progress(prog_ph, 90, "テキスト整形中...")
                segments_data = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
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
                import json, pathlib
                pathlib.Path("/tmp/Claude").mkdir(exist_ok=True)
                with open("/tmp/Claude/" + st.session_state.file_base + "_backup.json", "w") as bk:
                    json.dump({"raw_text": raw_text_built, "file_base": st.session_state.file_base,
                               "segments_data": segments_data, "speaker_turns": speaker_turns}, bk)
                show_animal_progress(prog_ph, 100, "完了！")
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
            participants = st.text_area("参加者（氏名・所属）", value=st.session_state.participants,
                placeholder="例: ぶーちゃん社長（万世ぶーちゃん商事）")
            emphasis  = st.text_area("強調したい項目", value=st.session_state.emphasis_items,
                placeholder="例: 次回の搬入日程や費用負担についてまとめたい")
            decisions = st.text_area("決定事項", value=st.session_state.decisions,
                placeholder="例: 来月までにサンプルを提出する")
            pending   = st.text_area("未決定の宿題事項", value=st.session_state.pending_items,
                placeholder="例: もーちゃん食品から来週中に回答をもらう")
            col1, col2 = st.columns(2)
            with col1:
                q_date  = st.text_input("会議日時", value=st.session_state.q_date)
                q_place = st.text_input("場所", value=st.session_state.q_place)
            with col2:
                q_title = st.text_input("会議タイトル", value=st.session_state.q_title)
            mode3 = st.radio("出力スタイル 📝", ["議事録のみ", "議事録＋文字起こしデータ"],
                index=0 if st.session_state.mode == "議事録のみ" else 1)
            if st.button("🐷 議事録を作る", type="primary"):
                st.session_state.update({
                    "participants": participants, "emphasis_items": emphasis,
                    "decisions": decisions, "pending_items": pending,
                    "q_date": q_date, "q_title": q_title, "q_place": q_place,
                    "mode": mode3, "step": 5,
                })
                st.rerun()

        elif st.session_state.step == 5:
            st.subheader("✅ Step 5：かんたん生成＆ダウンロード")
            if not st.session_state.minutes_html:
                with st.spinner("Claude API で議事録を生成中..."):
                    try:
                        minutes_html = call_claude_minutes(
                            st.session_state.raw_text, st.session_state.q_date,
                            st.session_state.q_title, st.session_state.q_place,
                            st.session_state.participants, st.session_state.emphasis_items,
                            st.session_state.decisions, st.session_state.pending_items,
                        )
                        st.session_state["minutes_html"] = minutes_html
                    except Exception as e:
                        st.error(f"議事録生成エラー: {e}")
                if st.session_state.mode == "議事録＋文字起こしデータ":
                    with st.spinner("文字起こしデータを整理中..."):
                        try:
                            legal_html = call_claude_legal(
                                st.session_state.raw_text, st.session_state.q_title)
                            st.session_state["legal_html"] = legal_html
                        except Exception as e:
                            st.warning(f"文字起こしデータ整理エラー: {e}")
                play_completion_sound()

            fb = st.session_state.file_base
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.divider()
            if st.session_state.minutes_html:
                st.markdown("#### 📄 議事録")
                st.download_button("📄 議事録 HTML をダウンロード",
                    data=st.session_state.minutes_html.encode("utf-8"),
                    file_name=f"{fb}_議事録_{ts}.html", mime="text/html", use_container_width=True)
            if st.session_state.legal_html:
                st.markdown("#### 📄 文字起こしデータ")
                st.download_button("📄 文字起こしデータ HTML をダウンロード",
                    data=st.session_state.legal_html.encode("utf-8"),
                    file_name=f"{fb}_文字起こし_{ts}.html", mime="text/html", use_container_width=True)
            if st.session_state.raw_text:
                st.download_button("📝 文字起こし TXT をダウンロード",
                    data=st.session_state.raw_text.encode("utf-8"),
                    file_name=f"{fb}_文字起こし_{ts}.txt", mime="text/plain", use_container_width=True)
            st.divider()
            col3, col4 = st.columns(2)
            with col3:
                if st.button("🔄 別の音声ファイルを処理する"):
                    for k, v in DEFAULTS.items():
                        st.session_state[k] = v
                    st.rerun()
            with col4:
                if st.button("✏️ 会議情報を修正して再生成"):
                    st.session_state["step"] = 4
                    st.session_state["minutes_html"] = ""
                    st.rerun()
