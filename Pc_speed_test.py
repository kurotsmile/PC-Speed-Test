#!/usr/bin/env python3
"""CLI tool to inspect system details and run lightweight speed tests."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - optional GUI path
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - fallback path is intentional
    psutil = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except ImportError:  # pragma: no cover - optional export path
    colors = None
    A4 = None
    ParagraphStyle = None
    getSampleStyleSheet = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None


AUTO_REFRESH_MS = 3000
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
REPORT_DIR = OUTPUT_DIR / "reports"
PDF_DIR = OUTPUT_DIR / "pdf"
HISTORY_DIR = OUTPUT_DIR / "history"
BUILD_DIR = BASE_DIR / "build"
HISTORY_FILE = HISTORY_DIR / "benchmark_history.json"
MAX_BENCHMARK_HISTORY = 100


@dataclass
class Benchmarks:
    cpu_loop_seconds: float | None
    cpu_loop_ops_per_sec: float | None
    memory_copy_mb_s: float | None
    disk_write_mb_s: float | None
    disk_read_mb_s: float | None
    file_ops_per_sec: float | None
    tcp_latency_ms: float | None


def ensure_output_dirs() -> None:
    for path in (OUTPUT_DIR, REPORT_DIR, PDF_DIR, HISTORY_DIR):
        path.mkdir(parents=True, exist_ok=True)


def safe_slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip())
    return cleaned.strip("_") or "pc_speed_test"


def default_report_stem(info: dict[str, Any]) -> str:
    hostname = safe_slug(info.get("hostname", "host"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"pc_speed_test_{hostname}_{timestamp}"


def run_command(cmd: list[str]) -> str:
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def human_bytes(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def get_cpu_name() -> str:
    system = platform.system()
    if system == "Darwin":
        hardware = run_command(["system_profiler", "SPHardwareDataType"])
        for line in hardware.splitlines():
            stripped = line.strip()
            if stripped.startswith("Chip:"):
                return stripped.split(":", 1)[1].strip()
        value = run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
        if value:
            return value
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    if system == "Windows":
        value = run_command(["wmic", "cpu", "get", "name"])
        lines = [line.strip() for line in value.splitlines() if line.strip() and "Name" not in line]
        if lines:
            return lines[0]
    return platform.processor() or "Unknown CPU"


def get_gpu_name() -> str:
    system = platform.system()
    if system == "Darwin":
        value = run_command(["system_profiler", "SPDisplaysDataType"])
        for line in value.splitlines():
            stripped = line.strip()
            if stripped.startswith("Chipset Model:"):
                return stripped.split(":", 1)[1].strip()
    if system == "Linux":
        value = run_command(["lspci"])
        for line in value.splitlines():
            lower = line.lower()
            if "vga compatible controller" in lower or "3d controller" in lower:
                return line.split(":", 2)[-1].strip()
    if system == "Windows":
        value = run_command(["wmic", "path", "win32_VideoController", "get", "name"])
        lines = [line.strip() for line in value.splitlines() if line.strip() and "Name" not in line]
        if lines:
            return lines[0]
    return "Unknown GPU"


def get_ip_addresses() -> list[str]:
    addresses: list[str] = []
    hostname = socket.gethostname()
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return addresses
    for info in infos:
        addr = info[4][0]
        if addr not in addresses and not addr.startswith("127.") and addr != "::1":
            addresses.append(addr)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            addr = sock.getsockname()[0]
            if addr not in addresses and not addr.startswith("127."):
                addresses.append(addr)
    except OSError:
        pass
    return addresses


def get_total_memory_fallback() -> int | None:
    system = platform.system()
    if system == "Darwin":
        value = run_command(["sysctl", "-n", "hw.memsize"])
        if value.isdigit():
            return int(value)
    if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_pages = os.sysconf("SC_PHYS_PAGES")
            if isinstance(page_size, int) and isinstance(total_pages, int):
                return page_size * total_pages
        except (OSError, ValueError):
            pass
    return None


def gather_basic_info() -> dict[str, Any]:
    uname = platform.uname()
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "os": f"{uname.system} {uname.release}",
        "os_version": uname.version,
        "machine": uname.machine,
        "architecture": platform.architecture()[0],
        "python": sys.version.split()[0],
        "cpu": {
            "model": get_cpu_name(),
            "physical_cores": os.cpu_count() or 0,
            "logical_cores": os.cpu_count() or 0,
        },
        "gpu": get_gpu_name(),
        "network": {"ip_addresses": get_ip_addresses()},
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    if psutil:
        try:
            freq = psutil.cpu_freq()
        except Exception:
            freq = None
        try:
            info["cpu"]["physical_cores"] = psutil.cpu_count(logical=False) or 0
            info["cpu"]["logical_cores"] = psutil.cpu_count(logical=True) or 0
            info["cpu"]["usage_percent"] = psutil.cpu_percent(interval=0.3)
        except Exception:
            pass
        if freq:
            info["cpu"]["current_freq_mhz"] = round(freq.current, 2)
            info["cpu"]["max_freq_mhz"] = round(freq.max, 2)

        try:
            vm = psutil.virtual_memory()
        except Exception:
            vm = None
        try:
            sm = psutil.swap_memory()
        except Exception:
            sm = None
        if vm:
            info["memory"] = {
                "total": vm.total,
                "available": vm.available,
                "used": vm.used,
                "usage_percent": vm.percent,
                "swap_total": sm.total if sm else 0,
                "swap_used": sm.used if sm else 0,
                "swap_percent": sm.percent if sm else 0,
            }

        try:
            du = psutil.disk_usage(str(Path.home()))
            info["disk"] = {
                "path": str(Path.home()),
                "total": du.total,
                "used": du.used,
                "free": du.free,
                "usage_percent": du.percent,
            }
        except Exception:
            pass

        try:
            net = psutil.net_io_counters()
        except Exception:
            net = None
        if net:
            info["network"].update(
                {
                    "bytes_sent": net.bytes_sent,
                    "bytes_recv": net.bytes_recv,
                    "packets_sent": net.packets_sent,
                    "packets_recv": net.packets_recv,
                }
            )

        try:
            boot_timestamp = psutil.boot_time()
            boot_time = datetime.fromtimestamp(boot_timestamp)
            info["uptime_seconds"] = time.time() - boot_timestamp
            info["boot_time"] = boot_time.isoformat(timespec="seconds")
        except Exception:
            pass
        try:
            info["process_count"] = len(psutil.pids())
        except Exception:
            pass

        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery:
            info["battery"] = {
                "percent": battery.percent,
                "plugged": battery.power_plugged,
                "time_left_seconds": battery.secsleft if battery.secsleft >= 0 else None,
            }
    else:
        total_memory = get_total_memory_fallback()
        if total_memory:
            info["memory"] = {"total": total_memory}
        usage = shutil.disk_usage(Path.home())
        info["disk"] = {
            "path": str(Path.home()),
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "usage_percent": round((usage.used / usage.total) * 100, 2) if usage.total else 0,
        }

    return info


def gather_top_processes(limit: int = 5) -> list[dict[str, Any]]:
    if not psutil:
        return []

    processes: list[dict[str, Any]] = []
    try:
        process_iter = psutil.process_iter(["pid", "name", "memory_info"])
    except Exception:
        return processes

    try:
        for process in process_iter:
            try:
                cpu_percent = process.cpu_percent(interval=None)
                name = process.info.get("name") or f"PID {process.pid}"
                memory_info = process.info.get("memory_info")
                rss = int(memory_info.rss) if memory_info else 0
                processes.append(
                    {
                        "pid": process.pid,
                        "name": name,
                        "cpu_percent": round(float(cpu_percent), 2),
                        "memory_rss": rss,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, AttributeError):
                continue
            except Exception:
                continue
    except Exception:
        return []

    processes.sort(key=lambda item: (item["cpu_percent"], item["memory_rss"]), reverse=True)
    return processes[:limit]


def load_benchmark_history() -> list[dict[str, Any]]:
    ensure_output_dirs()
    if not HISTORY_FILE.exists():
        return []
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def append_benchmark_history(info: dict[str, Any], benchmarks: Benchmarks) -> list[dict[str, Any]]:
    if benchmarks.cpu_loop_seconds is None:
        return load_benchmark_history()

    history = load_benchmark_history()
    entry = {
        "timestamp": info.get("timestamp"),
        "hostname": info.get("hostname"),
        "cpu_loop_ops_per_sec": benchmarks.cpu_loop_ops_per_sec,
        "memory_copy_mb_s": benchmarks.memory_copy_mb_s,
        "disk_write_mb_s": benchmarks.disk_write_mb_s,
        "disk_read_mb_s": benchmarks.disk_read_mb_s,
        "file_ops_per_sec": benchmarks.file_ops_per_sec,
        "tcp_latency_ms": benchmarks.tcp_latency_ms,
    }
    history.append(entry)
    history = history[-MAX_BENCHMARK_HISTORY:]
    try:
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return history


def run_cpu_benchmark(duration: float = 1.5) -> tuple[float, float]:
    iterations = 0
    start = time.perf_counter()
    while True:
        iterations += 1
        math.sqrt(iterations * 12345.6789)
        if time.perf_counter() - start >= duration:
            break
    elapsed = time.perf_counter() - start
    return elapsed, iterations / elapsed


def run_disk_benchmark(file_size_mb: int = 64) -> tuple[float, float]:
    chunk = b"x" * (1024 * 1024)
    chunks = [chunk] * file_size_mb

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        tmp_path = Path(handle.name)

    try:
        start = time.perf_counter()
        with open(tmp_path, "wb") as handle:
            for data in chunks:
                handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        write_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        with open(tmp_path, "rb") as handle:
            while handle.read(1024 * 1024):
                pass
        read_elapsed = time.perf_counter() - start
    finally:
        tmp_path.unlink(missing_ok=True)

    write_speed = file_size_mb / write_elapsed if write_elapsed else 0.0
    read_speed = file_size_mb / read_elapsed if read_elapsed else 0.0
    return write_speed, read_speed


def run_memory_benchmark(buffer_size_mb: int = 64, rounds: int = 8) -> float:
    source = bytearray(os.urandom(buffer_size_mb * 1024 * 1024))
    start = time.perf_counter()
    for _ in range(rounds):
        target = source[:]
        if target[0] == 256:  # pragma: no cover - impossible guard to keep the copy alive
            raise RuntimeError("Unreachable state")
    elapsed = time.perf_counter() - start
    total_mb = buffer_size_mb * rounds
    return total_mb / elapsed if elapsed else 0.0


def run_file_ops_benchmark(file_count: int = 200) -> float:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        for index in range(file_count):
            path = base / f"bench_{index}.tmp"
            path.write_text("pc-speed-test", encoding="utf-8")
        for index in range(file_count):
            path = base / f"bench_{index}.tmp"
            path.unlink(missing_ok=True)
    elapsed = time.perf_counter() - start
    total_ops = file_count * 2
    return total_ops / elapsed if elapsed else 0.0


def run_tcp_latency_benchmark(
    host: str = "1.1.1.1",
    port: int = 443,
    timeout: float = 0.35,
) -> float | None:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return None
    elapsed = time.perf_counter() - start
    return elapsed * 1000.0


def gather_benchmarks(enable: bool) -> Benchmarks:
    if not enable:
        return Benchmarks(None, None, None, None, None, None, None)

    cpu_elapsed, cpu_ops = run_cpu_benchmark()
    memory_speed = run_memory_benchmark()
    disk_write, disk_read = run_disk_benchmark()
    file_ops = run_file_ops_benchmark()
    tcp_latency = run_tcp_latency_benchmark()
    return Benchmarks(
        cpu_loop_seconds=round(cpu_elapsed, 3),
        cpu_loop_ops_per_sec=round(cpu_ops, 2),
        memory_copy_mb_s=round(memory_speed, 2),
        disk_write_mb_s=round(disk_write, 2),
        disk_read_mb_s=round(disk_read, 2),
        file_ops_per_sec=round(file_ops, 2),
        tcp_latency_ms=round(tcp_latency, 2) if tcp_latency is not None else None,
    )


def render_text_report(info: dict[str, Any], benchmarks: Benchmarks) -> str:
    lines: list[str] = []

    lines.append("=== PC SPEED TEST REPORT ===")
    lines.append(f"Time: {info['timestamp']}")
    lines.append(f"Host: {info['hostname']}")
    lines.append(f"OS: {info['os']}")
    lines.append(f"OS Version: {info['os_version']}")
    lines.append(f"Machine: {info['machine']} ({info['architecture']})")
    lines.append(f"Python: {info['python']}")
    lines.append("")

    cpu = info["cpu"]
    lines.append("[CPU]")
    lines.append(f"Model: {cpu['model']}")
    lines.append(f"Cores: {cpu['physical_cores']} physical / {cpu['logical_cores']} logical")
    if "usage_percent" in cpu:
        lines.append(f"Current Usage: {cpu['usage_percent']}%")
    if "current_freq_mhz" in cpu:
        lines.append(f"Frequency: {cpu['current_freq_mhz']} MHz (max {cpu['max_freq_mhz']} MHz)")
    lines.append("")

    lines.append("[GPU]")
    lines.append(f"Model: {info['gpu']}")
    lines.append("")

    if "memory" in info:
        memory = info["memory"]
        lines.append("[MEMORY]")
        if "used" in memory:
            lines.append(
                f"RAM: {human_bytes(memory['used'])} used / {human_bytes(memory['total'])} total "
                f"({memory['usage_percent']}%)"
            )
            lines.append(
                f"Available: {human_bytes(memory['available'])} | "
                f"Swap: {human_bytes(memory['swap_used'])} / {human_bytes(memory['swap_total'])} "
                f"({memory['swap_percent']}%)"
            )
        else:
            lines.append(f"RAM Total: {human_bytes(memory['total'])}")
        lines.append("")

    disk = info["disk"]
    lines.append("[DISK]")
    lines.append(f"Path: {disk['path']}")
    lines.append(
        f"Usage: {human_bytes(disk['used'])} used / {human_bytes(disk['total'])} total "
        f"({disk['usage_percent']}%)"
    )
    lines.append(f"Free: {human_bytes(disk['free'])}")
    lines.append("")

    network = info["network"]
    lines.append("[NETWORK]")
    lines.append("IP: " + (", ".join(network.get("ip_addresses", [])) or "Not detected"))
    if "bytes_sent" in network:
        lines.append(
            f"Traffic: sent {human_bytes(network['bytes_sent'])}, "
            f"received {human_bytes(network['bytes_recv'])}"
        )
        lines.append(
            f"Packets: sent {network['packets_sent']}, received {network['packets_recv']}"
        )
    lines.append("")

    if "boot_time" in info:
        lines.append("[SYSTEM]")
        lines.append(f"Boot Time: {info['boot_time']}")
        lines.append(f"Uptime: {format_seconds(info['uptime_seconds'])}")
        lines.append(f"Processes: {info['process_count']}")
        if "battery" in info:
            battery = info["battery"]
            battery_line = f"Battery: {battery['percent']}% | Plugged in: {battery['plugged']}"
            if battery["time_left_seconds"] is not None:
                battery_line += f" | Time left: {format_seconds(battery['time_left_seconds'])}"
            lines.append(battery_line)
        lines.append("")

    top_processes = info.get("top_processes", [])
    if top_processes:
        lines.append("[TOP PROCESSES]")
        for process in top_processes:
            lines.append(
                f"{process['name']} (PID {process['pid']}): "
                f"CPU {process['cpu_percent']}% | RAM {human_bytes(process['memory_rss'])}"
            )
        lines.append("")

    lines.append("[BENCHMARK]")
    if benchmarks.cpu_loop_seconds is None:
        lines.append("Skipped. Run with --benchmark to execute active speed tests.")
    else:
        lines.append(
            f"CPU loop: {benchmarks.cpu_loop_ops_per_sec:,.2f} ops/s "
            f"(sample window {benchmarks.cpu_loop_seconds}s)"
        )
        lines.append(f"Memory copy: {benchmarks.memory_copy_mb_s} MB/s")
        lines.append(f"Disk write: {benchmarks.disk_write_mb_s} MB/s")
        lines.append(f"Disk read: {benchmarks.disk_read_mb_s} MB/s")
        lines.append(f"File ops: {benchmarks.file_ops_per_sec:,.2f} ops/s")
        if benchmarks.tcp_latency_ms is None:
            lines.append("TCP latency: unavailable")
        else:
            lines.append(f"TCP latency: {benchmarks.tcp_latency_ms} ms")

    if not psutil:
        lines.append("")
        lines.append("Note: install 'psutil' for deeper metrics: pip install psutil")

    history = info.get("benchmark_history", [])
    if history:
        latest = history[-1]
        lines.append("")
        lines.append("[HISTORY]")
        lines.append(f"Saved Runs: {len(history)}")
        lines.append(f"Last Saved Run: {latest.get('timestamp', 'Unknown')}")

    return "\n".join(lines)


def build_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "info": payload["info"],
        "benchmarks": payload["benchmarks"],
    }
    return report


def export_report_json(payload: dict[str, Any], path: Path) -> Path:
    ensure_output_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    report = build_report_payload(payload)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def export_report_text(payload: dict[str, Any], path: Path) -> Path:
    ensure_output_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    info = payload["info"]
    benchmarks = Benchmarks(**payload["benchmarks"])
    body = render_text_report(info, benchmarks)
    path.write_text(body + "\n", encoding="utf-8")
    return path


def export_report_pdf(payload: dict[str, Any], path: Path) -> Path:
    if SimpleDocTemplate is None or Table is None or TableStyle is None or A4 is None:
        raise RuntimeError("PDF export requires reportlab. Install with: python3 -m pip install reportlab")

    ensure_output_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        spaceAfter=12,
        textColor=colors.HexColor("#122033"),
    )
    section_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        spaceBefore=8,
        spaceAfter=6,
        textColor=colors.HexColor("#0ea5e9"),
    )
    body_style = styles["BodyText"]
    body_style.fontName = "Helvetica"
    body_style.fontSize = 9
    body_style.leading = 12

    info = payload["info"]
    benchmarks = Benchmarks(**payload["benchmarks"])
    story: list[Any] = [
        Paragraph("PC Speed Test Report", title_style),
        Paragraph(f"Generated: {datetime.now().isoformat(timespec='seconds')}", body_style),
        Spacer(1, 8),
    ]

    sections = build_sections(info, benchmarks)
    for title, rows in sections:
        story.append(Paragraph(title, section_style))
        table_data = [[str(key), str(value)] for key, value in rows]
        table = Table(table_data, colWidths=[150, 340])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.whitesmoke, colors.HexColor("#eef6fb")]),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#122033")),
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#243b53")),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6e2ee")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 8))

    doc.build(story)
    return path


def export_report(payload: dict[str, Any], fmt: str = "pdf", base_path: Path | None = None) -> Path:
    ensure_output_dirs()
    info = payload["info"]
    stem = default_report_stem(info)
    if base_path is None:
        if fmt == "pdf":
            base_path = PDF_DIR / f"{stem}.pdf"
        elif fmt == "json":
            base_path = REPORT_DIR / f"{stem}.json"
        else:
            base_path = REPORT_DIR / f"{stem}.txt"

    fmt = fmt.lower()
    if fmt == "json":
        return export_report_json(payload, base_path)
    if fmt == "txt":
        return export_report_text(payload, base_path)
    if fmt == "pdf":
        return export_report_pdf(payload, base_path)
    raise ValueError(f"Unsupported report format: {fmt}")


def build_sections(info: dict[str, Any], benchmarks: Benchmarks) -> list[tuple[str, list[tuple[str, str]]]]:
    cpu = info["cpu"]
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "Overview",
            [
                ("Time", info["timestamp"]),
                ("Host", info["hostname"]),
                ("OS", info["os"]),
                ("Machine", f"{info['machine']} ({info['architecture']})"),
                ("Python", info["python"]),
            ],
        ),
        (
            "CPU",
            [
                ("Model", cpu["model"]),
                ("Cores", f"{cpu['physical_cores']} physical / {cpu['logical_cores']} logical"),
            ],
        ),
        ("GPU", [("Model", info["gpu"])]),
    ]

    if "usage_percent" in cpu:
        sections[1][1].append(("Usage", f"{cpu['usage_percent']}%"))
    if "current_freq_mhz" in cpu:
        sections[1][1].append(
            ("Frequency", f"{cpu['current_freq_mhz']} MHz / max {cpu['max_freq_mhz']} MHz")
        )

    if "memory" in info:
        memory = info["memory"]
        memory_rows = [("Total", human_bytes(memory["total"]))]
        if "used" in memory:
            memory_rows.extend(
                [
                    ("Used", f"{human_bytes(memory['used'])} ({memory['usage_percent']}%)"),
                    ("Available", human_bytes(memory["available"])),
                    (
                        "Swap",
                        f"{human_bytes(memory['swap_used'])} / {human_bytes(memory['swap_total'])} "
                        f"({memory['swap_percent']}%)",
                    ),
                ]
            )
        sections.append(("Memory", memory_rows))

    disk = info["disk"]
    sections.append(
        (
            "Disk",
            [
                ("Path", disk["path"]),
                ("Usage", f"{disk['usage_percent']}% used"),
                ("Available Space", human_bytes(disk["free"])),
            ],
        )
    )

    network = info["network"]
    network_rows = [("IP", ", ".join(network.get("ip_addresses", [])) or "Not detected")]
    if "bytes_sent" in network:
        network_rows.extend(
            [
                ("Sent", human_bytes(network["bytes_sent"])),
                ("Received", human_bytes(network["bytes_recv"])),
                ("Packets", f"{network['packets_sent']} sent / {network['packets_recv']} recv"),
            ]
        )
    sections.append(("Network", network_rows))

    if "boot_time" in info:
        system_rows = [
            ("Boot Time", info["boot_time"]),
            ("Uptime", format_seconds(info["uptime_seconds"])),
            ("Processes", str(info["process_count"])),
        ]
        if "battery" in info:
            battery = info["battery"]
            battery_text = f"{battery['percent']}% | Plugged: {battery['plugged']}"
            if battery["time_left_seconds"] is not None:
                battery_text += f" | {format_seconds(battery['time_left_seconds'])} left"
            system_rows.append(("Battery", battery_text))
        sections.append(("System", system_rows))

    benchmark_rows: list[tuple[str, str]]
    if benchmarks.cpu_loop_seconds is None:
        benchmark_rows = [("Status", "Skipped. Run benchmark to collect active speed tests.")]
    else:
        benchmark_rows = [
            (
                "CPU Loop",
                f"{benchmarks.cpu_loop_ops_per_sec:,.2f} ops/s ({benchmarks.cpu_loop_seconds}s)",
            ),
            ("Memory Copy", f"{benchmarks.memory_copy_mb_s} MB/s"),
            ("Disk Write", f"{benchmarks.disk_write_mb_s} MB/s"),
            ("Disk Read", f"{benchmarks.disk_read_mb_s} MB/s"),
            ("File Ops", f"{benchmarks.file_ops_per_sec:,.2f} ops/s"),
            (
                "TCP Latency",
                "Unavailable"
                if benchmarks.tcp_latency_ms is None
                else f"{benchmarks.tcp_latency_ms} ms",
            ),
        ]
    sections.append(("Benchmark", benchmark_rows))

    if not psutil:
        sections.append(
            (
                "Notes",
                [("Optional", "Install psutil for deeper live metrics when network is available.")],
            )
        )

    top_processes = info.get("top_processes", [])
    if top_processes:
        process_rows = [
            (
                f"{item['name']} (PID {item['pid']})",
                f"CPU {item['cpu_percent']}% | RAM {human_bytes(item['memory_rss'])}",
            )
            for item in top_processes
        ]
        sections.append(("Top Processes", process_rows))

    history = info.get("benchmark_history", [])
    if history:
        latest = history[-1]
        sections.append(
            (
                "History",
                [
                    ("Saved Runs", str(len(history))),
                    ("Last Run", str(latest.get("timestamp", "Unknown"))),
                    (
                        "Last CPU",
                        f"{latest.get('cpu_loop_ops_per_sec', 'N/A')} ops/s",
                    ),
                ],
            )
        )

    return sections


def launch_gui(run_benchmark_on_start: bool) -> int:
    if tk is None or ttk is None:
        print("GUI is not available because tkinter is not installed.")
        return 1

    root = tk.Tk()
    root.title("PC Speed Test Dashboard")
    root.geometry("1420x860")
    root.minsize(1220, 720)
    root.configure(bg="#09111f")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    palette = {
        "bg": "#09111f",
        "panel": "#122033",
        "panel_alt": "#0f1a2b",
        "text": "#eef4ff",
        "muted": "#9fb1c9",
        "accent": "#38bdf8",
        "accent_alt": "#0ea5e9",
        "line": "#1f3550",
    }

    style.configure("App.TFrame", background=palette["bg"])
    style.configure("CardOuter.TFrame", background=palette["panel"])
    style.configure("Card.TFrame", background=palette["panel"])
    style.configure("Header.TFrame", background=palette["bg"])
    style.configure(
        "CardTitle.TLabel",
        background=palette["panel"],
        foreground=palette["accent"],
        font=("Helvetica", 12, "bold"),
    )
    style.configure(
        "Title.TLabel",
        background=palette["bg"],
        foreground=palette["text"],
        font=("Helvetica", 22, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        background=palette["bg"],
        foreground=palette["muted"],
        font=("Helvetica", 10),
    )
    style.configure(
        "LabelKey.TLabel",
        background=palette["panel"],
        foreground=palette["muted"],
        font=("Helvetica", 10, "bold"),
    )
    style.configure(
        "LabelValue.TLabel",
        background=palette["panel"],
        foreground=palette["text"],
        font=("Helvetica", 10),
    )
    style.configure(
        "Status.TLabel",
        background=palette["bg"],
        foreground=palette["muted"],
        font=("Helvetica", 10),
    )
    style.configure(
        "Primary.TButton",
        background=palette["accent"],
        foreground="#04111d",
        borderwidth=0,
        focusthickness=0,
        focuscolor=palette["accent"],
        padding=(14, 8),
        font=("Helvetica", 10, "bold"),
    )
    style.map(
        "Primary.TButton",
        background=[("active", palette["accent_alt"]), ("pressed", palette["accent_alt"])],
    )
    style.configure(
        "Secondary.TButton",
        background=palette["panel"],
        foreground=palette["text"],
        borderwidth=1,
        relief="solid",
        padding=(12, 8),
        font=("Helvetica", 10, "bold"),
    )
    style.map(
        "Secondary.TButton",
        background=[("active", palette["panel_alt"]), ("pressed", palette["panel_alt"])],
    )
    style.configure(
        "App.Vertical.TScrollbar",
        background=palette["panel_alt"],
        troughcolor=palette["bg"],
        arrowcolor=palette["accent"],
        bordercolor=palette["bg"],
        darkcolor=palette["bg"],
        lightcolor=palette["bg"],
        gripcount=0,
        relief="flat",
        width=12,
    )
    style.map(
        "App.Vertical.TScrollbar",
        background=[
            ("active", palette["panel"]),
            ("pressed", palette["accent_alt"]),
        ],
    )

    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)

    header = ttk.Frame(root, style="Header.TFrame", padding=(20, 18, 20, 8))
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)

    ttk.Label(header, text="PC Speed Test Dashboard", style="Title.TLabel").grid(
        row=0, column=0, sticky="w"
    )
    subtitle_var = tk.StringVar(value="Grouped hardware panels with live refresh and benchmark.")
    ttk.Label(header, textvariable=subtitle_var, style="Subtitle.TLabel").grid(
        row=1, column=0, sticky="w", pady=(4, 0)
    )

    controls = ttk.Frame(header, style="Header.TFrame")
    controls.grid(row=0, column=1, rowspan=2, sticky="e")

    viewport = ttk.Frame(root, style="App.TFrame", padding=(20, 8, 20, 8))
    viewport.grid(row=1, column=0, sticky="nsew")
    viewport.columnconfigure(0, weight=1)
    viewport.rowconfigure(0, weight=1)

    content_canvas = tk.Canvas(
        viewport,
        bg=palette["bg"],
        highlightthickness=0,
        bd=0,
    )
    content_canvas.grid(row=0, column=0, sticky="nsew")

    auto_refresh_paused_for_scroll = False

    def update_scroll_pause_state() -> None:
        nonlocal auto_refresh_paused_for_scroll
        current_view = content_canvas.yview()
        auto_refresh_paused_for_scroll = bool(current_view and current_view[0] > 0.01)

    def on_scrollbar(*args: str) -> None:
        content_canvas.yview(*args)
        update_scroll_pause_state()

    scroll_bar = ttk.Scrollbar(
        viewport,
        orient="vertical",
        command=on_scrollbar,
        style="App.Vertical.TScrollbar",
    )
    scroll_bar.grid(row=0, column=1, sticky="ns")
    content_canvas.configure(yscrollcommand=scroll_bar.set)

    content = ttk.Frame(content_canvas, style="App.TFrame")
    content_window = content_canvas.create_window((0, 0), window=content, anchor="nw")
    for column in range(2):
        content.columnconfigure(column, weight=1)

    def sync_content_width(event: tk.Event) -> None:
        content_canvas.itemconfigure(content_window, width=max(event.width, 1160))

    def update_scroll_region() -> None:
        content_canvas.configure(scrollregion=content_canvas.bbox("all"))

    content_canvas.bind("<Configure>", sync_content_width)
    content.bind("<Configure>", lambda _event: update_scroll_region())

    def on_mousewheel(event: tk.Event) -> None:
        if getattr(event, "delta", 0):
            raw_delta = int(event.delta)
            step = -1 if raw_delta > 0 else 1
            if abs(raw_delta) >= 120:
                step = int(-raw_delta / 120)
            content_canvas.yview_scroll(step, "units")
            update_scroll_pause_state()
            return
        if getattr(event, "num", None) == 4:
            content_canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            content_canvas.yview_scroll(1, "units")
        update_scroll_pause_state()

    content_canvas.bind_all("<MouseWheel>", on_mousewheel)
    content_canvas.bind_all("<Button-4>", on_mousewheel)
    content_canvas.bind_all("<Button-5>", on_mousewheel)

    def capture_screenshot() -> None:
        if filedialog is None or messagebox is None:
            status_var.set("Screenshot dialogs are unavailable in this environment.")
            return

        default_name = f"pc_speed_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        selected_path = filedialog.asksaveasfilename(
            title="Save Dashboard Screenshot",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG image", "*.png")],
        )
        if not selected_path:
            return

        target_path = Path(selected_path)
        if target_path.suffix.lower() != ".png":
            target_path = target_path.with_suffix(".png")

        root.update_idletasks()
        x = root.winfo_rootx()
        y = root.winfo_rooty()
        width = root.winfo_width()
        height = root.winfo_height()

        system = platform.system()
        error_message = ""
        success = False
        try:
            if system == "Darwin":
                result = subprocess.run(
                    [
                        "screencapture",
                        "-x",
                        f"-R{x},{y},{width},{height}",
                        str(target_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                success = result.returncode == 0
                error_message = result.stderr.strip()
            else:
                error_message = "Screenshot capture is currently implemented for macOS."
        except OSError as exc:
            error_message = str(exc)

        if success:
            status_var.set(f"Screenshot saved: {target_path}")
            messagebox.showinfo("Screenshot Saved", f"Saved to:\n{target_path}")
        else:
            status_var.set("Failed to save screenshot.")
            messagebox.showerror("Screenshot Failed", error_message or "Could not save screenshot.")

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(root, textvariable=status_var, style="Status.TLabel").grid(
        row=2, column=0, sticky="ew", padx=20, pady=(0, 16)
    )

    panel_frames: list[ttk.Frame] = []
    memory_history: list[float] = []
    refresh_in_progress = False
    auto_refresh_job: str | None = None
    latest_payload: dict[str, Any] | None = None

    def render_disk_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        disk_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)

        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart_wrap.columnconfigure(1, weight=1)

        canvas = tk.Canvas(
            chart_wrap,
            width=180,
            height=180,
            bg=palette["panel"],
            highlightthickness=0,
            bd=0,
        )
        canvas.grid(row=0, column=0, sticky="n")

        used = float(disk_info.get("used", 0))
        free = float(disk_info.get("free", 0))
        total = float(disk_info.get("total", 0))
        if total <= 0:
            total = max(used + free, 1.0)

        used_extent = max(0.0, min(359.9, (used / total) * 360.0))
        radius_box = (18, 18, 162, 162)
        arc_width = 26
        used_color = "#38bdf8"
        free_color = "#22c55e"
        total_color = "#94a3b8"

        canvas.create_oval(*radius_box, outline=palette["line"], width=arc_width)
        if free > 0:
            canvas.create_arc(
                *radius_box,
                start=90,
                extent=-(360.0 - used_extent),
                style="arc",
                outline=free_color,
                width=arc_width,
            )
        if used > 0:
            canvas.create_arc(
                *radius_box,
                start=90,
                extent=-used_extent,
                style="arc",
                outline=used_color,
                width=arc_width,
            )

        canvas.create_text(
            90,
            78,
            text="TOTAL",
            fill=palette["muted"],
            font=("Helvetica", 10, "bold"),
        )
        canvas.create_text(
            90,
            102,
            text=human_bytes(total),
            fill=palette["text"],
            font=("Helvetica", 13, "bold"),
        )

        legend = ttk.Frame(chart_wrap, style="Card.TFrame")
        legend.grid(row=0, column=1, sticky="nw", padx=(14, 0), pady=(8, 0))
        legend_items = [
            ("Used", used_color, f"{human_bytes(used)} ({disk_info.get('usage_percent', 0)}%)"),
            ("Free", free_color, human_bytes(free)),
            ("Total", total_color, human_bytes(total)),
        ]
        for row_index, (label, color, value) in enumerate(legend_items):
            dot = tk.Canvas(
                legend,
                width=10,
                height=10,
                bg=palette["panel"],
                highlightthickness=0,
                bd=0,
            )
            dot.grid(row=row_index, column=0, sticky="w", padx=(0, 8), pady=3)
            dot.create_oval(1, 1, 9, 9, fill=color, outline=color)
            ttk.Label(legend, text=label, style="LabelKey.TLabel").grid(
                row=row_index, column=1, sticky="w", pady=3
            )
            ttk.Label(legend, text=value, style="LabelValue.TLabel").grid(
                row=row_index, column=2, sticky="w", padx=(10, 0), pady=3
            )

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        details.columnconfigure(1, weight=1)
        for row_index, (key, value) in enumerate(rows):
            ttk.Label(details, text=key, style="LabelKey.TLabel").grid(
                row=row_index,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=4,
            )
            ttk.Label(
                details,
                text=value,
                style="LabelValue.TLabel",
                justify="left",
                wraplength=340,
            ).grid(row=row_index, column=1, sticky="nw", pady=4)

    def render_key_value_rows(
        parent: ttk.Frame,
        rows: list[tuple[str, str]],
        wraplength: int = 340,
    ) -> None:
        parent.columnconfigure(1, weight=1)
        for row_index, (key, value) in enumerate(rows):
            ttk.Label(parent, text=key, style="LabelKey.TLabel").grid(
                row=row_index,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=4,
            )
            ttk.Label(
                parent,
                text=value,
                style="LabelValue.TLabel",
                justify="left",
                wraplength=wraplength,
            ).grid(row=row_index, column=1, sticky="nw", pady=4)

    def draw_meter(
        canvas: tk.Canvas,
        y: float,
        label: str,
        ratio: float,
        value_text: str,
        fill_color: str,
        width: int = 300,
    ) -> None:
        ratio = max(0.0, min(ratio, 1.0))
        x1 = 16
        x2 = x1 + width
        canvas.create_text(x1, y - 10, text=label, fill=palette["muted"], font=("Helvetica", 9, "bold"), anchor="w")
        canvas.create_rectangle(x1, y, x2, y + 14, fill=palette["panel_alt"], outline=palette["line"], width=1)
        canvas.create_rectangle(x1, y, x1 + (width * ratio), y + 14, fill=fill_color, outline=fill_color, width=1)
        canvas.create_text(x2, y - 10, text=value_text, fill=palette["text"], font=("Helvetica", 9), anchor="e")

    def render_memory_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        memory_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)

        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)

        chart = tk.Canvas(
            chart_wrap,
            width=320,
            height=180,
            bg=palette["panel"],
            highlightthickness=0,
            bd=0,
        )
        chart.grid(row=0, column=0, sticky="n")

        chart_width = 320
        chart_height = 180
        left_pad = 18
        right_pad = 10
        top_pad = 12
        bottom_pad = 24
        plot_width = chart_width - left_pad - right_pad
        plot_height = chart_height - top_pad - bottom_pad

        chart.create_rectangle(
            left_pad,
            top_pad,
            left_pad + plot_width,
            top_pad + plot_height,
            outline=palette["line"],
            width=1,
        )

        for marker in (25, 50, 75):
            y = top_pad + plot_height - (marker / 100.0) * plot_height
            chart.create_line(
                left_pad,
                y,
                left_pad + plot_width,
                y,
                fill=palette["line"],
                width=1,
                dash=(3, 3),
            )
            chart.create_text(
                10,
                y,
                text=f"{marker}%",
                fill=palette["muted"],
                font=("Helvetica", 8),
            )

        if len(memory_history) >= 2:
            points: list[float] = []
            denominator = max(len(memory_history) - 1, 1)
            for index, value in enumerate(memory_history):
                x = left_pad + (index / denominator) * plot_width
                y = top_pad + plot_height - (max(0.0, min(value, 100.0)) / 100.0) * plot_height
                points.extend([x, y])
            chart.create_line(
                *points,
                fill=palette["accent"],
                width=3,
                smooth=True,
            )

        if memory_history:
            latest = memory_history[-1]
            marker_x = left_pad + plot_width
            marker_y = top_pad + plot_height - (max(0.0, min(latest, 100.0)) / 100.0) * plot_height
            chart.create_oval(
                marker_x - 4,
                marker_y - 4,
                marker_x + 4,
                marker_y + 4,
                fill=palette["accent"],
                outline=palette["accent"],
            )
            chart.create_text(
                marker_x - 8,
                marker_y - 12,
                text=f"{latest:.1f}%",
                fill=palette["text"],
                font=("Helvetica", 9, "bold"),
                anchor="e",
            )

        chart.create_text(
            left_pad,
            chart_height - 8,
            text=f"Last {len(memory_history)} samples",
            fill=palette["muted"],
            font=("Helvetica", 8),
            anchor="w",
        )

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_overview_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)

        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")
        cpu_ratio = float(info.get("cpu", {}).get("usage_percent", 0.0)) / 100.0
        mem_ratio = float(info.get("memory", {}).get("usage_percent", 0.0)) / 100.0 if "memory" in info else 0.0
        disk_ratio = float(info.get("disk", {}).get("usage_percent", 0.0)) / 100.0
        draw_meter(chart, 36, "CPU Load", cpu_ratio, f"{cpu_ratio * 100:.1f}%", "#38bdf8")
        draw_meter(chart, 84, "Memory Use", mem_ratio, f"{mem_ratio * 100:.1f}%", "#22c55e")
        draw_meter(chart, 132, "Disk Use", disk_ratio, f"{disk_ratio * 100:.1f}%", "#f59e0b")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_cpu_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        cpu_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)

        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        usage = float(cpu_info.get("usage_percent", 0.0))
        freq = float(cpu_info.get("current_freq_mhz", 0.0))
        max_freq = float(cpu_info.get("max_freq_mhz", 0.0))
        freq_ratio = (freq / max_freq) if max_freq > 0 else 0.0

        chart.create_oval(26, 20, 146, 140, outline=palette["line"], width=14)
        chart.create_arc(
            26,
            20,
            146,
            140,
            start=90,
            extent=-(usage * 3.6),
            style="arc",
            outline=palette["accent"],
            width=14,
        )
        chart.create_text(86, 68, text="CPU", fill=palette["muted"], font=("Helvetica", 10, "bold"))
        chart.create_text(86, 92, text=f"{usage:.1f}%", fill=palette["text"], font=("Helvetica", 16, "bold"))
        draw_meter(chart, 56, "Frequency", freq_ratio, f"{freq:.0f}/{max_freq:.0f} MHz" if max_freq else f"{freq:.0f} MHz", "#22c55e", width=140)
        draw_meter(
            chart,
            104,
            "Threads",
            min(float(cpu_info.get("logical_cores", 0)) / max(float(cpu_info.get("physical_cores", 1)) * 2.0, 1.0), 1.0),
            f"{cpu_info.get('logical_cores', 0)} logical",
            "#f59e0b",
            width=140,
        )

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_gpu_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        gpu_name: str,
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        gpu_lower = gpu_name.lower()
        mode = "Unified" if "apple" in gpu_lower or "m1" in gpu_lower or "m2" in gpu_lower or "m3" in gpu_lower or "m4" in gpu_lower else "Integrated" if "intel" in gpu_lower or "iris" in gpu_lower or "uhd" in gpu_lower else "Discrete"
        segments = [("Integrated", "#38bdf8"), ("Discrete", "#f97316"), ("Unified", "#22c55e")]
        chart.create_text(16, 20, text="Graphics Class", fill=palette["muted"], font=("Helvetica", 9, "bold"), anchor="w")
        start_x = 16
        for label, color in segments:
            width = 96
            fill = color if label == mode else palette["panel_alt"]
            text_color = "#03111d" if label == mode else palette["muted"]
            chart.create_rectangle(start_x, 36, start_x + width, 68, fill=fill, outline=palette["line"], width=1)
            chart.create_text(start_x + (width / 2), 52, text=label, fill=text_color, font=("Helvetica", 9, "bold"))
            start_x += width + 8
        chart.create_rectangle(16, 92, 316, 142, fill=palette["panel_alt"], outline=palette["line"], width=1)
        chart.create_text(166, 108, text="GPU Identity", fill=palette["muted"], font=("Helvetica", 9, "bold"))
        chart.create_text(166, 128, text=gpu_name, fill=palette["text"], font=("Helvetica", 11, "bold"), width=280)

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_network_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        network_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        sent = float(network_info.get("bytes_sent", 0.0))
        recv = float(network_info.get("bytes_recv", 0.0))
        total = max(sent + recv, 1.0)
        packets_sent = float(network_info.get("packets_sent", 0.0))
        packets_recv = float(network_info.get("packets_recv", 0.0))
        packet_total = max(packets_sent + packets_recv, 1.0)
        draw_meter(chart, 36, "Traffic Sent", sent / total, human_bytes(sent), "#38bdf8")
        draw_meter(chart, 84, "Traffic Recv", recv / total, human_bytes(recv), "#22c55e")
        draw_meter(chart, 132, "Packet Mix", packets_recv / packet_total, f"{int(packets_recv)} recv", "#f59e0b")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_system_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        uptime_seconds = float(info.get("uptime_seconds", 0.0))
        uptime_days = uptime_seconds / 86400.0
        uptime_ratio = min(uptime_days / 30.0, 1.0)
        draw_meter(chart, 36, "Uptime Window", uptime_ratio, f"{uptime_days:.1f} days", "#38bdf8")
        process_ratio = min(float(info.get("process_count", 0)) / 500.0, 1.0)
        draw_meter(chart, 84, "Process Load", process_ratio, str(info.get("process_count", 0)), "#22c55e")
        battery = info.get("battery")
        battery_ratio = (float(battery.get("percent", 0.0)) / 100.0) if isinstance(battery, dict) else 0.0
        battery_text = f"{battery.get('percent', 0)}%" if isinstance(battery, dict) else "N/A"
        draw_meter(chart, 132, "Battery", battery_ratio, battery_text, "#f59e0b")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_benchmark_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        benchmarks: Benchmarks,
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=206, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        metrics = [
            ("CPU", benchmarks.cpu_loop_ops_per_sec or 0.0, "#38bdf8"),
            ("Mem", benchmarks.memory_copy_mb_s or 0.0, "#22c55e"),
            ("Write", benchmarks.disk_write_mb_s or 0.0, "#f59e0b"),
            ("Read", benchmarks.disk_read_mb_s or 0.0, "#a78bfa"),
            ("Files", benchmarks.file_ops_per_sec or 0.0, "#f97316"),
        ]
        max_value = max((value for _, value, _ in metrics), default=1.0) or 1.0
        base_y = 182
        bar_width = 44
        gap = 16
        start_x = 18
        chart.create_line(14, base_y, 318, base_y, fill=palette["line"], width=1)
        for index, (label, value, color) in enumerate(metrics):
            x1 = start_x + index * (bar_width + gap)
            x2 = x1 + bar_width
            height = (value / max_value) * 128 if max_value else 0.0
            y1 = base_y - height
            chart.create_rectangle(x1, y1, x2, base_y, fill=color, outline=color)
            chart.create_text((x1 + x2) / 2, y1 - 10, text=f"{value:.0f}", fill=palette["muted"], font=("Helvetica", 8))
            chart.create_text((x1 + x2) / 2, base_y + 12, text=label, fill=palette["text"], font=("Helvetica", 8, "bold"))
        latency = "n/a" if benchmarks.tcp_latency_ms is None else f"{benchmarks.tcp_latency_ms} ms"
        chart.create_text(16, 18, text=f"TCP latency: {latency}", fill=palette["muted"], font=("Helvetica", 9), anchor="w")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_payload(payload: dict[str, Any]) -> None:
        nonlocal latest_payload
        latest_payload = payload
        current_scroll = content_canvas.yview()
        top_pixel = max(content_canvas.canvasy(0), 0.0)
        for frame in panel_frames:
            frame.destroy()
        panel_frames.clear()

        info = payload["info"]
        benchmarks = Benchmarks(**payload["benchmarks"])
        sections = build_sections(info, benchmarks)
        memory = info.get("memory")
        if memory and "usage_percent" in memory:
            memory_history.append(float(memory["usage_percent"]))
            del memory_history[:-60]
        column_count = 2
        for column in range(2):
            content.columnconfigure(column, weight=1 if column < column_count else 0)

        for index, (title, rows) in enumerate(sections):
            panel = ttk.Frame(content, style="CardOuter.TFrame", padding=(14, 12))
            panel.grid(
                row=index // column_count,
                column=index % column_count,
                sticky="nsew",
                padx=8,
                pady=8,
            )
            content.rowconfigure(index // column_count, weight=1)
            panel_frames.append(panel)
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(1, weight=1)

            ttk.Label(panel, text=title, style="CardTitle.TLabel").grid(
                row=0,
                column=0,
                sticky="w",
                pady=(0, 10),
            )

            panel_body = ttk.Frame(panel, style="Card.TFrame")
            panel_body.grid(row=1, column=0, sticky="nsew")
            panel_body.columnconfigure(1, weight=1)

            if title == "Overview":
                render_overview_panel(panel_body, rows, info)
                continue
            if title == "CPU":
                render_cpu_panel(panel_body, rows, info["cpu"])
                continue
            if title == "GPU":
                render_gpu_panel(panel_body, rows, info["gpu"])
                continue
            if title == "Disk":
                render_disk_panel(panel_body, rows, info["disk"])
                continue
            if title == "Memory" and memory and "usage_percent" in memory:
                render_memory_panel(panel_body, rows, memory)
                continue
            if title == "Network":
                render_network_panel(panel_body, rows, info["network"])
                continue
            if title == "System":
                render_system_panel(panel_body, rows, info)
                continue
            if title == "Benchmark":
                render_benchmark_panel(panel_body, rows, benchmarks)
                continue

            render_key_value_rows(panel_body, rows, wraplength=420)

        update_scroll_region()

        def restore_scroll_position() -> None:
            bbox = content_canvas.bbox("all")
            if not bbox:
                return
            content_height = max(float(bbox[3] - bbox[1]), 0.0)
            viewport_height = float(content_canvas.winfo_height())
            scrollable_height = max(content_height - viewport_height, 0.0)
            if scrollable_height <= 0:
                content_canvas.yview_moveto(0.0)
                return

            if top_pixel > 0:
                target_fraction = min(top_pixel / scrollable_height, 1.0)
            elif current_scroll:
                target_fraction = min(max(current_scroll[0], 0.0), 1.0)
            else:
                target_fraction = 0.0
            content_canvas.yview_moveto(target_fraction)
            update_scroll_pause_state()

        root.after_idle(lambda: root.after_idle(restore_scroll_position))
        subtitle_var.set(
            f"Last update: {info['timestamp']} | psutil: {'yes' if payload['psutil_available'] else 'no'}"
        )

    def export_report_from_gui() -> None:
        if filedialog is None or messagebox is None:
            status_var.set("Report export dialogs are unavailable in this environment.")
            return
        if latest_payload is None:
            status_var.set("No data available yet. Refresh once before exporting.")
            return

        target = filedialog.asksaveasfilename(
            title="Export PC Speed Test Report",
            defaultextension=".pdf",
            initialfile=f"{default_report_stem(latest_payload['info'])}.pdf",
            filetypes=[
                ("PDF report", "*.pdf"),
                ("Text report", "*.txt"),
                ("JSON report", "*.json"),
            ],
        )
        if not target:
            return

        target_path = Path(target)
        suffix = target_path.suffix.lower()
        if suffix == ".txt":
            fmt = "txt"
        elif suffix == ".json":
            fmt = "json"
        else:
            fmt = "pdf"
            if suffix != ".pdf":
                target_path = target_path.with_suffix(".pdf")

        try:
            saved_path = export_report(latest_payload, fmt=fmt, base_path=target_path)
        except Exception as exc:
            status_var.set("Failed to export report.")
            messagebox.showerror("Export Failed", str(exc))
            return

        status_var.set(f"Report exported: {saved_path}")
        messagebox.showinfo("Report Exported", f"Saved to:\n{saved_path}")

    def load_payload(include_benchmark: bool) -> None:
        nonlocal refresh_in_progress
        if refresh_in_progress:
            return
        refresh_in_progress = True

        def worker() -> None:
            action = "benchmark" if include_benchmark else "refresh"
            root.after(0, lambda: status_var.set(f"Running {action}..."))
            try:
                payload = build_output(include_benchmark=include_benchmark)
            except Exception as exc:  # pragma: no cover - defensive GUI path
                def show_error() -> None:
                    nonlocal refresh_in_progress
                    refresh_in_progress = False
                    status_var.set(f"Failed: {exc}")

                root.after(0, show_error)
                return

            def apply_result() -> None:
                nonlocal refresh_in_progress
                render_payload(payload)
                if include_benchmark:
                    status_var.set("Benchmark completed.")
                else:
                    status_var.set("System info refreshed.")
                refresh_in_progress = False

            root.after(0, apply_result)

        threading.Thread(target=worker, daemon=True).start()

    def schedule_auto_refresh() -> None:
        nonlocal auto_refresh_job
        if auto_refresh_job is not None:
            root.after_cancel(auto_refresh_job)
        update_scroll_pause_state()
        if not auto_refresh_paused_for_scroll:
            load_payload(False)
        elif not refresh_in_progress:
            status_var.set("Auto refresh paused while scrolling. Return near the top to resume.")
        auto_refresh_job = root.after(AUTO_REFRESH_MS, schedule_auto_refresh)

    ttk.Button(
        controls,
        text="Refresh",
        style="Secondary.TButton",
        command=lambda: load_payload(False),
    ).grid(row=0, column=0, padx=(0, 10))
    ttk.Button(
        controls,
        text="Capture",
        style="Secondary.TButton",
        command=capture_screenshot,
    ).grid(row=0, column=1, padx=(0, 10))
    ttk.Button(
        controls,
        text="Export Report",
        style="Secondary.TButton",
        command=export_report_from_gui,
    ).grid(row=0, column=2, padx=(0, 10))
    ttk.Button(
        controls,
        text="Run Benchmark",
        style="Primary.TButton",
        command=lambda: load_payload(True),
    ).grid(row=0, column=3)

    if run_benchmark_on_start:
        load_payload(True)
    else:
        load_payload(False)
    auto_refresh_job = root.after(AUTO_REFRESH_MS, schedule_auto_refresh)
    root.mainloop()
    return 0


def build_output(include_benchmark: bool) -> dict[str, Any]:
    ensure_output_dirs()
    info = gather_basic_info()
    info["top_processes"] = gather_top_processes()
    benchmarks = gather_benchmarks(include_benchmark)
    if include_benchmark and benchmarks.cpu_loop_seconds is not None:
        info["benchmark_history"] = append_benchmark_history(info, benchmarks)
    else:
        info["benchmark_history"] = load_benchmark_history()
    return {
        "info": info,
        "benchmarks": asdict(benchmarks),
        "psutil_available": bool(psutil),
    }


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def print_text(payload: dict[str, Any]) -> None:
    info = payload["info"]
    benchmarks = Benchmarks(**payload["benchmarks"])
    print(render_text_report(info, benchmarks))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect system details and run lightweight speed tests."
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run active CPU and disk benchmarks (takes a few seconds).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of a human-readable report.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open a desktop GUI dashboard with grouped panels.",
    )
    parser.add_argument(
        "--export-report",
        action="store_true",
        help="Export a report file after collecting data.",
    )
    parser.add_argument(
        "--report-format",
        choices=("pdf", "txt", "json"),
        default="pdf",
        help="Format used with --export-report. Default: pdf.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.gui:
        return launch_gui(run_benchmark_on_start=args.benchmark)
    payload = build_output(include_benchmark=args.benchmark)
    if args.export_report:
        try:
            exported = export_report(payload, fmt=args.report_format)
            print(f"Report exported: {exported}")
        except Exception as exc:
            print(f"Report export failed: {exc}", file=sys.stderr)
            if args.report_format == "pdf":
                print("Tip: install reportlab or export with --report-format txt/json", file=sys.stderr)
    if args.json:
        print_json(payload)
    else:
        print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
