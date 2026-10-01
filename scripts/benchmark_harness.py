#!/usr/bin/env python3
"""HarborIQ Standard Micro-benchmarking Harness.

Used to measure latency, throughput, and memory footprint of critical backend components:
- Dispatch Priority Scoring
- Invoice PDF Generation (ReportLab Platypus API)
- Database Query Performance (if database is reachable)

Every PR claiming performance improvements must execute this harness and paste the
before/after output into the PR description.
"""
from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
import uuid
from decimal import Decimal

# Ensure project root is in the path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from app.services.dispatch import score_job
    from app.services.invoice_pdf import render_invoice_pdf, InvoicePdfData, InvoicePdfLineItem
except ImportError as e:
    print(f"Error importing app modules: {e}", file=sys.stderr)
    sys.exit(1)


class SimpleNamespace:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def benchmark_dispatch_scoring(iterations: int = 1000) -> dict:
    """Benchmark the pure-function dispatch scoring engine."""
    job = SimpleNamespace(
        priority="urgent",
        scheduled_at=None,
        revenue_amount=Decimal("1500.00"),
        required_skills=["outboard", "electrical", "fiberglass"]
    )
    customer = SimpleNamespace(latitude=Decimal("27.33"), longitude=Decimal("-82.53"))
    technician = SimpleNamespace(
        home_latitude=Decimal("27.34"),
        home_longitude=Decimal("-82.52"),
        skills=["outboard", "electrical"]
    )

    tracemalloc.start()
    start_time = time.perf_counter()

    for _ in range(iterations):
        _ = score_job(
            job,
            customer=customer,
            technician=technician,
            completed_job_count=5,
            active_technician_job_count=1,
            inventory_shortfall=False
        )

    end_time = time.perf_counter()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    duration = end_time - start_time
    throughput = iterations / duration

    return {
        "iterations": iterations,
        "total_time_ms": duration * 1000,
        "avg_latency_ms": (duration / iterations) * 1000,
        "throughput_ops_sec": throughput,
        "peak_memory_kb": peak / 1024,
    }


def benchmark_invoice_pdf_generation(iterations: int = 100) -> dict:
    """Benchmark ReportLab PDF compilation performance."""
    line_items = [
        InvoicePdfLineItem(
            description="Rebuild Carburetor",
            quantity=Decimal("2.50"),
            unit_price=Decimal("110.00"),
            line_total=Decimal("275.00"),
        ),
        InvoicePdfLineItem(
            description="OEM Gasket Kit",
            quantity=Decimal("1.00"),
            unit_price=Decimal("45.50"),
            line_total=Decimal("45.50"),
        ),
        InvoicePdfLineItem(
            description="Diagnostic labor",
            quantity=Decimal("1.00"),
            unit_price=Decimal("85.00"),
            line_total=Decimal("85.00"),
        ),
    ]

    pdf_data = InvoicePdfData(
        invoice_id=uuid.uuid4(),
        company_name="Acme Marine Pilot",
        status="sent",
        subtotal=Decimal("405.50"),
        tax_total=Decimal("28.39"),
        total=Decimal("433.89"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("433.89"),
        currency="USD",
        customer_name="Sarasota Charter Co",
        customer_email="fleet@sarasotacharters.invalid",
        vessel_name="Sea Ray 270",
        pay_url="https://pay.harboriq.app/inv_test_123",
        line_items=line_items,
    )

    tracemalloc.start()
    start_time = time.perf_counter()

    for _ in range(iterations):
        _ = render_invoice_pdf(pdf_data)

    end_time = time.perf_counter()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    duration = end_time - start_time
    throughput = iterations / duration

    return {
        "iterations": iterations,
        "total_time_ms": duration * 1000,
        "avg_latency_ms": (duration / iterations) * 1000,
        "throughput_ops_sec": throughput,
        "peak_memory_kb": peak / 1024,
    }


def benchmark_database_queries(iterations: int = 100) -> dict | None:
    """Benchmark lightweight database queries if connected."""
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        # Ping check
        db.execute(text("SELECT 1")).scalar()
    except Exception:
        # DB not available (expected in local environments without Postgres/Sqlite active)
        return None

    tracemalloc.start()
    start_time = time.perf_counter()

    try:
        for _ in range(iterations):
            # Simple metadata query / read timing
            db.execute(text("SELECT 1")).scalar()
    finally:
        db.close()

    end_time = time.perf_counter()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    duration = end_time - start_time
    throughput = iterations / duration

    return {
        "iterations": iterations,
        "total_time_ms": duration * 1000,
        "avg_latency_ms": (duration / iterations) * 1000,
        "throughput_ops_sec": throughput,
        "peak_memory_kb": peak / 1024,
    }


def print_results_table(results: dict[str, dict | None]):
    """Print results in a clean Markdown table format suitable for PR descriptions."""
    print("# HARBORIQ PERFORMANCE BENCHMARK REPORT")
    print(f"Generated on: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print()
    print("| Component | Iterations | Total Time (ms) | Avg Latency (ms) | Throughput (ops/sec) | Peak Memory (KB) |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: |")

    for component, metrics in results.items():
        if metrics is None:
            print(f"| {component} | N/A | (No connection) | N/A | N/A | N/A |")
        else:
            print(
                f"| {component} "
                f"| {metrics['iterations']} "
                f"| {metrics['total_time_ms']:.2f} "
                f"| {metrics['avg_latency_ms']:.4f} "
                f"| {metrics['throughput_ops_sec']:.2f} "
                f"| {metrics['peak_memory_kb']:.2f} |"
            )
    print()
    print("Compare these values before/after optimization PRs to demonstrate measurable improvement.")


def main():
    parser = argparse.ArgumentParser(description="HarborIQ Micro-benchmarking Harness")
    parser.add_argument("--iterations-dispatch", type=int, default=2000, help="Iterations for dispatch scoring")
    parser.add_argument("--iterations-pdf", type=int, default=100, help="Iterations for PDF rendering")
    parser.add_argument("--iterations-db", type=int, default=100, help="Iterations for DB queries")
    args = parser.parse_args()

    results = {}
    results["Dispatch Priority Scoring"] = benchmark_dispatch_scoring(args.iterations_dispatch)
    results["Invoice PDF Generation"] = benchmark_invoice_pdf_generation(args.iterations_pdf)
    results["Database Basic Query"] = benchmark_database_queries(args.iterations_db)

    print_results_table(results)


if __name__ == "__main__":
    main()
