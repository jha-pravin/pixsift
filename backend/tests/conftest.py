import os

# Tests drive the drive watcher with fake drive lists; never poll the machine's real drives.
os.environ.setdefault("PIXSIFT_WATCH_DRIVES", "0")
