import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import json
import importlib
import shutil
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

VIDEO_FOLDER = os.path.join(SCRIPT_DIR, "YouTube_Video")
AUDIO_FOLDER = os.path.join(SCRIPT_DIR, "YouTube_Audio")
TEXT_FOLDER = os.path.join(SCRIPT_DIR, "Transcriber")

os.makedirs(VIDEO_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(TEXT_FOLDER, exist_ok=True)

CONFIG_FILE = os.path.join(SCRIPT_DIR, "transcriber_config.json")

def load_config():
    default = {"cookies_file": "", "mode": "full"}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                default.update(cfg)
        except:
            pass
    return default

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except:
        pass

def install_package(package_name, import_name=None):
    if import_name is None:
        import_name = package_name.replace("-", "_")
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        print(f"Устанавливаю {package_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", package_name])
        return True

def ensure_ffmpeg():
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        os.environ["FFMPEG_BINARY"] = ffmpeg_path
        os.environ["PATH"] = os.path.dirname(ffmpeg_path) + os.pathsep + os.environ.get("PATH", "")
        return True
    except ImportError:
        print("Устанавливаю imageio-ffmpeg...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "imageio-ffmpeg"])
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        os.environ["FFMPEG_BINARY"] = ffmpeg_path
        os.environ["PATH"] = os.path.dirname(ffmpeg_path) + os.pathsep + os.environ.get("PATH", "")
        return True

def ensure_dependencies():
    install_package("yt-dlp", "yt_dlp")
    install_package("openai-whisper", "whisper")
    ensure_ffmpeg()

print("Проверка и установка зависимостей...")
ensure_dependencies()
print("Все зависимости готовы!")

import yt_dlp
import whisper

# Удаляем проблемный плагин ytse, если он остался
try:
    import yt_dlp_plugins
    plugin_path = os.path.join(os.path.dirname(yt_dlp_plugins.__file__), 'extractor', 'ytse.py')
    if os.path.exists(plugin_path):
        os.remove(plugin_path)
        print("Удалён конфликтующий плагин ytse.py")
except:
    pass

import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Whisper будет использовать устройство: {device.upper()}")

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Transcriber + Video Downloader")
        self.root.geometry("620x500")

        self.config = load_config()

        self.url = tk.StringVar()
        self.status = tk.StringVar(value="Готов")
        self.progress = tk.DoubleVar()
        self.cookies_path = tk.StringVar(value=self.config.get("cookies_file", ""))
        self.mode = tk.StringVar(value=self.config.get("mode", "full"))
        self.audio_file_path = tk.StringVar()

        self.model = None
        self.model_lock = threading.Lock()
        self._busy = False

        self.create_widgets()

    def create_widgets(self):
        mode_frame = tk.LabelFrame(self.root, text="Режим работы", padx=5, pady=5)
        mode_frame.pack(fill=tk.X, padx=10, pady=10)

        modes = [
            ("📥 Скачать видео + аудио и расшифровать", "full"),
            ("⬇️ Только скачать видео и аудио", "download_only"),
            ("🎤 Только расшифровать аудиофайл", "transcribe_only")
        ]

        for text, value in modes:
            tk.Radiobutton(mode_frame, text=text, variable=self.mode,
                           value=value, command=self.on_mode_change).pack(anchor=tk.W)

        self.input_frame = tk.LabelFrame(self.root, text="Ссылка на YouTube", padx=5, pady=5)
        self.input_frame.pack(fill=tk.X, padx=10, pady=5)

        self.url_frame = tk.Frame(self.input_frame)
        self.url_frame.pack(fill=tk.X)
        tk.Label(self.url_frame, text="Ссылка:").pack(anchor=tk.W)
        entry_frame = tk.Frame(self.url_frame)
        entry_frame.pack(fill=tk.X)
        self.entry = tk.Entry(entry_frame, textvariable=self.url)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(entry_frame, text="📋", command=self.paste).pack(side=tk.LEFT, padx=5)
        self.setup_entry_bindings()

        self.audio_frame = tk.Frame(self.input_frame)
        tk.Label(self.audio_frame, text="Аудиофайл:").pack(anchor=tk.W)
        af_entry = tk.Frame(self.audio_frame)
        af_entry.pack(fill=tk.X)
        tk.Entry(af_entry, textvariable=self.audio_file_path, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(af_entry, text="📁", command=self.browse_audio_file).pack(side=tk.LEFT, padx=5)

        cookies_frame = tk.LabelFrame(self.root, text="Cookies (для обхода защиты YouTube)", padx=5, pady=5)
        cookies_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(cookies_frame, text="Файл cookies.txt (необязательно):").grid(row=0, column=0, sticky=tk.W)
        tk.Entry(cookies_frame, textvariable=self.cookies_path, state="readonly").grid(row=1, column=0, sticky=tk.EW, padx=(0,5))
        tk.Button(cookies_frame, text="📁", command=self.browse_cookies).grid(row=1, column=1)
        cookies_frame.columnconfigure(0, weight=1)

        info_frame = tk.LabelFrame(self.root, text="Папки для сохранения (создаются рядом со скриптом)", padx=5, pady=5)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(info_frame, text=f"📁 Видео: {VIDEO_FOLDER}", fg="blue").pack(anchor=tk.W)
        tk.Label(info_frame, text=f"🎵 Аудио: {AUDIO_FOLDER}", fg="blue").pack(anchor=tk.W)
        tk.Label(info_frame, text=f"📄 Текст: {TEXT_FOLDER}", fg="blue").pack(anchor=tk.W)

        model_frame = tk.Frame(self.root)
        model_frame.pack(pady=5)
        tk.Label(model_frame, text="Модель Whisper:").pack(side=tk.LEFT, padx=5)
        self.combo = ttk.Combobox(model_frame,
                                  values=["tiny", "base", "small", "medium", "large"],
                                  state="readonly")
        self.combo.set("small")
        self.combo.pack(side=tk.LEFT)

        self.start_btn = tk.Button(self.root, text="Старт", command=self.start,
                                   bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20)
        self.start_btn.pack(pady=10)

        ttk.Progressbar(self.root, variable=self.progress, maximum=100).pack(fill=tk.X, padx=10)
        tk.Label(self.root, textvariable=self.status).pack()

        self.on_mode_change()

    def setup_entry_bindings(self):
        self.entry.bind("<Control-v>", self.handle_paste)
        self.entry.bind("<Control-V>", self.handle_paste)
        self.menu = tk.Menu(self.entry, tearoff=0)
        self.menu.add_command(label="Вставить", command=self.paste)
        self.menu.add_command(label="Копировать", command=self.copy)
        self.menu.add_command(label="Вырезать", command=self.cut)
        self.entry.bind("<Button-3>", self.show_menu)

    def on_mode_change(self):
        mode = self.mode.get()
        if mode == "transcribe_only":
            self.input_frame.config(text="Выбор аудиофайла")
            self.url_frame.pack_forget()
            self.audio_frame.pack(fill=tk.X)
            self.start_btn.config(text="Расшифровать аудио")
        else:
            self.input_frame.config(text="Ссылка на YouTube")
            self.audio_frame.pack_forget()
            self.url_frame.pack(fill=tk.X)
            self.start_btn.config(text="Скачать и расшифровать" if mode == "full" else "Скачать видео и аудио")
        self.config["mode"] = mode
        save_config(self.config)

    def paste(self):
        try:
            text = self.root.clipboard_get()
            self.entry.insert(tk.INSERT, text)
        except:
            pass

    def handle_paste(self, event):
        self.paste()
        return "break"

    def copy(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.entry.selection_get())
        except:
            pass

    def cut(self):
        self.copy()
        try:
            self.entry.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except:
            pass

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def browse_cookies(self):
        path = filedialog.askopenfilename(
            title="Выберите файл cookies.txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if path:
            self.cookies_path.set(path)
            self.config["cookies_file"] = path
            save_config(self.config)

    def browse_audio_file(self):
        path = filedialog.askopenfilename(
            title="Выберите аудиофайл",
            filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac *.ogg"), ("All files", "*.*")]
        )
        if path:
            self.audio_file_path.set(path)

    def start(self):
        if self._busy:
            return
        mode = self.mode.get()
        url = self.url.get().strip()
        audio_path = self.audio_file_path.get()
        if mode != "transcribe_only" and not url:
            messagebox.showerror("Ошибка", "Вставьте ссылку на YouTube")
            return
        if mode == "transcribe_only" and (not audio_path or not os.path.exists(audio_path)):
            messagebox.showerror("Ошибка", "Выберите существующий аудиофайл")
            return

        self.config["cookies_file"] = self.cookies_path.get()
        self.config["mode"] = mode
        save_config(self.config)

        self._busy = True
        self.start_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.run, daemon=True).start()

    def load_model(self):
        """Потокобезопасная загрузка модели Whisper (только один раз)."""
        with self.model_lock:
            if self.model is None:
                model_name = self.combo.get()
                self.model = whisper.load_model(model_name)
            return self.model

    def run(self):
        try:
            mode = self.mode.get()
            if mode == "transcribe_only":
                audio_path = self.audio_file_path.get()
                if not audio_path or not os.path.exists(audio_path):
                    raise Exception("Выберите аудиофайл")
                self.transcribe_audio_file(audio_path)
                return

            url = self.url.get().strip()
            if not url:
                raise Exception("Вставьте ссылку на YouTube")

            self.set("Скачивание видео и аудио...", 20)
            audio_file, video_file, video_title = self.download(url)

            if mode == "download_only":
                self.set("Готово", 100)
                self.show_info("OK",
                    f"Скачивание завершено!\n\n"
                    f"Видео сохранено в:\n{video_file}\n\n"
                    f"Аудио сохранено в:\n{audio_file}"
                )
                return

            self.set("Загрузка модели Whisper...", 40)
            model = self.load_model()

            self.set("Распознавание речи...", 60)
            result = model.transcribe(audio_file, language="ru")
            text = result["text"]

            safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not safe_title:
                safe_title = "transcript"
            out_text = os.path.join(TEXT_FOLDER, f"{safe_title}.txt")
            with open(out_text, "w", encoding="utf-8") as f:
                f.write(text)

            self.set("Готово", 100)
            self.show_info("OK",
                f"Успешно!\n\n"
                f"Видео сохранено в:\n{video_file}\n\n"
                f"Аудио сохранено в:\n{audio_file}\n\n"
                f"Текст сохранён в:\n{out_text}"
            )
        except Exception as e:
            self.set("Ошибка", 0)
            self.show_error("Ошибка", f"Произошла ошибка:\n{str(e)}")
        finally:
            self._busy = False
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

    def show_info(self, title, msg):
        """Показ информационного окна только из потока Tkinter."""
        self.root.after(0, lambda: messagebox.showinfo(title, msg))

    def show_error(self, title, msg):
        """Показ окна ошибки только из потока Tkinter."""
        self.root.after(0, lambda: messagebox.showerror(title, msg))

    def transcribe_audio_file(self, audio_path):
        self.set("Загрузка модели...", 30)
        model = self.load_model()
        self.set("Распознавание...", 50)
        result = model.transcribe(audio_path, language="ru")
        text = result["text"]
        base = os.path.splitext(os.path.basename(audio_path))[0]
        out_text = os.path.join(TEXT_FOLDER, f"{base}.txt")
        with open(out_text, "w", encoding="utf-8") as f:
            f.write(text)
        self.set("Готово", 100)
        self.show_info("OK", f"Расшифровка завершена!\n\nФайл сохранён:\n{out_text}")

    def download(self, url):
        cookies_file = self.cookies_path.get()
        if cookies_file and os.path.exists(cookies_file):
            try:
                return self._download_with_opts(url, {'cookiefile': cookies_file})
            except Exception as e:
                print(f"Ошибка с cookies.txt: {e}")

        for browser in ['firefox', 'chrome', 'edge']:
            try:
                return self._download_with_opts(url, {'cookiesfrombrowser': (browser,)})
            except Exception as e:
                print(f"Ошибка с {browser}: {e}")

        # Если всё выше не сработало, пробуем без cookies (скорее всего будет ошибка бота)
        return self._download_with_opts(url, {})

    def _download_with_opts(self, url, extra_opts):
        # Очищаем папку VIDEO_FOLDER от временных файлов перед скачиванием (чтобы не было старых .f*.mp4)
        self.cleanup_temp_files(VIDEO_FOLDER)

        outtmpl_video = os.path.join(VIDEO_FOLDER, '%(title)s.%(ext)s')
        ydl_opts = {
            'format': (
                'bestvideo[height>=720][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height>=720]+bestaudio/'
                'best[height>=720]/best'
            ),
            'merge_output_format': 'mp4',
            'outtmpl': outtmpl_video,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 30,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web', 'mweb', 'tv'],
                }
            },
        }
        ydl_opts.update(extra_opts)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info.get('title', 'transcript')

        # После скачивания находим финальный видеофайл
        video_file = self.find_final_video(VIDEO_FOLDER)
        if not video_file:
            raise Exception("Финальный видеофайл не найден")

        # Аудио скачиваем ОТДЕЛЬНО в формате WAV: постпроцессор извлечения аудио
        # не конфликтует с объединением видео+аудио (в старом варианте m4a-аудио
        # могло переименовываться/удаляться при merge, и WAV мог не создаться).
        audio_file = self.download_audio(url, video_title, extra_opts)

        # Удаляем временные файлы из папки видео
        self.cleanup_temp_files(VIDEO_FOLDER)

        return audio_file, video_file, video_title

    def download_audio(self, url, video_title, extra_opts):
        """Скачивает только аудио и конвертирует его в WAV в AUDIO_FOLDER."""
        base_name = re.sub(r'[\\/:*?"<>|]', '_', video_title).strip() or 'audio'
        outtmpl_audio = os.path.join(AUDIO_FOLDER, f'{base_name}.%(ext)s')
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': outtmpl_audio,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 30,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                # Для WAV битрейт ('-b:a') неприменим — ffmpeg сам выберет
                # PCM s16le; качество задаётся частотой дискретизации ниже.
                'preferredquality': None,
            }],
        }
        ydl_opts.update(extra_opts)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        wav_file = os.path.join(AUDIO_FOLDER, f'{base_name}.wav')
        if not os.path.exists(wav_file):
            # Запасной вариант: любой свежий аудиофайл в папке конвертируем в WAV
            fallback = self.find_latest_audio(AUDIO_FOLDER)
            if not fallback:
                raise Exception("Аудиофайл не найден после скачивания")
            wav_file = self.convert_to_wav(fallback, os.path.splitext(fallback)[0] + '.wav')
        return wav_file

    def find_latest_audio(self, folder):
        exts = ('.wav', '.m4a', '.mp3', '.opus', '.ogg', '.webm')
        candidates = []
        for f in os.listdir(folder):
            low = f.lower()
            if not low.endswith(exts):
                continue
            if '.part' in f or re.search(r'\.f\d+\.[^.]+$', f):
                continue  # временный файл yt-dlp
            candidates.append(os.path.join(folder, f))
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)

    def get_ffmpeg_path(self):
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return shutil.which('ffmpeg') or 'ffmpeg'

    def convert_to_wav(self, src, dst):
        """Конвертирует аудиофайл в WAV (16 kHz mono) с помощью ffmpeg."""
        ffmpeg = self.get_ffmpeg_path()
        subprocess.run(
            [ffmpeg, '-y', '-i', src, '-vn', '-acodec', 'pcm_s16le',
             '-ar', '16000', '-ac', '1', dst],
            check=True, capture_output=True,
        )
        if os.path.splitext(src)[1].lower() != '.wav':
            os.remove(src)
        return dst

    def cleanup_temp_files(self, folder):
        """Удаляет временные файлы yt-dlp (.fцифры.xxx и .part)."""
        for f in os.listdir(folder):
            full = os.path.join(folder, f)
            if not os.path.isfile(full):
                continue
            # Временные файлы yt-dlp содержат '.f' перед идентификатором формата
            # (например 'Title.f140.m4a') или не завершены ('.part').
            is_temp = '.part' in f or re.search(r'\.f\d+\.[^.]+$', f) is not None
            if is_temp:
                try:
                    os.remove(full)
                    print(f"Удалён временный файл: {f}")
                except OSError:
                    pass

    def find_final_video(self, folder):
        """Ищет финальное объединённое видео без временных суффиксов yt-dlp."""
        video_exts = ('.mp4', '.mkv', '.webm', '.mov', '.flv', '.m4v')
        candidates = []
        for f in os.listdir(folder):
            low = f.lower()
            if not low.endswith(video_exts):
                continue
            if '.part' in f or re.search(r'\.f\d+\.[^.]+$', f):
                continue  # временный/незавершённый файл
            candidates.append(os.path.join(folder, f))
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)

    def set(self, text, prog):
        self.root.after(0, lambda: self.status.set(text))
        self.root.after(0, lambda: self.progress.set(prog))


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
