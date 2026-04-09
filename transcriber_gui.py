import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import json
import importlib
import time

# Определяем папку, где находится запущенный скрипт
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

# Подпапки для хранения файлов
VIDEO_FOLDER = os.path.join(SCRIPT_DIR, "YouTube_Video")
AUDIO_FOLDER = os.path.join(SCRIPT_DIR, "YouTube_Audio")
TEXT_FOLDER = os.path.join(SCRIPT_DIR, "Transcriber")

# Создаём папки, если их ещё нет
os.makedirs(VIDEO_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(TEXT_FOLDER, exist_ok=True)

# Файл для хранения настроек (только cookies)
CONFIG_FILE = os.path.join(SCRIPT_DIR, "transcriber_config.json")

def load_config():
    default = {"cookies_file": ""}
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
    """Устанавливает pip-пакет, если он не установлен."""
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
    """Проверяет наличие ffmpeg и при необходимости устанавливает imageio-ffmpeg."""
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
    """Проверяет и устанавливает все необходимые зависимости."""
    # Устанавливаем yt-dlp-ytse
    install_package("yt-dlp-ytse", "yt_dlp")
    # Устанавливаем whisper
    install_package("openai-whisper", "whisper")
    # Настраиваем ffmpeg
    ensure_ffmpeg()

# Запускаем проверку зависимостей до создания GUI
print("Проверка и установка зависимостей...")
ensure_dependencies()
print("Все зависимости готовы!")

# Теперь импортируем библиотеки (они уже точно установлены)
import yt_dlp
import whisper
import imageio_ffmpeg

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Transcriber + Video Downloader")
        self.root.geometry("600x380")

        self.config = load_config()

        self.url = tk.StringVar()
        self.status = tk.StringVar(value="Готов")
        self.progress = tk.DoubleVar()
        self.cookies_path = tk.StringVar(value=self.config.get("cookies_file", ""))

        self.model = None

        self.create_widgets()

    def create_widgets(self):
        # === Ссылка ===
        frame_url = tk.Frame(self.root)
        frame_url.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(frame_url, text="Ссылка на YouTube:").pack(anchor=tk.W)
        entry_frame = tk.Frame(frame_url)
        entry_frame.pack(fill=tk.X)
        self.entry = tk.Entry(entry_frame, textvariable=self.url)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(entry_frame, text="📋", command=self.paste).pack(side=tk.LEFT, padx=5)

        self.entry.bind("<Control-v>", self.handle_paste)
        self.entry.bind("<Control-V>", self.handle_paste)
        self.menu = tk.Menu(self.entry, tearoff=0)
        self.menu.add_command(label="Вставить", command=self.paste)
        self.menu.add_command(label="Копировать", command=self.copy)
        self.menu.add_command(label="Вырезать", command=self.cut)
        self.entry.bind("<Button-3>", self.show_menu)

        # === Cookies ===
        cookies_frame = tk.LabelFrame(self.root, text="Cookies (для обхода защиты YouTube)", padx=5, pady=5)
        cookies_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(cookies_frame, text="Файл cookies.txt (необязательно):").grid(row=0, column=0, sticky=tk.W)
        tk.Entry(cookies_frame, textvariable=self.cookies_path, state="readonly").grid(row=1, column=0, sticky=tk.EW, padx=(0,5))
        tk.Button(cookies_frame, text="📁", command=self.browse_cookies).grid(row=1, column=1)

        cookies_frame.columnconfigure(0, weight=1)

        # === Информация о папках ===
        info_frame = tk.LabelFrame(self.root, text="Папки для сохранения (создаются рядом со скриптом)", padx=5, pady=5)
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(info_frame, text=f"📁 Видео: {VIDEO_FOLDER}", fg="blue").pack(anchor=tk.W)
        tk.Label(info_frame, text=f"🎵 Аудио: {AUDIO_FOLDER}", fg="blue").pack(anchor=tk.W)
        tk.Label(info_frame, text=f"📄 Текст: {TEXT_FOLDER}", fg="blue").pack(anchor=tk.W)

        # === Модель ===
        model_frame = tk.Frame(self.root)
        model_frame.pack(pady=5)
        tk.Label(model_frame, text="Модель Whisper:").pack(side=tk.LEFT, padx=5)
        self.combo = ttk.Combobox(model_frame,
                                  values=["tiny", "base", "small", "medium", "large"],
                                  state="readonly")
        self.combo.set("small")
        self.combo.pack(side=tk.LEFT)

        # === Кнопка старт ===
        tk.Button(self.root, text="Старт", command=self.start, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20).pack(pady=10)

        # === Прогресс ===
        ttk.Progressbar(self.root, variable=self.progress, maximum=100).pack(fill=tk.X, padx=10)
        tk.Label(self.root, textvariable=self.status).pack()

    # ====== clipboard ======
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

    # ====== main ======
    def start(self):
        # Сохраняем cookies в конфиг
        self.config["cookies_file"] = self.cookies_path.get()
        save_config(self.config)

        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            url = self.url.get().strip()
            if not url:
                raise Exception("Вставь ссылку")

            self.set("Скачивание видео и аудио...", 20)

            audio_file, video_file, video_title = self.download(url)

            self.set("Модель...", 40)

            if not self.model:
                self.model = whisper.load_model(self.combo.get())

            self.set("Распознавание...", 60)

            result = self.model.transcribe(audio_file, fp16=False, language="ru")
            text = result["text"]

            # Формируем безопасное имя файла
            safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not safe_title:
                safe_title = "transcript"

            out_text = os.path.join(TEXT_FOLDER, f"{safe_title}.txt")

            with open(out_text, "w", encoding="utf-8") as f:
                f.write(text)

            self.set("Готово", 100)
            messagebox.showinfo("OK",
                f"Успешно!\n\n"
                f"Видео сохранено в:\n{video_file}\n\n"
                f"Аудио сохранено в:\n{audio_file}\n\n"
                f"Текст сохранён в:\n{out_text}"
            )

        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка:\n{str(e)}")
            self.set("Ошибка", 0)

    def download(self, url):
        cookies_file = self.cookies_path.get()
        if cookies_file and os.path.exists(cookies_file):
            try:
                print("[Log] Пробуем с указанным файлом cookies.txt...")
                return self._download_with_opts(url, {'cookiefile': cookies_file})
            except Exception as e:
                print(f"[Log] Ошибка с файлом cookies.txt: {e}")

        for browser in ['firefox', 'chrome', 'edge']:
            try:
                print(f"[Log] Пробуем куки из {browser}...")
                return self._download_with_opts(url, {'cookiesfrombrowser': (browser,)})
            except Exception as e:
                print(f"[Log] Ошибка с браузером {browser}: {e}")

        try:
            print("[Log] Пробуем скачать без куки...")
            return self._download_with_opts(url, {})
        except Exception as e:
            print(f"[Log] Скачивание без куки тоже не удалось: {e}")
            raise Exception("Не удалось скачать. YouTube блокирует доступ.\nПопробуйте указать файл cookies.txt или войдите в YouTube в Firefox/Chrome.")

    def _download_with_opts(self, url, extra_opts):
        outtmpl_video = os.path.join(VIDEO_FOLDER, '%(title)s.%(ext)s')

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': outtmpl_video,
            'quiet': False,
            'noplaylist': True,
            'socket_timeout': 30,
            'js_runtimes': {'deno': {'path': None}},
            'remote_components': ['ejs:github', 'ejs:npm'],
            'extractor_args': {'youtube': {'player_client': ['android', 'web', 'mweb']}},
            'postprocessors': [
                {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav', 'preferredquality': '192'},
            ],
            'keepvideo': True,
        }

        ydl_opts.update(extra_opts)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info.get('title', 'transcript')

        # Находим видеофайл
        video_file = self.find_file(VIDEO_FOLDER, ['.mp4', '.mkv', '.webm'])
        if not video_file:
            raise Exception("Видеофайл не найден после скачивания.")

        # Аудиофайл (wav) должен быть рядом с видео, переместим его в AUDIO_FOLDER
        base_video = os.path.splitext(video_file)[0]
        audio_file = None
        for ext in ['.wav', '.m4a', '.opus']:
            test = base_video + ext
            if os.path.exists(test):
                audio_file = test
                break

        if not audio_file:
            raise Exception("Аудиофайл не найден после скачивания.")

        # Перемещаем аудио в специальную папку
        import shutil
        dest_audio = os.path.join(AUDIO_FOLDER, os.path.basename(audio_file))
        if not os.path.exists(dest_audio):
            shutil.move(audio_file, dest_audio)
        audio_file = dest_audio

        return audio_file, video_file, video_title

    def find_file(self, folder, extensions):
        candidates = []
        for f in os.listdir(folder):
            full = os.path.join(folder, f)
            if os.path.isfile(full):
                ext = os.path.splitext(f)[1].lower()
                if ext in extensions:
                    candidates.append(full)
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