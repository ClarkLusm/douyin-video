
from faster_whisper import WhisperModel
from deep_translator.exceptions import TranslationNotFound
import os, platform, subprocess, shutil, psutil
import numpy as np
from pathlib import Path
try:
    import mlx_whisper
except ImportError:
    mlx_whisper = None

BASE_DIR = Path(__file__).parent.resolve()
HF_CACHE_DIR = BASE_DIR / "hf_cache"
HF_CACHE_DIR.mkdir(exist_ok=True)

os.environ["HF_HOME"] = str(HF_CACHE_DIR)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"  # tắt cảnh báo symlink
os.environ["HF_TOKEN"] = ""  # token của bạn lấy ở huggingface.co/settings/tokens

_model=None; _current=None
def get_ram(): 
    try: return psutil.virtual_memory().total/(1024**3)
    except: return 8
def auto_model(): return "medium" if get_ram()>=16 else "small"
def get_model(name=None):
    global _model,_current
    target=name if name else auto_model()
    # Thử dùng mps nếu có, sẽ nhanh hơn cpu 3 lần trên Mac
    try:
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    except:
        device = "cpu"
    _model = WhisperModel(target, device=device, compute_type="int8")
    if _current!=target:
        _current=target
    return _model,target
def fmt(s): 
    h=int(s//3600); m=int((s%3600)//60); sec=int(s%60); ms=int((s-int(s))*1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
def get_faster_model(name=None):
    global _model, _current
    from faster_whisper import WhisperModel
    target = name if name else auto_model()

    # Check xem có GPU không
    try:
        import torch
        if torch.cuda.is_available():
            device = "cuda"
            compute = "float16"
        else:
            device = "cpu"
            compute = "int8"
    except:
        device = "cpu"
        compute = "int8"

    if _model is None or _current!= target:
        print(f"[SUB] Loading faster-whisper {target} on {device} ({compute})", flush=True)
        _model = WhisperModel(target, device=device, compute_type=compute)
        _current = target
    return _model, target
def video_to_subs(vid, lang="zh", model_name=None):
    system = platform.system()
    machine = platform.machine()
    print(f"[SUB] OS={system} ARCH={machine} Model={model_name}", flush=True)

    base = os.path.splitext(vid)[0]
    used = model_name or "small"
    srt = base + f".{used}.zh.srt"
    txt = base + f".{used}.zh.txt"

    # ===== MAC M1/M2/M3 -> dùng mlx-whisper (nhanh x10) =====
    if system == "Darwin" and machine in ["arm64", "aarch64"] and mlx_whisper is not None:
        try:
            import mlx_whisper
            from ffmpeg_helper import get_ffmpeg_path

            model_map = {
                "tiny": "mlx-community/whisper-tiny-mlx",
                "base": "mlx-community/whisper-base-mlx",
                "small": "mlx-community/whisper-small-mlx",
                "medium": "mlx-community/whisper-small-mlx", # medium trên mlx chậm nên dùng small cho nhanh
                "large": "mlx-community/whisper-small-mlx",
            }
            mlx_model = model_map.get(used, "mlx-community/whisper-small-mlx")
            ffmpeg_path = get_ffmpeg_path()
            wav_path = base + "_16k.wav"

            # Tách audio 16k mono
            subprocess.run([ffmpeg_path, "-y", "-i", vid, "-ac", "1", "-ar", "16000", wav_path],
                           capture_output=True)

            print(f"[SUB] [MAC-MLX] Transcribing {os.path.basename(vid)} with {mlx_model}...", flush=True)
            result = mlx_whisper.transcribe(wav_path, path_or_hf_repo=mlx_model, language=lang if lang!="auto" else None)

            full = ""
            with open(srt, "w", encoding="utf-8") as sf:
                for i, seg in enumerate(result["segments"], 1):
                    full += seg["text"] + " "
                    sf.write(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{seg['text'].strip()}\n\n")

            with open(txt, "w", encoding="utf-8") as f:
                f.write(full.strip())

            if os.path.exists(wav_path): os.remove(wav_path)
            print(f"[SUB] [MAC-MLX] Done {srt} ({len(result['segments'])} segs)", flush=True)
            return srt, txt, lang, used

        except ImportError:
            print("[SUB] [MAC] mlx-whisper chưa cài, fallback sang faster-whisper", flush=True)
        except Exception as e:
            print(f"[SUB] [MAC-MLX ERROR] {e}, fallback faster-whisper", flush=True)

    # ===== WINDOWS / LINUX / MAC INTEL -> dùng faster-whisper =====
    print(f"[SUB] [FASTER-WHISPER] Transcribing {os.path.basename(vid)}...", flush=True)
    model, real_used = get_faster_model(used)

    # Dùng beam_size=1 cho nhanh, 5 cho chính xác
    # Trên Win CPU thì beam_size=1 nhanh gấp 5 lần
    beam = 1 if system == "Windows" else 5
    segs, info = model.transcribe(vid, language=None if lang=="auto" else lang,
                                  beam_size=beam, vad_filter=True,
                                  condition_on_previous_text=False)

    full = ""
    with open(srt, "w", encoding="utf-8") as sf:
        for i, seg in enumerate(segs, 1):
            full += seg.text + " "
            sf.write(f"{i}\n{fmt(seg.start)} --> {fmt(seg.end)}\n{seg.text.strip()}\n\n")

    with open(txt, "w", encoding="utf-8") as f:
        f.write(full.strip())

    print(f"[SUB] [FASTER] Done {srt}", flush=True)
    return srt, txt, info.language, real_used

def _translate_blocks(srt_path, fn, target, fallback_engine="qwen", api_key=None):
    print(f"[TRANSLATE] Bắt đầu {srt_path} -> {target}", flush=True)
    base = os.path.splitext(srt_path)[0].replace(".zh","")
    out_srt = base + f".{target}.srt"
    out_txt = base + f".{target}.txt"

    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = [b for b in content.strip().split("\n\n") if b.strip()]
    print(f"[TRANSLATE] Tổng {len(blocks)} blocks", flush=True)

    # Tạo fallback fn nếu Google lỗi
    fallback_fn = None
    if fallback_engine and api_key:
        try:
            fallback_fn = get_translator_fn(fallback_engine, target, api_key=api_key)
            print(f"[TRANSLATE] Đã chuẩn bị fallback {fallback_engine}", flush=True)
        except:
            pass

    out = []; full = ""
    for idx, b in enumerate(blocks):
        lines = b.split("\n")
        if len(lines) < 3: continue
        src = " ".join(lines[2:]).strip()
        if not src: continue

        print(f"[{idx+1}/{len(blocks)}] {src[:50]}...", flush=True)
        try:
            tr = fn(src)
            print(f" -> {tr[:50]} OK", flush=True)
        except TranslationNotFound as e:
            print(f" -> GOOGLE FAIL block {idx}, thử fallback {fallback_engine}", flush=True)
            if fallback_fn:
                try:
                    tr = fallback_fn(src)
                    print(f" -> Fallback OK: {tr[:50]}", flush=True)
                except Exception as e2:
                    print(f" -> Fallback cũng fail: {e2}, giữ nguyên zh", flush=True)
                    tr = src
            else:
                print(f" -> Không có fallback, giữ nguyên zh", flush=True)
                tr = src
        except Exception as e:
            print(f" -> Lỗi {e}, giữ nguyên", flush=True)
            tr = src

        out.append(f"{lines[0]}\n{lines[1]}\n{tr}\n")
        full += tr + " "
        import time; time.sleep(0.3) # nghỉ 0.3s giữa các câu để không bị Google chặn

    with open(out_srt, "w", encoding="utf-8") as f: f.write("\n".join(out))
    with open(out_txt, "w", encoding="utf-8") as f: f.write(full.strip())
    print(f"[TRANSLATE DONE] {out_srt}", flush=True)
    return out_srt, out_txt

def get_translator_fn(engine, target, api_key=None):
    print(f"[TRANSLATOR] Engine={engine} Target={target}", flush=True)
    engine = engine.lower()

    if engine == "google":
        from deep_translator import GoogleTranslator
        # Dùng 2 translator để fallback
        tr_primary = GoogleTranslator(source='zh-CN', target=target, timeout=15)

        def google_with_retry(text):
            # Cắt câu quá dài > 400 ký tự thành 2 phần
            if len(text) > 400:
                parts = [text[i:i+400] for i in range(0, len(text), 400)]
                return " ".join([google_with_retry(p) for p in parts])

            for attempt in range(3): # thử 3 lần
                try:
                    result = tr_primary.translate(text)
                    if not result or result.strip() == text.strip():
                        raise TranslationNotFound(text)
                    return result
                except TranslationNotFound:
                    print(f"[GOOGLE RETRY {attempt}] TranslationNotFound, thử lại...", flush=True)
                    import time; time.sleep(1)
                except Exception as e:
                    print(f"[GOOGLE RETRY {attempt}] {e}", flush=True)
                    import time; time.sleep(1)
            # Sau 3 lần vẫn lỗi -> ném lỗi để fallback
            raise TranslationNotFound(text)

        return google_with_retry

    elif engine == "qwen":
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        return lambda t: client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role":"user","content":f"Dịch tiếng Trung sang tiếng Việt, chỉ trả bản dịch, không giải thích: {t}"}],
            temperature=0.2
        ).choices[0].message.content.strip()

    elif engine == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        return lambda t: model.generate_content(f"Dịch sang tiếng Việt: {t}").text.strip()

    else:
        raise Exception(f"Unknown translator {engine}")

VOICE_DIR=os.path.join(os.path.dirname(__file__),"voices")
DEFAULT_FEMALE=os.path.join(VOICE_DIR,"my_voice_female.wav")
DEFAULT_MALE=os.path.join(VOICE_DIR,"my_voice_male.wav")
DEFAULT_VOICE=os.path.join(VOICE_DIR,"my_voice.wav")

async def ensure_default_voices():
    os.makedirs(VOICE_DIR, exist_ok=True)
    try:
        import edge_tts
        from ffmpeg_helper import get_ffmpeg_path
        # check ffmpeg available for edge-tts? edge-tts saves mp3 directly, no need ffmpeg
        if not os.path.exists(DEFAULT_FEMALE):
            comm=edge_tts.Communicate("Xin chào mọi người, chào mừng đến với kênh của mình.", "vi-VN-HoaiMyNeural")
            await comm.save(DEFAULT_FEMALE)
        if not os.path.exists(DEFAULT_MALE):
            comm=edge_tts.Communicate("Xin chào mọi người, chào mừng đến với kênh của mình.", "vi-VN-NamMinhNeural")
            await comm.save(DEFAULT_MALE)
        if not os.path.exists(DEFAULT_VOICE) and os.path.exists(DEFAULT_FEMALE):
            shutil.copy(DEFAULT_FEMALE, DEFAULT_VOICE)
    except Exception as e:
        print(e)
    return {"female": DEFAULT_FEMALE if os.path.exists(DEFAULT_FEMALE) else None, "male": DEFAULT_MALE if os.path.exists(DEFAULT_MALE) else None}

async def tts_edge(text, voice, out_path):
    import edge_tts
    comm=edge_tts.Communicate(text, voice)
    await comm.save(out_path)
    return out_path

async def tts_openai(text, voice, api_key, out_path):
    from openai import OpenAI
    client=OpenAI(api_key=api_key)
    resp=client.audio.speech.create(model="tts-1", voice=voice, input=text)
    resp.stream_to_file(out_path)
    return out_path

async def tts_coqui(text, speaker_wav_path, out_path, language="vi"):
    try:
        from TTS.api import TTS
    except ImportError:
        raise Exception("Chua cai coqui-tts")
    global _coqui_model
    try: _coqui_model
    except NameError: _coqui_model=None
    if _coqui_model is None:
        try:
            import torch
            device="cuda" if torch.cuda.is_available() else "mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu"
        except: device="cpu"
        _coqui_model=TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    if not os.path.exists(speaker_wav_path):
        speaker_wav_path=DEFAULT_FEMALE if os.path.exists(DEFAULT_FEMALE) else DEFAULT_VOICE
    _coqui_model.tts_to_file(text=text, file_path=out_path, speaker_wav=speaker_wav_path, language=language)
    return out_path

def detect_gender_from_video(video_path):
    try:
        import librosa
    except ImportError:
        return {"gender":"unknown","pitch":0}
    sample_wav=video_path.replace(".mp4","_gender_sample.wav")
    try:
        from ffmpeg_helper import get_ffmpeg_path
        ffmpeg_path=get_ffmpeg_path()
        subprocess.run([ffmpeg_path,"-y","-i",video_path,"-t","15","-ac","1","-ar","16000", sample_wav], capture_output=True)
        y, sr=librosa.load(sample_wav, sr=16000)
        f0, _, _=librosa.pyin(y, fmin=50, fmax=500, sr=sr)
        f0_clean=f0[~np.isnan(f0)]
        if len(f0_clean)==0:
            return {"gender":"unknown","pitch":0}
        mean_pitch=float(np.mean(f0_clean))
        gender="female" if mean_pitch>=160 else "male"
        return {"gender":gender,"pitch":round(mean_pitch,1)}
    except Exception as e:
        return {"gender":"unknown","pitch":0,"error":str(e)}
    finally:
        if os.path.exists(sample_wav):
            try: os.remove(sample_wav)
            except: pass

def get_tts_options():
    return {
        "engines": [
            {"id":"edge","label":"Edge TTS - Free","need_key":False},
            {"id":"openai","label":"OpenAI TTS","need_key":True},
            {"id":"coqui","label":"Coqui XTTS - Clone giọng","need_key":False},
            {"id":"piper","label":"Piper TTS - Offline, nhẹ","need_key":False},
        ],
        "voices": {
            "edge": [{"id":"vi-VN-HoaiMyNeural","label":"Hoài My - Nữ"},{"id":"vi-VN-NamMinhNeural","label":"Nam Minh - Nam"}],
            "openai": [{"id":"nova","label":"Nova - Nữ"},{"id":"onyx","label":"Onyx - Nam"}],
            "coqui": [{"id":"vi","label":"Tiếng Việt"}],
            "piper": [
                {"id":"vi_VN-vais1000-medium","label":"Vais1000 - Nữ (vi)"},
                {"id":"vi_VN-25hours-single-medium","label":"25hours - Nam (vi)"}
            ]
        }
    }

async def tts_piper(text, voice_model, out_path):
    # voice_model = vi_VN-vais1000-medium
    try:
        from piper import PiperVoice
    except ImportError:
        raise Exception("Chua cai piper-tts: pip install piper-tts")
    
    model_dir = os.path.join(VOICE_DIR, "piper", voice_model)
    onnx_path = os.path.join(model_dir, f"{voice_model}.onnx")
    json_path = os.path.join(model_dir, f"{voice_model}.onnx.json")
    
    if not os.path.exists(onnx_path):
        # Auto download model nếu chưa có
        os.makedirs(model_dir, exist_ok=True)
        # Tải từ HuggingFace rhasspy/piper-voices
        import requests
        base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/{voice_model.split('-')[-2]}/{voice_model.split('-')[-1]}"
        print(f"Downloading Piper model {voice_model}...")
        for f in [f"{voice_model}.onnx", f"{voice_model}.onnx.json"]:
            url = f"{base_url}/{f}"
            r = requests.get(url, stream=True)
            with open(os.path.join(model_dir, f), 'wb') as out:
                for chunk in r.iter_content(8192):
                    out.write(chunk)
    
    voice = PiperVoice.load(onnx_path)
    # Piper tạo wav
    wav_path = out_path.replace(".mp3", ".wav")
    with open(wav_path, "wb") as wav_file:
        for audio_bytes in voice.synthesize_stream_raw(text):
            wav_file.write(audio_bytes)
    
    # Convert wav -> mp3 bằng ffmpeg
    from ffmpeg_helper import get_ffmpeg_path
    ffmpeg_path = get_ffmpeg_path()
    subprocess.run([ffmpeg_path, "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-qscale:a", "2", out_path], check=False)
    if os.path.exists(wav_path):
        os.remove(wav_path)
    return out_path
