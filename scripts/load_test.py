#!/usr/bin/env python3
"""
KubeScale AI - High-Throughput Concurrent Load Tester
Simulates concurrent production traffic to trigger Horizontal Pod Autoscaling (HPA)
scaling FastAPI and Triton pods from 2 to 10 replicas.
"""

import argparse
import concurrent.futures
import json
import random
import sys
import time
import urllib.error
import urllib.request


def send_inference_request(url: str, request_id: int):
    # Generate 128-dimensional synthetic embedding vector
    features = [round(random.uniform(-1.0, 1.0), 4) for _ in range(128)]
    payload = {
        "request_id": f"load-test-{request_id}",
        "model_name": "sentiment_onnx",
        "inputs": [features]
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            latency = (time.perf_counter() - start) * 1000.0
            return resp.status, latency, None
    except urllib.error.HTTPError as e:
        latency = (time.perf_counter() - start) * 1000.0
        return e.code, latency, str(e)
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000.0
        return 0, latency, str(e)


def main():
    parser = argparse.ArgumentParser(description="KubeScale AI HPA Load Generator")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/v1/models/sentiment_onnx/predict",
        help="Inference endpoint URL"
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=500,
        help="Total number of requests to generate"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=25,
        help="Concurrent worker threads"
    )

    args = parser.parse_args()

    print(f"=== KubeScale AI Load Test ===")
    print(f"Target:      {args.url}")
    print(f"Total Reqs:  {args.requests}")
    print(f"Concurrency: {args.concurrency}")
    print("--------------------------------------------------")

    latencies = []
    status_counts = {}
    errors = []

    start_total = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(send_inference_request, args.url, i)
            for i in range(args.requests)
        ]

        completed = 0
        for f in concurrent.futures.as_completed(futures):
            status_code, lat, err = f.result()
            latencies.append(lat)
            status_counts[status_code] = status_counts.get(status_code, 0) + 1
            if err:
                errors.append(err)
            completed += 1
            if completed % 50 == 0 or completed == args.requests:
                sys.stdout.write(f"\rProgress: {completed}/{args.requests} requests completed...")
                sys.stdout.flush()

    total_time = time.perf_counter() - start_total
    print("\n--------------------------------------------------")
    print(f"Total Duration:     {total_time:.2f} seconds")
    print(f"Throughput:         {args.requests / total_time:.2f} req/sec")
    if latencies:
        latencies.sort()
        avg_lat = sum(latencies) / len(latencies)
        p50 = latencies[int(len(latencies) * 0.50)]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        print(f"Average Latency:    {avg_lat:.2f} ms")
        print(f"p50 Latency:        {p50:.2f} ms")
        print(f"p95 Latency:        {p95:.2f} ms")
        print(f"p99 Latency:        {p99:.2f} ms")
    print(f"Status Breakdown:   {status_counts}")
    if errors:
        print(f"Sample Errors:      {errors[:3]}")
    print("==================================================")


if __name__ == "__main__":
    main()
