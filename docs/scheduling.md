# Scheduler Guidance

Do not register a task automatically. Test `collect-fixture`, then a verified current-day live collection, before registering anything. Use Asia/Seoul for all planned times. Every live run captures and observes only its current Seoul date. An initial hourly cadence is reasonable; add a final daily observation only after confirming when the actual site clears or changes its daily view. A stopped or sleeping PC creates irrecoverable gaps.

## Windows Task Scheduler

Create a task manually. Set **Program/script** to the absolute `uv.exe` path, **Add arguments** to `run --directory "C:\Users\eunsu\Desktop\GILIB" gist-studyroom --config "C:\Users\eunsu\Desktop\GILIB\config.toml" collect-once`, and **Start in** to `C:\Users\eunsu\Desktop\GILIB`. Replace the user directory and project path on the desktop. Redirect output using a `.cmd` wrapper only if logs are needed. Configure the desired hourly trigger, inspect Task Scheduler history, and choose wake-after-sleep/run-after-missed-start settings intentionally.

## Linux or WSL cron

This development checkout is `/mnt/c/Users/eunsu/바탕 화면/GILIB`; use the actual absolute Linux project path on the machine that owns collection. Example hourly entry:

```cron
0 * * * * /home/USER/.local/bin/uv run --directory "/absolute/path/GILIB" gist-studyroom --config "/absolute/path/GILIB/config.toml" collect-once >> "/absolute/path/GILIB/private/collector.log" 2>&1
```

Cron has a minimal environment, so use absolute paths for `uv`, project, config, and log. Inspect the cron service log and `gist-studyroom status`; do not assume a heartbeat exists. The kernel-held lock prevents overlap on one machine, not unsafe concurrent writes from two PCs to a shared database.
