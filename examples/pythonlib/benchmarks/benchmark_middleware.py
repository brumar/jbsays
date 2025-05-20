"""
Performance benchmarking suite for the mware library.

This module provides comprehensive benchmarks to ensure the middleware
implementation performs at the level expected of a top 0.1% Python library.
"""

import asyncio
import time
import statistics
from typing import List, Callable, Dict, Any
import functools

# Import from parent directory
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mware import middleware, Context
from src.mware.decorators import timing, cache, retry


class BenchmarkSuite:
    """Run performance benchmarks for middleware operations."""
    
    def __init__(self, iterations: int = 10000):
        self.iterations = iterations
        self.results: Dict[str, Dict[str, float]] = {}
    
    async def benchmark_function(self, func: Callable, name: str, *args, **kwargs) -> Dict[str, float]:
        """Benchmark a single function with multiple iterations."""
        times = []
        
        # Warm up
        for _ in range(min(100, self.iterations // 10)):
            if asyncio.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                func(*args, **kwargs)
        
        # Actual benchmark
        for _ in range(self.iterations):
            start = time.perf_counter_ns()
            if asyncio.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                func(*args, **kwargs)
            times.append(time.perf_counter_ns() - start)
        
        results = {
            'mean': statistics.mean(times) / 1e9,  # Convert to seconds
            'median': statistics.median(times) / 1e9,
            'std_dev': statistics.stdev(times) / 1e9 if len(times) > 1 else 0,
            'min': min(times) / 1e9,
            'max': max(times) / 1e9,
            'total': sum(times) / 1e9,
            'iterations': self.iterations
        }
        
        self.results[name] = results
        return results
    
    async def run_all_benchmarks(self):
        """Run all benchmark scenarios."""
        print(f"Running benchmarks with {self.iterations} iterations each...\n")
        
        # Benchmark 1: Basic middleware overhead
        print("1. Basic middleware overhead")
        
        async def raw_handler(ctx: Context):
            return {"status": "ok"}
        
        @middleware
        async def noop_middleware(ctx: Context, next):
            return await next(ctx)
        
        @noop_middleware
        async def wrapped_handler(ctx: Context):
            return {"status": "ok"}
        
        ctx = Context()
        raw_results = await self.benchmark_function(raw_handler, "raw_handler", ctx)
        wrapped_results = await self.benchmark_function(wrapped_handler, "single_middleware", ctx)
        overhead = ((wrapped_results['mean'] - raw_results['mean']) / raw_results['mean']) * 100
        
        print(f"  Raw handler: {raw_results['mean']*1e6:.2f} μs")
        print(f"  With middleware: {wrapped_results['mean']*1e6:.2f} μs")
        print(f"  Overhead: {overhead:.1f}%\n")
        
        # Benchmark 2: Multiple middleware chain
        print("2. Multiple middleware chain")
        
        @middleware
        async def middleware1(ctx: Context, next):
            ctx.data1 = True
            return await next(ctx)
        
        @middleware
        async def middleware2(ctx: Context, next):
            ctx.data2 = True
            return await next(ctx)
        
        @middleware
        async def middleware3(ctx: Context, next):
            ctx.data3 = True
            return await next(ctx)
        
        @middleware1
        @middleware2
        @middleware3
        async def chained_handler(ctx: Context):
            return {"status": "ok", "data": ctx.data1 and ctx.data2 and ctx.data3}
        
        chained_results = await self.benchmark_function(chained_handler, "triple_middleware", Context())
        chain_overhead = ((chained_results['mean'] - raw_results['mean']) / raw_results['mean']) * 100
        
        print(f"  Triple middleware: {chained_results['mean']*1e6:.2f} μs")
        print(f"  Overhead vs raw: {chain_overhead:.1f}%\n")
        
        # Benchmark 3: Built-in decorators
        print("3. Built-in decorators performance")
        
        @timing
        async def timed_handler(ctx: Context):
            await asyncio.sleep(0.00001)  # Simulate small work
            return {"status": "ok"}
        
        @cache(ttl=60)
        async def cached_handler(ctx: Context, value: int):
            await asyncio.sleep(0.00001)  # Simulate work
            return {"value": value * 2}
        
        @retry(max_attempts=3)
        async def retry_handler(ctx: Context):
            return {"status": "ok"}
        
        timing_results = await self.benchmark_function(timed_handler, "timing_decorator", Context())
        
        # Cache benchmark - first call
        ctx_cache = Context()
        cache_miss_results = await self.benchmark_function(cached_handler, "cache_miss", ctx_cache, 42)
        
        # Cache benchmark - subsequent calls (should be faster)
        cache_hit_results = await self.benchmark_function(cached_handler, "cache_hit", ctx_cache, 42)
        
        retry_results = await self.benchmark_function(retry_handler, "retry_decorator", Context())
        
        print(f"  Timing decorator: {timing_results['mean']*1e6:.2f} μs")
        print(f"  Cache (miss): {cache_miss_results['mean']*1e6:.2f} μs")
        print(f"  Cache (hit): {cache_hit_results['mean']*1e6:.2f} μs")
        print(f"  Cache speedup: {cache_miss_results['mean']/cache_hit_results['mean']:.1f}x")
        print(f"  Retry decorator: {retry_results['mean']*1e6:.2f} μs\n")
        
        # Benchmark 4: Context operations
        print("4. Context operations")
        
        def context_operations():
            ctx = Context()
            ctx.user_id = 123
            ctx.session_id = "abc123"
            ctx.metadata = {"key": "value"}
            _ = ctx.user_id
            _ = ctx.session_id
            _ = ctx.metadata
            return ctx
        
        context_results = await self.benchmark_function(context_operations, "context_operations")
        print(f"  Context creation & access: {context_results['mean']*1e6:.2f} μs\n")
        
        # Summary
        print("=== Performance Summary ===")
        print(f"Basic middleware overhead: {overhead:.1f}%")
        print(f"Typical operation time: ~{wrapped_results['mean']*1e6:.0f} μs")
        print(f"Context operations: ~{context_results['mean']*1e6:.0f} μs")
        
        if overhead > 10:
            print("\n⚠️  WARNING: Middleware overhead exceeds 10% - optimization needed!")
        else:
            print("\n✅ Performance meets expectations for a top-tier library!")
        
        return self.results
    
    def generate_report(self, output_file: str = "benchmark_results.md"):
        """Generate a markdown report of benchmark results."""
        with open(output_file, 'w') as f:
            f.write("# mware Performance Benchmark Results\n\n")
            f.write(f"Total iterations per benchmark: {self.iterations}\n\n")
            
            f.write("## Results Summary\n\n")
            f.write("| Benchmark | Mean (μs) | Median (μs) | Std Dev (μs) | Min (μs) | Max (μs) |\n")
            f.write("|-----------|-----------|-------------|--------------|----------|----------|\n")
            
            for name, results in self.results.items():
                f.write(f"| {name} | {results['mean']*1e6:.2f} | {results['median']*1e6:.2f} | "
                       f"{results['std_dev']*1e6:.2f} | {results['min']*1e6:.2f} | {results['max']*1e6:.2f} |\n")
            
            # Calculate overhead percentage
            if 'raw_handler' in self.results and 'single_middleware' in self.results:
                overhead = ((self.results['single_middleware']['mean'] - 
                           self.results['raw_handler']['mean']) / 
                          self.results['raw_handler']['mean']) * 100
                
                f.write(f"\n## Key Metrics\n\n")
                f.write(f"- **Basic middleware overhead**: {overhead:.1f}%\n")
                f.write(f"- **Raw handler time**: {self.results['raw_handler']['mean']*1e6:.2f} μs\n")
                f.write(f"- **Single middleware time**: {self.results['single_middleware']['mean']*1e6:.2f} μs\n")
                
                if 'triple_middleware' in self.results:
                    triple_overhead = ((self.results['triple_middleware']['mean'] - 
                                     self.results['raw_handler']['mean']) / 
                                    self.results['raw_handler']['mean']) * 100
                    f.write(f"- **Triple middleware overhead**: {triple_overhead:.1f}%\n")
                
                if 'cache_hit' in self.results and 'cache_miss' in self.results:
                    cache_speedup = self.results['cache_miss']['mean'] / self.results['cache_hit']['mean']
                    f.write(f"- **Cache speedup**: {cache_speedup:.1f}x\n")
            
            f.write("\n## Performance Goals\n\n")
            f.write("To achieve top 0.1% DX in Python libraries, we target:\n")
            f.write("- Middleware overhead < 10%\n")
            f.write("- Sub-microsecond operations for simple middleware\n")
            f.write("- Predictable performance with low variance\n")


async def main():
    """Run the benchmark suite."""
    suite = BenchmarkSuite(iterations=10000)
    results = await suite.run_all_benchmarks()
    suite.generate_report("benchmark_results.md")
    print("\n📊 Full report saved to benchmark_results.md")


if __name__ == "__main__":
    asyncio.run(main())