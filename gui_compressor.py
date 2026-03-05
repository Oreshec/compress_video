#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой GUI для VideoCompressor.

Позволяет:
- выбрать входной файл;
- указать, куда сохранить результат;
- задать целевой размер (по умолчанию 10 МБ);
- запустить сжатие и увидеть статус.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from compress_video import (
    DEFAULT_TARGET_SIZE_MB,
    check_ffmpeg,
    compress_video,
)


class VideoCompressorGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Video Compressor")
        self.resizable(False, False)

        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.size_var = tk.StringVar(value=str(DEFAULT_TARGET_SIZE_MB))
        self.status_var = tk.StringVar(value="Готово.")

        self._build_ui()

    def _build_ui(self) -> None:
        padding = {"padx": 8, "pady": 4}

        # Входной файл
        tk.Label(self, text="Входной файл:").grid(row=0, column=0, sticky="w", **padding)
        entry_in = tk.Entry(self, textvariable=self.input_path_var, width=45)
        entry_in.grid(row=0, column=1, **padding)
        tk.Button(self, text="Обзор...", command=self.browse_input).grid(
            row=0, column=2, **padding
        )

        # Выходной файл
        tk.Label(self, text="Выходной файл:").grid(row=1, column=0, sticky="w", **padding)
        entry_out = tk.Entry(self, textvariable=self.output_path_var, width=45)
        entry_out.grid(row=1, column=1, **padding)
        tk.Button(self, text="Обзор...", command=self.browse_output).grid(
            row=1, column=2, **padding
        )

        # Целевой размер
        tk.Label(self, text="Целевой размер (МБ):").grid(
            row=2, column=0, sticky="w", **padding
        )
        tk.Entry(self, textvariable=self.size_var, width=10).grid(
            row=2, column=1, sticky="w", **padding
        )

        # Кнопка запуска
        tk.Button(self, text="Сжать", command=self.on_compress).grid(
            row=3, column=0, columnspan=3, pady=(8, 4)
        )

        # Статус
        tk.Label(self, textvariable=self.status_var, anchor="w", fg="blue").grid(
            row=4, column=0, columnspan=3, sticky="we", padx=8, pady=(4, 8)
        )

    def browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите видеофайл",
            filetypes=(
                ("Видео файлы", "*.mp4;*.mkv;*.avi;*.mov;*.wmv;*.flv"),
                ("Все файлы", "*.*"),
            ),
        )
        if path:
            self.input_path_var.set(path)
            # По умолчанию предлагаем выход рядом с исходником
            base, ext = os.path.splitext(path)
            if not self.output_path_var.get():
                self.output_path_var.set(f"{base}_compressed{ext}")

    def browse_output(self) -> None:
        initial = self.output_path_var.get() or self.input_path_var.get() or ""
        directory = os.path.dirname(initial) if initial else ""
        filename = os.path.basename(initial) if initial else "output_compressed.mp4"
        path = filedialog.asksaveasfilename(
            title="Куда сохранить сжатое видео",
            defaultextension=".mp4",
            initialdir=directory,
            initialfile=filename,
            filetypes=(("Видео MP4", "*.mp4"), ("Все файлы", "*.*")),
        )
        if path:
            self.output_path_var.set(path)

    def on_compress(self) -> None:
        input_path = self.input_path_var.get().strip()
        output_path = self.output_path_var.get().strip()
        size_text = self.size_var.get().strip().replace(",", ".")

        if not input_path:
            messagebox.showerror("Ошибка", "Укажите входной файл.")
            return
        if not os.path.isfile(input_path):
            messagebox.showerror("Ошибка", f"Файл не найден:\n{input_path}")
            return
        if not output_path:
            messagebox.showerror("Ошибка", "Укажите выходной файл.")
            return
        try:
            target_size = float(size_text)
            if target_size <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Целевой размер должен быть положительным числом.")
            return

        # Проверка FFmpeg
        try:
            check_ffmpeg()
        except SystemExit:
            # check_ffmpeg уже вывел сообщение в консоль; дублируем в GUI
            messagebox.showerror(
                "FFmpeg",
                "FFmpeg не найден в PATH.\n"
                "Установите FFmpeg и добавьте его в переменную PATH,\n"
                "затем перезапустите программу.",
            )
            return

        self.status_var.set("Сжатие запущено, подождите...")
        self._set_controls_state(tk.DISABLED)

        thread = threading.Thread(
            target=self._run_compress_worker,
            args=(input_path, output_path, target_size),
            daemon=True,
        )
        thread.start()

    def _set_controls_state(self, state: str) -> None:
        for child in self.winfo_children():
            if isinstance(child, tk.Button) or isinstance(child, tk.Entry):
                child.configure(state=state)

    def _run_compress_worker(self, input_path: str, output_path: str, target_size: float) -> None:
        try:
            ok = compress_video(input_path, output_path, target_size)
        except Exception as exc:  # noqa: BLE001
            ok = False
            msg = f"Ошибка: {exc}"
        else:
            msg = "Сжатие завершено успешно." if ok else "Сжатие завершилось с ошибкой."

        def finish() -> None:
            self._set_controls_state(tk.NORMAL)
            self.status_var.set(msg)
            if ok:
                messagebox.showinfo("Готово", f"{msg}\n\nФайл:\n{output_path}")
            else:
                messagebox.showerror("Ошибка", msg)

        self.after(0, finish)


def main() -> None:
    app = VideoCompressorGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

