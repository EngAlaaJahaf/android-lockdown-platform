@echo off
rem ---------------------------------------------------------------
rem Install the DEV build (alp-agent.apk): visible in the drawer,
rem testOnly (needs -t), CANNOT be a Device Owner. Use for quick
rem on-table debugging of the agent UI / receivers.
rem
rem Optional arg: adb serial, e.g.  install_agent_dev.cmd LT8110260130351
rem ---------------------------------------------------------------
call "%~dp0install_agent.cmd" "%~dp0..\android-agent\alp-agent.apk" %*