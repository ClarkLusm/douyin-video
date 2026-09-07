# Douyin Video Merger v10.2

Tool tự động: Download Douyin -> Merge -> Detect Nam/Nữ -> TTS -> Dub giọng -> Upload YouTube

## Tính năng v10.2

- ✅ Download từng video, log lỗi từng video, KHÔNG merge nếu thiếu video
- ✅ Luôn có 2 giọng mặc định Nam (Nam Minh) / Nữ (Hoài My) tự tạo từ Edge TTS
- ✅ Auto detect giới tính video gốc bằng pitch (librosa) -> tự chọn giọng nam/nữ tương ứng
- ✅ Thư viện giọng: upload nhiều lần, tag nam/nữ, set mặc định, nghe thử, xóa
- ✅ TTS 3 options: Edge Free (mặc định), OpenAI, Coqui XTTS
- ✅ 3 video player: Final Merged / Burned (có sub) / Dubbed (đã thay giọng - video này mới upload YouTube)
- ✅ YouTube auto upload TẮT mặc định, bật khi luồng chạy ngon. Nhập client_secret.json từ frontend
- ✅ Upload video đã dub giọng lên YouTube (không phải video gốc)

## Cài đặt (chạy 1 lần duy nhất)

### 1. Yêu cầu
- Python 3.9+ 
- ffmpeg (bắt buộc)

Cài ffmpeg:
- Mac: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`
- Windows: tải từ ffmpeg.org, add vào PATH

### 2. Giải nén
```bash
unzip -o douyin-video-v10.2.zip -d .
cd douyin-video
# Hoặc nếu bạn giải nén ra thư mục douyin-video/
cd backendz

py -3.11 -m venv venv

source venv/Scripts/activate
```

### 3. Cài thư viện
```bash
pip install -r requirements.txt

# Nếu thiếu, cài thêm:
pip install faster-whisper yt-dlp fastapi uvicorn python-multipart edge-tts deep-translator librosa soundfile google-api-python-client google-auth-oauthlib google-auth torch torchaudio

# Nếu dùng Coqui XTTS (optional, nặng ~2GB):
pip install coqui-tts
```

### 4. Chạy server
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload --workers 2
```
Hoặc:
```bash
python main.py
```

### 5. Mở frontend
Mở browser: http://localhost:8000

Bạn sẽ thấy giao diện với 3 cột.

## Cách dùng

### Bước 1: Paste link Douyin
- Mỗi dòng 1 link Douyin
- Lưu ý: Link Douyin hết hạn sau 1-2h. Nếu báo lỗi "Link không hỗ trợ hoặc hết hạn", hãy lấy link mới

### Bước 2: Bấm "Download từng video + Merge chỉ khi đủ full list"
- Tool sẽ download từng video riêng biệt
- Hiện log chi tiết:
  - ✅ Video 1 OK
  - ❌ Video 2 LỖI: ...
- Nếu thiếu 1 video -> DỪNG, KHÔNG MERGE, báo lỗi video nào
- Nếu đủ full list -> Merge -> Detect giới tính -> Tạo sub

### Bước 3: Xem 3 video player
- 1. Video Final (merged)
- 2. Video Burned (sau khi bấm Burn sub)
- 3. Video Dubbed (sau khi bấm Ghép Voice -> đây là video sẽ upload YouTube)

### Bước 4: TTS + Dub
- Chọn TXT tiếng Việt
- Chọn TTS Engine:
  - Edge TTS (Free, mặc định, hay nhất)
  - Coqui XTTS: tự động chọn giọng nam/nữ theo video gốc
- Bấm "Tạo Voice"
- Bấm "Ghép Voice -> Video Dubbed"

### Bước 5: YouTube (tùy chọn)
#### Nhập client_secret.json từ frontend:
1. Tạo Google Cloud Project:
   - Vào console.cloud.google.com
   - New Project
   - APIs & Services -> Enable APIs -> YouTube Data API v3 -> Enable
   - Credentials -> Create Credentials -> OAuth Client ID -> Desktop App
   - Download JSON

2. Paste JSON vào ô "Paste client_secret.json" trong frontend -> Bấm "Lưu client_secret.json"

3. Upload:
   - Nhập Title (tự điền từ transcript)
   - Chọn Privacy: private (khuyên dùng) / unlisted / public
   - Bấm "Upload video đã dub lên YouTube ngay"
   - Lần đầu sẽ mở browser đăng nhập Google -> cho phép -> lưu token.json
   - Trả về link youtube.com/watch?v=...

#### Bật auto upload (TẮT mặc định):
- Toggle "Bật tự động upload sau khi dub (TẮT mặc định)"
- Khi BẬT: sau khi dub xong tự upload luôn
- Khi TẮT: phải bấm tay nút Upload

## Cấu trúc thư mục

```
douyin-video/
  backend/
    main.py
    subtitle.py
    youtube_uploader.py
    requirements.txt
    voices/
      my_voice_female.wav (tự tạo Hoài My)
      my_voice_male.wav (tự tạo Nam Minh)
      my_voice.wav (alias)
      voices.json (thư viện giọng upload)
    downloads/ (video tải về, sub, audio)
    client_secret.json (bạn paste từ frontend sẽ tạo file này)
    token.json (tự tạo sau khi login Google lần đầu)
    config.json (lưu trạng thái auto upload ON/OFF)
  frontend/
    index.html
```

## Lỗi thường gặp

1. "Link không hỗ trợ hoặc hết hạn":
   - Link Douyin hết hạn sau 1-2h. Lấy link mới từ Douyin app/website

2. "Chưa cài librosa / ffmpeg":
   - `pip install librosa soundfile`
   - `brew install ffmpeg` hoặc `apt install ffmpeg`

3. YouTube "Chưa có client_secret.json":
   - Paste JSON vào ô trong frontend -> Lưu

4. Coqui TTS chậm / lỗi VRAM:
   - Dùng Edge TTS mặc định, nhanh và hay nhất
   - Coqui chỉ khi cần clone giọng

## Git

```bash
git add .
git commit -m "feat: v10.2 no merge if fail + per video error log"
git push
```

## Liên hệ / Góp ý

Nếu cần thêm tính năng, báo mình build tiếp.
