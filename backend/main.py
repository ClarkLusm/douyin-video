from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import subprocess, os, uuid, shlex, shutil, json, traceback, re
import yt_dlp
from subtitle import video_to_subs, auto_model, get_ram, _translate_blocks, get_translator_fn, tts_edge, tts_openai, tts_coqui, tts_piper, get_tts_options, ensure_default_voices, detect_gender_from_video, DEFAULT_FEMALE, DEFAULT_MALE, DEFAULT_VOICE, VOICE_DIR
from ffmpeg_helper import get_ffmpeg_path, check_ffmpeg, run_ffmpeg
from pathlib import Path
from datetime import datetime

try:
    from youtube_uploader import upload_video as yt_upload, check_auth as yt_check_auth, save_client_secret_from_json
    YT_AVAILABLE=True
except:
    YT_AVAILABLE=False

app=FastAPI(title="Douyin v10.3 pip install ffmpeg")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
BASE_DIR=os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR=os.path.join(BASE_DIR,"downloads")
os.makedirs(DOWNLOAD_DIR,exist_ok=True)
os.makedirs(VOICE_DIR,exist_ok=True)
FRONTEND_DIR=os.path.join(os.path.dirname(BASE_DIR),"frontend")
META_FILE=os.path.join(VOICE_DIR,"voices.json")
CONFIG_FILE=os.path.join(BASE_DIR,"config.json")

DOWNLOADS_DIR = Path(DOWNLOAD_DIR)
DOWNLOADS_DIR.mkdir(exist_ok=True)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE,"r") as f: return json.load(f)
        except: return {}
    return {}
def save_config(cfg):
    with open(CONFIG_FILE,"w") as f: json.dump(cfg,f,indent=2)
def load_meta():
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except: return []
    return []
def save_meta(data):
    with open(META_FILE,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)

def extract_douyin_id(url):
    m = re.search(r'modal_id=(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/note/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'share/video/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'aweme_id=(\d+)', url)
    if m:
        return m.group(1)
    return None

def normalize_douyin_url(url):
    vid = extract_douyin_id(url)
    if vid:
        return f"https://www.douyin.com/video/{vid}", vid
    return url, None

def get_cookies_file():
    for name in ["douyin_cookies.txt", "cookies.txt", "www.douyin.com_cookies.txt"]:
        p=os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            return p
        p2=os.path.join(DOWNLOAD_DIR, name)
        if os.path.exists(p2):
            return p2
    return None

def dl_single_video(url, idx, job_dir=None):
    original_url = url.strip()
    norm_url, extracted_id = normalize_douyin_url(original_url)

    # Thư mục download = job_dir nếu có, không thì DOWNLOAD_DIR
    dl_dir = job_dir if job_dir else DOWNLOAD_DIR
    os.makedirs(dl_dir, exist_ok=True)

    tmpl=os.path.join(dl_dir,f"{idx:03d}.%(ext)s")
    final=os.path.join(dl_dir,f"{idx:03d}.mp4")
    if os.path.exists(final):
        try: os.remove(final)
        except: pass

    # Direct CDN link từ Network tab
    if norm_url.endswith('.mp4') or 'douyinvod.com' in norm_url or 'douyinpic.com' in norm_url or 'aweme/v1/play' in norm_url or 'v3-dy-o' in norm_url or original_url.endswith('.mp4'):
        try:
            dl_url = original_url if 'douyinvod' in original_url or original_url.endswith('.mp4') else norm_url
            r = requests.get(dl_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.douyin.com/'}, stream=True, timeout=30)
            r.raise_for_status()
            with open(final, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk: f.write(chunk)
            if os.path.exists(final) and os.path.getsize(final) > 1024:
                return {"success": True, "url": original_url, "idx": idx, "file": final, "error": None, "method": "direct-cdn"}
        except: pass

    cookies_file = get_cookies_file()
    ydl_opts={
        'outtmpl': tmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/best',
        'merge_output_format': 'mp4',
        'quiet': True, 'noplaylist': True, 'no_warnings': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'referer': 'https://www.douyin.com/',
        'headers': {'Referer': 'https://www.douyin.com/'},
    }
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts['cookiefile'] = cookies_file

    urls_to_try = [norm_url]
    if extracted_id:
        urls_to_try = [
            f"https://www.douyin.com/video/{extracted_id}",
            f"https://www.iesdouyin.com/share/video/{extracted_id}",
            f"https://www.douyin.com/note/{extracted_id}",
            original_url
        ]

    last_error = None
    for try_url in urls_to_try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([try_url.strip()])
            found = final if os.path.exists(final) else None
            if not found:
                for fn in os.listdir(dl_dir):
                    if fn.startswith(f"{idx:03d}.") and fn.endswith(".mp4"):
                        found=os.path.join(dl_dir, fn); break
            if found and os.path.exists(found):
                return {"success": True, "url": original_url, "idx": idx, "file": found, "error": None, "tried_url": try_url, "method": "yt-dlp"}
        except Exception as e:
            last_error = str(e)
            continue

    return {"success": False, "url": original_url, "idx": idx, "file": None, "error": last_error, "trace": traceback.format_exc()[-800:], "extracted_id": extracted_id}

def get_video_wh(fpath):
    try:
        ffprobe = get_ffmpeg_path().replace("ffmpeg", "ffprobe")
        cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-of", "json", fpath]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
        info = json.loads(out)
        w = int(info['streams'][0]['width'])
        h = int(info['streams'][0]['height'])
        return w, h
    except:
        return 1920, 1080

def normalize(files, job_dir=None):
    out=[]
    ffmpeg_path=get_ffmpeg_path()
    dl_dir = job_dir if job_dir else DOWNLOAD_DIR

    # 1. CHECK 1 LƯỢT LẤY MIN SCALE
    sizes = []
    for f in files:
        w, h = get_video_wh(f)
        sizes.append((w, h))
        print(f"[CHECK] {os.path.basename(f)}: {w}x{h}")

    # lấy video có diện tích nhỏ nhất làm chuẩn -> tránh upscale
    min_idx = min(range(len(sizes)), key=lambda i: sizes[i][0]*sizes[i][1])
    target_w, target_h = sizes[min_idx]
    target_w = (target_w // 2) * 2
    target_h = (target_h // 2) * 2
    print(f"[NORM] Target chung: {target_w}x{target_h} (lấy từ file nhỏ nhất)")

    # 2. NORMALIZE TẤT CẢ VỀ TARGET CHUNG
    for i, fpath in enumerate(files):
        base_name=os.path.basename(fpath)
        name_without_ext=os.path.splitext(base_name)[0]
        o=os.path.join(dl_dir, f"{name_without_ext}_norm.mp4")

        w, h = sizes[i]
        # nếu file này đã bằng target thì chỉ fix chẵn pixel, không scale
        if w == target_w and h == target_h:
            vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        else:
            # file to hơn -> hạ xuống target, file nhỏ hơn -> giữ nguyên + pad đen
            vf = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black"

        cmd=[ffmpeg_path,"-y","-i",fpath,"-vf",vf,"-c:v","libx264","-preset","fast","-crf","18","-c:a","aac","-r","30",o]
        subprocess.run(cmd, check=False)
        out.append(o if os.path.exists(o) else fpath)
    return out

def burn(video_path, srt_path):
    ffmpeg_path=get_ffmpeg_path()
    base=os.path.splitext(video_path)[0]
    lang=os.path.splitext(srt_path)[0].split(".")[-1]
    out=base+f".burned_{lang}.mp4"
    vf=f"subtitles={shlex.quote(srt_path)}:force_style='FontName=Arial,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,MarginV=60,Alignment=2'"
    cmd=[ffmpeg_path,"-y","-i",video_path,"-vf",vf,"-c:a","copy","-c:v","libx264","-preset","fast","-crf","23",out]
    r=subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out): raise Exception(r.stderr[-500:])
    return out

def dub_video(video_path, audio_path):
    ffmpeg_path=get_ffmpeg_path()
    out=os.path.splitext(video_path)[0]+".dubbed.mp4"
    cmd=[ffmpeg_path,"-y","-i",video_path,"-i",audio_path,"-c:v","copy","-map","0:v:0","-map","1:a:0","-shortest",out]
    subprocess.run(cmd, check=False)
    return out

def get_folder_info(folder_path: Path):
    files = list(folder_path.glob("*"))
    mp4_files = list(folder_path.glob("*.mp4"))
    srt_files = list(folder_path.glob("*.srt"))
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    return {
        "id": folder_path.name,
        "name": folder_path.name,
        "created": datetime.fromtimestamp(folder_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        "file_count": len(files),
        "total_size_mb": round(total_size / (1024*1024), 2),
        "total_size_str": f"{round(total_size/(1024*1024),1)} MB",
        "has_zh": any("zh.srt" in f.name for f in srt_files),
        "has_vi": any("vi.srt" in f.name for f in srt_files),
        "has_dubbed": any("dubbed" in f.name for f in mp4_files),
        "has_burned": any("burned" in f.name for f in mp4_files),
        "has_final": any("final" in f.name for f in mp4_files),
        "mp4_count": len(mp4_files),
        "srt_count": len(srt_files),
    }

@app.get("/api/system")
async def sysinfo():
    dv=await ensure_default_voices()
    meta=load_meta()
    cfg=load_config()
    yt_status=yt_check_auth() if YT_AVAILABLE else {"has_client_secret":False,"has_token":False,"ready":False}
    ffmpeg_info=check_ffmpeg()
    all_files=[f for f in os.listdir(VOICE_DIR) if f.endswith((".wav",".mp3"))] if os.path.exists(VOICE_DIR) else []
    return {
        "ram_gb": round(get_ram(),1),
        "auto_model": auto_model(),
        "tts_options": get_tts_options(),
        "default_voices": {"female": os.path.basename(DEFAULT_FEMALE) if os.path.exists(DEFAULT_FEMALE) else None, "male": os.path.basename(DEFAULT_MALE) if os.path.exists(DEFAULT_MALE) else None},
        "voice_library": meta,
        "all_files": all_files,
        "youtube": yt_status,
        "youtube_available": YT_AVAILABLE,
        "config": cfg,
        "youtube_auto_upload_enabled": cfg.get("youtube_auto_upload_enabled", False),
        "ffmpeg": ffmpeg_info
    }

@app.post("/api/config")
async def set_config(data: dict):
    cfg=load_config()
    if "youtube_auto_upload_enabled" in data:
        cfg["youtube_auto_upload_enabled"]=bool(data["youtube_auto_upload_enabled"])
    save_config(cfg)
    return cfg

@app.post("/api/youtube/save-client-secret")
async def save_client_secret(data: dict):
    if not YT_AVAILABLE:
        return {"error":"Chua cai google api"}
    try:
        content=data.get("json_content") or data
        if isinstance(content, str):
            json.loads(content)
            save_client_secret_from_json(content)
        else:
            secret_data={k:v for k,v in data.items() if k not in ["youtube_auto_upload_enabled"]}
            if "installed" in secret_data or "web" in secret_data:
                save_client_secret_from_json(secret_data)
            else:
                save_client_secret_from_json(content)
        return {"success": True, "status": yt_check_auth()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/upload-voice")
async def upload_voice(file: UploadFile = File(...), name: str = Form(""), gender: str = Form("female")):
    ext=os.path.splitext(file.filename)[1] or ".wav"
    uid=uuid.uuid4().hex[:6]
    safe_name=name.strip() if name.strip() else os.path.splitext(file.filename)[0]
    filename=f"{safe_name}_{uid}{ext}".replace(" ","_")
    path=os.path.join(VOICE_DIR, filename)
    with open(path,"wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    meta=load_meta()
    meta.append({"id": uid, "filename": filename, "display_name": safe_name, "gender": gender, "original": file.filename, "path": f"/voices/{filename}"})
    save_meta(meta)
    return {"filename": filename, "library": meta}

def safe_folder_name(name: str):
    name = name.strip()
    if not name:
        return None
    # bỏ ký tự cấm của Windows
    name = re.sub(r'[\\/:*?"<>|]+', '', name)
    name = re.sub(r'\s+', '_', name)
    return name[:80]

@app.post("/api/merge")
async def merge(data: dict):
    urls=[u.strip() for u in data.get("urls",[]) if u.strip()]
    model_name=data.get("model",None)
    translate_targets=data.get("translate_targets",["vi"])
    translator_engine=data.get("translator_engine","google")
    api_key=data.get("api_key",None)
    auto_gender=data.get("auto_gender", True)
    raw_title = data.get("title","").strip() # <-- LẤY TITLE TỪ FRONTEND

    if not urls:
        return {"error":"no urls", "download_results": []}

    # Tạo thư mục theo title, nếu không có title thì fallback uuid như cũ
    safe_title = safe_folder_name(raw_title)
    if safe_title:
        base_dir_name = safe_title
    else:
        base_dir_name = str(uuid.uuid4())[:8]

    # chống trùng folder
    job_id = base_dir_name
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    counter = 1
    while os.path.exists(job_dir):
        job_id = f"{base_dir_name}_{counter}"
        job_dir = os.path.join(DOWNLOAD_DIR, job_id)
        counter += 1

    os.makedirs(job_dir, exist_ok=True)
    print(f"[JOB {job_id}] Title: {raw_title} -> dir: {job_dir}")

    # lưu metadata để sau này up Youtube dùng luôn
    try:
        with open(os.path.join(job_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump({"title": raw_title, "safe_title": job_id, "urls": urls}, f, ensure_ascii=False, indent=2)
    except: pass

    download_results=[]
    successful_files=[]
    for i, url in enumerate(urls):
        res=dl_single_video(url, i, job_dir=job_dir)
        download_results.append(res)
        if res["success"]:
            successful_files.append(res["file"])

    failed=[r for r in download_results if not r["success"]]
    succeeded=[r for r in download_results if r["success"]]
    if len(failed) > 0:
        return {
            "error": f"Chi download duoc {len(succeeded)}/{len(urls)} video. Khong merge vi thieu video.",
            "download_results": download_results,
            "failed_count": len(failed), "succeeded_count": len(succeeded),
            "should_merge": False, "final_file": None,
            "job_id": job_id, "job_dir": f"/downloads/{job_id}/",
            "title": raw_title
        }

    norm=normalize(successful_files, job_dir=job_dir)
    list_path=os.path.join(job_dir,f"list_{job_id}.txt")
    with open(list_path,"w") as f:
        for nf in norm: f.write(f"file '{os.path.abspath(nf)}'\n")

    output=os.path.join(job_dir,f"final_{job_id}.mp4")
    ffmpeg_path=get_ffmpeg_path()
    subprocess.run([ffmpeg_path,"-y","-f","concat","-safe","0","-i",list_path,"-c","copy",output], check=False)

    try:
        if os.path.exists(list_path): os.remove(list_path)
    except: pass

    result={
        "job_id": job_id,
        "title": raw_title, # trả về để frontend hiển thị
        "job_dir": f"/downloads/{job_id}/",
        "job_dir_path": job_dir,
        "final_file":f"/downloads/{job_id}/final_{job_id}.mp4",
        "final_path": output,
        "download_results": download_results,
        "succeeded_count": len(succeeded),
        "should_merge": True,
        "files_in_job": os.listdir(job_dir)
    }

    if auto_gender:
        try:
            gender_info=detect_gender_from_video(output)
            result["detected_gender"]=gender_info
        except Exception as e:
            result["gender_error"]=str(e)

    try:
        srt_path,txt_path,_,used=video_to_subs(output, lang="zh", model_name=model_name)
        result["srt_zh"]=f"/downloads/{job_id}/{os.path.basename(srt_path)}"
        result["txt_zh"]=f"/downloads/{job_id}/{os.path.basename(txt_path)}"
        result["used_model"]=used
        result["translations"]={}
        for target in translate_targets:
            if target=="zh": continue
            try:
                fn=get_translator_fn(translator_engine, target, api_key=api_key)
                out_srt,out_txt=_translate_blocks(srt_path, fn, target)
                result["translations"][target]={"srt":f"/downloads/{job_id}/{os.path.basename(out_srt)}","txt":f"/downloads/{job_id}/{os.path.basename(out_txt)}","txt_path":out_txt,"engine":translator_engine}
            except Exception as e:
                import traceback
                result["translations"][target]={"error":str(e)}
        result["files_in_job"]=os.listdir(job_dir)
    except Exception as e:
        import traceback
        result["sub_error"]=str(e)

    return result

@app.post("/api/translate-srt")
async def api_translate_srt(data: dict):
    srt_file = data.get("srt_file")
    target = data.get("target", "vi")
    engine = data.get("engine", "google")
    api_key = data.get("api_key", None)
    job_id = data.get("job_id", None)

    if not srt_file:
        return {"error": "Thiếu srt_file"}

    # Tìm file thực tế
    # srt_file có thể là /downloads/xxx/file.srt hoặc /downloads/job_id/file.srt
    if job_id:
        real_path = os.path.join(DOWNLOAD_DIR, job_id, os.path.basename(srt_file))
    else:
        real_path = os.path.join(DOWNLOAD_DIR, os.path.basename(srt_file))
        # Thử tìm trong các job folder nếu không thấy ở root
        if not os.path.exists(real_path):
            for j in os.listdir(DOWNLOAD_DIR):
                candidate = os.path.join(DOWNLOAD_DIR, j, os.path.basename(srt_file))
                if os.path.exists(candidate):
                    real_path = candidate
                    job_id = j
                    break

    if not os.path.exists(real_path):
        return {"error": f"File not found: {real_path}"}

    print(f"[TRANSLATE-API] {real_path} -> {target} via {engine}, job={job_id}")

    try:
        # fn = get_translator_fn(engine, target, api_key=api_key)
        # out_srt, out_txt = _translate_blocks(real_path, fn, target)
        fn = get_translator_fn(translator_engine, target, api_key=api_key)
        out_srt, out_txt = _translate_blocks(srt_path, fn, target, fallback_engine="qwen", api_key=api_key)

        # Trả về đường dẫn đúng job_id
        if job_id:
            return {
                "success": True,
                "srt": f"/downloads/{job_id}/{os.path.basename(out_srt)}",
                "txt": f"/downloads/{job_id}/{os.path.basename(out_txt)}",
                "txt_path": out_txt,
                "engine": engine,
                "target": target
            }
        else:
            return {
                "success": True,
                "srt": f"/downloads/{os.path.basename(out_srt)}",
                "txt": f"/downloads/{os.path.basename(out_txt)}",
                "txt_path": out_txt,
                "engine": engine,
                "target": target
            }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "trace": traceback.format_exc()[-1000:]}

@app.post("/api/tts")
async def make_tts(data: dict):
    txt_file=data.get("txt_file")
    tts_engine=data.get("tts_engine","edge")
    voice=data.get("voice","vi-VN-HoaiMyNeural")
    api_key=data.get("tts_api_key",None)
    custom_voice_file=data.get("custom_voice_file",None)
    lang=data.get("tts_lang","vi")
    auto_voice=data.get("auto_voice_suggest",None)
    real_txt=os.path.join(DOWNLOAD_DIR, os.path.basename(txt_file))
    if not os.path.exists(real_txt): return {"error":"txt not found"}
    with open(real_txt,"r",encoding="utf-8") as f: text=f.read()
    if len(text)>4000: text=text[:4000]
    out_name=os.path.splitext(os.path.basename(real_txt))[0]+f".{tts_engine}_{voice}.mp3"
    out_path=os.path.join(DOWNLOAD_DIR,out_name)
    try:
        if tts_engine=="edge":
            await tts_edge(text, voice, out_path)
        elif tts_engine=="openai":
            if not api_key: return {"error":"Can OpenAI Key"}
            await tts_openai(text, voice, api_key, out_path)
        elif tts_engine=="coqui":
            if custom_voice_file:
                speaker_path=os.path.join(VOICE_DIR, os.path.basename(custom_voice_file))
            elif auto_voice:
                speaker_path=os.path.join(VOICE_DIR, os.path.basename(auto_voice))
            else:
                speaker_path=DEFAULT_FEMALE if os.path.exists(DEFAULT_FEMALE) else DEFAULT_VOICE
            if not os.path.exists(speaker_path):
                await ensure_default_voices()
            await tts_coqui(text, speaker_path, out_path, language=lang)
        elif tts_engine=="piper":
            await tts_piper(text, voice, out_path)
        else:
            return {"error":"Piper chua ho tro"}
        return {"audio": f"/downloads/{os.path.basename(out_path)}", "audio_path": out_path, "used_speaker": os.path.basename(custom_voice_file or auto_voice or DEFAULT_FEMALE)}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/burn")
async def api_burn(data: dict):
    vp=os.path.join(DOWNLOAD_DIR, os.path.basename(data.get("file","")))
    sp=os.path.join(DOWNLOAD_DIR, os.path.basename(data.get("srt_file","")))
    try:
        out=burn(vp, sp)
        return {"burned_file": f"/downloads/{os.path.basename(out)}", "burned_path": out}
    except Exception as e: return {"error":str(e)}

@app.post("/api/dub")
async def api_dub(data: dict):
    vp=os.path.join(DOWNLOAD_DIR, os.path.basename(data.get("file","")))
    ap=os.path.join(DOWNLOAD_DIR, os.path.basename(data.get("audio_file","")))
    try:
        out=dub_video(vp, ap)
        return {"dubbed_file": f"/downloads/{os.path.basename(out)}", "dubbed_path": out}
    except Exception as e: return {"error":str(e)}

@app.post("/api/youtube/upload")
async def api_youtube_upload(data: dict):
    video_file=data.get("file")
    title=data.get("title","Douyin Auto Dubbed")
    description=data.get("description","")
    tags=data.get("tags",["douyin"])
    privacy=data.get("privacy","private")
    if not video_file:
        return {"error":"Thieu file"}
    vp=os.path.join(DOWNLOAD_DIR, os.path.basename(video_file))
    if not os.path.exists(vp):
        return {"error": f"File not found {vp}"}
    if not YT_AVAILABLE:
        return {"error":"Chua cai google api"}
    try:
        result=yt_upload(vp, title, description, tags, privacy)
        return {"success": True, "youtube_url": result["url"], "video_id": result["video_id"], "privacy": privacy}
    except Exception as e:
        return {"error": str(e)}

@app.get("/")
async def fe():
    idx=os.path.join(FRONTEND_DIR,"index.html")
    if os.path.exists(idx): return FileResponse(idx)
    return {"ok":True}

@app.get("/api/videos/list")
async def list_videos():
    if not DOWNLOADS_DIR.exists():
        return {"folders": []}
    folders = [get_folder_info(p) for p in DOWNLOADS_DIR.iterdir() if p.is_dir()]
    folders.sort(key=lambda x: x["created"], reverse=True)
    return {"folders": folders, "total": len(folders)}

@app.get("/api/videos/{folder_id}")
async def get_video_detail(folder_id: str):
    folder_path = DOWNLOADS_DIR / folder_id
    if not folder_path.exists():
        return {"error": "Folder not found"}
    files = []
    for f in folder_path.iterdir():
        if f.is_file():
            files.append({
                "name": f.name,
                "size_mb": round(f.stat().st_size / (1024*1024), 2),
                "ext": f.suffix,
                "is_video": f.suffix == ".mp4",
                "is_srt": f.suffix == ".srt",
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            })
    files.sort(key=lambda x: (0 if x["is_video"] else 1, x["name"]))
    info = get_folder_info(folder_path)
    info["files"] = files
    return info

@app.delete("/api/videos/{folder_id}")
async def delete_video_folder(folder_id: str):
    folder_path = DOWNLOADS_DIR / folder_id
    if not folder_path.exists():
        return {"success": False, "error": "Not found"}
    shutil.rmtree(folder_path)
    return {"success": True}

app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")
app.mount("/voices", StaticFiles(directory=VOICE_DIR), name="voices")
if __name__=="__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=8000)
