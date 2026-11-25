# TikTok Downloader

Tool tải video TikTok có giao diện cho **Windows 10/11**: dán link, xem trước, chọn độ phân giải / dung lượng rồi tải về. Bản portable chạy ngay, **không cần cài Python**.

## Tính năng

- Nhận link dài và link rút gọn (`vt.tiktok.com`, `vm.tiktok.com`)
- Xem trước: ảnh bìa, tiêu đề, tác giả, thời lượng, lượt xem + nút **Phát thử**
- Bảng chất lượng: độ phân giải, dung lượng, bitrate, codec
- Tải bản đang chọn, hoặc **tự chọn bản nét nhất ≤ N MB**
- Mặc định chỉ hiện bản **H.264** (Windows phát được ngay). Video chỉ có HEVC/H.265 sẽ được **tự chuyển sang H.264** bằng ffmpeg đi kèm
- Thanh tiến trình, tốc độ tải, nút huỷ

## Tải về & sử dụng

1. Vào [**Releases**](../../releases) → tải `TikTokDownloader_Portable.zip`
2. Giải nén cả thư mục → nhấp đúp `TikTokDownloader.exe`
3. Nếu Windows SmartScreen cảnh báo: **More info → Run anyway** (exe chưa ký số)

Khi TikTok đổi API khiến tải lỗi, chạy `Cap nhat yt-dlp.bat` trong thư mục portable.

## Chạy từ source

Cần Python 3.10+:

```bat
run_from_source.bat
```

hoặc thủ công:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python src\app.py
```

## Build bản portable

**Tự động (GitHub Actions):** push một tag dạng `v*`, workflow sẽ build và gắn file zip vào Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Hoặc vào tab **Actions → Build portable → Run workflow** để lấy file ở mục Artifacts.

**Thủ công (Linux / WSL):**

```bash
sudo apt install gcc-mingw-w64-x86-64 zip
./scripts/build_portable.sh      # -> dist/TikTokDownloader_Portable.zip
```

Script tải [python-build-standalone](https://github.com/astral-sh/python-build-standalone) (Python cho Windows có sẵn tkinter), cài thư viện bản `win_amd64` vào trong đó và build một launcher `.exe` nhỏ viết bằng C.

## Cấu trúc

```
src/app.py                 Giao diện Tkinter + logic tải (yt-dlp)
src/icon.ico               Icon
launcher/launcher.c        Launcher .exe: chạy python\pythonw.exe app\app.py
scripts/build_portable.sh  Script đóng gói bản portable
.github/workflows/         CI build + release
```

## Công nghệ

[yt-dlp](https://github.com/yt-dlp/yt-dlp) · [curl_cffi](https://github.com/lexiforest/curl_cffi) · [Pillow](https://python-pillow.org) · [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) · Tkinter

## Lưu ý

Chỉ tải video bạn sở hữu hoặc được phép sử dụng, và tuân thủ [Điều khoản dịch vụ của TikTok](https://www.tiktok.com/legal/terms-of-service). Dự án không liên kết với TikTok/ByteDance.

## License

[MIT](LICENSE)
