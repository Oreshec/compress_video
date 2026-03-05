#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сжатие видео до заданного размера с предварительной оценкой и автоматической подстройкой битрейта.
Требуется FFmpeg в PATH.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys


# Целевой размер по умолчанию (МБ)
DEFAULT_TARGET_SIZE_MB = 10

# Запас на контейнер и неточность кодирования (0.92 = 92% от расчёта идёт в битрейт)
SAFETY_FACTOR = 0.92


def get_media_info(path: str) -> dict:
    """Получить информацию о видео через ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Ошибка анализа файла (нужен FFmpeg): {e}") from e


def get_duration_seconds(media: dict) -> float:
    """Длительность в секундах."""
    try:
        return float(media["format"].get("duration", 0))
    except (KeyError, TypeError, ValueError):
        return 0.0


def get_video_stream(media: dict) -> dict | None:
    """Первый видеопоток."""
    for s in media.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None


def get_audio_stream(media: dict) -> dict | None:
    """Первый аудиопоток."""
    for s in media.get("streams", []):
        if s.get("codec_type") == "audio":
            return s
    return None


def get_audio_bitrate_bps(media: dict) -> int:
    """Оценка битрейта аудио в битах/сек."""
    stream = get_audio_stream(media)
    if not stream:
        return 0
    # Из потока
    br = stream.get("bit_rate")
    if br:
        try:
            return int(br)
        except (TypeError, ValueError):
            pass
    # Из формата (общий битрейт - грубая оценка)
    fmt = media.get("format", {})
    total = fmt.get("bit_rate")
    if total:
        try:
            total = int(total)
            video = get_video_stream(media)
            if video and video.get("bit_rate"):
                try:
                    return max(0, total - int(video.get("bit_rate", 0)))
                except (TypeError, ValueError):
                    pass
            return total // 5  # грубо 20% на аудио
        except (TypeError, ValueError):
            pass
    # Дефолт: 128 kbps
    return 128 * 1000


def estimate_output_size_mb(
    duration_sec: float,
    video_bitrate_bps: int,
    audio_bitrate_bps: int,
) -> float:
    """Оценка размера результата в МБ."""
    if duration_sec <= 0:
        return 0.0
    total_bits = (video_bitrate_bps + audio_bitrate_bps) * duration_sec
    return total_bits / (8 * 1024 * 1024)


def calculate_target_video_bitrate(
    target_size_mb: float,
    duration_sec: float,
    audio_bitrate_bps: int,
) -> int:
    """
    Целевой видеобитрейт в б/с, чтобы итог уместился в target_size_mb.
    Учитывается запас SAFETY_FACTOR.
    """
    if duration_sec <= 0:
        return 1_000_000
    target_bits = target_size_mb * 8 * 1024 * 1024
    audio_bits = audio_bitrate_bps * duration_sec
    video_bits = (target_bits * SAFETY_FACTOR) - audio_bits
    if video_bits <= 0:
        video_bits = target_bits // 2
    return max(50_000, int(video_bits / duration_sec))


def compress_video(
    input_path: str,
    output_path: str,
    target_size_mb: float,
    video_bitrate_bps: int | None = None,
    audio_bitrate_bps: int = 128_000,
    extra_args: list[str] | None = None,
) -> bool:
    """
    Сжать видео. Если video_bitrate_bps не задан — вычислится из target_size_mb.
    """
    media = get_media_info(input_path)
    duration_sec = get_duration_seconds(media)
    if duration_sec <= 0:
        print("Не удалось определить длительность видео.")
        return False

    audio_bps = get_audio_bitrate_bps(media)
    if video_bitrate_bps is None:
        video_bitrate_bps = calculate_target_video_bitrate(
            target_size_mb, duration_sec, audio_bps
        )

    # Оценка размера после сжатия
    estimated_mb = estimate_output_size_mb(duration_sec, video_bitrate_bps, audio_bps)
    print(f"Целевой размер: {target_size_mb:.2f} МБ")
    print(f"Расчётный видеобитрейт: {video_bitrate_bps // 1000} кбит/с")
    print(f"Предварительная оценка размера: {estimated_mb:.2f} МБ")

    # Если предварительная оценка больше цели — снижаем битрейт
    effective_target_mb = target_size_mb
    while estimated_mb > target_size_mb and effective_target_mb > 0.5:
        effective_target_mb *= 0.92  # уменьшаем целевую «планку»
        video_bitrate_bps = calculate_target_video_bitrate(
            effective_target_mb, duration_sec, audio_bps
        )
        estimated_mb = estimate_output_size_mb(duration_sec, video_bitrate_bps, audio_bps)
        print(f"Оценка превышает цель — снижен битрейт до {video_bitrate_bps // 1000} кбит/с")
        print(f"Новая оценка размера: {estimated_mb:.2f} МБ")

    video_bitrate_k = video_bitrate_bps // 1000
    audio_bitrate_k = min(audio_bps // 1000, 192)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-b:v", f"{video_bitrate_k}k",
        "-maxrate", f"{int(video_bitrate_k * 1.2)}k",
        "-bufsize", f"{video_bitrate_k * 2}k",
        "-c:a", "aac",
        "-b:a", f"{audio_bitrate_k}k",
        "-movflags", "+faststart",
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(output_path)

    try:
        subprocess.run(
            cmd,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Готово. Размер файла: {size_mb:.2f} МБ")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка FFmpeg: {e}")
        return False
    except FileNotFoundError:
        print("FFmpeg не найден. Установите FFmpeg и добавьте его в PATH.")
        return False


def check_ffmpeg() -> None:
    """Проверить наличие ffprobe и ffmpeg в PATH; при отсутствии вывести подсказку и выйти."""
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        print("Ошибка: FFmpeg не найден в PATH.")
        print("Установите FFmpeg и добавьте папку с ffmpeg.exe и ffprobe.exe в переменную PATH.")
        print("  • Сайт: https://ffmpeg.org/download.html")
        print("  • Windows: winget install ffmpeg  или скачайте с https://www.gyan.dev/ffmpeg/builds/")
        print("  • После установки перезапустите терминал.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Сжатие видео до заданного размера с предварительной оценкой и подстройкой битрейта."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Входной видеофайл",
    )
    parser.add_argument(
        "-i", "--input",
        dest="input_alt",
        default=None,
        help="Входной видеофайл (альтернатива позиционному аргументу)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Выходной файл (по умолчанию: имя_входа_compressed.расширение)",
    )
    parser.add_argument(
        "-s", "--size",
        type=float,
        default=DEFAULT_TARGET_SIZE_MB,
        metavar="MB",
        help=f"Целевой размер в МБ (по умолчанию: {DEFAULT_TARGET_SIZE_MB})",
    )
    args = parser.parse_args()

    input_path = (args.input_alt or args.input)
    if not input_path:
        parser.error("Укажите входной файл: путь к видео или используйте -i путь")
    input_path = os.path.abspath(input_path)
    if not os.path.isfile(input_path):
        print(f"Файл не найден: {input_path}")
        sys.exit(1)

    check_ffmpeg()

    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_compressed{ext}"

    print(f"Вход: {input_path}")
    print(f"Выход: {output_path}")
    success = compress_video(input_path, output_path, args.size)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
