#!/bin/bash
# Quick script to run performance benchmarks for the mware library

echo "🚀 Running mware performance benchmarks..."
echo

# Create benchmarks directory if it doesn't exist
mkdir -p benchmarks

# Run the benchmark suite
python benchmarks/benchmark_middleware.py

# Check if benchmark passed performance goals
if [ $? -eq 0 ]; then
    echo
    echo "✅ Benchmarks completed successfully!"
    echo "📊 Results saved to benchmark_results.md"
else
    echo
    echo "❌ Benchmarks failed or performance goals not met"
    exit 1
fi

# Optional: Run with different iteration counts for quick vs thorough testing
if [ "$1" == "quick" ]; then
    echo
    echo "Running quick benchmark (1000 iterations)..."
    python benchmarks/benchmark_middleware.py --iterations 1000
elif [ "$1" == "thorough" ]; then
    echo
    echo "Running thorough benchmark (100000 iterations)..."
    python benchmarks/benchmark_middleware.py --iterations 100000
fi