#!/bin/bash

# Grid Clash - Automated Test Runner
# Phase 2 Complete Script
# Fixes: Permissions, PCAP capture, and Lag issues

set -e  # Exit immediately if a command exits with a non-zero status

# Configuration
SERVER_SCRIPT="server_optimized.py"
CLIENT_SCRIPT="client.py"
PYTHON_CMD="python3"

# Colors for pretty output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Create output directories
mkdir -p test_results
mkdir -p captures
# Ensure they are writable
chmod 777 captures 2>/dev/null || true
chmod 777 test_results 2>/dev/null || true

# Get the real user ID (the user who typed sudo) to fix file ownership later
REAL_USER=${SUDO_USER:-$USER}
REAL_GROUP=$(id -gn $REAL_USER)

print_header() { echo -e "\n${BLUE}=== $1 ===${NC}"; }

# Cleanup function to kill processes and reset network
cleanup() {
    pkill -f "$SERVER_SCRIPT" 2>/dev/null || true
    pkill -f "$CLIENT_SCRIPT" 2>/dev/null || true
    if pgrep tshark > /dev/null; then sudo pkill tshark 2>/dev/null || true; fi
    # Remove network simulations
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then sudo tc qdisc del dev lo root 2>/dev/null || true; fi
}

check_dependencies() {
    if ! command -v python3 &>/dev/null; then echo "Error: Python3 missing"; exit 1; fi
    if ! command -v tshark &>/dev/null; then 
        echo "Warning: tshark missing. PCAP capture will be skipped."; 
        SKIP_PCAP=true
    fi
}

run_test() {
    local scenario=$1
    local loss=$2
    local delay=$3
    local jitter=$4
    
    print_header "Running Scenario: $scenario"
    cleanup
    
    # Test Duration (40s is sufficient for data collection)
    DURATION=40
    
    timestamp=$(date +"%Y%m%d_%H%M%S")
    results_dir="test_results/${scenario}_${timestamp}"
    mkdir -p "$results_dir"
    
    # 1. Apply Network Conditions (Linux Netem)
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Clear existing rules
        sudo tc qdisc del dev lo root 2>/dev/null || true
        # Apply new rules
        if [[ "$loss" -gt 0 ]]; then sudo tc qdisc add dev lo root netem loss ${loss}%; fi
        if [[ "$delay" -gt 0 ]]; then sudo tc qdisc add dev lo root netem delay ${delay}ms ${jitter}ms; fi
    fi

    # 2. Start PCAP Capture
    pcap_file="$(pwd)/captures/${scenario}_${timestamp}.pcap"
    if [[ "$SKIP_PCAP" != true ]]; then
        echo "Starting Tshark..."
        # Capture on loopback, port 5555, quiet mode, run in background
        sudo tshark -i lo -f "udp port 5555" -w "$pcap_file" -q 2>/dev/null &
        PCAP_PID=$!
        sleep 2
    fi

    # 3. Start Server
    echo "Starting Server..."
    server_cmd="$PYTHON_CMD -u $SERVER_SCRIPT"
    # If not on Linux, use software simulation (fallback)
    if [[ "$loss" -gt 0 ]] && [[ "$OSTYPE" != "linux-gnu"* ]]; then
        server_cmd="$server_cmd --loss $(python3 -c "print($loss/100.0)")"
    fi
    $server_cmd > "$results_dir/server.log" 2>&1 &
    SERVER_PID=$!
    sleep 2

    # 4. Start 4 Clients (Headless)
    echo "Starting 4 Clients..."
    CLIENT_PIDS=()
    for i in {1..4}; do
        $PYTHON_CMD -u $CLIENT_SCRIPT 127.0.0.1 --headless > "$results_dir/client_$i.log" 2>&1 &
        CLIENT_PIDS+=($!)
        sleep 0.5
    done

    # 5. Wait Loop (Progress bar)
    for ((sec=1; sec<=DURATION; sec++)); do
        echo -ne "Test Running: ${sec}s / ${DURATION}s \r"
        sleep 1
    done
    echo -e "\nTest Complete."

    # 6. Stop Everything
    for pid in "${CLIENT_PIDS[@]}"; do kill $pid 2>/dev/null || true; done
    kill $SERVER_PID 2>/dev/null || true
    
    if [[ -n "$PCAP_PID" ]]; then
        sudo kill $PCAP_PID 2>/dev/null || true
        sleep 1
        
        # --- PERMISSION FIX ---
        # Change ownership of the root-created PCAP file back to the normal user
        if [[ -f "$pcap_file" ]]; then
            sudo chown $REAL_USER:$REAL_GROUP "$pcap_file" 2>/dev/null || true
            sudo chmod 666 "$pcap_file" 2>/dev/null || true
            
            # Copy PCAP to the results folder for easy zipping
            cp "$pcap_file" "$results_dir/"
            echo "${GREEN}✓ PCAP captured and saved${NC}"
        fi
    fi
    
    # 7. Collect CSV Logs
    # Move all .csv files generated in the current folder to the results dir
    mv *.csv "$results_dir/" 2>/dev/null || true
    
    # Fix ownership of the results folder
    sudo chown -R $REAL_USER:$REAL_GROUP "$results_dir" 2>/dev/null || true
    
    cleanup
}

# --- MAIN EXECUTION ---
check_dependencies

# Run all 5 mandatory scenarios
run_test "baseline" 0 0 0
sleep 2
run_test "loss_2pct" 2 0 0
sleep 2
run_test "loss_5pct" 5 0 0
sleep 2
run_test "delay_100ms" 0 100 0
sleep 2
run_test "delay_jitter" 0 100 10

print_header "ALL TESTS COMPLETE"
echo "To analyze results, run: python3 analyze_result.py"