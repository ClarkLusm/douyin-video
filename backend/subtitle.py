
from faster_whisper import WhisperModel
import os, psutil, subprocess, shutil
import numpy as np

_model=None; _current=None
def get_ram(): 
    try: return psutil.virtual_memory().total/(1024**3)
    except: return 8
def auto_model(): return "medium" if get_ram()>=16 else "small"
def get_model(name=None):
    global _model,_current
    target=name if name else auto_model()
    if _model is None or _current!=target:
        _model=WhisperModel(target, device="cpu", compute_type="int8")
        _current=target
    return _model,target
def fmt(s): 
    h=int(s//3600); m=int((s%3600)//60); sec=int(s%60); ms=int((s-int(s))*1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
def video_to_subs(vid, lang="zh", model_name=None):
    model,used=get_model(model_name)
    lp=None if lang=="auto" else lang
    segs,info=model.transcribe(vid, language=lp, beam_size=5, vad_filter=True)
    base=os.path.splitext(vid)[0]
    srt=base+f".{used}.zh.srt"; txt=base+f".{used}.zh.txt"; full=""
    with open(srt,"w",encoding="utf-8") as sf:
        for i,seg in enumerate(segs,1):
            full+=seg.text+" "
            sf.write(f"{i}\n{fmt(seg.start)} --> {fmt(seg.end)}\n{seg.text.strip()}\n\n")
    with open(txt,"w",encoding="utf-8") as f: f.write(full.strip())
    return srt,txt,info.language,used
def _translate_blocks(srt_path, fn, target):
    print(f"[TRANSLATE] Translating {srt_path} -> {target} using {fn}")
    base=os.path.splitext(srt_path)[0].replace(".zh","")
    out_srt=base+f".{target}.srt"; out_txt=base+f".{target}.txt"
    try:
        with open(srt_path,"r",encoding="utf-8") as f: content=f.read()
    except Exception as e:
        print(f"[TRANSLATE ERROR] Cannot read {srt_path}: {e}")
        raise

    blocks=[b for b in content.strip().split("\n\n") if b.strip()]
    print(f"[TRANSLATE] Found {len(blocks)} blocks to translate")
    out=[]; full=""
    for idx, b in enumerate(blocks):
        lines=b.split("\n")
        if len(lines)>=3:
            src=" ".join(lines[2:]).strip()
            if not src: continue
            try:
                tr=fn(src)
                print(f"[TRANSLATE {idx}] {src[:30]}... -> {tr[:30]}...")
            except Exception as e:
                print(f"[TRANSLATE ERROR block {idx}] {e}")
                import traceback; traceback.print_exc()
                tr=src
            out.append(f"{lines[0]}\n{lines[1]}\n{tr}\n")
            full+=tr+" "

    with open(out_srt,"w",encoding="utf-8") as f: f.write("\n".join(out))
    with open(out_txt,"w",encoding="utf-8") as f: f.write(full.strip())
    print(f"[TRANSLATE] Done -> {out_srt}, {out_txt}")
    return out_srt,out_txt

def get_translator_fn(engine, target, api_key=None):
    print(f"[TRANSLATOR] Engine={engine}, Target={target}, HasKey={bool(api_key)}")
    engine=engine.lower()
    if engine=="google":
        try:
            from deep_translator import GoogleTranslator
            tr=GoogleTranslator(source='zh-CN', target=target)
            print(f"[TRANSLATOR] GoogleTranslator created zh-CN->{target}")
            return lambda t: tr.translate(t)
        except Exception as e:
            print(f"[TRANSLATOR ERROR Google] {e}")
            import traceback; traceback.print_exc()
            raise
    elif engine=="deepl":
        import deepl
        if not api_key:
            raise Exception("Can DeepL API Key")
        tr=deepl.Translator(api_key)
        return lambda t: tr.translate_text(t, source_lang="ZH", target_lang=target.upper()).text
    elif engine=="gemini":
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model=genai.GenerativeModel("gemini-1.5-flash")
        ln="Tiếng Việt" if target=="vi" else "English"
        return lambda t: model.generate_content(f"Dịch tiếng Trung sang {ln}. Chỉ trả bản dịch: \n{t}").text.strip()
    elif engine=="gpt":
        from openai import OpenAI
        if not api_key:
            raise Exception("Can OpenAI API Key")
        client=OpenAI(api_key=api_key)
        ln="Tiếng Việt" if target=="vi" else "English"
        return lambda t: client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":f"Dịch sang {ln}, chỉ trả bản dịch: {t}"}], temperature=0.3).choices[0].message.content.strip()
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
