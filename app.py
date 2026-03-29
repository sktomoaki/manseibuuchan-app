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
    "pending_items": "", "mode": "議事録のみ",
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
    prompt = f"""以下の会議文字起こしから、裁判・法的交渉で有利になる重要箇所を抽出した証拠資料HTMLを作成してください。

件名: {q_title}

【文字起こし】
{raw_text[:15000]}

【出力形式】
- DOCTYPE〜</html>まで完全なHTML、A4印刷対応
- 重要箇所を5〜10点抽出し、タイムスタンプ・発言内容・法的意義を表形式で整理
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
    if legal_html:   w(f"{file_base}_証拠資料.html", legal_html)
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
  <p style='color:#888;font-size:12px;margin:0;'>音声→文字起こし→話者識別→議事録HTML・証拠資料を自動生成</p>
</div>
""", unsafe_allow_html=True)

st.markdown(f"{ram_info()} &nbsp; ステップ: {st.session_state.step}/5",
            unsafe_allow_html=True)
steps_label = ["① ファイル選択","② 文字起こし","③ 話者名設定","④ 会議情報入力","⑤ 生成・DL"]
st.progress((st.session_state.step - 1) / 4)
st.caption(steps_label[st.session_state.step - 1])
st.divider()

# ================================================================
# Step 1: ファイルアップロード
# ================================================================
if st.session_state.step == 1:
    st.subheader("🎙 Step 1：音声ファイルのアップロード")

    # 操作説明書（修正4）
    with st.expander("📖 操作説明書（クリックで開く）", expanded=False):
        st.markdown("""
    ## 🐷 万世ぶーちゃん 操作マニュアル

    ### ① 音声ファイルを選ぶ（Step 1）
    - 「音声ファイルを選択」ボタンで会議の録音ファイルをアップロード
    - 対応形式：MP3・MP4・WAV・M4A など
    - Whisperモデルは通常「medium」を推奨

    ### ② 文字起こし開始（Step 2）
    - 「文字起こし開始」ボタンを押すと自動で処理が始まります
    - ファイルサイズに応じて数分かかります（目安時間が表示されます）
    - 完了したら通知音が鳴ります

    ### ③ 話者名を設定（Step 3）
    - 話者A・話者B… の名前を実際の人名に変更してください

    ### ④ 会議情報を入力（Step 4）
    - 日時・件名・場所・参加者などを入力します

    ### ⑤ 議事録を保存（Step 5）
    - 完成した議事録をダウンロードまたは保存します

    ---
    ⚠️ **困ったときは？** → ページを更新するか、Step 1からやり直してください
    """)

    # クラッシュ復旧
    backup_dir = os.path.join(DRIVE_BASE, "議事録アウトプット")
    backups = []
    if os.path.exists(backup_dir):
        for d in os.listdir(backup_dir):
            bak = os.path.join(backup_dir, d, f"{d}_backup.json")
            if os.path.exists(bak):
                backups.append((d, bak))

    if backups:
        st.info(f"💾 以前の処理データが {len(backups)} 件見つかりました。復旧できます。")
        names = [b[0] for b in backups]
        selected = st.selectbox("復旧するセッションを選択:", names)
        if st.button("🔄 このデータから再開する"):
            bak_path = dict(backups)[selected]
            with open(bak_path, encoding="utf-8") as f:
                bak = json.load(f)
            segs  = bak.get("segments", [])
            turns = bak.get("speaker_turns", [])
            speakers = sorted(set(s.get("speaker","") for s in segs if s.get("speaker")))
            st.session_state.update({
                "segments_data": segs, "speaker_turns": turns,
                "file_base": selected, "detected_speakers": speakers,
                "crash_recovered": True,
                "raw_text": build_raw_text(merge_segments_with_speakers(segs, turns, {})),
                "step": 3,
            })
            st.rerun()
        st.divider()

    uploaded = st.file_uploader(
        "音声ファイルをアップロード（m4a/mp3/wav/mp4/ogg/flac）",
        type=["m4a","mp3","wav","mp4","ogg","flac"]
    )
    model_size = st.selectbox("Whisperモデル", ["medium","small","large-v2"],
                               index=0, help="medium推奨。RAMが少ない場合はsmall")
    mode = st.radio("生成モード", ["議事録のみ", "議事録＋証拠資料（法的資料）"], index=0)

    # ファイルサイズ・予想処理時間の表示（修正5）
    if uploaded:
        file_size_bytes = uploaded.size
        file_size_mb = file_size_bytes / (1024 * 1024)
        est_time = estimate_transcription_time(file_size_bytes, model_size)
        st.info(f"📊 ファイルサイズ: {file_size_mb:.1f} MB　⏱ 予想処理時間: {est_time}")

    st.markdown(f"現在の{ram_info()}", unsafe_allow_html=True)

    if uploaded and st.button("▶ 文字起こし開始", type="primary"):
        # lazy import pydub
        IS_COLAB = os.path.exists('/content')
        if not IS_COLAB:
            st.error("⚠️ 音声文字起こし機能は現在このバージョンでは利用できません。テキスト直接入力をご利用ください。")
            st.stop()
        from pydub import AudioSegment
        file_base = Path(uploaded.name).stem
        raw_path  = f"/tmp/{uploaded.name}"
        with open(raw_path, "wb") as f:
            f.write(uploaded.read())
        audio = AudioSegment.from_file(raw_path)
        audio.export(WAV_FILE, format="wav")
        st.session_state.update({
            "file_base": file_base, "model_size": model_size,
            "mode": mode, "audio_path": WAV_FILE, "step": 2,
        })
        st.rerun()

# ================================================================
# Step 2: 文字起こし＆話者識別
# ================================================================
elif st.session_state.step == 2:
    st.subheader("⚙ Step 2：文字起こし＆話者識別")
    st.markdown(f"対象: **{st.session_state.file_base}**")
    st.markdown(f"{ram_info()}", unsafe_allow_html=True)

    anim = st.empty()

    # lazy import heavy libs
    import torch
    from faster_whisper import WhisperModel
    from pyannote.audio import Pipeline
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    # GPU / CPU 自動判定
    use_gpu = os.environ.get("USE_GPU", "0") == "1" and torch.cuda.is_available()
    device       = "cuda" if use_gpu else "cpu"
    compute_type = "float16" if use_gpu else "int8"
    hw_label = "🚀 GPU" if use_gpu else "🐢 CPU"

    # Whisper
    show_animal_progress(anim, 5, f"🐷 Whisper モデルをロード中... ({hw_label})")
    wmodel = WhisperModel(st.session_state.model_size, device=device, compute_type=compute_type)
    show_animal_progress(anim, 15, "🎙 音声を認識中... しばらくお待ちください")
    segs_iter, _ = wmodel.transcribe(st.session_state.audio_path, language="ja", beam_size=5)
    segments_data = [{"start": s.start, "end": s.end, "text": s.text, "speaker": ""}
                     for s in segs_iter]
    show_animal_progress(anim, 45, f"✅ 文字起こし完了: {len(segments_data)}セグメント")

    del wmodel, segs_iter
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    ram_pct = psutil.virtual_memory().percent
    show_animal_progress(anim, 50, f"💾 Drive に中間保存中... RAM {ram_pct:.0f}%")

    # Drive中間保存
    bak_dir = os.path.join(DRIVE_BASE, "議事録アウトプット", st.session_state.file_base)
    os.makedirs(bak_dir, exist_ok=True)
    with open(os.path.join(bak_dir, f"{st.session_state.file_base}_backup.json"),
              "w", encoding="utf-8") as f:
        json.dump({"segments": segments_data, "speaker_turns": []}, f, ensure_ascii=False)

    # pyannote 話者識別
    speaker_turns = []
    if ram_pct < 80:
        show_animal_progress(anim, 55, f"🐮 話者識別モデルをロード中... ({hw_label})")
        try:
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=HF_TOKEN
            )
            if use_gpu:
                pipeline = pipeline.to(torch.device("cuda"))
            show_animal_progress(anim, 65, "🐷🐮 誰が話しているか識別中... 少しかかります")
            with ProgressHook() as hook:
                diarization = pipeline(st.session_state.audio_path, hook=hook)
            speaker_turns = [
                {"start": turn.start, "end": turn.end, "speaker": label}
                for turn, _, label in diarization.itertracks(yield_label=True)
            ]
            show_animal_progress(anim, 80, f"✅ 話者識別完了 / RAM {psutil.virtual_memory().percent:.0f}%")
            for seg in segments_data:
                s, e = seg["start"], seg["end"]
                best_sp, best_ov = "SPEAKER_00", 0
                for t in speaker_turns:
                    ov = max(0, min(e, t["end"]) - max(s, t["start"]))
                    if ov > best_ov:
                        best_ov, best_sp = ov, t["speaker"]
                seg["speaker"] = best_sp
            del pipeline, diarization
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            st.warning(f"話者識別エラー（スキップ）: {e}")
            for seg in segments_data:
                seg["speaker"] = "SPEAKER_00"
    else:
        st.warning(f"⚠️ RAM {ram_pct:.0f}% — メモリ不足のため話者識別をスキップしました")
        for seg in segments_data:
            seg["speaker"] = "SPEAKER_00"

    show_animal_progress(anim, 90, "💾 結果を Drive に保存中...")
    with open(os.path.join(bak_dir, f"{st.session_state.file_base}_backup.json"),
              "w", encoding="utf-8") as f:
        json.dump({"segments": segments_data, "speaker_turns": speaker_turns},
                  f, ensure_ascii=False)

    show_animal_progress(anim, 100, "🎉 完了！次のステップへ進みます")

    # 文字起こし完了通知音（修正6）
    play_completion_sound()

    detected = sorted(set(seg.get("speaker","") for seg in segments_data if seg.get("speaker")))
    st.session_state.update({
        "segments_data": segments_data, "speaker_turns": speaker_turns,
        "detected_speakers": detected, "step": 3,
    })
    st.rerun()

# ================================================================
# Step 3: 話者名の設定
# ================================================================
elif st.session_state.step == 3:
    st.subheader("👥 Step 3：話者名の設定")
    st.markdown(f"{ram_info()}", unsafe_allow_html=True)

    if st.session_state.crash_recovered:
        st.success("✅ バックアップデータから正常に復旧しました")

    detected = st.session_state.detected_speakers or ["SPEAKER_00"]
    st.caption(f"{len(detected)} 名の話者が検出されました")

    name_map = {}
    for sp in detected:
        default = st.session_state.speaker_names.get(sp, sp)
        name = st.text_input(f"{sp} の名前（例: 鹿野会長）:", value=default, key=f"sp_{sp}")
        name_map[sp] = name.strip() or sp

    if st.button("▶ 次へ（会議情報入力）", type="primary"):
        st.session_state["speaker_names"] = name_map
        merged = merge_segments_with_speakers(
            st.session_state.segments_data or [],
            st.session_state.speaker_turns or [],
            name_map,
        )
        st.session_state["raw_text"] = build_raw_text(merged)
        st.session_state["step"] = 4
        st.rerun()

    if st.session_state.get("segments_data"):
        with st.expander("📜 文字起こしプレビュー（最初の10セグメント）"):
            for seg in st.session_state.segments_data[:10]:
                sp = name_map.get(seg.get("speaker",""), seg.get("speaker",""))
                st.write(f"`{seg['start']:.1f}s` **{sp}**: {seg['text']}")

# ================================================================
# Step 4: 会議情報フォーム
# ================================================================
elif st.session_state.step == 4:
    st.subheader("📋 Step 4：会議情報の入力")
    st.markdown(f"{ram_info()}", unsafe_allow_html=True)
    st.caption("文字起こしから読み取れない情報を補足してください（空欄でも生成できます）")

    with st.form("meeting_form"):
        col1, col2 = st.columns(2)
        with col1:
            q_date  = st.text_input("会議日時", value=st.session_state.q_date)
            q_place = st.text_input("開催場所", value=st.session_state.q_place)
        with col2:
            q_title = st.text_input("件名・会議名", value=st.session_state.q_title)
        participants = st.text_area("参加者（氏名・所属）", value=st.session_state.participants,
                                     placeholder="例: 鹿野会長（万世）、遠藤部長（タニコー）")
        emphasis  = st.text_area("強調したい項目・特記事項", value=st.session_state.emphasis_items,
                                  placeholder="例: タニコーの過失を法的に明確にしたい")
        decisions = st.text_area("決定事項（わかっているもの）", value=st.session_state.decisions,
                                  placeholder="例: 2号機を来週搬入する")
        pending   = st.text_area("未決定課題・宿題事項", value=st.session_state.pending_items,
                                  placeholder="例: タニコーからの書面回答を19日に要求")
        mode = st.radio("生成モード", ["議事録のみ", "議事録＋証拠資料（法的資料）"],
                         index=0 if st.session_state.mode == "議事録のみ" else 1)
        submitted = st.form_submit_button("▶ 議事録を生成する", type="primary")

    if submitted:
        st.session_state.update({
            "q_date": q_date, "q_title": q_title, "q_place": q_place,
            "participants": participants, "emphasis_items": emphasis,
            "decisions": decisions, "pending_items": pending, "mode": mode,
            "minutes_html": "", "legal_html": "", "step": 5,
        })
        st.rerun()

# ================================================================
# Step 5: 生成・ダウンロード
# ================================================================
elif st.session_state.step == 5:
    st.subheader("✅ Step 5：生成・ダウンロード")
    st.markdown(f"{ram_info()}", unsafe_allow_html=True)

    if not st.session_state.minutes_html:
        with st.spinner("Claude API で議事録を生成中..."):
            try:
                minutes_html = call_claude_minutes(
                    st.session_state.raw_text,
                    st.session_state.q_date,
                    st.session_state.q_title,
                    st.session_state.q_place,
                    st.session_state.participants,
                    st.session_state.emphasis_items,
                    st.session_state.decisions,
                    st.session_state.pending_items,
                )
                st.session_state["minutes_html"] = minutes_html
            except Exception as e:
                st.error(f"議事録生成エラー: {e}")
                st.stop()

        if st.session_state.mode != "議事録のみ":
            with st.spinner("証拠資料を生成中..."):
                try:
                    legal_html = call_claude_legal(
                        st.session_state.raw_text,
                        st.session_state.q_title,
                    )
                    st.session_state["legal_html"] = legal_html
                except Exception as e:
                    st.warning(f"証拠資料生成エラー（スキップ）: {e}")

        # Drive保存
        try:
            save_dir, _ = save_to_drive(
                st.session_state.file_base,
                st.session_state.minutes_html,
                st.session_state.legal_html,
                st.session_state.raw_text,
                st.session_state.segments_data,
                st.session_state.speaker_turns,
            )
            st.session_state["drive_save_dir"] = save_dir
            st.success(f"✅ ドライブに保存: {save_dir}")
        except Exception as e:
            st.warning(f"Drive保存エラー: {e}")

        # 議事録生成完了通知音（修正6）
        play_completion_sound()

    fb = st.session_state.file_base
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.divider()

    # 議事録ダウンロード（修正7: カスタムファイル名）
    if st.session_state.minutes_html:
        st.markdown("#### 📄 議事録")
        default_minutes_name = f"{fb}_議事録_{ts}.html"
        minutes_filename = st.text_input(
            "議事録ファイル名（変更可）",
            value=default_minutes_name,
            key="minutes_filename_input"
        )
        st.download_button(
            "📄 議事録 HTML をダウンロード",
            data=st.session_state.minutes_html.encode("utf-8"),
            file_name=minutes_filename,
            mime="text/html",
            use_container_width=True,
        )

    # 証拠資料ダウンロード（修正7: カスタムファイル名）
    if st.session_state.legal_html:
        st.markdown("#### ⚖ 証拠資料")
        default_legal_name = f"{fb}_証拠資料_{ts}.html"
        legal_filename = st.text_input(
            "証拠資料ファイル名（変更可）",
            value=default_legal_name,
            key="legal_filename_input"
        )
        st.download_button(
            "⚖ 証拠資料 HTML をダウンロード",
            data=st.session_state.legal_html.encode("utf-8"),
            file_name=legal_filename,
            mime="text/html",
            use_container_width=True,
        )

    if st.session_state.raw_text:
        st.download_button(
            "📝 文字起こし TXT をダウンロード",
            data=st.session_state.raw_text.encode("utf-8"),
            file_name=f"{fb}_文字起こし_{ts}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    if st.session_state.drive_save_dir:
        st.info(f"📁 Drive保存先: {st.session_state.drive_save_dir}")

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
            st.rerun()
