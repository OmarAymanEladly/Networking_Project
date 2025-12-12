#!/bin/bash

# Grid Clash - Automated Test Runner
# Runs each test scenario once (not 5 times as in PDF requirement for final submission)
# For development and quick testing

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

# Test durations (in seconds)
BASELINE_DURATION=30
OTHER_DURATION=20

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

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

cleanup() {
    print_header "Cleaning up..."
    
    # Kill any running processes
    pkill -f "$SERVER_SCRIPT" 2>/dev/null || true
    pkill -f "$CLIENT_SCRIPT" 2>/dev/null || true
    pkill -f "tshark" 2>/dev/null || true
    
    # Clean network rules (Linux only)
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo tc qdisc del dev lo root 2>/dev/null || true
    fi
    
    sleep 2
    print_success "Cleanup complete"
}

check_dependencies() {
    print_header "Checking Dependencies"
    
    # Check Python
    if command -v python3 &>/dev/null; then
        print_success "Python3 found"
    else
        print_error "Python3 not found. Please install Python 3."
        exit 1
    fi
    
    # Check tshark
    if command -v tshark &>/dev/null; then
        print_success "tshark found"
    else
        print_warning "tshark not found. PCAP capture will be skipped."
        SKIP_PCAP=true
    fi
    
    # Check sudo on Linux
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if sudo -v &>/dev/null; then
            print_success "sudo access available"
        else
            print_warning "sudo access not available. Network simulation may not work."
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
        echo "Using software-based simulation where available"
        return 0
    fi
    
    # Remove existing rules
    sudo tc qdisc del dev lo root 2>/dev/null || true
    sleep 1
    
    case $scenario in
        "baseline")
            print_success "Baseline (no network impairment)"
            ;;
        "loss_2pct")
            sudo tc qdisc add dev lo root netem loss 2%
            print_success "Applied 2% packet loss"
            ;;
        "loss_5pct")
            sudo tc qdisc add dev lo root netem loss 5%
            print_success "Applied 5% packet loss"
            ;;
        "delay_100ms")
            sudo tc qdisc add dev lo root netem delay 100ms
            print_success "Applied 100ms delay"
            ;;
        "delay_jitter")
            sudo tc qdisc add dev lo root netem delay 100ms 10ms
            print_success "Applied 100ms delay with 10ms jitter"
            ;;
    esac
    
    # Show current rules
    echo -e "\nCurrent network rules:"
    sudo tc qdisc show dev lo
}

start_pcap_capture() {
    local scenario=$1
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local pcap_file="captures/${scenario}_${timestamp}.pcap"
    
    if [[ "$SKIP_PCAP" == true ]]; then
        echo "Skipping PCAP capture (tshark not available)"
        return
    fi
    
    print_header "Starting PCAP Capture"
    echo "Saving to: $pcap_file"
    
    # Determine interface
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        INTERFACE="lo"
        sudo tshark -i $INTERFACE -f "udp port 5555" -w "$pcap_file" -q &
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        INTERFACE="lo0"
        tshark -i $INTERFACE -f "udp port 5555" -w "$pcap_file" -q &
    else
        # Windows or unknown
        tshark -i 1 -f "udp port 5555" -w "$pcap_file" -q &
    fi
    
    PCAP_PID=$!
    sleep 3
    
    if ps -p $PCAP_PID > /dev/null; then
        print_success "PCAP capture started (PID: $PCAP_PID)"
        echo $pcap_file
    else
        print_warning "PCAP capture failed to start"
        echo ""
    fi
}

stop_pcap_capture() {
    if [[ -n "$PCAP_PID" ]] && ps -p $PCAP_PID > /dev/null; then
        print_header "Stopping PCAP Capture"
        kill $PCAP_PID 2>/dev/null || true
        sleep 2
        print_success "PCAP capture stopped"
    fi
    PCAP_PID=""
}

run_test_scenario() {
    local scenario=$1
    local loss=$2
    local delay=$3
    local jitter=$4
    
    print_header "Running Test: $scenario"
    
    # Set duration
    if [[ "$scenario" == "baseline" ]]; then
        DURATION=$BASELINE_DURATION
    else
        DURATION=$OTHER_DURATION
    fi
    
    # Cleanup first
    cleanup
    
    # Create results directory
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local results_dir="test_results/${scenario}_${timestamp}"
    mkdir -p "$results_dir"
    
    # Apply network conditions
    apply_network_conditions "$scenario" "$loss" "$delay" "$jitter"
    
    # Start PCAP capture
    local pcap_file=$(start_pcap_capture "$scenario")
    
    # Start Server
    print_header "Starting Server"
    local server_cmd="$PYTHON_CMD -u $SERVER_SCRIPT"
    
    # Add loss parameter for non-Linux or when netem not available
    if [[ "$loss" -gt 0 ]] && [[ "$OSTYPE" != "linux-gnu"* ]]; then
        server_cmd="$server_cmd --loss $(echo "scale=2; $loss/100" | bc)"
    fi
    
    echo "Command: $server_cmd"
    $server_cmd > "$results_dir/server.log" 2>&1 &
    SERVER_PID=$!
    
    sleep 5
    
    if ! ps -p $SERVER_PID > /dev/null; then
        print_error "Server failed to start. Check $results_dir/server.log"
        return 1
    fi
    
    print_success "Server started (PID: $SERVER_PID)"
    
    # Start 4 Clients
    print_header "Starting 4 Clients"
    CLIENT_PIDS=()
    
    for i in {1..4}; do
        $PYTHON_CMD -u $CLIENT_SCRIPT 127.0.0.1 --headless > "$results_dir/client_$i.log" 2>&1 &
        CLIENT_PIDS+=($!)
        echo "Client $i started (PID: ${CLIENT_PIDS[-1]})"
        sleep 1.5
    done
    
    # Wait for connections
    print_header "Waiting for connections..."
    sleep 8
    
    # Check connections
    local connected_clients=0
    for i in {1..4}; do
        if grep -q -E "(Connected!|\[OK\]|Assigned ID|player_)" "$results_dir/client_$i.log" 2>/dev/null; then
            print_success "Client $i connected"
            ((connected_clients++))
        else
            print_warning "Client $i connection unclear"
        fi
    done
    
    echo -e "\n${GREEN}Connected: $connected_clients/4 clients${NC}"
    
    # Run test for duration
    print_header "Running Test ($DURATION seconds)"
    
    for ((sec=1; sec<=DURATION; sec++)); do
        echo -ne "\rElapsed: ${sec}s / ${DURATION}s"
        sleep 1
    done
    echo -e "\n${GREEN}Test completed${NC}"
    
    # Stop everything
    print_header "Stopping Test"
    
    # Stop clients
    for pid in "${CLIENT_PIDS[@]}"; do
        kill $pid 2>/dev/null || true
    done
    
    # Stop server
    kill $SERVER_PID 2>/dev/null || true
    
    # Stop PCAP
    stop_pcap_capture
    
    # Wait for processes to exit
    sleep 3
    
    # Collect CSV files
    print_header "Collecting Results"
    
    local csv_count=0
    for csv_file in *.csv; do
        if [[ -f "$csv_file" ]]; then
            mv "$csv_file" "$results_dir/"
            print_success "Moved: $csv_file"
            ((csv_count++))
        fi
    done
    
    # Move PCAP file if captured
    if [[ -n "$pcap_file" ]] && [[ -f "$pcap_file" ]]; then
        mv "$pcap_file" "$results_dir/"
        print_success "Moved PCAP: $(basename $pcap_file)"
    fi
    
    # Create summary file
    cat > "$results_dir/summary.txt" << EOF
Test: $scenario
Time: $(date)
Duration: ${DURATION}s
Network: Loss=${loss}%, Delay=${delay}ms, Jitter=${jitter}ms
Clients Connected: $connected_clients/4
CSV Files: $csv_count
PCAP File: $(basename $pcap_file 2>/dev/null || echo "None")
EOF
    
    print_success "Results saved to: $results_dir"
    
    # Cleanup for next test
    cleanup
    
    return 0
}

run_all_scenarios() {
    print_header "GRID CLASH - TEST SUITE"
    echo "Running all scenarios once (no repetitions)"
    echo "Baseline: ${BASELINE_DURATION}s, Others: ${OTHER_DURATION}s"
    echo ""
    
    check_dependencies
    
    local total_scenarios=${#SCENARIOS[@]}
    local current=1
    
    for scenario in "${!SCENARIOS[@]}"; do
        print_header "Scenario $current of $total_scenarios"
        
        # Parse network conditions
        IFS=' ' read -r loss delay jitter <<< "${SCENARIOS[$scenario]}"
        
        # Run the scenario
        if run_test_scenario "$scenario" "$loss" "$delay" "$jitter"; then
            print_success "$scenario completed successfully"
        else
            print_error "$scenario failed"
        fi
        
        ((current++))
        
        # Wait between scenarios (except after last)
        if [[ $current -le $total_scenarios ]]; then
            print_header "Waiting 15 seconds before next scenario..."
            sleep 15
        fi
    done
}

run_single_scenario() {
    local scenario=$1
    
    if [[ -z "${SCENARIOS[$scenario]}" ]]; then
        print_error "Unknown scenario: $scenario"
        echo "Available scenarios: ${!SCENARIOS[@]}"
        exit 1
    fi
    
    print_header "Running Single Scenario: $scenario"
    
    check_dependencies
    
    # Parse network conditions
    IFS=' ' read -r loss delay jitter <<< "${SCENARIOS[$scenario]}"
    
    # Run the scenario
    if run_test_scenario "$scenario" "$loss" "$delay" "$jitter"; then
        print_success "$scenario completed successfully"
    else
        print_error "$scenario failed"
        exit 1
    fi
}

# Main execution
main() {
    if [[ $# -eq 0 ]]; then
        # Run all scenarios by default
        run_all_scenarios
    elif [[ $1 == "--scenario" ]] && [[ -n $2 ]]; then
        # Run specific scenario
        run_single_scenario "$2"
    elif [[ $1 == "--help" ]] || [[ $1 == "-h" ]]; then
        # Show help
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --scenario NAME    Run specific scenario (baseline, loss_2pct, loss_5pct, delay_100ms, delay_jitter)"
        echo "  --help, -h         Show this help message"
        echo ""
        echo "If no options provided, runs all scenarios."
        echo ""
        echo "Example:"
        echo "  $0                    # Run all scenarios"
        echo "  $0 --scenario baseline # Run only baseline"
        exit 0
    else
        print_error "Unknown option: $1"
        echo "Use --help for usage information"
        exit 1
    fi
    
    print_header "TESTING COMPLETE"
    echo "All results saved in: test_results/"
    echo "Run analysis with: python analyze_results.py"
}

# Handle script interruption
trap 'print_error "Script interrupted by user"; cleanup; exit 1' INT TERM

# Run main function with all arguments
main "$@"