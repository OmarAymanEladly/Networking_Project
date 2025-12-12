#!/bin/bash

# Grid Clash - Automated Test Runner
# UPDATED FIX: Writes PCAP to /tmp first to solve VirtualBox Permission Denied errors

set -e  # Exit on error

# Configuration
SERVER_SCRIPT="server_optimized.py"
CLIENT_SCRIPT="client.py"
PYTHON_CMD="python3"
BASE_DIR=$(pwd)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test durations
BASELINE_DURATION=40
OTHER_DURATION=40

# Test scenarios with network conditions
declare -A SCENARIOS=(
    ["baseline"]="0 0 0"
    ["loss_2pct"]="2 0 0"
    ["loss_5pct"]="5 0 0"
    ["delay_100ms"]="0 100 0"
    ["delay_jitter"]="0 100 10"
)

# Create directories
mkdir -p test_results
mkdir -p captures
chmod 777 captures
chmod 777 test_results

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }

cleanup() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}  Cleaning up...${NC}"
    echo -e "${BLUE}========================================${NC}"
    
    pkill -f "$SERVER_SCRIPT" 2>/dev/null || true
    pkill -f "$CLIENT_SCRIPT" 2>/dev/null || true
    
    if pgrep tshark > /dev/null; then
        sudo pkill tshark 2>/dev/null || true
    fi
    
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo tc qdisc del dev lo root 2>/dev/null || true
    fi
    
    sleep 2
    echo -e "${GREEN}✓ Cleanup complete${NC}"
}

check_dependencies() {
    print_header "Checking Dependencies"
    
    if command -v python3 &>/dev/null; then
        print_success "Python3 found"
    else
        print_error "Python3 not found."
        exit 1
    fi
    
    if command -v tshark &>/dev/null; then
        print_success "tshark found"
    else
        print_warning "tshark not found. PCAP capture will be skipped."
        SKIP_PCAP=true
    fi
    
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if sudo -v &>/dev/null; then
            print_success "sudo access available"
        else
            print_warning "sudo access not available."
        fi
    fi
}

apply_network_conditions() {
    local scenario=$1
    local loss=$2
    local delay=$3
    local jitter=$4
    
    print_header "Applying Network Conditions: $scenario"
    echo "Loss: ${loss}%, Delay: ${delay}ms, Jitter: ${jitter}ms"
    
    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        print_warning "Network simulation only available on Linux"
        return 0
    fi
    
    sudo tc qdisc del dev lo root 2>/dev/null || true
    sleep 1
    
    case $scenario in
        "baseline") print_success "Baseline (no network impairment)" ;;
        "loss_2pct") sudo tc qdisc add dev lo root netem loss 2%; print_success "Applied 2% packet loss" ;;
        "loss_5pct") sudo tc qdisc add dev lo root netem loss 5%; print_success "Applied 5% packet loss" ;;
        "delay_100ms") sudo tc qdisc add dev lo root netem delay 100ms; print_success "Applied 100ms delay" ;;
        "delay_jitter") sudo tc qdisc add dev lo root netem delay 100ms 10ms; print_success "Applied 100ms delay + 10ms jitter" ;;
    esac
}

start_pcap_capture() {
    local scenario=$1
    
    if [[ "$SKIP_PCAP" == true ]]; then
        return ""
    fi
    
    print_header "Starting PCAP Capture"
    
    # --- FIX STARTS HERE ---
    # Write to /tmp/ because it is universally writable
    local temp_pcap="/tmp/${scenario}_temp.pcap"
    
    # Remove old temp file if exists
    sudo rm -f "$temp_pcap"
    
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        INTERFACE="lo"
        # Run tshark writing to /tmp
        sudo tshark -i $INTERFACE -f "udp port 5555" -w "$temp_pcap" -q 2>/dev/null &
        PCAP_PID=$!
        sleep 3
        
        if ps -p $PCAP_PID > /dev/null 2>&1; then
            print_success "PCAP capture started (PID: $PCAP_PID)"
            # Return the TEMP path, not the final path yet
            echo "$temp_pcap"
        else
            print_warning "PCAP capture failed to start."
            echo ""
        fi
    else
        echo ""
    fi
}

stop_pcap_capture() {
    local temp_file=$1
    local final_file=$2
    
    if [[ -n "$PCAP_PID" ]]; then
        print_header "Stopping PCAP Capture"
        sudo kill $PCAP_PID 2>/dev/null || true
        sleep 2
        
        if [[ -f "$temp_file" ]]; then
            # 1. Make the temp file readable by everyone (since it was created by root)
            sudo chmod 666 "$temp_file"
            
            # 2. COPY it to the destination (cp works better than mv across filesystems)
            cp "$temp_file" "$final_file"
            
            # 3. Verify it arrived
            if [[ -f "$final_file" ]]; then
                print_success "PCAP saved to $(basename $final_file)"
                # Delete the temp file
                rm "$temp_file"
            else
                print_error "Failed to move PCAP to captures folder"
            fi
        else
            print_warning "PCAP file was empty or not created"
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
    
    # Start Capture to TEMP path
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
    for ((sec=1; sec<=DURATION; sec++)); do
        echo -ne "\rElapsed: ${sec}s / ${DURATION}s"
        sleep 1
    done
    echo ""
    
    print_header "Stopping Test"
    for pid in "${CLIENT_PIDS[@]}"; do kill $pid 2>/dev/null || true; done
    kill $SERVER_PID 2>/dev/null || true
    
    # Stop PCAP and move file
    stop_pcap_capture "$temp_pcap_path" "$final_pcap_path"
    
    sleep 2
    
    print_header "Collecting Results"
    
    local csv_count=0
    for csv_file in *.csv; do
        if [[ -f "$csv_file" ]]; then
            mv "$csv_file" "$results_dir/"
            ((csv_count++))
        fi
    done
    
    # Copy the PCAP to the results folder too
    if [[ -f "$final_pcap_path" ]]; then
        cp "$final_pcap_path" "$results_dir/"
        print_success "PCAP included in results folder"
    fi
    
    print_success "Results saved to: $results_dir"
    cleanup
    return 0
}

run_all_scenarios() {
    check_dependencies
    
    run_test_scenario "baseline" 0 0 0
    sleep 5
    run_test_scenario "loss_2pct" 2 0 0
    sleep 5
    run_test_scenario "loss_5pct" 5 0 0
    sleep 5
    run_test_scenario "delay_100ms" 0 100 0
    sleep 5
    run_test_scenario "delay_jitter" 0 100 10
}

# Run
run_all_scenarios