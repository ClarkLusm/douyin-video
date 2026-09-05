
import shutil, os, subprocess

def get_ffmpeg_path():
    # 1. Check system ffmpeg
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    # 2. Check imageio-ffmpeg
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(path):
            return path
    except:
        pass
    # 3. fallback
    return "ffmpeg"

def run_ffmpeg(cmd_list):
    # Replace "ffmpeg" with actual path
    ffmpeg_path = get_ffmpeg_path()
    if cmd_list[0] == "ffmpeg":
        cmd_list[0] = ffmpeg_path
    # Also handle ffprobe if needed
    if cmd_list[0] == "ffprobe":
        try:
            import imageio_ffmpeg
            ffprobe_path = imageio_ffmpeg.get_ffprobe_exe() if hasattr(imageio_ffmpeg, 'get_ffprobe_exe') else shutil.which("ffprobe")
            if ffprobe_path and os.path.exists(ffprobe_path):
                cmd_list[0] = ffprobe_path
        except:
            pass
    return subprocess.run(cmd_list, capture_output=True, text=True)

def check_ffmpeg():
    ffmpeg_path = get_ffmpeg_path()
    exists = os.path.exists(ffmpeg_path) or shutil.which(ffmpeg_path) is not None or shutil.which("ffmpeg") is not None
    # Try run version
    try:
        result = run_ffmpeg([ffmpeg_path, "-version"])
        version = result.stdout.split("\n")[0] if result.stdout else "unknown"
        return {"exists": True, "path": ffmpeg_path, "version": version}
    except Exception as e:
        return {"exists": False, "path": ffmpeg_path, "error": str(e)}
