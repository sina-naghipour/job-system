# Terminal 1
python -m packages.server.main

# Terminal 2
$env:AGENT_ID = "agent-1"
python -m packages.agent.main

# Terminal 3
.\scripts\demo.ps1