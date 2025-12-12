#!/bin/bash

# Grid Clash - Automated Test Runner
# STABILITY VERSION: Aggressive cleanup + Memory flushing to prevent VM lag

set -e

# Configuration
SERVER_SCRIPT="server_optimized.py"
CLIENT_SCRIPT="client.py"
PYTHON_CMD="python3"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Create directories
mkdir -p test_results
mkdir -p captures
chmod 777 captures 2>/dev/null || true
chmod 777 test_results 2>/dev/null || true

# Get real user for permission fixing
REAL_USER=${SUDO_USER:-$USER}
REAL_GROUP=$(id -gn $REAL_USER)

print_header() { echo -e "\n${BLUE}=== $1 ===${NC}"; }

# --- IMPROVED CLEANUP FUNCTION ---
cleanup() {
    # 1. Force kill python processes (prevent zombies)
    sudo killall -9 python3 2>/dev/null || true
    
    # 2. Force kill tshark
    sudo killall -9 tshark 2>/dev/null || true
    
    # 3. Clear network rules
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then 
        sudo tc qdisc del dev lo root 2>/dev/null || true
    fi
    
    # 4. CRITICAL: Flush disk buffers to free up VM RAM
    sync
    echo "   (System cleaned & buffers flushed)"
}

check_dependencies() {
    if ! command -v python3 &>/dev/null; then echo "Error: Python3 missing"; exit 1; fi
    if ! command -v tshark &>/dev/null; then 
        echo "Warning: tshark missing. PCAP will be skipped."; 
        SKIP_PCAP=true
    fi
}

run_test() {
    local scenario=$1
    local loss=$2
    local delay=$3
    local jitter=$4
    local run_num=$5
    
    print_header "Running: $scenario (Iteration $run_num)"
    cleanup
    
    DURATION=40
    timestamp=$(date +"%Y%m%d_%H%M%S")
    results_dir="test_results/${scenario}_run${run_num}_${timestamp}"
    mkdir -p "$results_dir"
    
    # 1. Network Conditions
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo tc qdisc del dev lo root 2>/dev/null || true
        # Add small sleep to ensure kernel registers the deletion
        sleep 0.5 
        if [[ "$loss" -gt 0 ]]; then sudo tc qdisc add dev lo root netem loss ${loss}%; fi
        if [[ "$delay" -gt 0 ]]; then sudo tc qdisc add dev lo root netem delay ${delay}ms ${jitter}ms; fi
    fi

    # 2. Start PCAP (To /tmp/ always)
    temp_pcap="/tmp/${scenario}_${timestamp}.pcap"
    final_pcap="$(pwd)/captures/${scenario}_run${run_num}_${timestamp}.pcap"
    
    if [[ "$SKIP_PCAP" != true ]]; then
        echo "Starting Capture..."
        sudo rm -f "$temp_pcap"
        sudo tshark -i lo -f "udp port 5555" -w "$temp_pcap" -q 2>/dev/null &
        PCAP_PID=$!
        sleep 2
    fi

    # 3. Start Server
    echo "Starting Server..."
    server_cmd="$PYTHON_CMD -u $SERVER_SCRIPT"
    if [[ "$loss" -gt 0 ]] && [[ "$OSTYPE" != "linux-gnu"* ]]; then
        server_cmd="$server_cmd --loss $(python3 -c "print($loss/100.0)")"
    fi
    $server_cmd > "$results_dir/server.log" 2>&1 &
    SERVER_PID=$!
    sleep 2

    # 4. Start Clients
    echo "Starting 4 Clients..."
    CLIENT_PIDS=()
    for i in {1..4}; do
        $PYTHON_CMD -u $CLIENT_SCRIPT 127.0.0.1 --headless > "$results_dir/client_$i.log" 2>&1 &
        CLIENT_PIDS+=($!)
        sleep 0.5
    done

    # 5. Wait
    for ((sec=1; sec<=DURATION; sec++)); do
        echo -ne "Test Running: ${sec}s / ${DURATION}s \r"
        sleep 1
    done
    echo -e "\nTest Complete."

    # 6. Stop
    # Force kill specific PIDs first
    for pid in "${CLIENT_PIDS[@]}"; do sudo kill -9 $pid 2>/dev/null || true; done
    sudo kill -9 $SERVER_PID 2>/dev/null || true
    
    # 7. PCAP Retrieval
    if [[ -n "$PCAP_PID" ]]; then
        sudo kill $PCAP_PID 2>/dev/null || true
        sleep 1
        
        if [[ -f "$temp_pcap" ]]; then
            sudo chmod 666 "$temp_pcap"
            if sudo cat "$temp_pcap" > "$final_pcap" 2>/dev/null; then
                echo "${GREEN}✓ PCAP saved${NC}"
                sudo cat "$temp_pcap" > "$results_dir/trace.pcap" 2>/dev/null || true
                sudo rm "$temp_pcap"
            else
                echo "${YELLOW}⚠️  PCAP move failed. Saved at: $temp_pcap${NC}"
            fi
        fi
    fi
    
    # 8. CSV Retrieval
    mv *.csv "$results_dir/" 2>/dev/null || true
    sudo chown -R $REAL_USER:$REAL_GROUP "$results_dir" 2>/dev/null || true
    
    # Final cleanup for this run
    cleanup
}

# --- MAIN ---
check_dependencies

run_batch() {
    local name=$1
    local loss=$2
    local delay=$3
    local jitter=$4
    
    print_header "STARTING BATCH: $name"
    
    for i in {1..5}; do
        run_test "$name" "$loss" "$delay" "$jitter" "$i"
        
        # Extended cooldown to prevent VM lag
        echo "Cooling down system (10s)..."
        sleep 10
    done
}

# Run all batches
run_batch "baseline" 0 0 0
run_batch "loss_2pct" 2 0 0
run_batch "loss_5pct" 5 0 0
run_batch "delay_100ms" 0 100 0
run_batch "delay_jitter" 0 100 10

echo -e "\n${GREEN}ALL 25 TESTS FINISHED SUCCESSFULY.${NC}"
echo "Run 'python3 analyze_result.py' to generate the report."