import argparse
import json
import os
import random
import string
import time

import pika
import redis


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", required=True, choices=["rabbitmq", "redis"])
    parser.add_argument("--count", type=int, required=True, help="Number of messages to send")
    parser.add_argument("--size", type=int, required=True, help="Payload size in bytes")
    parser.add_argument("--rate", type=int, default=0, help="Target messages/sec, 0 = max speed")
    parser.add_argument("--queue", required=True, help="Queue/list name")
    return parser


def limit_rate(start_time, sent_idx, rate):
    if rate <= 0:
        return
    target_time = start_time + (sent_idx / rate)
    sleep_time = target_time - time.time()
    if sleep_time > 0:
        time.sleep(sleep_time)


def main():
    args = build_parser().parse_args()
    payload = "".join(random.choices(string.ascii_letters, k=args.size))
    start_time = time.time()
    sent = 0
    errors = 0

    if args.broker == "rabbitmq":
        rabbit_host = os.getenv("RABBITMQ_HOST", "localhost")
        rabbit_port = int(os.getenv("RABBITMQ_PORT", "5672"))
        conn = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host, port=rabbit_port))
        channel = conn.channel()
        channel.queue_declare(queue=args.queue, durable=False, auto_delete=True)
        for i in range(args.count):
            try:
                msg = json.dumps({"id": i, "sent_ts": time.time(), "payload": payload})
                channel.basic_publish(exchange="", routing_key=args.queue, body=msg.encode("utf-8"))
                sent += 1
            except Exception:
                errors += 1
            limit_rate(start_time, i + 1, args.rate)
        conn.close()
    else:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)
        redis_client.delete(args.queue)
        for i in range(args.count):
            try:
                msg = json.dumps({"id": i, "sent_ts": time.time(), "payload": payload})
                redis_client.rpush(args.queue, msg)
                sent += 1
            except Exception:
                errors += 1
            limit_rate(start_time, i + 1, args.rate)

    duration = time.time() - start_time
    metrics = {
        "role": "producer",
        "broker": args.broker,
        "queue": args.queue,
        "count_target": args.count,
        "size_bytes": args.size,
        "rate_target": args.rate,
        "sent": sent,
        "errors": errors,
        "duration_sec": duration,
        "actual_rate_msg_sec": sent / duration,
    }
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()