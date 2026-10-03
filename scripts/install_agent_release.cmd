@echo off
rem ---------------------------------------------------------------
rem Install the RELEASE build (alp-agent-release.apk): hidden from the
rem app drawer (reachable via *#*#2026#*#* dialer secret code or the
rem console), not testOnly, and the engine then claims the Device Owner
rem role so the agent can enforce policy as a DPC.
rem
rem Optional arg: adb serial, e.g.  install_agent_release.cmd LT8110260130351
rem ---------------------------------------------------------------
call "%~dp0install_agent.cmd" "%~dp0..\android-agent\alp-agent-release.apk" %*