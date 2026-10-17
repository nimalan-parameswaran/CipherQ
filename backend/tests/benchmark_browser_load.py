"""
Empirical Performance and Memory Profiling Script for CipherQ
Measures throughput, latency, process RSS memory delta, and concurrency overhead
during streaming AEAD uploads and downloads with realistic file sizes.
"""
import os
import sys
import time
import socket
import platform
import tempfile
import asyncio
import subprocess
import urllib.request
from pathlib import Path
import psutil
import httpx

import nacl


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_system_specs():
    cpu_freq = psutil.cpu_freq()
    freq_str = f"{cpu_freq.current:.1f} MHz" if cpu_freq else "Unknown"
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.architecture()[0]})",
        "cpu": f"{platform.processor() or platform.machine()} ({psutil.cpu_count(logical=False)} cores, {psutil.cpu_count(logical=True)} threads @ {freq_str})",
        "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "python_version": platform.python_version(),
        "libsodium_version": f"PyNaCl {nacl.__version__} (libsodium engine)"
    }


class BenchmarkRunner:
    def __init__(self):
        self.port = get_free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tpath = Path(self.tmp_dir.name)
        self.proc = None
        self.server_psutil = None

    def start_server(self):
        env = os.environ.copy()
        env["DATA_DIR"] = str(self.tpath / "data")
        env["VAULT_DIR"] = str(self.tpath / "vault")
        env["KEYS_DIR"] = str(self.tpath / "keys")
        env["MASTER_KEY_PATH"] = str(self.tpath / "keys" / ".vault_master.key")
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{self.tpath}/data/bench.db"
        env["PREMIUM_QUOTA_BYTES"] = str(10 * 1024 * 1024 * 1024)  # 10 GB for load testing

        cmd = [
            sys.executable, "-m", "uvicorn", "backend.app.main:app",
            "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "error"
        ]
        self.proc = subprocess.Popen(cmd, env=env)
        self.server_psutil = psutil.Process(self.proc.pid)

        # Wait for health
        for _ in range(40):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(f"{self.base_url}/api/v1/health") as resp:
                    if resp.status == 200:
                        return
            except Exception:
                pass
        raise RuntimeError("Benchmark server failed to start.")

    def stop_server(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        time.sleep(0.5)
        self.tmp_dir.cleanup()

    def get_server_rss_mb(self) -> float:
        try:
            mem = self.server_psutil.memory_info().rss
            for child in self.server_psutil.children(recursive=True):
                try:
                    mem += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return round(mem / (1024 * 1024), 2)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0


async def profile_transfers():
    runner = BenchmarkRunner()
    runner.start_server()
    specs = get_system_specs()
    print("=" * 70)
    print("CIPHERQ EMPIRICAL PROFILE & RESOURCE UTILIZATION BENCHMARK")
    print("=" * 70)
    print(f"OS:               {specs['os']}")
    print(f"CPU:              {specs['cpu']}")
    print(f"RAM:              {specs['total_ram_gb']} GB")
    print(f"Python:           {specs['python_version']}")
    print(f"Libsodium:        {specs['libsodium_version']}")
    print("=" * 70)

    results = []

    async with httpx.AsyncClient(base_url=runner.base_url, timeout=120.0) as client:
        # 1. Register and Login a test Premium user
        reg_resp = await client.post("/api/v1/auth/register", json={
            "email": "bench_user@example.com",
            "password": "BenchmarkPassword2026!",
            "plan_type": "PREMIUM"
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "bench_user@example.com",
            "password": "BenchmarkPassword2026!"
        })
        csrf_token = login_resp.json()["csrf_token"]
        auth_headers = {"X-CSRF-Token": csrf_token}

        # -------------------------------------------------------------
        # Test 1: 25 MB Upload & Download Streaming Profiling
        # -------------------------------------------------------------
        size_25mb = 25 * 1024 * 1024
        payload_25mb = os.urandom(size_25mb)

        # Baseline RAM
        baseline_ram = runner.get_server_rss_mb()

        # Upload 25 MB
        t0 = time.perf_counter()
        upload_resp = await client.post(
            "/api/v1/files",
            files={"file": ("bench_25mb.bin", payload_25mb, "application/octet-stream")},
            headers=auth_headers
        )
        t_upload_25 = time.perf_counter() - t0
        peak_upload_ram = runner.get_server_rss_mb()
        assert upload_resp.status_code == 201, f"Upload 25MB failed: {upload_resp.text}"
        file_25_id = upload_resp.json()["id"]

        # Download 25 MB
        t0 = time.perf_counter()
        download_resp = await client.get(f"/api/v1/files/{file_25_id}/download")
        t_download_25 = time.perf_counter() - t0
        peak_download_ram = runner.get_server_rss_mb()
        assert download_resp.status_code == 200
        assert download_resp.content == payload_25mb, "25MB downloaded plaintext integrity mismatch!"

        upload_25_mbps = round((25 / t_upload_25), 2)
        download_25_mbps = round((25 / t_download_25), 2)

        results.append({
            "test": "25 MB Single Transfer",
            "size_mb": 25,
            "upload_time_s": round(t_upload_25, 3),
            "upload_throughput_mb_s": upload_25_mbps,
            "download_time_s": round(t_download_25, 3),
            "download_throughput_mb_s": download_25_mbps,
            "baseline_ram_mb": baseline_ram,
            "peak_upload_ram_mb": peak_upload_ram,
            "peak_download_ram_mb": peak_download_ram,
            "ram_delta_mb": round(max(peak_upload_ram, peak_download_ram) - baseline_ram, 2)
        })

        # -------------------------------------------------------------
        # Test 2: 50 MB Upload & Download Streaming Profiling
        # -------------------------------------------------------------
        size_50mb = 50 * 1024 * 1024
        payload_50mb = os.urandom(size_50mb)

        ram_pre_50 = runner.get_server_rss_mb()

        # Upload 50 MB
        t0 = time.perf_counter()
        upload_resp_50 = await client.post(
            "/api/v1/files",
            files={"file": ("bench_50mb.bin", payload_50mb, "application/octet-stream")},
            headers=auth_headers
        )
        t_upload_50 = time.perf_counter() - t0
        peak_upload_ram_50 = runner.get_server_rss_mb()
        assert upload_resp_50.status_code == 201
        file_50_id = upload_resp_50.json()["id"]

        # Download 50 MB
        t0 = time.perf_counter()
        download_resp_50 = await client.get(f"/api/v1/files/{file_50_id}/download")
        t_download_50 = time.perf_counter() - t0
        peak_download_ram_50 = runner.get_server_rss_mb()
        print(f"50MB Download Status: {download_resp_50.status_code}, Length: {len(download_resp_50.content)}")
        assert download_resp_50.status_code == 200
        assert download_resp_50.content == payload_50mb, "50MB downloaded plaintext integrity mismatch!"

        upload_50_mbps = round((50 / t_upload_50), 2)
        download_50_mbps = round((50 / t_download_50), 2)

        results.append({
            "test": "50 MB Single Transfer",
            "size_mb": 50,
            "upload_time_s": round(t_upload_50, 3),
            "upload_throughput_mb_s": upload_50_mbps,
            "download_time_s": round(t_download_50, 3),
            "download_throughput_mb_s": download_50_mbps,
            "baseline_ram_mb": ram_pre_50,
            "peak_upload_ram_mb": peak_upload_ram_50,
            "peak_download_ram_mb": peak_download_ram_50,
            "ram_delta_mb": round(max(peak_upload_ram_50, peak_download_ram_50) - ram_pre_50, 2)
        })

        # -------------------------------------------------------------
        # Test 3: 100 MB Upload & Download Streaming Profiling
        # -------------------------------------------------------------
        size_100mb = 100 * 1024 * 1024
        payload_100mb = os.urandom(size_100mb)

        ram_pre_100 = runner.get_server_rss_mb()

        # Upload 100 MB
        t0 = time.perf_counter()
        upload_resp_100 = await client.post(
            "/api/v1/files",
            files={"file": ("bench_100mb.bin", payload_100mb, "application/octet-stream")},
            headers=auth_headers
        )
        t_upload_100 = time.perf_counter() - t0
        peak_upload_ram_100 = runner.get_server_rss_mb()
        assert upload_resp_100.status_code == 201
        file_100_id = upload_resp_100.json()["id"]

        # Download 100 MB
        t0 = time.perf_counter()
        download_resp_100 = await client.get(f"/api/v1/files/{file_100_id}/download")
        t_download_100 = time.perf_counter() - t0
        peak_download_ram_100 = runner.get_server_rss_mb()
        assert download_resp_100.status_code == 200
        assert download_resp_100.content == payload_100mb, "100MB downloaded plaintext integrity mismatch!"

        upload_100_mbps = round((100 / t_upload_100), 2)
        download_100_mbps = round((100 / t_download_100), 2)

        results.append({
            "test": "100 MB Single Transfer",
            "size_mb": 100,
            "upload_time_s": round(t_upload_100, 3),
            "upload_throughput_mb_s": upload_100_mbps,
            "download_time_s": round(t_download_100, 3),
            "download_throughput_mb_s": download_100_mbps,
            "baseline_ram_mb": ram_pre_100,
            "peak_upload_ram_mb": peak_upload_ram_100,
            "peak_download_ram_mb": peak_download_ram_100,
            "ram_delta_mb": round(max(peak_upload_ram_100, peak_download_ram_100) - ram_pre_100, 2)
        })

        # -------------------------------------------------------------
        # Test 4: 2 Concurrent 25 MB Streaming Transfers
        # -------------------------------------------------------------
        c_payload_1 = os.urandom(25 * 1024 * 1024)
        c_payload_2 = os.urandom(25 * 1024 * 1024)

        ram_pre_conc = runner.get_server_rss_mb()

        # Concurrent Uploads
        t0 = time.perf_counter()
        up_task1 = client.post(
            "/api/v1/files",
            files={"file": ("concurrent_1.bin", c_payload_1, "application/octet-stream")},
            headers=auth_headers
        )
        up_task2 = client.post(
            "/api/v1/files",
            files={"file": ("concurrent_2.bin", c_payload_2, "application/octet-stream")},
            headers=auth_headers
        )
        res1, res2 = await asyncio.gather(up_task1, up_task2)
        t_conc_upload = time.perf_counter() - t0
        peak_conc_up_ram = runner.get_server_rss_mb()

        assert res1.status_code == 201 and res2.status_code == 201
        c_id1 = res1.json()["id"]
        c_id2 = res2.json()["id"]

        # Concurrent Downloads
        t0 = time.perf_counter()
        down_task1 = client.get(f"/api/v1/files/{c_id1}/download")
        down_task2 = client.get(f"/api/v1/files/{c_id2}/download")
        d_res1, d_res2 = await asyncio.gather(down_task1, down_task2)
        t_conc_download = time.perf_counter() - t0
        peak_conc_down_ram = runner.get_server_rss_mb()

        assert d_res1.status_code == 200 and d_res2.status_code == 200
        assert d_res1.content == c_payload_1
        assert d_res2.content == c_payload_2

        total_conc_mb = 50.0  # 25MB * 2
        conc_up_mbps = round((total_conc_mb / t_conc_upload), 2)
        conc_down_mbps = round((total_conc_mb / t_conc_download), 2)

        results.append({
            "test": "2x 25 MB Concurrent Transfers (50 MB Aggregate)",
            "size_mb": 50,
            "upload_time_s": round(t_conc_upload, 3),
            "upload_throughput_mb_s": conc_up_mbps,
            "download_time_s": round(t_conc_download, 3),
            "download_throughput_mb_s": conc_down_mbps,
            "baseline_ram_mb": ram_pre_conc,
            "peak_upload_ram_mb": peak_conc_up_ram,
            "peak_download_ram_mb": peak_conc_down_ram,
            "ram_delta_mb": round(max(peak_conc_up_ram, peak_conc_down_ram) - ram_pre_conc, 2)
        })

    runner.stop_server()

    # Print Table of Measured Results
    print("\nMEASURED EMPIRICAL PROFILING RESULTS:")
    print("-" * 105)
    print(f"{'Scenario':<40} | {'Size':<6} | {'Up Time':<8} | {'Up MB/s':<9} | {'Down Time':<10} | {'Down MB/s':<10} | {'Peak RAM':<9} | {'RAM Delta':<9}")
    print("-" * 105)
    for r in results:
        print(
            f"{r['test']:<40} | "
            f"{r['size_mb']:>4} MB | "
            f"{r['upload_time_s']:>6.2f} s | "
            f"{r['upload_throughput_mb_s']:>7.2f} | "
            f"{r['download_time_s']:>8.2f} s | "
            f"{r['download_throughput_mb_s']:>8.2f} | "
            f"{max(r['peak_upload_ram_mb'], r['peak_download_ram_mb']):>7.1f} MB | "
            f"+{r['ram_delta_mb']:>6.1f} MB"
        )
    print("-" * 105)

    return specs, results


if __name__ == "__main__":
    asyncio.run(profile_transfers())
