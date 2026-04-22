import argparse
import json
import statistics
import time
from typing import List

import pika
import redis


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", required=True, choices=["rabbitmq", "redis"])
    parser.add_argument("--count", required=True, type=int, help="Number of messages to consume")
    parser.add_argument("--queue", required=True, help="Queue/list name")
    parser.add_argument("--max-wait-sec", type=int, default=30, help="Max idle wait before stop")
    return parser


def calc_percentile(sorted_values, percentile) -> float:
    if not sorted_values:
        return 0.0
    idx = int((len(sorted_values) - 1) * percentile)
    return sorted_values[idx]


def main():
    args = build_parser().parse_args()
    start = time.time()
    last_msg_time = start
    consumed = 0
    errors = 0
    latencies_ms = []

    if args.broker == "rabbitmq":
        conn = pika.BlockingConnection(pika.ConnectionParameters(host="localhost", port=5672))
        channel = conn.channel()
        channel.queue_declare(queue=args.queue, durable=False, auto_delete=True)
        while consumed < args.count:
            method, _, body = channel.basic_get(queue=args.queue, auto_ack=False)
            if method is None:
                if time.time() - last_msg_time > args.max_wait_sec:
                    break
                time.sleep(0.01)
                continue
            try:
                payload = json.loads(body.decode("utf-8"))
                latency_ms = (time.time() - payload["sent_ts"]) * 1000
                latencies_ms.append(latency_ms)
                consumed += 1
                last_msg_time = time.time()
                channel.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                errors += 1
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        conn.close()
    else:
        redis_client = redis.Redis(host="localhost", port=6379, decode_responses=False)
        while consumed < args.count:
            raw = redis_client.blpop(args.queue, timeout=1)
            if raw is None:
                if time.time() - last_msg_time > args.max_wait_sec:
                    break
                continue
            try:
                _, body = raw
                if isinstance(body, bytes):
                    body = body.decode("utf-8")
                payload = json.loads(body)
                latency_ms = (time.time() - payload["sent_ts"]) * 1000
                latencies_ms.append(latency_ms)
                consumed += 1
                last_msg_time = time.time()
            except Exception:
                errors += 1

        redis_client.delete(args.queue)

    duration = time.time() - start
    latencies_sorted = sorted(latencies_ms)
    metrics = {
        "role": "consumer",
        "broker": args.broker,
        "queue": args.queue,
        "count_target": args.count,
        "consumed": consumed,
        "errors": errors,
        "lost": args.count - consumed,
        "duration_sec": duration,
        "throughput_msg_sec": consumed / duration,
        "avg_latency_ms": statistics.mean(latencies_ms) if latencies_ms else 0.0,
        "p95_latency_ms": calc_percentile(latencies_sorted, 0.95),
        "max_latency_ms": max(latencies_ms) if latencies_ms else 0.0,
    }
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()