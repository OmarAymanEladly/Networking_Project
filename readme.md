Grid Clash - Phase 2 Submission

HOW TO RUN:
1. Install dependencies: sudo apt install python3-pip tshark; pip3 install pygame pandas matplotlib seaborn scipy
2. Run tests: sudo ./run_tests.sh
3. Analyze: python3 analyze_result.py

NOTES:
- We use /tmp/ for pcap capture to avoid VirtualBox shared folder permission errors.
- Headless clients use a dummy video driver to save CPU.