"""
TikTok Downloader - GUI cho Windows 11
- Nhập link TikTok (link dài hoặc link rút gọn vt.tiktok.com / vm.tiktok.com)
- Xem trước: ảnh bìa, tiêu đề, tác giả, thời lượng + phát thử bản nhẹ nhất
- Chọn độ phân giải / dung lượng cụ thể, hoặc tự chọn bản tốt nhất dưới N MB
"""
import os
import sys
import queue
import tempfile
import threading
import subprocess
import io

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

import yt_dlp

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

APP_TITLE = "TikTok Downloader"
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "TikTok")
PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "tiktok_dl_preview")


# ---------------------------------------------------------------- helpers
def human_size(n):
    if not n:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(sec):
    if not sec:
        return "?"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def estimate_size(fmt, duration):
    """Dung lượng thật nếu có, không thì ước lượng từ bitrate."""
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if not size and fmt.get("tbr") and duration:
        size = fmt["tbr"] * 1000 / 8 * duration
    return size


def open_file(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


HEVC_TAGS = ("h265", "hevc", "hvc1", "hev1", "bytevc1", "bvc1")


def is_hevc(fmt):
    v = (fmt.get("vcodec") or "").lower()
    note = (fmt.get("format_id") or "").lower()
    return any(t in v for t in HEVC_TAGS) or "bytevc1" in note or "h265" in note


def codec_label(fmt):
    if is_hevc(fmt):
        return "H.265 ⚠"
    v = (fmt.get("vcodec") or "").lower()
    if v.startswith(("avc", "h264")) or v == "":
        return "H.264"
    return v.split(".")[0] or "?"


def find_ffmpeg():
    """ffmpeg đi kèm imageio-ffmpeg (pip), hoặc ffmpeg có trong PATH."""
    if imageio_ffmpeg:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    from shutil import which
    return which("ffmpeg")


NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x640")
        self.minsize(780, 560)

        self.info = None            # info dict của video hiện tại
        self.all_formats = []       # mọi format video (đã sắp xếp)
        self.formats = []           # format đang hiện trong bảng
        self.proc = None            # tiến trình ffmpeg đang chạy
        self.thumb_img = None
        self.busy = False
        self.cancel_flag = threading.Event()
        self.ui_queue = queue.Queue()

        self.url_var = tk.StringVar()
        self.dir_var = tk.StringVar(value=DEFAULT_DIR)
        self.mode_var = tk.StringVar(value="pick")   # pick | maxsize
        self.maxsize_var = tk.StringVar(value="10")
        self.h264_only_var = tk.BooleanVar(value=True)
        self.convert_var = tk.BooleanVar(value=True)
        self.ffmpeg = find_ffmpeg()
        self.status_var = tk.StringVar(value="Dán link TikTok rồi bấm 'Lấy thông tin'.")

        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon):
            try:
                self.iconbitmap(icon)
            except Exception:
                pass
        self._style()
        self._build()
        self.after(50, self._drain_queue)

    # ---------------- UI
    def _style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build(self):
        pad = dict(padx=10, pady=6)

        # --- URL row
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Link TikTok:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.url_var, font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda e: self.fetch_info())
        ttk.Button(top, text="Dán", width=6, command=self.paste).pack(side="left")
        self.btn_fetch = ttk.Button(top, text="Lấy thông tin", style="Accent.TButton",
                                    command=self.fetch_info)
        self.btn_fetch.pack(side="left", padx=(6, 0))

        # --- middle: preview (left) + formats (right)
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)

        left = ttk.LabelFrame(mid, text=" Xem trước ")
        left.pack(side="left", fill="y", padx=(0, 8))
        self.thumb_lbl = tk.Label(left, text="(chưa có video)", width=30, height=18,
                                  bg="#1e1e1e", fg="#aaaaaa")
        self.thumb_lbl.pack(padx=8, pady=8)
        self.title_lbl = ttk.Label(left, text="", wraplength=240, justify="left",
                                   style="Title.TLabel")
        self.title_lbl.pack(fill="x", padx=8)
        self.meta_lbl = ttk.Label(left, text="", wraplength=240, justify="left")
        self.meta_lbl.pack(fill="x", padx=8, pady=(4, 8))
        self.btn_preview = ttk.Button(left, text="▶ Phát thử", command=self.preview,
                                      state="disabled")
        self.btn_preview.pack(fill="x", padx=8, pady=(0, 8))

        right = ttk.LabelFrame(mid, text=" Chất lượng / Dung lượng ")
        right.pack(side="left", fill="both", expand=True)

        cols = ("res", "size", "bitrate", "codec", "note")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", selectmode="browse")
        heads = {"res": ("Độ phân giải", 110), "size": ("Dung lượng", 100),
                 "bitrate": ("Bitrate", 90), "codec": ("Codec", 80), "note": ("Ghi chú", 160)}
        for c, (t, w) in heads.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center" if c != "note" else "w")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="left", fill="y", pady=8, padx=(0, 8))
        self.tree.bind("<Double-1>", lambda e: self.download())

        # --- options
        opt = ttk.LabelFrame(self, text=" Tuỳ chọn tải ")
        opt.pack(fill="x", **pad)

        r1 = ttk.Frame(opt)
        r1.pack(fill="x", padx=8, pady=4)
        ttk.Radiobutton(r1, text="Tải bản đang chọn trong bảng", value="pick",
                        variable=self.mode_var).pack(side="left")
        ttk.Radiobutton(r1, text="Tự chọn bản nét nhất có dung lượng ≤", value="maxsize",
                        variable=self.mode_var).pack(side="left", padx=(20, 4))
        ttk.Spinbox(r1, from_=1, to=500, width=6, textvariable=self.maxsize_var).pack(side="left")
        ttk.Label(r1, text="MB").pack(side="left", padx=4)

        r3 = ttk.Frame(opt)
        r3.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(r3, text="Chỉ hiện bản H.264 (Win 11 phát được ngay)",
                        variable=self.h264_only_var,
                        command=self.refresh_table).pack(side="left")
        ff_txt = "Tự chuyển HEVC → H.264 sau khi tải"
        if not self.ffmpeg:
            ff_txt += " (không tìm thấy ffmpeg)"
        ttk.Checkbutton(r3, text=ff_txt, variable=self.convert_var,
                        state="normal" if self.ffmpeg else "disabled").pack(side="left", padx=(20, 0))

        r2 = ttk.Frame(opt)
        r2.pack(fill="x", padx=8, pady=4)
        ttk.Label(r2, text="Lưu vào:").pack(side="left")
        ttk.Entry(r2, textvariable=self.dir_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r2, text="Chọn...", command=self.choose_dir).pack(side="left")
        ttk.Button(r2, text="Mở thư mục", command=self.open_dir).pack(side="left", padx=(6, 0))

        # --- bottom: progress + buttons
        bot = ttk.Frame(self)
        bot.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(bot, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        row = ttk.Frame(bot)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.btn_cancel = ttk.Button(row, text="Huỷ", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="right")
        self.btn_dl = ttk.Button(row, text="⬇ Tải về", style="Accent.TButton",
                                 command=self.download, state="disabled")
        self.btn_dl.pack(side="right", padx=6)

    # ---------------- thread -> UI
    def ui(self, fn, *args):
        self.ui_queue.put((fn, args))

    def _drain_queue(self):
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(50, self._drain_queue)

    def set_busy(self, busy, can_cancel=False):
        self.busy = busy
        st = "disabled" if busy else "normal"
        self.btn_fetch.config(state=st)
        has_info = "normal" if (self.info and not busy) else "disabled"
        self.btn_dl.config(state=has_info)
        self.btn_preview.config(state=has_info)
        self.btn_cancel.config(state="normal" if (busy and can_cancel) else "disabled")
        self.config(cursor="watch" if busy and not can_cancel else "")

    # ---------------- actions
    def paste(self):
        try:
            self.url_var.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or DEFAULT_DIR)
        if d:
            self.dir_var.set(d)

    def open_dir(self):
        d = self.dir_var.get()
        os.makedirs(d, exist_ok=True)
        open_file(d)

    def cancel(self):
        self.cancel_flag.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.status_var.set("Đang huỷ...")

    def base_opts(self):
        return {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "windowsfilenames": True,
        }

    # ---- fetch info
    def fetch_info(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning(APP_TITLE, "Bạn chưa nhập link TikTok.")
            return
        if "tiktok.com" not in url:
            if not messagebox.askyesno(APP_TITLE, "Link không giống link TikTok. Vẫn thử?"):
                return
        self.set_busy(True)
        self.status_var.set("Đang lấy thông tin video...")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def _fetch_worker(self, url):
        try:
            with yt_dlp.YoutubeDL(self.base_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get("_type") == "playlist" and info.get("entries"):
                    info = info["entries"][0]
                thumb = None
                turl = info.get("thumbnail")
                if turl and Image:
                    try:
                        thumb = ydl.urlopen(turl).read()
                    except Exception:
                        thumb = None
            self.ui(self._on_info, info, thumb)
        except Exception as e:
            self.ui(self._on_error, "Không lấy được thông tin video", e)

    def _on_info(self, info, thumb_bytes):
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.info = info
        duration = info.get("duration")

        # lọc format có hình (TikTok là mp4 có sẵn tiếng, không cần ffmpeg)
        fmts = []
        for f in info.get("formats", []):
            if f.get("vcodec") in (None, "none"):
                continue
            if f.get("protocol", "").startswith("m3u8"):
                continue
            f = dict(f)
            f["_size"] = estimate_size(f, duration)
            fmts.append(f)
        fmts.sort(key=lambda f: ((f.get("height") or 0), (f.get("_size") or 0)), reverse=True)
        self.all_formats = fmts
        self.refresh_table()
        self._fill_meta(info, thumb_bytes)

    def refresh_table(self):
        fmts = self.all_formats
        self.table_note = ""
        if self.h264_only_var.get():
            h264 = [f for f in fmts if not is_hevc(f)]
            if h264:
                fmts = h264
            elif fmts:
                self.table_note = ("Video này chỉ có bản HEVC (H.265). "
                                   "Bật 'Tự chuyển HEVC → H.264' để xem được trên Win 11.")
        self.formats = fmts

        self.tree.delete(*self.tree.get_children())
        for i, f in enumerate(fmts):
            w, h = f.get("width"), f.get("height")
            res = f"{w}x{h}" if w and h else (f"{h}p" if h else "?")
            size = human_size(f["_size"])
            if f["_size"] and not f.get("filesize"):
                size = "~" + size
            br = f"{int(f['tbr'])} kbps" if f.get("tbr") else "?"
            codec = codec_label(f)
            note = f.get("format_note") or f.get("format_id") or ""
            self.tree.insert("", "end", iid=str(i), values=(res, size, br, codec, note))
        if fmts:
            self.tree.selection_set("0")
            self.tree.focus("0")
        if self.info and not self.busy:
            self.status_var.set(self.table_note or
                                "Chọn chất lượng rồi bấm 'Tải về' (hoặc nhấp đúp vào dòng).")

    def _fill_meta(self, info, thumb_bytes):
        duration = info.get("duration")
        fmts = self.all_formats
        self.title_lbl.config(text=(info.get("title") or info.get("description") or "")[:150])
        meta = [
            f"Tác giả: {info.get('uploader') or info.get('creator') or '?'}",
            f"Thời lượng: {human_time(duration)}",
            f"Lượt xem: {info.get('view_count', '?'):,}" if isinstance(info.get("view_count"), int) else "",
            f"Số bản chất lượng: {len(fmts)}",
        ]
        self.meta_lbl.config(text="\n".join(m for m in meta if m))

        if thumb_bytes and Image:
            try:
                img = Image.open(io.BytesIO(thumb_bytes))
                img.thumbnail((240, 360))
                self.thumb_img = ImageTk.PhotoImage(img)
                self.thumb_lbl.config(image=self.thumb_img, text="", width=img.width,
                                      height=img.height)
            except Exception:
                self.thumb_lbl.config(image="", text="(không tải được ảnh bìa)")
        else:
            self.thumb_lbl.config(image="", text="(không có ảnh bìa)")

        self.set_busy(False)
        if not fmts:
            self.status_var.set("Không tìm thấy bản video nào (có thể là bài đăng ảnh).")
        else:
            self.refresh_table()

    # ---- choose format
    def selected_format(self):
        if not self.formats:
            return None
        if self.mode_var.get() == "maxsize":
            try:
                limit = float(self.maxsize_var.get()) * 1024 * 1024
            except ValueError:
                messagebox.showwarning(APP_TITLE, "Dung lượng tối đa không hợp lệ.")
                return None
            ok = [f for f in self.formats if f["_size"] and f["_size"] <= limit]
            if not ok:
                smallest = min(self.formats, key=lambda f: f["_size"] or float("inf"))
                if messagebox.askyesno(
                        APP_TITLE,
                        f"Không có bản nào ≤ {self.maxsize_var.get()} MB.\n"
                        f"Tải bản nhỏ nhất ({human_size(smallest['_size'])})?"):
                    return smallest
                return None
            # nét nhất, cùng độ nét thì lấy bản to nhất (bitrate cao hơn)
            return max(ok, key=lambda f: ((f.get("height") or 0), f["_size"]))
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Hãy chọn một dòng trong bảng chất lượng.")
            return None
        return self.formats[int(sel[0])]

    # ---- download
    def download(self):
        if self.busy or not self.info:
            return
        fmt = self.selected_format()
        if not fmt:
            return
        outdir = self.dir_var.get().strip() or DEFAULT_DIR
        os.makedirs(outdir, exist_ok=True)
        tmpl = os.path.join(outdir, "%(uploader).40s_%(id)s_" + f"{fmt.get('height') or 'video'}p.%(ext)s")
        self._start_download(fmt, tmpl, open_after=False)

    def preview(self):
        if self.busy or not self.formats:
            return
        pool = [f for f in self.all_formats if not is_hevc(f)] or self.all_formats
        smallest = min(pool, key=lambda f: f["_size"] or float("inf"))
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        tmpl = os.path.join(PREVIEW_DIR, "%(id)s_preview.%(ext)s")
        self._start_download(smallest, tmpl, open_after=True)

    def _start_download(self, fmt, tmpl, open_after):
        self.cancel_flag.clear()
        self.set_busy(True, can_cancel=True)
        self.progress.config(mode="determinate", value=0)
        label = "bản xem trước" if open_after else f"{fmt.get('height')}p"
        self.status_var.set(f"Đang tải {label}...")
        url = self.info.get("webpage_url") or self.url_var.get().strip()
        threading.Thread(target=self._dl_worker, args=(url, fmt, tmpl, open_after),
                         daemon=True).start()

    def _dl_worker(self, url, fmt, tmpl, open_after):
        result = {}

        def hook(d):
            if self.cancel_flag.is_set():
                raise Cancelled()
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or fmt.get("_size")
                done = d.get("downloaded_bytes", 0)
                pct = done / total * 100 if total else 0
                speed = d.get("speed")
                txt = f"Đang tải: {human_size(done)} / {human_size(total)}"
                if speed:
                    txt += f"  •  {human_size(speed)}/s"
                self.ui(self._on_progress, pct, txt)
            elif d["status"] == "finished":
                result["file"] = d.get("filename")

        opts = self.base_opts()
        opts.update({
            "format": fmt["format_id"],
            "outtmpl": tmpl,
            "progress_hooks": [hook],
            "overwrites": not open_after,
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = result.get("file") or ydl.prepare_filename(info)
            if is_hevc(fmt) and self.convert_var.get() and self.ffmpeg:
                path = self._convert_to_h264(path, info.get("duration"), fast=open_after)
            self.ui(self._on_done, path, open_after)
        except Exception as e:
            if self.cancel_flag.is_set() or isinstance(e, Cancelled) or "Cancelled" in repr(e):
                self.ui(self._on_cancelled)
            else:
                self.ui(self._on_error, "Tải video thất bại", e)

    def _convert_to_h264(self, src, duration, fast=False):
        """Chuyển HEVC -> H.264 (giữ nguyên tiếng). Trả về đường dẫn file mới."""
        root, _ = os.path.splitext(src)
        dst = root.replace("_preview", "_preview_h264") if fast else root + "_h264"
        dst += ".mp4"
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-i", src,
               "-c:v", "libx264", "-preset", "ultrafast" if fast else "veryfast",
               "-crf", "28" if fast else "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", dst]
        self.ui(self._on_progress, 0, "Đang chuyển HEVC → H.264...")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, creationflags=NO_WINDOW)
        for line in self.proc.stdout:
            if self.cancel_flag.is_set():
                self.proc.kill()
                raise Cancelled()
            if line.startswith("out_time_us=") and duration:
                try:
                    t = int(line.split("=")[1]) / 1e6
                except ValueError:
                    continue
                pct = min(t / duration * 100, 100)
                self.ui(self._on_progress, pct, f"Đang chuyển HEVC → H.264... {pct:.0f}%")
        self.proc.wait()
        err = self.proc.stderr.read()
        code, self.proc = self.proc.returncode, None
        if self.cancel_flag.is_set():
            raise Cancelled()
        if code != 0 or not os.path.exists(dst):
            raise RuntimeError(f"ffmpeg lỗi khi chuyển định dạng:\n{err[-400:]}")
        try:
            os.remove(src)
        except OSError:
            pass
        return dst

    def _on_progress(self, pct, txt):
        self.progress.config(value=pct)
        self.status_var.set(txt)

    def _on_done(self, path, open_after):
        self.progress.config(value=100)
        self.set_busy(False)
        if open_after:
            self.status_var.set("Đang mở bản xem trước...")
            try:
                open_file(path)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Không mở được trình phát:\n{e}")
            return
        size = human_size(os.path.getsize(path)) if os.path.exists(path) else "?"
        self.status_var.set(f"Xong! {os.path.basename(path)} ({size})")
        if messagebox.askyesno(APP_TITLE, f"Đã tải xong ({size}).\nMở video ngay?"):
            open_file(path)

    def _on_cancelled(self):
        self.progress.config(value=0)
        self.set_busy(False)
        self.status_var.set("Đã huỷ.")

    def _on_error(self, title, err):
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.set_busy(False)
        msg = str(err).replace("\x1b[0;31mERROR:\x1b[0m ", "")
        self.status_var.set(title)
        messagebox.showerror(APP_TITLE, f"{title}:\n\n{msg[:600]}\n\n"
                             "Gợi ý: chạy 'Cap nhat yt-dlp.bat' (bản portable) hoặc 'pip install -U yt-dlp' để cập nhật, "
                             "TikTok hay đổi API.")


def enable_dpi_awareness():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


if __name__ == "__main__":
    enable_dpi_awareness()
    App().mainloop()
