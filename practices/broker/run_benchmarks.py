import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-sec", type=int, default=20, help="Duration per scenario")
    parser.add_argument("--sizes", nargs="+", type=int, default=[128, 1024, 10240, 102400])
    parser.add_argument("--rates", nargs="+", type=int, default=[1000, 5000, 10000])
    parser.add_argument("--brokers", nargs="+", default=["rabbitmq", "redis"], choices=["rabbitmq", "redis"])
    parser.add_argument("--max-wait-sec", type=int, default=30)
    parser.add_argument("--out-dir", default="results", help="Output directory for metrics")
    return parser.parse_args()


def extract_json(stdout):
    for line in stdout.splitlines()[::-1]:
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise ValueError(f"Cannot find JSON in output: {stdout}")


def run_command(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return extract_json(proc.stdout)


def run_single_case(
    broker: str,
    size: int,
    rate: int,
    duration_sec: int,
    max_wait_sec: int,
):
    count = duration_sec * rate
    queue = f"{broker}_q_{size}_{rate}_{int(time.time() * 1000)}"

    consumer_cmd = [
        sys.executable,
        "consumer.py",
        "--broker",
        broker,
        "--count",
        str(count),
        "--queue",
        queue,
        "--max-wait-sec",
        str(max_wait_sec),
    ]
    producer_cmd = [
        sys.executable,
        "producer.py",
        "--broker",
        broker,
        "--count",
        str(count),
        "--size",
        str(size),
        "--rate",
        str(rate),
        "--queue",
        queue,
    ]

    consumer_proc = subprocess.Popen(consumer_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1)

    producer_metrics = run_command(producer_cmd)
    consumer_stdout, consumer_stderr = consumer_proc.communicate(timeout=duration_sec + max_wait_sec + 30)
    if consumer_proc.returncode != 0:
        raise RuntimeError(
            f"Consumer failed ({consumer_proc.returncode})\nSTDOUT:\n{consumer_stdout}\nSTDERR:\n{consumer_stderr}"
        )
    consumer_metrics = extract_json(consumer_stdout)

    row = {
        "broker": broker,
        "size_bytes": size,
        "rate_target_msg_sec": rate,
        "duration_target_sec": duration_sec,
        "count_target": count,
        "producer_sent": producer_metrics["sent"],
        "producer_errors": producer_metrics["errors"],
        "producer_actual_rate_msg_sec": round(producer_metrics["actual_rate_msg_sec"], 2),
        "consumer_consumed": consumer_metrics["consumed"],
        "consumer_errors": consumer_metrics["errors"],
        "lost_messages": consumer_metrics["lost"],
        "consumer_throughput_msg_sec": round(consumer_metrics["throughput_msg_sec"], 2),
        "avg_latency_ms": round(consumer_metrics["avg_latency_ms"], 2),
        "p95_latency_ms": round(consumer_metrics["p95_latency_ms"], 2),
        "max_latency_ms": round(consumer_metrics["max_latency_ms"], 2),
        "queue_backlog": max(0, producer_metrics["sent"] - consumer_metrics["consumed"]),
        "degradation_flag": int(
            (consumer_metrics["lost"] > 0)
            or (producer_metrics["errors"] > 0)
            or (consumer_metrics["errors"] > 0)
            or (consumer_metrics["throughput_msg_sec"] < rate * 0.9)
        ),
    }
    return row


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def write_markdown_table(path, rows):
    if not rows:
        return

    columns = [
        "broker",
        "size_bytes",
        "rate_target_msg_sec",
        "producer_sent",
        "consumer_consumed",
        "consumer_throughput_msg_sec",
        "p95_latency_ms",
        "lost_messages",
        "degradation_flag",
    ]

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[col]) for col in columns) + " |")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for broker in args.brokers:
        for size in args.sizes:
            for rate in args.rates:
                print(f"[RUN] broker={broker} size={size}B rate={rate} msg/sec")
                row = run_single_case(
                    broker=broker,
                    size=size,
                    rate=rate,
                    duration_sec=args.duration_sec,
                    max_wait_sec=args.max_wait_sec,
                )
                rows.append(row)
                print(
                    f"      throughput={row['consumer_throughput_msg_sec']} "
                    f"p95={row['p95_latency_ms']}ms lost={row['lost_messages']}"
                )

    csv_path = output_dir / "benchmark_results.csv"
    json_path = output_dir / "benchmark_results.json"
    md_table_path = output_dir / "benchmark_table.md"

    write_csv(csv_path, rows)
    write_json(json_path, rows)
    write_markdown_table(md_table_path, rows)

    print(f"\nSaved:\n- {csv_path}\n- {json_path}\n- {md_table_path}")


if __name__ == "__main__":
    main()