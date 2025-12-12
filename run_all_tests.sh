#!/bin/bash

# Grid Clash - Automated Test Runner
# FIX: Captures to /tmp to avoid Permission Denied errors on Shared Folders

set -e  # Exit on error

# Configuration
SERVER_SCRIPT="server_optimized.py"
CLIENT_SCRIPT="client.py"
PYTHON_CMD="python3"
BASE_DIR=$(pwd)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Test durations
BASELINE_DURATION=40
OTHER_DURATION=40

declare -A SCENARIOS=(
    ["baseline"]="0 0 0"
    ["loss_2pct"]="2 0 0"
    ["loss_5pct"]="5 0 0"
    ["delay_100ms"]="0 100 0"
    ["delay_jitter"]="0 100 10"
)

# Setup directories
mkdir -p test_results
mkdir -p captures
chmod 777 captures
chmod 777 test_results

print_header() { echo -e "\n${BLUE}========================================${NC}\n${BLUE}  $1${NC}\n${BLUE}========================================${NC}"; }
print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }

cleanup() {
    pkill -f "$SERVER_SCRIPT" 2>/dev/null || true
    pkill -f "$CLIENT_SCRIPT" 2>/dev/null || true
    if pgrep tshark > /dev/null; then sudo pkill tshark 2>/dev/null || true; fi
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then sudo tc qdisc del dev lo root 2>/dev/null || true; fi
}

check_dependencies() {
    print_header "Checking Dependencies"
    if ! command -v python3 &>/dev/null; then print_error "Python3 not found"; exit 1; fi
    if command -v tshark &>/dev/null; then print_success "tshark found"; else print_warning "tshark not found. PCAP skipped."; SKIP_PCAP=true; fi
}

apply_network_conditions() {
    local scenario=$1
    local loss=$2
    local delay=$3
    local jitter=$4
    
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo tc qdisc del dev lo root 2>/dev/null || true
        sleep 1
        if [[ "$scenario" == "loss_2pct" ]]; then sudo tc qdisc add dev lo root netem loss 2%; fi
        if [[ "$scenario" == "loss_5pct" ]]; then sudo tc qdisc add dev lo root netem loss 5%; fi
        if [[ "$scenario" == "delay_100ms" ]]; then sudo tc qdisc add dev lo root netem delay 100ms; fi
        if [[ "$scenario" == "delay_jitter" ]]; then sudo tc qdisc add dev lo root netem delay 100ms 10ms; fi
        print_success "Applied network conditions for $scenario"
    fi
}

start_pcap_capture() {
    local scenario=$1
    if [[ "$SKIP_PCAP" == true ]]; then return ""; fi
    
    # FIX: Write to /tmp first to avoid permission issues
    local temp_pcap="/tmp/${scenario}_temp.pcap"
    
    # Clean old temp file
    sudo rm -f "$temp_pcap"
    
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Run tshark pointing to /tmp
        sudo tshark -i lo -f "udp port 5555" -w "$temp_pcap" -q 2>/dev/null &
        PCAP_PID=$!
        sleep 3
        if ps -p $PCAP_PID > /dev/null 2>&1; then
            print_success "PCAP capture started (PID: $PCAP_PID)"
            echo "$temp_pcap"
        else
            print_warning "PCAP capture failed to start."
            echo ""
        fi
    fi
}

stop_pcap_capture() {
    local temp_pcap=$1
    local final_pcap=$2
    
    if [[ -n "$PCAP_PID" ]]; then
        sudo kill $PCAP_PID 2>/dev/null || true
        sleep 2
        
        # Move from /tmp to actual folder
        if [[ -f "$temp_pcap" ]]; then
            # Use cp then rm to handle filesystem boundaries (Shared Folders)
            cp "$temp_pcap" "$final_pcap"
            sudo rm "$temp_pcap"
            print_success "PCAP saved to $(basename $final_pcap)"
        else
            print_warning "PCAP file was not created in /tmp"
        fi
    fi
    PCAP_PID=""
}

run_test_scenario() {
    local scenario=$1
    local loss=$2
    local delay=$3
    local jitter=$4
    
    print_header "Running Test: $scenario"
    
    if [[ "$scenario" == "baseline" ]]; then DURATION=$BASELINE_DURATION; else DURATION=$OTHER_DURATION; fi
    cleanup
    
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local results_dir="test_results/${scenario}_${timestamp}"
    mkdir -p "$results_dir"
    chmod 777 "$results_dir"
    
    apply_network_conditions "$scenario" "$loss" "$delay" "$jitter"
    
    # Start Capture to TEMP file
    local temp_pcap_path=$(start_pcap_capture "$scenario")
    local final_pcap_path="$(pwd)/captures/${scenario}_${timestamp}.pcap"
    
    print_header "Starting Server"
    local server_cmd="$PYTHON_CMD -u $SERVER_SCRIPT"
    if [[ "$loss" -gt 0 ]] && [[ "$OSTYPE" != "linux-gnu"* ]]; then
        loss_decimal=$(python3 -c "print($loss/100.0)")
        server_cmd="$server_cmd --loss $loss_decimal"
    fi
    $server_cmd > "$results_dir/server.log" 2>&1 &
    SERVER_PID=$!
    sleep 3
    
    print_header "Starting 4 Clients"
    CLIENT_PIDS=()
    for i in {1..4}; do
        $PYTHON_CMD -u $CLIENT_SCRIPT 127.0.0.1 --headless > "$results_dir/client_$i.log" 2>&1 &
        CLIENT_PIDS+=($!)
        sleep 1
    done
    
    print_header "Running Test ($DURATION seconds)"
    for ((sec=1; sec<=DURATION; sec++)); do echo -ne "\rElapsed: ${sec}s / ${DURATION}s"; sleep 1; done
    echo ""
    
    print_header "Stopping Test"
    for pid in "${CLIENT_PIDS[@]}"; do kill $pid 2>/dev/null || true; done
    kill $SERVER_PID 2>/dev/null || true
    
    # Stop PCAP and Move file
    stop_pcap_capture "$temp_pcap_path" "$final_pcap_path"
    
    sleep 2
    
    print_header "Collecting Results"
    for csv_file in *.csv; do if [[ -f "$csv_file" ]]; then mv "$csv_file" "$results_dir/"; fi; done
    
    # Copy the PCAP to the results folder as well for safe keeping
    if [[ -f "$final_pcap_path" ]]; then
        cp "$final_pcap_path" "$results_dir/"
    fi
    
    cleanup
}

run_all_scenarios() {
    check_dependencies
    # Baseline
    run_test_scenario "baseline" 0 0 0
    sleep 5
    # Loss 2%
    run_test_scenario "loss_2pct" 2 0 0
    sleep 5
    # Loss 5%
    run_test_scenario "loss_5pct" 5 0 0
    sleep 5
    # Delay
    run_test_scenario "delay_100ms" 0 100 0
    sleep 5
    # Jitter
    run_test_scenario "delay_jitter" 0 100 10
}

# Run
run_all_scenarios