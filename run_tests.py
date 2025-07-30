#!/usr/bin/env python3
"""
Test runner script for CalDAV Sync Microservice.

Provides convenient commands for running different test suites and generating reports.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"\n✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} failed with exit code {e.returncode}")
        return False
    except FileNotFoundError:
        print(f"\n❌ Command not found: {cmd[0]}")
        print("Make sure pytest is installed: pip install -r requirements-dev.txt")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run tests for CalDAV Sync Microservice")
    parser.add_argument(
        "suite",
        nargs="?",
        choices=["all", "unit", "integration", "api", "sync", "database", "config", "coverage"],
        default="all",
        help="Test suite to run (default: all)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--no-cov",
        action="store_true",
        help="Disable coverage reporting"
    )
    parser.add_argument(
        "--parallel", "-n",
        type=int,
        help="Run tests in parallel (number of workers)"
    )
    parser.add_argument(
        "--failfast", "-x",
        action="store_true",
        help="Stop on first failure"
    )
    parser.add_argument(
        "--lf",
        action="store_true",
        help="Run only tests that failed in the last run"
    )
    
    args = parser.parse_args()
    
    # Base pytest command
    cmd = ["python", "-m", "pytest"]
    
    # Add verbosity
    if args.verbose:
        cmd.append("-vv")
    
    # Add coverage options
    if not args.no_cov and args.suite != "coverage":
        cmd.extend(["--cov=app", "--cov-report=term-missing"])
    
    # Add parallel execution
    if args.parallel:
        cmd.extend(["-n", str(args.parallel)])
    
    # Add fail fast
    if args.failfast:
        cmd.append("-x")
    
    # Add last failed
    if args.lf:
        cmd.append("--lf")
    
    # Test suite selection
    success = True
    
    if args.suite == "all":
        cmd.append("tests/")
        success = run_command(cmd, "All tests")
        
    elif args.suite == "unit":
        cmd.extend(["-m", "unit", "tests/"])
        success = run_command(cmd, "Unit tests")
        
    elif args.suite == "integration":
        cmd.extend(["-m", "integration", "tests/"])
        success = run_command(cmd, "Integration tests")
        
    elif args.suite == "api":
        cmd.append("tests/test_api.py")
        success = run_command(cmd, "API tests")
        
    elif args.suite == "sync":
        cmd.append("tests/test_sync_engine.py")
        success = run_command(cmd, "Sync engine tests")
        
    elif args.suite == "database":
        cmd.append("tests/test_database.py")
        success = run_command(cmd, "Database tests")
        
    elif args.suite == "config":
        cmd.append("tests/test_config.py")
        success = run_command(cmd, "Configuration tests")
        
    elif args.suite == "coverage":
        # Run tests with coverage and generate HTML report
        cmd.extend([
            "--cov=app",
            "--cov-report=html:htmlcov",
            "--cov-report=term-missing",
            "--cov-report=xml",
            "tests/"
        ])
        success = run_command(cmd, "Coverage analysis")
        
        if success:
            print(f"\n📊 Coverage report generated:")
            print(f"   HTML: htmlcov/index.html")
            print(f"   XML:  coverage.xml")
    
    # Summary
    print(f"\n{'='*60}")
    if success:
        print("🎉 All tests completed successfully!")
        
        # Show coverage summary if available
        if not args.no_cov and args.suite != "coverage":
            print("\n📊 Coverage summary available in terminal output above")
            
    else:
        print("💥 Some tests failed!")
        print("\nTips for debugging:")
        print("  - Run with --verbose for more details")
        print("  - Run with --failfast to stop on first failure")
        print("  - Run with --lf to only run failed tests")
        print("  - Check the test output above for specific error messages")
    
    print(f"{'='*60}")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
